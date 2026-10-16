"""Detached launch, the one-run lock, stop and resume (ADR 0033), with a fake Popen and fake clocks."""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any, List

from robot_debug.viewer import launcher as lc
from robot_debug.viewer import processes
from robot_debug.viewer.security import ApiError
from robot_debug.viewer.specs import SpecService

NOW = dt.datetime(2026, 10, 17, 1, 2, 3, tzinfo=dt.timezone.utc)
SOURCE = Path(__file__).resolve().parents[1] / "src"


class FakeProcess:
    def __init__(self, exit_code=None):
        self.exit_code, self.pid = exit_code, 999999

    def poll(self):
        return self.exit_code


class FakePopen:
    """Records the launch and plays the child's part: create the run folder, report it, record the process."""

    def __init__(self, runs: Path, behaviour="normal", run_name="demo-20261017T010203Z"):
        self.runs, self.behaviour, self.run_name = runs, behaviour, run_name
        self.calls: List[dict] = []
        self.children: List[FakeProcess] = []

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": list(argv), **kwargs})
        child = self._child(argv, kwargs)
        self.children.append(child)
        return child

    def _child(self, argv, kwargs):
        if self.behaviour == "oserror":
            raise FileNotFoundError("python")
        if self.behaviour == "exit":
            kwargs["stdout"].write(b"error: spec: budget.max_spend_usd: must be positive\n")
            kwargs["stdout"].flush()
            return FakeProcess(exit_code=2)
        if self.behaviour == "silent":
            return FakeProcess()
        folder = self.runs / self.run_name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "steps.json").write_text(json.dumps({"schema_version": 1, "name": "demo", "mode": "scenario", "steps": {}}),
                                           encoding="utf-8")
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        (folder / "process.json").write_text(json.dumps({"pid": os.getpid(), "started_at": stamp, "command": "diagnose"}),
                                             encoding="utf-8")
        target = argv[argv.index("--run-dir-file") + 1]
        Path(target).write_text(str(folder), encoding="utf-8")
        return FakeProcess()


class Ticker:
    """A clock that advances when slept on, so the discovery loop ends without real waiting."""

    def __init__(self):
        self.now = 0.0

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class LauncherCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "artifacts"
        self.runs = self.root / "runs"
        self.runs.mkdir(parents=True)
        self.specs = SpecService(self.root, clock=lambda: NOW)
        self.ticker = Ticker()

    def make(self, behaviour="normal", **options):
        self.popen = FakePopen(self.runs, behaviour)
        options.setdefault("popen", self.popen)
        options.setdefault("env", {"PATH": "/bin", "HOME": "/home/fake"})
        options.setdefault("env_file", self.root.parent / ".env")
        options.setdefault("sleep", self.ticker.sleep)
        options.setdefault("clock", self.ticker.clock)
        options.setdefault("discover_seconds", 5.0)
        options.setdefault("win32", False)
        options.setdefault("source_root", SOURCE)
        return lc.Launcher(self.root, self.runs, self.specs, **options)

    def launch_dir(self, name="demo"):
        directory = self.specs.new_directory(name)
        return directory, directory / "spec.yaml"

    def make_run(self, name="old-20261016T010203Z", mode="scenario", run=None, process=False, steps=None):
        folder = self.runs / name
        folder.mkdir(parents=True)
        data = {"schema_version": 1, "name": name.rsplit("-", 1)[0], "mode": mode, "steps": steps or {}}
        if run is not None:
            data["run"] = run
        (folder / "steps.json").write_text(json.dumps(data), encoding="utf-8")
        if process:
            stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            (folder / "process.json").write_text(json.dumps(
                {"pid": os.getpid(), "started_at": stamp, "command": "diagnose"}), encoding="utf-8")
        return folder


