"""Run a diagnosis Job as a local Docker container on an NVIDIA GPU.

UNTESTED ON A REAL GPU: the development machine has no suitable GPU, so this
backend is verified only against a fake ``docker``. It runs the same image and
entrypoint as the Nebius Serverless Job, with the workload file mounted
read-only at ``/etc/faultline/workload.json`` and a per-Job folder mounted at
``/persistent`` so the Job's export lands in the run folder.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Callable, Dict, Mapping, Optional

from . import (
    BackendError,
    JobHandle,
    JobResult,
    check_job,
    iso_utc,
    redact,
    run_command,
    write_workload,
)

ENTRYPOINT = "/opt/conda/envs/libero/bin/python"
SCRIPT_ARGS = ["/opt/robot-debug/scripts/run_serverless_workload.py",
               "--config", "/etc/faultline/workload.json"]
STOP_GRACE_SECONDS = 30
KILL_GRACE_SECONDS = 60.0
TOKEN_VARIABLE = "HF_TOKEN"


class _Running:
    def __init__(self, process: Any, started: float, log: Any) -> None:
        self.process = process
        self.started = started
        self.log = log


class LocalBackend:
    """Docker backend. ``runner`` runs short docker commands; ``popen`` starts a container."""

    kind = "local"

    def __init__(
        self,
        image: str,
        *,
        docker: str = "docker",
        runner: Optional[Callable[..., Any]] = None,
        popen: Optional[Callable[..., Any]] = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        environ: Optional[Mapping[str, str]] = None,
        shm_size: str = "16g",
    ) -> None:
        self.image = image
        self._docker = docker
        self._run = runner or run_command
        self._popen = popen or subprocess.Popen
        self._clock = clock
        self._sleep = sleep
        self._environ = os.environ if environ is None else environ
        self._shm_size = shm_size
        self._run_dir: Optional[Path] = None
        self._running: Dict[str, _Running] = {}

    @classmethod
    def from_spec(cls, spec: Mapping[str, Any]) -> "LocalBackend":
        backend = spec.get("backend", {})
        image = backend.get("image")
        if not isinstance(image, str) or not image:
            raise BackendError("backend.image is required for the local backend")
        executable = backend.get("docker_executable", "docker")
        return cls(image, docker=str(executable))

    # -- Backend protocol -------------------------------------------------

    def prepare(self, run_dir: Path, spec: Mapping[str, Any]) -> None:
        try:
            result = self._run([self._docker, "info", "--format", "{{json .Runtimes}}"], timeout=60)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as error:
            raise BackendError("docker is not available: %s" % type(error).__name__) from error
        if result.returncode != 0:
            raise BackendError("docker info failed; is the Docker daemon running?")
        try:
            runtimes = json.loads(result.stdout or "{}")
        except ValueError:
            runtimes = {}
        if not isinstance(runtimes, dict) or "nvidia" not in runtimes:
            raise BackendError(
                "docker shows no nvidia runtime; install the NVIDIA Container Toolkit "
                "and a GPU driver, or use the nebius backend"
            )
        self._run_dir = Path(run_dir)

    def submit(self, job_name: str, workload: Mapping[str, Any]) -> JobHandle:
        run_dir = self._need_run_dir()
        check_job(job_name, workload)
        if not self._environ.get(TOKEN_VARIABLE):
            raise BackendError("%s is not set; export your Hugging Face token first" % TOKEN_VARIABLE)
        job_dir = run_dir / "jobs" / job_name
        persistent = job_dir / "persistent"
        persistent.mkdir(parents=True, exist_ok=True)
        workload_file = job_dir / "workload.json"
        write_workload(workload_file, workload)
        argv = [
            self._docker, "run", "--rm", "--name", job_name,
            "--gpus", "all", "--shm-size", self._shm_size,
            "--env", TOKEN_VARIABLE,
            "--mount", "type=bind,source=%s,target=/etc/faultline/workload.json,readonly" % workload_file,
            "--mount", "type=bind,source=%s,target=/persistent" % persistent,
            "-w", "/opt/robot-debug", "--entrypoint", ENTRYPOINT,
            self.image, *SCRIPT_ARGS,
        ]
        log = open(job_dir / "container.log", "ab")
        try:
            process = self._popen(
                argv, stdout=log, stderr=subprocess.STDOUT,
                env={**self._environ},
            )
        except (OSError, ValueError) as error:
            log.close()
            raise BackendError("could not start docker: %s" % type(error).__name__) from error
        self._running[job_name] = _Running(process, self._clock(), log)
        return JobHandle(job_name, job_name)

    def wait(self, handle: JobHandle, *, running_max_seconds: float,
             total_max_seconds: float, poll_seconds: float = 60.0) -> JobResult:
        running = self._running.get(handle.job_name)
        if running is None:
            # A container started by an earlier process cannot be observed here.
            return JobResult(handle.job_name, handle.job_id, "UNKNOWN",
                             "not_started_by_this_process", None, None, None)
        process = running.process
        cancelled_at: Optional[float] = None
        step = max(0.1, min(float(poll_seconds), 5.0))
        while True:
            code = process.poll()
            now = self._clock()
            if code is not None:
                break
            if cancelled_at is None:
                elapsed = now - running.started
                if elapsed > running_max_seconds or elapsed > total_max_seconds:
                    cancelled_at = now
                    self._stop(handle.job_name)
            elif now - cancelled_at > KILL_GRACE_SECONDS:
                self._kill(handle.job_name, process)
                self._finish_log(running)
                return self._result(handle, running, "TIMEOUT", "watchdog_cancel", now)
            self._sleep(step)
        self._finish_log(running)
        now = self._clock()
        if cancelled_at is not None:
            return self._result(handle, running, "CANCELLED", "watchdog_cancel", now)
        if code == 0:
            return self._result(handle, running, "COMPLETED", None, now)
        return self._result(handle, running, "FAILED", "ContainerFailed", now)

    def download(self, handle: JobHandle, dest: Path) -> Path:
        run_dir = self._need_run_dir()
        source = run_dir / "jobs" / handle.job_name / "persistent" / "faultline-runs" / handle.job_name
        if not source.is_dir():
            raise BackendError("the job exported no evidence for %s" % handle.job_name)
        for path in source.rglob("*"):
            if path.is_symlink():
                raise BackendError("refusing to copy a symbolic link from the job export")
        dest = Path(dest)
        shutil.copytree(source, dest, dirs_exist_ok=True)
        return dest

    def logs_tail(self, handle: JobHandle, lines: int = 200) -> str:
        run_dir = self._need_run_dir()
        log = run_dir / "jobs" / handle.job_name / "container.log"
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return "\n".join(text.splitlines()[-max(1, lines):])

    def cancel(self, handle: JobHandle) -> None:
        self._stop(handle.job_name)

    def finish(self) -> None:
        for running in self._running.values():
            self._finish_log(running)

    def price_per_hour(self) -> float:
        return 0.0

    # -- internals ----------------------------------------------------------

    def _need_run_dir(self) -> Path:
        if self._run_dir is None:
            raise BackendError("backend.prepare() must be called first")
        return self._run_dir

    def _stop(self, job_name: str) -> None:
        try:
            self._run([self._docker, "stop", "-t", str(STOP_GRACE_SECONDS), job_name],
                      timeout=STOP_GRACE_SECONDS + 30)
        except (OSError, subprocess.TimeoutExpired):
            pass  # best effort; wait() escalates to kill

    def _kill(self, job_name: str, process: Any) -> None:
        try:
            self._run([self._docker, "kill", job_name], timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            pass
        process.kill()

    @staticmethod
    def _finish_log(running: _Running) -> None:
        try:
            running.log.close()
        except OSError:
            pass

    def _result(self, handle: JobHandle, running: _Running, state: str,
                reason: Optional[str], finished: float) -> JobResult:
        return JobResult(
            job_name=handle.job_name, job_id=handle.job_id, state=state, reason=reason,
            started_at=iso_utc(running.started), finished_at=iso_utc(finished),
            container_seconds=max(0.0, finished - running.started),
        )
