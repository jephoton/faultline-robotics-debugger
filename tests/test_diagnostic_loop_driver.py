import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))


class DiagnosticLoopDriverTests(unittest.TestCase):
    def test_local_fake_policies_certify_the_same_rectangle(self):
        from scripts.run_diagnostic_loop import run_local_fixture

        outcomes = {
            "search-01": "policy_failure",
            "default": "policy_failure",
            "nominal": "success",
            "control": "success",
            "reduction-sentinel": "success",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sequential = run_local_fixture(policy="sequential", outcomes=outcomes,
                                           results_root=root / "sequential")
            adaptive = run_local_fixture(policy="adaptive", outcomes=outcomes,
                                         results_root=root / "adaptive")
        self.assertTrue(sequential["certified"])
        self.assertEqual(sequential["certified_rectangle"], adaptive["certified_rectangle"])
        self.assertTrue(sequential["controls_passed"])
        self.assertTrue(adaptive["controls_passed"])
        self.assertGreaterEqual(adaptive["physical_attempts"], adaptive["valid_episodes"])

    def test_timeout_leaves_durable_partial_noncertifying_summary(self):
        from scripts.run_diagnostic_loop import run_session
        import subprocess

        def timeout(_request, *, launch_observer, **_kwargs):
            launch_observer(9123, "vla-eval-9123")
            raise subprocess.TimeoutExpired("fake", 1)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = run_session(upstream_root=root, project_root=Path(__file__).parents[1],
                                 results_root=root, policy="sequential", launch_cutoff_seconds=600,
                                 episode_limit=20, hourly_rate_usd=1, max_estimated_usd=10,
                                 evaluator=timeout, dry_run=True)
            saved = root / result["session_id"] / "session_summary.json"
            self.assertTrue(saved.is_file())
        self.assertFalse(result["certified"])
        self.assertEqual("uncertain", result["stop_reason"])
        self.assertGreaterEqual(result["uncertain_attempts"], 1)

    def test_shared_interrupt_event_persists_partial_session(self):
        from scripts.run_diagnostic_loop import run_session
        interrupted = threading.Event()

        def active_then_interrupt(request, *, launch_observer, **_kwargs):
            launch_observer(9124, "vla-eval-9124")
            request.output_dir.mkdir(parents=True)
            evidence = request.output_dir / "aggregate.json"
            evidence.write_text("{}", encoding="utf-8")
            interrupted.set()
            return {"status": "valid", "outcome": "success", "evidence_paths": [str(evidence)]}

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = run_session(upstream_root=root, project_root=Path(__file__).parents[1],
                                 results_root=root, policy="sequential", launch_cutoff_seconds=600,
                                 episode_limit=20, hourly_rate_usd=1, max_estimated_usd=10,
                                 evaluator=active_then_interrupt, dry_run=True,
                                 interrupt_event=interrupted)
            self.assertTrue((root / result["session_id"] / "session_summary.json").is_file())
        self.assertFalse(result["certified"])
        self.assertEqual("interrupted", result["stop_reason"])

    @unittest.skipUnless(os.name == "posix", "requires real POSIX signal delivery")
    def test_cli_sigterm_contains_active_evaluator_group(self):
        """The CLI signal must reach the same lifecycle as the active child."""
        source_root = Path(__file__).parents[1]
        child_program = """
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, {source!r})
from scripts import run_diagnostic_loop as driver
from scripts import run_parallel_eval as parallel

def evaluator(_upstream):
    def run(request, *, launch_observer, lifecycle):
        parallel._run_evaluator_safely(
            [sys.executable, '-c', 'import time; time.sleep(120)'],
            cwd=Path({source!r}), check=False, timeout=120,
            docker_runner=lambda *_args, **_kwargs: SimpleNamespace(
                returncode=0, stdout='', stderr=''),
            stop_event=lifecycle.stop_requested,
            interrupt_event=lifecycle.interrupt_event,
            launch_lock=lifecycle.launch_lock,
            launch_observer=launch_observer,
            graceful_group_wait_seconds=.5,
            forced_cleanup_wait_seconds=.5,
        )
        raise AssertionError('sleep evaluator unexpectedly completed')
    return run

sys.argv = ['run_diagnostic_loop.py', '--upstream-root', {source!r},
            '--project-root', {source!r}, '--results-root', {results!r},
            '--policy', 'sequential', '--launch-cutoff-seconds', '600',
            '--episode-limit', '100', '--hourly-rate-usd', '1',
            '--max-estimated-usd', '10']
with patch.object(driver, '_production_evaluator', evaluator):
    driver.main()
""".format(source=str(source_root), results="{results}")
        with tempfile.TemporaryDirectory() as temporary:
            results_root = Path(temporary) / "signal-run"
            program = child_program.replace("{results}", str(results_root))
            process = subprocess.Popen([sys.executable, "-c", program], cwd=source_root,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            evaluator_pid = None
            try:
                deadline = time.monotonic() + 20
                sidecars = []
                while time.monotonic() < deadline and process.poll() is None:
                    sidecars = list(results_root.glob(
                        "diagnostic-sequential-*/rounds/round-0001/launches/nominal-01.json"))
                    if sidecars:
                        break
                    time.sleep(.05)
                self.assertEqual(1, len(sidecars), "active evaluator did not publish its identity")
                evaluator_pid = json.loads(sidecars[0].read_text(encoding="utf-8"))["evaluator_pid"]
                os.kill(process.pid, signal.SIGTERM)
                _stdout, stderr = process.communicate(timeout=30)
                self.assertEqual(1, process.returncode, stderr)
                summary_path = next(results_root.glob("diagnostic-sequential-*/session_summary.json"))
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                self.assertEqual("interrupted", summary["stop_reason"])
                self.assertFalse(summary["certified"])
                with self.assertRaises(ProcessLookupError):
                    os.kill(evaluator_pid, 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)
                if evaluator_pid is not None:
                    try:
                        os.killpg(evaluator_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass


if __name__ == "__main__":
    unittest.main()