class StartTests(LauncherCase):
    def test_the_command_line_is_the_one_a_terminal_would_use(self):
        launcher = self.make()
        directory, spec = self.launch_dir()
        run = launcher.start(spec, directory)
        self.assertEqual(run, "demo-20261017T010203Z")
        argv = self.popen.calls[0]["argv"]
        self.assertEqual(argv[:5], [launcher.python, "-m", "robot_debug.cli", "diagnose", str(spec)])
        self.assertEqual(argv[argv.index("--runs-root") + 1], str(self.runs.resolve()))
        self.assertEqual(argv[argv.index("--run-dir-file") + 1], str((directory / "run-dir.txt").resolve()))
        self.assertEqual(argv.count("--runs-root"), 1)

    def test_the_env_file_is_passed_when_it_exists_and_nothing_secret_is_in_the_command(self):
        env_file = self.root.parent / ".env"
        env_file.write_text("NEBIUS_API_KEY=FAKE-SECRET-VALUE\n", encoding="utf-8")
        launcher = self.make(env_file=env_file)
        directory, spec = self.launch_dir()
        launcher.start(spec, directory)
        argv = self.popen.calls[0]["argv"]
        self.assertEqual(argv[argv.index("--env-file") + 1], str(env_file))
        self.assertNotIn("FAKE-SECRET-VALUE", " ".join(argv))
        self.assertNotIn("FAKE-SECRET-VALUE", json.dumps({k: str(v) for k, v in self.popen.calls[0]["env"].items()}))

    def test_the_project_dotenv_is_used_only_when_it_exists(self):
        project = self.root.parent / "project"
        (project / "src").mkdir(parents=True)
        (project / "pyproject.toml").write_text("", encoding="utf-8")
        directory, spec = self.launch_dir()
        launcher = self.make(env_file=None, source_root=project / "src")
        launcher.start(spec, directory)
        self.assertNotIn("--env-file", self.popen.calls[0]["argv"])
        (project / ".env").write_text("NEBIUS_API_KEY=x\n", encoding="utf-8")
        self.ticker.now = 0
        self.runs_cleanup()
        launcher = self.make(env_file=None, source_root=project / "src")
        directory, spec = self.launch_dir("again")
        launcher.start(spec, directory)
        argv = self.popen.calls[0]["argv"]
        self.assertEqual(argv[argv.index("--env-file") + 1], str(project / ".env"))

    def runs_cleanup(self):
        for folder in self.runs.iterdir():
            (folder / "process.json").unlink(missing_ok=True)

    def test_no_llm_is_passed_on(self):
        directory, spec = self.launch_dir()
        self.make().start(spec, directory, no_llm=True)
        self.assertIn("--no-llm", self.popen.calls[0]["argv"])

    def test_windows_detaches_with_a_new_process_group_and_no_console(self):
        launcher = self.make(win32=True)
        directory, spec = self.launch_dir()
        launcher.start(spec, directory)
        call = self.popen.calls[0]
        self.assertEqual(call["creationflags"], 0x200 | 0x8)
        self.assertNotIn("start_new_session", call)
        self.assertTrue(call["close_fds"])
        self.assertEqual(call["stdin"], subprocess.DEVNULL)
        self.assertEqual(call["stderr"], subprocess.STDOUT)

    def test_posix_starts_a_new_session(self):
        launcher = self.make(win32=False)
        directory, spec = self.launch_dir()
        launcher.start(spec, directory)
        call = self.popen.calls[0]
        self.assertTrue(call["start_new_session"])
        self.assertNotIn("creationflags", call)
        self.assertTrue(call["close_fds"])
        self.assertEqual(call["stdin"], subprocess.DEVNULL)

    def test_output_goes_to_a_log_in_the_launch_folder_and_the_environment_is_unbuffered_utf8(self):
        directory, spec = self.launch_dir()
        self.make().start(spec, directory)
        call = self.popen.calls[0]
        self.assertTrue((directory / "run.log").is_file())
        self.assertEqual(Path(call["stdout"].name), directory / "run.log")
        self.assertEqual((call["env"]["PYTHONUNBUFFERED"], call["env"]["PYTHONIOENCODING"]), ("1", "utf-8"))
        self.assertTrue(call["env"]["PYTHONPATH"].startswith(str(SOURCE)), "the source checkout is imported")
        self.assertEqual(call["cwd"], str(SOURCE.parent))

    def test_the_run_folder_is_linked_to_its_log_for_the_progress_page(self):
        directory, spec = self.launch_dir()
        run = self.make().start(spec, directory)
        (directory / "run.log").write_text("10:15 screen ... submitted\n", encoding="utf-8")
        progress = processes.run_progress(self.runs, run, lambda pid: processes.ProcessInfo(pid == os.getpid(), None))
        self.assertEqual(progress["log_tail"], ["10:15 screen ... submitted"])
        self.assertTrue((self.runs / run / "ui-launch.json").is_file())

    def test_a_second_start_is_refused_while_any_run_is_alive(self):
        self.make_run("terminal-20261017T000000Z", process=True)
        launcher = self.make()
        directory, spec = self.launch_dir()
        with self.assertRaises(ApiError) as caught:
            launcher.start(spec, directory)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.popen.calls, [])

    def test_two_starts_at_once_launch_one(self):
        launcher = self.make()
        directory, spec = self.launch_dir()
        gate, entered = threading.Event(), threading.Event()
        real = launcher._spawn

        def slow(args, launch):
            entered.set()
            gate.wait(5)
            return real(args, launch)

        launcher._spawn = slow
        outcome: List[Any] = []
        first = threading.Thread(target=lambda: outcome.append(launcher.start(spec, directory)))
        first.start()
        self.assertTrue(entered.wait(5))
        with self.assertRaises(ApiError) as caught:
            launcher.start(spec, directory)
        self.assertEqual(caught.exception.status, 409)
        gate.set()
        first.join(5)
        self.assertEqual(len(outcome), 1)
        self.assertEqual(len(self.popen.calls), 1)

    def test_a_child_that_exits_early_reports_its_last_line_without_paths(self):
        launcher = self.make("exit")
        directory, spec = self.launch_dir()
        with self.assertRaises(ApiError) as caught:
            launcher.start(spec, directory)
        self.assertEqual(caught.exception.status, 500)
        self.assertIn("budget.max_spend_usd: must be positive", caught.exception.message)

    def test_a_child_that_never_reports_a_folder_times_out_with_a_plain_message(self):
        launcher = self.make("silent")
        directory, spec = self.launch_dir()
        with self.assertRaises(ApiError) as caught:
            launcher.start(spec, directory)
        self.assertEqual(caught.exception.status, 504)
        self.assertGreaterEqual(self.ticker.now, 5.0)

    def test_python_that_cannot_start_is_a_plain_500(self):
        launcher = self.make("oserror")
        directory, spec = self.launch_dir()
        with self.assertRaises(ApiError) as caught:
            launcher.start(spec, directory)
        self.assertEqual(caught.exception.status, 500)
        self.assertNotIn("python", caught.exception.message.lower().replace("could not be started on this machine", ""))

    def test_a_real_detached_child_runs_and_its_output_is_captured(self):
        log = Path(tempfile.mkdtemp()) / "child.log"
        with open(str(log), "ab") as stream:
            process = subprocess.Popen([sys.executable, "-c", "print('detached ok')"], stdout=stream,
                                       stderr=subprocess.STDOUT, **lc.popen_options(sys.platform == "win32"))
        self.assertEqual(process.wait(30), 0)
        self.assertIn("detached ok", log.read_text(encoding="utf-8"))


