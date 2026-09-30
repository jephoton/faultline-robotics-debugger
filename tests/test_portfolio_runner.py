import json
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
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
    def test_runner_persists_atomic_dry_run_contract(self):
        from robot_debug.portfolio_manifest import PortfolioManifest
        from robot_debug.portfolio_runner import PortfolioLimits, run_portfolio
        manifest = PortfolioManifest(suite="libero_object", task_ids=(0, 1, 2), seed=7,
                                     family="agentview_rect_occlusion")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            summary = run_portfolio(manifest=manifest, mode="adaptive-portfolio", results_root=root,
                                    project_root=Path(__file__).parents[1], evaluator=FakeEvaluator(),
                                    limits=PortfolioLimits(episodes=3, seconds=600, estimated_usd=10, hourly_rate=1),
                                    dry_run=True)
            saved = json.loads((root / summary["session_id"] / "portfolio_summary.json").read_text(encoding="utf-8"))
        self.assertTrue(saved["dry_run"])
        self.assertTrue(saved["synthetic"])

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

    def test_sequential_mode_finishes_first_manifest_job_before_second_job_starts(self):
        from robot_debug.portfolio_manifest import PortfolioManifest
        from robot_debug.portfolio_runner import PortfolioLimits, run_portfolio
        manifest = PortfolioManifest(suite="libero_object", task_ids=(0, 1, 2), seed=7,
                                     family="agentview_rect_occlusion")
        evaluator = FakeEvaluator()
        with tempfile.TemporaryDirectory() as temporary:
            run_portfolio(manifest=manifest, mode="sequential-jobs", results_root=Path(temporary),
                          project_root=Path(__file__).parents[1], evaluator=evaluator,
                          limits=PortfolioLimits(episodes=12, seconds=600, estimated_usd=10, hourly_rate=1))
        job_ids = [request.case_id.split("--")[0] for request in evaluator.requests]
        first_task_1 = job_ids.index("task-01")
        self.assertEqual(["task-00"] * first_task_1, job_ids[:first_task_1])
        self.assertNotIn("task-00", job_ids[first_task_1:])

    def test_out_of_order_results_are_routed_to_owning_job_flows(self):
        from robot_debug.portfolio_manifest import PortfolioManifest
        from robot_debug.portfolio_runner import PortfolioLimits, run_portfolio
        manifest = PortfolioManifest(suite="libero_object", task_ids=(0, 1, 2), seed=7,
                                     family="agentview_rect_occlusion")
        def evaluator(request, *, launch_observer, **_kwargs):
            pid = 7700 + len(request.case_id); launch_observer(pid, f"vla-eval-{pid}")
            time.sleep({"task-00": .02, "task-01": .01, "task-02": 0}[request.case_id[:7]])
            request.output_dir.mkdir(parents=True); evidence = request.output_dir / "aggregate.json"
            evidence.write_text("{}", encoding="utf-8")
            outcome = "success" if "nominal" in request.case_id or request.case_id.startswith("task-01") else "policy_failure"
            return {"status": "valid", "outcome": outcome, "evidence_paths": [str(evidence)]}
        with tempfile.TemporaryDirectory() as temporary:
            summary = run_portfolio(manifest=manifest, mode="adaptive-portfolio", results_root=Path(temporary),
                                    project_root=Path(__file__).parents[1], evaluator=evaluator,
                                    limits=PortfolioLimits(episodes=6, seconds=600, estimated_usd=10, hourly_rate=1))
        self.assertIsNotNone(summary["jobs"]["task-00"]["flow"]["selected_search_id"])
        self.assertIsNone(summary["jobs"]["task-01"]["flow"]["selected_search_id"])
        self.assertIsNotNone(summary["jobs"]["task-02"]["flow"]["selected_search_id"])
        self.assertLessEqual(summary["max_observed_evaluator_calls"], 4)

    def test_invalid_evidence_and_shared_budget_leave_partial_summary(self):
        from robot_debug.portfolio_manifest import PortfolioManifest
        from robot_debug.portfolio_runner import PortfolioLimits, run_portfolio
        manifest = PortfolioManifest(suite="libero_object", task_ids=(0, 1, 2), seed=7,
                                     family="agentview_rect_occlusion")
        def invalid(request, *, launch_observer, **_kwargs):
            launch_observer(7788, "vla-eval-7788")
            return {"status": "invalid_evidence", "outcome": None, "evidence_paths": []}
        with tempfile.TemporaryDirectory() as temporary:
            failed = run_portfolio(manifest=manifest, mode="adaptive-portfolio", results_root=Path(temporary),
                                   project_root=Path(__file__).parents[1], evaluator=invalid,
                                   limits=PortfolioLimits(episodes=10, seconds=600, estimated_usd=10, hourly_rate=1))
        self.assertFalse(failed["certified"]); self.assertEqual("invalid_evidence", failed["stop_reason"])
        with tempfile.TemporaryDirectory() as temporary:
            exhausted = run_portfolio(manifest=manifest, mode="adaptive-portfolio", results_root=Path(temporary),
                                      project_root=Path(__file__).parents[1], evaluator=FakeEvaluator(),
                                      limits=PortfolioLimits(episodes=3, seconds=600, estimated_usd=10, hourly_rate=1))
        self.assertFalse(exhausted["certified"]); self.assertEqual("shared_budget_exhausted", exhausted["stop_reason"])

    def test_nominal_failure_stops_only_its_own_job(self):
        from robot_debug.portfolio_manifest import PortfolioManifest
        from robot_debug.portfolio_runner import PortfolioLimits, run_portfolio
        manifest = PortfolioManifest(suite="libero_object", task_ids=(0, 1, 2), seed=7,
                                     family="agentview_rect_occlusion")
        def evaluator(request, *, launch_observer, **_kwargs):
            launch_observer(7811, "vla-eval-7811"); request.output_dir.mkdir(parents=True)
            evidence = request.output_dir / "aggregate.json"; evidence.write_text("{}", encoding="utf-8")
            outcome = "policy_failure" if request.case_id.startswith("task-00") else "success"
            return {"status": "valid", "outcome": outcome, "evidence_paths": [str(evidence)]}
        with tempfile.TemporaryDirectory() as temporary:
            summary = run_portfolio(manifest=manifest, mode="adaptive-portfolio", results_root=Path(temporary),
                                    project_root=Path(__file__).parents[1], evaluator=evaluator,
                                    limits=PortfolioLimits(episodes=3, seconds=600, estimated_usd=10, hourly_rate=1))
        self.assertEqual("stopped", summary["jobs"]["task-00"]["flow"]["phase"])
        self.assertEqual("nominal_gate_failed", summary["jobs"]["task-00"]["flow"]["stop_reason"])
        self.assertEqual("search", summary["jobs"]["task-01"]["flow"]["phase"])

    def test_persists_per_job_gate_timestamps_and_nulls_for_absent_gates(self):
        from robot_debug.portfolio_manifest import PortfolioManifest
        from robot_debug.portfolio_runner import PortfolioLimits, run_portfolio
        manifest = PortfolioManifest(suite="libero_object", task_ids=(0, 1, 2), seed=7,
                                     family="agentview_rect_occlusion")
        def evaluator(request, *, launch_observer, **_kwargs):
            launch_observer(7900 + len(request.case_id), f"vla-eval-{7900 + len(request.case_id)}")
            request.output_dir.mkdir(parents=True); evidence = request.output_dir / "aggregate.json"
            evidence.write_text("{}", encoding="utf-8")
            success = request.case_id.startswith("task-01") or any(token in request.case_id for token in ("nominal", "sentinel", "control"))
            return {"status": "valid", "outcome": "success" if success else "policy_failure",
                    "evidence_paths": [str(evidence)]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            summary = run_portfolio(manifest=manifest, mode="adaptive-portfolio", results_root=root,
                                    project_root=Path(__file__).parents[1], evaluator=evaluator,
                                    limits=PortfolioLimits(episodes=100, seconds=600, estimated_usd=10, hourly_rate=1))
            saved = json.loads((root / summary["session_id"] / "portfolio_summary.json").read_text(encoding="utf-8"))
        phase = saved["jobs"]["task-00"]["phase_timestamps_seconds"]
        self.assertIsNotNone(phase["apparent_failure"])
        self.assertIsNotNone(phase["reproducible_failure"])
        self.assertIsNotNone(phase["reduced_failure"])
        self.assertLessEqual(phase["apparent_failure"], phase["reproducible_failure"])
        self.assertLessEqual(phase["reproducible_failure"], phase["reduced_failure"])
        absent = saved["jobs"]["task-01"]["phase_timestamps_seconds"]
        self.assertIsNone(absent["apparent_failure"])
        self.assertIsNotNone(absent["terminal"])

    def test_exception_after_durable_launch_intent_reconciles_or_marks_accounting_unknown(self):
        from robot_debug.portfolio_manifest import PortfolioManifest
        import robot_debug.portfolio_runner as runner
        from robot_debug.portfolio_runner import PortfolioLimits, run_portfolio
        manifest = PortfolioManifest(suite="libero_object", task_ids=(0, 1, 2), seed=7,
                                     family="agentview_rect_occlusion")
        original = runner.run_round
        def after_round(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("injected after durable launch")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(runner, "run_round", side_effect=after_round):
                with self.assertRaisesRegex(RuntimeError, "injected"):
                    run_portfolio(manifest=manifest, mode="adaptive-portfolio", results_root=root,
                                  project_root=Path(__file__).parents[1], evaluator=FakeEvaluator(),
                                  limits=PortfolioLimits(episodes=10, seconds=600, estimated_usd=10, hourly_rate=1))
            saved = next(root.glob("portfolio-*/portfolio_summary.json"))
            summary = json.loads(saved.read_text(encoding="utf-8"))
        self.assertFalse(summary["certified"])
        self.assertIn("runner_exception", summary["stop_reason"])
        self.assertTrue(summary["accounting_incomplete"] or summary["physical_attempts"] >= 1)

    def test_parseable_malformed_ledger_marks_attempt_accounting_unknown(self):
        from robot_debug.portfolio_manifest import PortfolioManifest
        import robot_debug.portfolio_runner as runner
        from robot_debug.portfolio_runner import PortfolioLimits, run_portfolio
        manifest = PortfolioManifest(suite="libero_object", task_ids=(0, 1, 2), seed=7,
                                     family="agentview_rect_occlusion")
        original = runner.run_round
        def corrupt_ledger(*args, **kwargs):
            result = original(*args, **kwargs)
            Path(kwargs["ledger_path"]).write_text(json.dumps({"attempt_records": {}}), encoding="utf-8")
            return result
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(runner, "run_round", side_effect=corrupt_ledger):
                with self.assertRaises(ValueError):
                    run_portfolio(manifest=manifest, mode="adaptive-portfolio", results_root=root,
                                  project_root=Path(__file__).parents[1], evaluator=FakeEvaluator(),
                                  limits=PortfolioLimits(episodes=10, seconds=600, estimated_usd=10, hourly_rate=1))
            summary = json.loads(next(root.glob("portfolio-*/portfolio_summary.json")).read_text(encoding="utf-8"))
        self.assertTrue(summary["accounting_incomplete"])
        self.assertIsNone(summary["physical_attempts"])
        self.assertFalse(summary["certified"])

    def test_parseable_scalar_ledger_marks_attempt_accounting_unknown(self):
        from robot_debug.portfolio_manifest import PortfolioManifest
        import robot_debug.portfolio_runner as runner
        from robot_debug.portfolio_runner import PortfolioLimits, run_portfolio
        manifest = PortfolioManifest(suite="libero_object", task_ids=(0, 1, 2), seed=7,
                                     family="agentview_rect_occlusion")
        original = runner.run_round
        for scalar in (None, 1):
            def corrupt_ledger(*args, **kwargs):
                result = original(*args, **kwargs)
                Path(kwargs["ledger_path"]).write_text(json.dumps(scalar), encoding="utf-8")
                return result
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with patch.object(runner, "run_round", side_effect=corrupt_ledger):
                    with self.assertRaises(ValueError):
                        run_portfolio(manifest=manifest, mode="adaptive-portfolio", results_root=root,
                                      project_root=Path(__file__).parents[1], evaluator=FakeEvaluator(),
                                      limits=PortfolioLimits(episodes=10, seconds=600, estimated_usd=10, hourly_rate=1))
                summary = json.loads(next(root.glob("portfolio-*/portfolio_summary.json")).read_text(encoding="utf-8"))
            self.assertTrue(summary["accounting_incomplete"])
            self.assertIsNone(summary["physical_attempts"])
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
