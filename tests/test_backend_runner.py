"""Captured CLI calls must not allocate a console for every Windows poll."""

from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from robot_debug.backends import run_command


class CapturedRunnerTests(unittest.TestCase):
    def test_windows_calls_are_windowless_without_detaching_the_child(self):
        answer = subprocess.CompletedProcess(["tool"], 3, "out", "err")
        with patch("sys.platform", "win32"), patch("robot_debug.backends.subprocess.run", return_value=answer) as run:
            result = run_command(["tool", "status"], cwd=Path("workspace"), timeout=12)
        self.assertIs(result, answer)
        self.assertEqual(run.call_args.args[0], ["tool", "status"])
        self.assertEqual(run.call_args.kwargs, {
            "cwd": "workspace", "capture_output": True, "text": True,
            "encoding": "utf-8", "errors": "replace", "timeout": 12,
            "check": False, "creationflags": 0x08000000,
        })

    def test_non_windows_calls_do_not_receive_windows_flags(self):
        with patch("sys.platform", "linux"), patch("robot_debug.backends.subprocess.run") as run:
            run_command(["tool"], timeout=4)
        self.assertNotIn("creationflags", run.call_args.kwargs)
        self.assertTrue(run.call_args.kwargs["capture_output"])
        self.assertEqual(run.call_args.kwargs["timeout"], 4)

    def test_timeout_is_still_propagated(self):
        error = subprocess.TimeoutExpired(["tool"], 2)
        with patch("sys.platform", "win32"), patch("robot_debug.backends.subprocess.run", side_effect=error):
            with self.assertRaises(subprocess.TimeoutExpired):
                run_command(["tool"], timeout=2)


if __name__ == "__main__":
    unittest.main()