class SlowStartTests(LauncherCase):
    """A start that gives up waiting (504) leaves a child that may still become a paid run (review H1)."""

    def slow_start(self, launcher=None):
        launcher = launcher or self.make("silent")
        directory, spec = self.launch_dir("slow")
        with self.assertRaises(ApiError) as caught:
            launcher.start(spec, directory)
        self.assertEqual(caught.exception.status, 504)
        return launcher, directory, caught.exception

    def test_the_timeout_names_the_launch_folder_and_keeps_its_log_findable(self):
        _launcher, directory, error = self.slow_start()
        self.assertEqual(error.payload()["launch"], directory.name)
        link = json.loads((directory / processes.LAUNCH_FILE).read_text(encoding="utf-8"))
        self.assertEqual(Path(link["log"]), (directory / "run.log").resolve())

    def test_a_start_after_a_timeout_is_refused_while_the_child_may_still_report(self):
        launcher, _directory, _error = self.slow_start()
        other, spec = self.launch_dir("second")
        with self.assertRaises(ApiError) as caught:
            launcher.start(spec, other)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(len(self.popen.calls), 1, "no second run was spawned")

    def test_a_resume_and_a_replay_are_refused_too(self):
        launcher, _directory, _error = self.slow_start()
        stopped = self.make_run(run={"status": "stopped", "reason": "stopped_by_user"})
        with self.assertRaises(ApiError) as resumed:
            launcher.resume(stopped.name)
        other, spec = self.launch_dir("replay")
        with self.assertRaises(ApiError) as replayed:
            launcher.replay(self.root, spec, other)
        self.assertEqual((resumed.exception.status, replayed.exception.status), (409, 409))
        self.assertEqual(len(self.popen.calls), 1)

    def test_busy_covers_a_pending_launch_that_active_runs_cannot_see(self):
        launcher, _directory, _error = self.slow_start()
        self.assertEqual(launcher.active(), [])
        self.assertTrue(launcher.busy())

    def test_the_launch_ends_when_the_child_exits(self):
        launcher, _directory, _error = self.slow_start()
        child = self.popen.children[0]
        child.exit_code = 2
        self.assertFalse(launcher.busy())
        other, spec = self.launch_dir("again")
        self.popen.behaviour = "normal"
        launcher.start(spec, other)
        self.assertEqual(len(self.popen.calls), 2)

    def test_the_launch_ends_when_the_child_reports_its_folder_and_the_log_is_linked_then(self):
        launcher, directory, _error = self.slow_start()
        folder = self.make_run("late-20261017T010203Z")
        (directory / lc.RUN_DIR_FILE).write_text(str(folder), encoding="utf-8")
        self.assertFalse(launcher.busy(), "the run now owns its folder; process.json (if any) is what counts")
        self.assertTrue((folder / processes.LAUNCH_FILE).is_file())
        self.assertFalse((directory / lc.PENDING_FILE).exists())

    def test_a_restarted_viewer_still_sees_the_pending_child(self):
        _launcher, directory, _error = self.slow_start()
        pid = json.loads((directory / lc.PENDING_FILE).read_text(encoding="utf-8"))["pid"]
        alive = self.make("silent", probe=lambda candidate: processes.ProcessInfo(candidate == pid, None))
        self.assertTrue(alive.busy())
        gone = self.make("silent", probe=lambda candidate: processes.ProcessInfo(False, None))
        self.assertFalse(gone.busy())

    def test_a_child_that_never_launched_leaves_no_pending_record(self):
        launcher = self.make("exit")
        directory, spec = self.launch_dir()
        with self.assertRaises(ApiError):
            launcher.start(spec, directory)
        self.assertFalse((directory / lc.PENDING_FILE).exists())
        self.assertFalse(launcher.busy())


