import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))


class FakeEvaluator:
    def __init__(self):
        self.active = self.maximum_active = 0
        self.lock = threading.Lock()
        self.requests = []

    def __call__(self, request, *, launch_observer, **_kwargs):
        with self.lock:
            self.active += 1; self.maximum_active = max(self.maximum_active, self.active)
            self.requests.append(request)
            pid = 7000 + len(self.requests)
        launch_observer(pid, f"vla-eval-{pid}")
        request.output_dir.mkdir(parents=True)
        evidence = request.output_dir / "aggregate.json"
        evidence.write_text("{}", encoding="utf-8")
        with self.lock:
            self.active -= 1
        return {"status": "valid", "outcome": "success", "evidence_paths": [str(evidence)]}


class PortfolioRunnerTests(unittest.TestCase):
    def test_global_wave_uses_unique_job_requests_and_frozen_task_configs(self):
        from robot_debug.portfolio_manifest import PortfolioManifest
        from robot_debug.portfolio_runner import PortfolioLimits, run_portfolio
        manifest = PortfolioManifest(suite="libero_object", task_ids=(0, 1, 2), seed=7,
                                     family="agentview_rect_occlusion")
        evaluator = FakeEvaluator()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            summary = run_portfolio(manifest=manifest, mode="adaptive-portfolio", results_root=root,
                                    project_root=Path(__file__).parents[1], evaluator=evaluator,
                                    limits=PortfolioLimits(episodes=3, seconds=600, estimated_usd=10, hourly_rate=1))
            saved = root / summary["session_id"] / "portfolio_summary.json"
            self.assertTrue(saved.is_file())
            self.assertEqual(3, summary["physical_attempts"])
            self.assertEqual(3, len(summary["waves"][0]["requests"]))
            self.assertEqual(3, len({request.case_id for request in evaluator.requests}))
            self.assertEqual(3, len({request.output_dir for request in evaluator.requests}))
            configs = [request.config_path.read_text(encoding="utf-8") for request in evaluator.requests]
        self.assertEqual({"task-00", "task-01", "task-02"}, {request.case_id.split("--")[0] for request in evaluator.requests})
        self.assertIn("task_id: 1", "\n".join(configs)); self.assertIn("task_id: 2", "\n".join(configs))
        self.assertLessEqual(evaluator.maximum_active, 4)
        self.assertFalse(summary["certified"])

    def test_confirmation_is_buffered_per_job_until_each_five_case_gate_is_complete(self):
        from robot_debug.portfolio_manifest import PortfolioManifest
        from robot_debug.portfolio_runner import PortfolioLimits, run_portfolio
        manifest = PortfolioManifest(suite="libero_object", task_ids=(0, 1, 2), seed=7,
                                     family="agentview_rect_occlusion")
        def outcomes(request, *, launch_observer, **_kwargs):
            launch_observer(7600 + len(request.case_id), f"vla-eval-{7600 + len(request.case_id)}")
            request.output_dir.mkdir(parents=True); evidence = request.output_dir / "aggregate.json"
            evidence.write_text("{}", encoding="utf-8")
            outcome = "success" if "nominal-01" in request.case_id else "policy_failure"
            return {"status": "valid", "outcome": outcome, "evidence_paths": [str(evidence)]}
        with tempfile.TemporaryDirectory() as temporary:
            summary = run_portfolio(manifest=manifest, mode="adaptive-portfolio", results_root=Path(temporary),
                                    project_root=Path(__file__).parents[1], evaluator=outcomes,
                                    limits=PortfolioLimits(episodes=21, seconds=600, estimated_usd=10, hourly_rate=1))
        self.assertEqual(21, summary["physical_attempts"])
        self.assertTrue(all(job["flow"]["phase"] == "reduction_sentinel"
                            for job in summary["jobs"].values()))

    def test_invalid_or_timeout_round_is_partial_and_never_certified(self):
        from robot_debug.portfolio_manifest import PortfolioManifest
        from robot_debug.portfolio_runner import PortfolioLimits, run_portfolio
        manifest = PortfolioManifest(suite="libero_object", task_ids=(0, 1, 2), seed=7,
                                     family="agentview_rect_occlusion")
        def timeout(_request, *, launch_observer, **_kwargs):
            launch_observer(7999, "vla-eval-7999")
            import subprocess
            raise subprocess.TimeoutExpired("fake", 1)
        with tempfile.TemporaryDirectory() as temporary:
            result = run_portfolio(manifest=manifest, mode="adaptive-portfolio", results_root=Path(temporary),
                                   project_root=Path(__file__).parents[1], evaluator=timeout,
                                   limits=PortfolioLimits(episodes=10, seconds=600, estimated_usd=10, hourly_rate=1))
        self.assertFalse(result["certified"])
        self.assertEqual("uncertain", result["stop_reason"])

    def test_shared_interrupt_stops_portfolio_with_a_durable_partial_summary(self):
        from robot_debug.portfolio_manifest import PortfolioManifest
        from robot_debug.portfolio_runner import PortfolioLimits, run_portfolio
        interrupted = threading.Event()
        manifest = PortfolioManifest(suite="libero_object", task_ids=(0, 1, 2), seed=7,
                                     family="agentview_rect_occlusion")
        def interrupting(request, *, launch_observer, **_kwargs):
            launch_observer(7888, "vla-eval-7888")
            request.output_dir.mkdir(parents=True); evidence = request.output_dir / "aggregate.json"
            evidence.write_text("{}", encoding="utf-8"); interrupted.set()
            return {"status": "valid", "outcome": "success", "evidence_paths": [str(evidence)]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            summary = run_portfolio(manifest=manifest, mode="adaptive-portfolio", results_root=root,
                                    project_root=Path(__file__).parents[1], evaluator=interrupting,
                                    limits=PortfolioLimits(episodes=10, seconds=600, estimated_usd=10, hourly_rate=1),
                                    interrupt_event=interrupted)
            self.assertTrue((root / summary["session_id"] / "portfolio_summary.json").is_file())
        self.assertEqual("interrupted", summary["stop_reason"])
        self.assertFalse(summary["certified"])


if __name__ == "__main__":
    unittest.main()
