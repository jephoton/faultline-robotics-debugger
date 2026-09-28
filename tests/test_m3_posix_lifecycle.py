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
            child = (
                "import pathlib, time; "
                "time.sleep(0.5); "
                f"pathlib.Path({str(marker)!r}).write_text('ran', encoding='utf-8')"
            )
            parent = (
                "import signal, subprocess, sys, time; "
                f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
                "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0)); "
                "time.sleep(10)"
            )
            processes = []

            def process_factory(*args, **kwargs):
                process = subprocess.Popen(*args, **kwargs)
                processes.append(process)
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
                        if process.poll() is None:
                            os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except PermissionError:
                        pass
                    process.wait(timeout=1)

