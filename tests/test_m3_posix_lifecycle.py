"""POSIX regression coverage for evaluator process-group containment."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest


@unittest.skipUnless(
    os.name == "posix" and hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"),
    "requires POSIX process groups and pidfd cleanup",
)
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
            child_pid_path = root / "descendant-pid"
            child = (
                "import os, pathlib, time; "
                f"pathlib.Path({str(child_pid_path)!r}).write_text(str(os.getpid()), encoding='utf-8'); "
                "time.sleep(0.5); "
                f"pathlib.Path({str(marker)!r}).write_text('ran', encoding='utf-8'); "
                "time.sleep(10)"
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

            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    runner._run_evaluator_safely(
                        [sys.executable, "-c", parent], cwd=root, check=False, timeout=0.1,
                        process_factory=process_factory,
                        graceful_group_wait_seconds=0.2,
                        docker_runner=lambda *args, **kwargs: SimpleNamespace(
                            returncode=0, stdout="", stderr=""),
                    )
                time.sleep(0.7)
                self.assertFalse(marker.exists(), "a descendant survived evaluator cleanup")
            finally:
                if child_pid_path.exists():
                    try:
                        child_pid = int(child_pid_path.read_text(encoding="utf-8"))
                        child_pidfd = os.pidfd_open(child_pid)
                    except ProcessLookupError:
                        child_pidfd = None
                    if child_pidfd is not None:
                        try:
                            signal.pidfd_send_signal(child_pidfd, signal.SIGKILL)
                            if not select.select([child_pidfd], [], [], 1)[0]:
                                self.fail("owned descendant did not exit after pidfd SIGKILL")
                        finally:
                            os.close(child_pidfd)
