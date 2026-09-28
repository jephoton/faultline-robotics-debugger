"""POSIX regression coverage for evaluator process-group containment."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest


@unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
class EvaluatorProcessGroupLifecycleTests(unittest.TestCase):
    def test_timeout_prevents_descendant_delayed_action(self):
        """The evaluator's SIGTERM must cover its child, not just its parent."""
        script_path = Path(__file__).parents[1] / "scripts" / "run_parallel_eval.py"
        spec = importlib.util.spec_from_file_location("m3_lifecycle_runner", script_path)
        runner = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = runner
        spec.loader.exec_module(runner)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "descendant-ran"
            ready = root / "parent-ready"
            child = (
                "import pathlib, time; "
                "time.sleep(0.5); "
                f"pathlib.Path({str(marker)!r}).write_text('ran', encoding='utf-8'); "
                "time.sleep(0.1)"
            )
            parent = (
                "import os, pathlib, signal, subprocess, sys, time; "
                "\ntry: os.setpgrp()\nexcept PermissionError: pass\n"
                f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
                "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0)); "
                f"pathlib.Path({str(ready)!r}).write_text('ready', encoding='utf-8'); "
                "time.sleep(10)"
            )
            def process_factory(*args, **kwargs):
                process = subprocess.Popen(*args, **kwargs)
                deadline = time.monotonic() + 2
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                if not ready.exists():
                    # This factory still owns an unreaped session leader, so
                    # this exact group cannot have been reused yet.
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=1)
                    self.fail("evaluator parent did not install its SIGTERM handler")
                return process

            with self.assertRaises(subprocess.TimeoutExpired):
                runner._run_evaluator_safely(
                    [sys.executable, "-c", parent], cwd=root, check=False, timeout=0.1,
                    process_factory=process_factory,
                    graceful_group_wait_seconds=0.2,
                    docker_runner=lambda *args, **kwargs: SimpleNamespace(
                        returncode=0, stdout="", stderr=""),
                )
            # The fixture's child exits naturally within 0.6 seconds.  Never
            # signal a numeric PID or PGID after the helper may have reaped
            # its session leader.
            time.sleep(0.7)
            self.assertFalse(marker.exists(), "a descendant survived evaluator cleanup")

    def test_pilot_cli_sigterm_persists_partial_summary_and_cleans_active_child(self):
        """The pilot command retains its partial record after SIGTERM cleanup."""
        script_path = Path(__file__).parents[1] / "scripts" / "run_parallel_eval.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upstream = root / "upstream"; upstream.mkdir()
            project = root / "project"; project.mkdir()
            results = root / "results"
            ready = root / "evaluator-ready"
            stopped = root / "evaluator-stopped"
            child = f'''
import importlib.util, subprocess, sys, time
from pathlib import Path
spec = importlib.util.spec_from_file_location("pilot_signal_child", {str(script_path)!r})
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
ready = Path({str(ready)!r})
stopped = Path({str(stopped)!r})
def fake_evaluator(argv, *, cwd, check, timeout, stop_event=None, interrupt_event=None, launch_lock=None, launch_observer=None):
    evaluator = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    launch_observer(evaluator.pid, f"vla-eval-{{evaluator.pid}}")
    ready.write_text(str(evaluator.pid), encoding="utf-8")
    while not interrupt_event.is_set():
        time.sleep(.01)
    evaluator.terminate()
    evaluator.wait(timeout=2)
    stopped.write_text("stopped", encoding="utf-8")
    error = module._EvaluatorInterrupted("session interrupted")
    error.cleanup_confirmed = True
    error.cleanup_error = None
    error.evaluator_pid = evaluator.pid
    error.expected_container = f"vla-eval-{{evaluator.pid}}"
    raise error
module._run_evaluator_safely = fake_evaluator
sys.argv = ["run_parallel_eval.py", "pilot", "--upstream-root", {str(upstream)!r},
    "--project-root", {str(project)!r}, "--results-root", {str(results)!r},
    "--launch-cutoff-seconds", "60", "--item-timeout-seconds", "5"]
module.main()
'''
            runner = subprocess.Popen([sys.executable, "-c", child], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
                env={**os.environ, "PYTHONPATH": str(script_path.parents[1] / "src")})
            evaluator_pid = None
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(ready.exists(), "fake evaluator did not become active")
                evaluator_pid = int(ready.read_text(encoding="utf-8"))
                os.kill(runner.pid, signal.SIGTERM)
                stdout, stderr = runner.communicate(timeout=10)
            finally:
                if runner.poll() is None:
                    runner.kill()
                    runner.communicate(timeout=2)
                if evaluator_pid is not None and not stopped.exists():
                    try:
                        os.kill(evaluator_pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
            self.assertEqual(1, runner.returncode, stderr)
            self.assertTrue(stopped.exists())
            self.assertIn("stop: interrupted", stdout)
            with self.assertRaises(ProcessLookupError):
                os.kill(evaluator_pid, 0)
            summary = json.loads((results / "m3-pilot-workers-2" / "session_summary.json").read_text())
            self.assertEqual("pilot", summary["purpose"])
            self.assertEqual("interrupted", summary["stop_reason"])
            self.assertEqual([], summary["in_flight_ids"])
            self.assertEqual(0, summary["valid_count"])