class ReplayTests(LauncherCase):
    def test_the_replay_command(self):
        launcher = self.make()
        directory, spec = self.launch_dir("replay")
        case = self.root / "diagnoses" / ("ab" * 32)
        launcher.replay(case, spec, directory, expect="fixed")
        argv = self.popen.calls[0]["argv"]
        self.assertEqual(argv[3:8], ["replay", str(case), "--spec", str(spec), "--expect"])
        self.assertEqual(argv[8], "fixed")

    def test_expect_is_one_of_two_words(self):
        launcher = self.make()
        directory, spec = self.launch_dir("replay")
        with self.assertRaises(ApiError) as caught:
            launcher.replay(self.root, spec, directory, expect="maybe")
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(self.popen.calls, [])

    def test_a_replay_is_refused_while_a_run_is_alive(self):
        self.make_run("busy-20261017T000000Z", process=True)
        directory, spec = self.launch_dir("replay")
        with self.assertRaises(ApiError) as caught:
            self.make().replay(self.root, spec, directory)
        self.assertEqual(caught.exception.status, 409)


class StopAndResumeTests(LauncherCase):
    def test_stop_writes_the_request_for_a_live_run(self):
        folder = self.make_run(process=True)
        result = self.make().stop(folder.name)
        self.assertEqual(result, {"status": "stopping"})
        self.assertTrue((folder / "stop-request.json").is_file())

    def test_stop_of_a_run_that_is_not_running_or_does_not_exist(self):
        folder = self.make_run()
        for name, status in ((folder.name, 409), ("nothing-20261017T000000Z", 404), ("../x", 404), ("a/b", 404)):
            with self.subTest(name=name), self.assertRaises(ApiError) as caught:
                self.make().stop(name)
            self.assertEqual(caught.exception.status, status)
        self.assertFalse((folder / "stop-request.json").exists())

    def test_resume_launches_the_resume_command_in_a_new_launch_folder(self):
        folder = self.make_run(run={"status": "stopped", "reason": "stopped_by_user"})
        launcher = self.make(behaviour="normal")
        self.popen.run_name = folder.name
        run = launcher.resume(folder.name)
        self.assertEqual(run, folder.name)
        argv = self.popen.calls[0]["argv"]
        self.assertEqual(argv[3:6], ["diagnose", "--resume", str(folder.resolve())])
        launch = [p for p in (self.root / "specs-ui").iterdir()]
        self.assertEqual(len(launch), 1)
        self.assertTrue(launch[0].name.endswith("-old-resume"))
        self.assertTrue((launch[0] / "run.log").is_file())

    def test_resume_refusals(self):
        live = self.make_run("live-20261017T000000Z", process=True)
        done = self.make_run("done-20261016T000000Z", run={"status": "completed"})
        replay = self.make_run("replay-20261016T000000Z", mode="replay", run={"status": "stopped"})
        stopped = self.make_run("stopped-20261016T000001Z", run={"status": "stopped", "reason": "budget_exhausted"})
        cases = [(live.name, "still running"), (done.name, "already finished"), (replay.name, "replay cannot be resumed"),
                 (stopped.name, "Another run is active")]
        for name, words in cases:
            with self.subTest(name=name), self.assertRaises(ApiError) as caught:
                self.make().resume(name)
            self.assertEqual(caught.exception.status, 409)
            self.assertIn(words, caught.exception.message)
        self.assertEqual(self.popen.calls, [])

    def test_resume_of_an_unknown_run(self):
        with self.assertRaises(ApiError) as caught:
            self.make().resume("nothing-20261017T000000Z")
        self.assertEqual(caught.exception.status, 404)


if __name__ == "__main__":
    unittest.main()
