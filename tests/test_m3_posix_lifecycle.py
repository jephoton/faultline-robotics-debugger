"""POSIX regression coverage for evaluator process-group containment."""

from __future__ import annotations

import importlib.util
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
            processes = []

            def process_factory(*args, **kwargs):
                process = subprocess.Popen(*args, **kwargs)
                processes.append(process)
                deadline = time.monotonic() + 2
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                if not ready.exists():
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=1)
                    self.fail("evaluator parent did not install its SIGTERM handler")
                return process

            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    runner._run_evaluator_safely(
                        [sys.executable, "-c", parent], cwd=root, check=False, timeout=0.1,
                        process_factory=process_factory,
                        docker_runner=lambda *args, **kwargs: SimpleNamespace(
                            returncode=0, stdout="", stderr=""),
                    )
                time.sleep(0.7)
                self.assertFalse(marker.exists(), "a descendant survived evaluator cleanup")
            finally:
                for process in processes:
                    try:
                        # The evaluator made itself a process-group leader before
                        # signalling readiness, so this group is ours even after
                        # its parent has already been reaped.
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except PermissionError:
                        pass
                    process.wait(timeout=1)
