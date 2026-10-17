"""Start, stop and resume ``faultline`` runs from the control panel (ADR 0033).

The panel wraps the command line; it never runs a diagnosis inside the server. A run is a detached
``python -m robot_debug.cli diagnose|replay ...`` process that survives closing the browser tab or restarting the
viewer (a new process group on Windows, a new session on POSIX). Its output goes to ``run.log`` in the launch
folder under ``artifacts/specs-ui/``; the CLI reports its run folder through ``--run-dir-file`` and records its own
process id in the run folder, which is how everything else (this server, ``faultline stop``) finds it.

One paid run at a time: a start is refused while any run's process is alive, whoever started it. Stopping only
writes ``stop-request.json``; the run itself cancels its Job and settles the ledger (see ``faultline stop``).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import robot_debug
from robot_debug import orchestrator as orch
from robot_debug.viewer import processes
from robot_debug.viewer.processes import Probe
from robot_debug.viewer.security import ApiError
from robot_debug.viewer.specs import SpecService

DISCOVER_SECONDS = 30.0          # how long a start waits for the run to report its folder
DISCOVER_POLL_SECONDS = 0.1
RUN_LOG = "run.log"
RUN_DIR_FILE = "run-dir.txt"
PENDING_FILE = "ui-pending.json"     # {"pid", "started_at"}: a spawned child that has not reported its run folder


CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def popen_options(win32: bool, breakaway: bool = True) -> Dict[str, Any]:
    """Keyword arguments that detach the child from this process: it must outlive the viewer.

    On Windows a process started inside a job object (a terminal, an IDE, a preview tool) is killed with that job
    unless it breaks away from it; ``DETACHED_PROCESS`` alone does not (found October 17: stopping the viewer killed
    a running diagnosis mid-Job). ``breakaway=False`` is the fallback for jobs that forbid breaking away."""

    options: Dict[str, Any] = {"stdin": subprocess.DEVNULL, "close_fds": True}
    if win32:
        options["creationflags"] = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
                                    | getattr(subprocess, "DETACHED_PROCESS", 0x8)
                                    | (CREATE_BREAKAWAY_FROM_JOB if breakaway else 0))
    else:
        options["start_new_session"] = True
    return options


class Launcher:
    """Spawns and controls the detached runs of one artifacts folder."""

    def __init__(self, artifact_root: Path, runs_root: Path, specs: SpecService, *,
                 popen: Callable[..., Any] = subprocess.Popen, python: Optional[str] = None,
                 env: Optional[Mapping[str, str]] = None, env_file: Optional[Path] = None,
                 probe: Probe = processes.default_probe, win32: Optional[bool] = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 discover_seconds: float = DISCOVER_SECONDS, source_root: Optional[Path] = None) -> None:
        # The child runs in the project folder, not here: every path it is given must be absolute, and must not
        # change if this process later changes directory.
        self.artifact_root, self.runs_root, self.specs = Path(artifact_root).resolve(), Path(runs_root).resolve(), specs
        self.popen, self.python = popen, python or sys.executable
        self.base_env = dict(os.environ if env is None else env)
        self.env_file, self.probe = None if env_file is None else Path(env_file).resolve(), probe
        self.win32 = (sys.platform == "win32") if win32 is None else win32
        self.sleep, self.clock, self.discover_seconds = sleep, clock, discover_seconds
        package_src = Path(robot_debug.__file__).resolve().parents[1]
        self.source_root = Path(source_root) if source_root else package_src
        self._lock = threading.Lock()
        self._children: Dict[str, Any] = {}              # launch folder name -> (process handle, launch folder)
        self._children_lock = threading.Lock()

    # -- what is running -------------------------------------------------------------------------------

    def active(self) -> List[Dict[str, Any]]:
        return processes.active_runs(self.runs_root, self.probe)

    def busy(self) -> bool:
        """Whether a new run must wait: a run's process is alive, or a spawned child has not yet reported its run
        folder (a slow start that gave up waiting, 504, can still become a paid run)."""

        return bool(self.active()) or self._launching()

    @staticmethod
    def _reported(launch_dir: Path) -> Optional[str]:
        try:
            return (launch_dir / RUN_DIR_FILE).read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    def _settle(self, launch_dir: Path, reported: Optional[str]) -> None:
        """A launch is over: the child reported its folder (link its log now) or it is gone."""

        if reported:
            self._link(self.runs_root / Path(reported).name, launch_dir / RUN_LOG, launch_dir)
        try:
            (launch_dir / PENDING_FILE).unlink()
        except OSError:
            pass

    def _launching(self) -> bool:
        pending = False
        with self._children_lock:
            for name, (process, launch_dir) in list(self._children.items()):
                reported = self._reported(launch_dir)
                if reported or process.poll() is not None:
                    del self._children[name]
                    self._settle(launch_dir, reported)
                else:
                    pending = True
            owned = set(self._children)
        try:                                              # children of an earlier viewer process
            records = [p for p in self.specs.specs_ui.glob("*/" + PENDING_FILE) if p.parent.name not in owned]
        except OSError:
            records = []
        for record_file in records:
            launch_dir = record_file.parent
            reported = self._reported(launch_dir)
            try:
                record = json.loads(record_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                record = None
            if reported or not processes.process_alive(record, self.probe):
                self._settle(launch_dir, reported)
            else:
                pending = True
        return pending

    def _refuse_if_busy(self) -> None:
        if self.busy():
            raise ApiError(409, "Another run is active. Stop it or wait for it to finish before starting another.")

    # -- spawning -----------------------------------------------------------------------------------------

    def _env(self) -> Dict[str, str]:
        env = dict(self.base_env)
        env["PYTHONUNBUFFERED"] = "1"                          # the run page tails this log as it grows
        env["PYTHONIOENCODING"] = "utf-8"
        if (self.source_root.parent / "pyproject.toml").is_file():       # a source checkout: import this copy
            env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(self.source_root), env.get("PYTHONPATH", "")]))
        return env

    def _cwd(self) -> Optional[str]:
        root = self.source_root.parent
        return str(root) if (root / "pyproject.toml").is_file() else None

    def env_path(self) -> Path:
        """The dotenv file runs read: the one given, else ``.env`` in the project folder (or where the viewer runs)."""

        if self.env_file is not None:
            return self.env_file
        return Path(self._cwd() or os.getcwd()) / ".env"

    def _env_file_args(self) -> List[str]:
        if self.env_file is not None or self.env_path().is_file():
            return ["--env-file", str(self.env_path())]
        return []

    def _spawn(self, args: List[str], launch_dir: Path) -> str:
        """Start ``python -m robot_debug.cli <args>`` detached, wait for it to report its run folder and return
        the folder's name. The caller holds the start lock."""

        launch_dir = Path(launch_dir).resolve()
        launch_file = launch_dir / RUN_DIR_FILE
        log_path = launch_dir / RUN_LOG
        argv = [self.python, "-m", "robot_debug.cli"] + args + self._env_file_args() + [
            "--runs-root", str(self.runs_root.resolve()), "--run-dir-file", str(launch_file.resolve())]
        with open(str(log_path), "ab") as log:
            try:
                process = self.popen(argv, stdout=log, stderr=subprocess.STDOUT, env=self._env(), cwd=self._cwd(),
                                     **popen_options(self.win32))
            except OSError:
                if not self.win32:
                    raise ApiError(500, "The run could not be started on this machine.") from None
                try:                    # a job object that forbids breaking away: start inside it instead
                    process = self.popen(argv, stdout=log, stderr=subprocess.STDOUT, env=self._env(),
                                         cwd=self._cwd(), **popen_options(self.win32, breakaway=False))
                except OSError:
                    raise ApiError(500, "The run could not be started on this machine.") from None
                log.write(b"note: this run could not leave the control panel's process group; stopping the panel "
                          b"stops it too (resume re-attaches)\n")
                log.flush()
        self._remember(process, launch_dir)
        deadline = self.clock() + self.discover_seconds
        while True:
            try:
                reported = launch_file.read_text(encoding="utf-8").strip()
            except OSError:
                reported = ""
            if reported:
                run = Path(reported).name
                self._forget(launch_dir)
                self._link(self.runs_root / run, log_path, launch_dir)
                return run
            if process.poll() is not None:
                self._forget(launch_dir)
                raise ApiError(500, "The run did not start. {}".format(self._failure_line(log_path)))
            if self.clock() >= deadline:
                self._link(None, log_path, launch_dir)      # the log stays findable though no run folder exists yet
                raise ApiError(504, "The run was started but has not reported its folder yet. It counts as running, "
                                    "so nothing else can start until it reports or ends; its log is in the launch "
                                    "folder.", extra={"launch": launch_dir.name})
            self.sleep(DISCOVER_POLL_SECONDS)

    def _remember(self, process: Any, launch_dir: Path) -> None:
        """Keep the child's handle and a pending record (for a restarted viewer) until it reports or ends."""

        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        try:
            (launch_dir / PENDING_FILE).write_text(
                json.dumps({"pid": getattr(process, "pid", None), "started_at": stamp}), encoding="utf-8")
        except OSError:
            pass
        with self._children_lock:
            self._children[launch_dir.name] = (process, launch_dir)

    def _forget(self, launch_dir: Path) -> None:
        with self._children_lock:
            self._children.pop(launch_dir.name, None)
        try:
            (launch_dir / PENDING_FILE).unlink()
        except OSError:
            pass

    @staticmethod
    def _failure_line(log_path: Path) -> str:
        try:
            lines = [line.strip() for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                     if line.strip()]
        except OSError:
            return ""
        return processes.scrub_text(lines[-1])[:300] if lines else ""

    @staticmethod
    def _link(run_dir: Optional[Path], log_path: Path, launch_dir: Path) -> None:
        """Tell the run folder where its UI log is (``ui-launch.json``), so the progress page can tail it. With no
        run folder yet, the record goes in the launch folder itself."""

        try:
            ((run_dir or launch_dir) / processes.LAUNCH_FILE).write_text(
                json.dumps({"log": str(log_path.resolve()), "launch": str(launch_dir.resolve())}), encoding="utf-8")
        except OSError:
            pass

    # -- the four actions ----------------------------------------------------------------------------------

    def start(self, spec_path: Path, launch_dir: Path, *, no_llm: bool = False) -> str:
        """``faultline diagnose SPEC``; returns the run folder name. 409 while any run is active."""

        if not self._lock.acquire(blocking=False):
            raise ApiError(409, "Another run is being started.")
        try:
            self._refuse_if_busy()
            return self._spawn(["diagnose", str(Path(spec_path).resolve())] + (["--no-llm"] if no_llm else []),
                               launch_dir)
        finally:
            self._lock.release()

    def replay(self, case_dir: Path, spec_path: Path, launch_dir: Path, expect: Optional[str] = None) -> str:
        """``faultline replay CASE --spec SPEC [--expect ...]``."""

        if expect not in (None, "reproduces", "fixed"):
            raise ApiError(400, "expect must be reproduces or fixed.")
        if not self._lock.acquire(blocking=False):
            raise ApiError(409, "Another run is being started.")
        try:
            self._refuse_if_busy()
            args = ["replay", str(Path(case_dir).resolve()), "--spec", str(Path(spec_path).resolve())] + (
                ["--expect", expect] if expect else [])
            return self._spawn(args, launch_dir)
        finally:
            self._lock.release()

    def resume(self, run: str) -> str:
        """``faultline diagnose --resume RUN_DIR``; the run keeps its folder."""

        folder = self._folder(run)
        if processes.recorded_process(folder, self.probe) is not None:
            raise ApiError(409, "This run is still running.")
        progress = processes.run_progress(self.runs_root, run, self.probe)
        if progress["status"] == "completed":
            raise ApiError(409, "This run already finished; there is nothing to resume.")
        if progress["mode"] == "replay":
            raise ApiError(409, "A replay cannot be resumed; start it again from its case.")
        if not self._lock.acquire(blocking=False):
            raise ApiError(409, "Another run is being started.")
        try:
            self._refuse_if_busy()
            launch_dir = self.specs.new_directory(progress["name"] + "-resume")
            no_llm = (processes.read_run_header(folder) or {}).get("no_llm") is True      # as the run started
            self._spawn(["diagnose", "--resume", str(folder.resolve())] + (["--no-llm"] if no_llm else []), launch_dir)
            return run
        finally:
            self._lock.release()

    def stop(self, run: str) -> Dict[str, str]:
        """Ask the run's process to stop (``stop-request.json``); it cancels its Job and ends by itself."""

        folder = self._folder(run)
        if processes.recorded_process(folder, self.probe) is None:
            raise ApiError(409, "This run is not running.")
        orch.request_stop(folder)
        return {"status": "stopping"}

    def _folder(self, run: str) -> Path:
        try:
            return processes.run_folder(self.runs_root, run)
        except ValueError:
            raise ApiError(404, "There is no such run.") from None
        except FileNotFoundError:
            raise ApiError(404, "There is no such run.") from None
