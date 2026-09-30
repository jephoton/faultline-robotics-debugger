"""Adversarial contract tests for conservative portfolio comparisons."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))


def complete_live_summary(mode: str, *, elapsed: float) -> dict:
    """Synthetic-derived unit fixture; relabelled live only to test pure comparison."""
    from robot_debug.diagnostic_flow import DiagnosticFlow
    from robot_debug.portfolio_manifest import PortfolioManifest
    from robot_debug.reduce import Rect

    manifest = PortfolioManifest(suite="libero_object", task_ids=(0, 1, 2), seed=7,
                                 family="agentview_rect_occlusion")
    jobs, nominal, search = {}, [], []
    for task_id in manifest.task_ids:
        job_id = f"task-{task_id:02d}"
        flow = DiagnosticFlow(search=[(f"search-{task_id:02d}", Rect(.1, .2, .3, .4))],
                              deltas=(.125,), nominal_count=1, candidate_attempt_budget=12,
                              control_count=5, config_hash=f"{manifest.config_hash}:{job_id}")
        flow.apply_round({"nominal-01": "success"})
        flow.apply_round({f"search-{task_id:02d}": "success"})
        jobs[job_id] = {"job_id": job_id, "flow": flow.snapshot(), "certified": False,
                        "terminal_status": "no_apparent_failure",
                        "phase_timestamps_seconds": {"apparent_failure": None,
                                                      "reproducible_failure": None,
                                                      "reduced_failure": None, "terminal": 5.0}}
        for local_id, target in (("nominal-01", nominal), (f"search-{task_id:02d}", search)):
            case_id = f"{job_id}--{local_id}"
            target.append({"case_id": case_id, "status": "valid", "outcome": "success",
                           "evidence_paths": [f"waves/{case_id}.json"]})
    return {"schema_version": 1, "session_id": mode, "mode": mode,
            "manifest": manifest.to_mapping(), "manifest_hash": manifest.config_hash,
            "dry_run": False, "synthetic": False, "execution_kind": "live",
            "limits": {"episodes": 30, "seconds": 600.0, "estimated_usd": 10.0, "hourly_rate": 1.0},
            "accounting_incomplete": False, "physical_attempts": 6, "valid_episodes": 6,
            "invalid_attempts": 0, "uncertain_attempts": 0, "elapsed_seconds": elapsed,
            "warm_diagnostic_estimate_usd": elapsed / 3600, "stop_reason": "all_jobs_terminal",
            "jobs": jobs,
            "waves": [
                {"wave_id": 1, "results": nominal, "launched_attempts": 3,
                 "attempt_accounting_validated": True, "ledger_path": "waves/1/ledger.json"},
                {"wave_id": 2, "results": search, "launched_attempts": 3,
                 "attempt_accounting_validated": True, "ledger_path": "waves/2/ledger.json"}]}


class PortfolioReportTests(unittest.TestCase):
    def compare(self, sequential=None, adaptive=None):
        from robot_debug.portfolio_report import compare_portfolios
        return compare_portfolios(sequential or complete_live_summary("sequential-jobs", elapsed=120),
                                  adaptive or complete_live_summary("adaptive-portfolio", elapsed=60))

    def test_logically_complete_live_fixture_reports_coverage_and_warm_speedup(self):
        report = self.compare()
        self.assertTrue(report["same_manifest"])
        self.assertTrue(report["comparable"])
        self.assertEqual(2.0, report["warm_diagnostic_speedup"])
        self.assertEqual({"no_failure": 3}, report["job_status_counts"])
        self.assertEqual({"sequential": 3, "adaptive": 3}, report["task_coverage"])
        self.assertEqual({"sequential": 0, "adaptive": 0}, report["speculative_valid_work"])
        self.assertEqual({"sequential": 0, "adaptive": 0}, report["unvalidated_attempts"])
        self.assertIsNone(report["full_vm_allocation_estimated_compute_usd"])
        self.assertIsNone(report["billed_cost_usd"])

    def test_real_runner_dry_run_summary_is_never_timing_evidence(self):
        from robot_debug.portfolio_manifest import PortfolioManifest
        from robot_debug.portfolio_runner import PortfolioLimits, run_portfolio
        def evaluator(request, *, launch_observer, **_kwargs):
            launch_observer(7001, "fake"); request.output_dir.mkdir(parents=True)
            evidence = request.output_dir / "aggregate.json"; evidence.write_text("{}", encoding="utf-8")
            return {"status": "valid", "outcome": "success", "evidence_paths": [str(evidence)]}
        manifest = PortfolioManifest(suite="libero_object", task_ids=(0, 1, 2), seed=7,
                                     family="agentview_rect_occlusion")
        with tempfile.TemporaryDirectory() as temporary:
            fake = run_portfolio(manifest=manifest, mode="adaptive-portfolio", results_root=Path(temporary),
                                 project_root=Path(__file__).parents[1], evaluator=evaluator,
                                 limits=PortfolioLimits(episodes=3, seconds=600, estimated_usd=10, hourly_rate=1),
                                 dry_run=True)
        report = self.compare(adaptive=fake)
        self.assertIsNone(report["warm_diagnostic_speedup"])
        self.assertTrue(any("live markers" in item for item in report["limitations"]))

    def test_flow_round_and_wave_records_must_match_for_terminal_job(self):
        adaptive = complete_live_summary("adaptive-portfolio", elapsed=60)
        adaptive["waves"][1]["results"][0]["outcome"] = "policy_failure"
        with self.assertRaisesRegex(ValueError, "flow rounds"):
            self.compare(adaptive=adaptive)

    def test_valid_and_physical_attempt_counts_must_reconcile_to_waves(self):
        adaptive = complete_live_summary("adaptive-portfolio", elapsed=60)
        adaptive["valid_episodes"] = 12
        with self.assertRaisesRegex(ValueError, "valid_episodes"):
            self.compare(adaptive=adaptive)
        adaptive = complete_live_summary("adaptive-portfolio", elapsed=60)
        adaptive["physical_attempts"] = 5
        with self.assertRaisesRegex(ValueError, "physical_attempts"):
            self.compare(adaptive=adaptive)

    def test_paired_attested_launch_or_accounting_tampering_cannot_claim_speedup(self):
        sequential = complete_live_summary("sequential-jobs", elapsed=120)
        adaptive = complete_live_summary("adaptive-portfolio", elapsed=60)
        for value in (sequential, adaptive):
            value["physical_attempts"] = 7
        with self.assertRaisesRegex(ValueError, "launched_attempts"):
            self.compare(sequential, adaptive)
        sequential = complete_live_summary("sequential-jobs", elapsed=120)
        adaptive = complete_live_summary("adaptive-portfolio", elapsed=60)
        for value in (sequential, adaptive):
            value.pop("accounting_incomplete")
        report = self.compare(sequential, adaptive)
        self.assertIsNone(report["warm_diagnostic_speedup"])

    def test_paired_interruption_or_runner_exception_cannot_claim_speedup(self):
        for reason in ("interrupted", "runner_exception: RuntimeError: fake"):
            with self.subTest(reason=reason):
                sequential = complete_live_summary("sequential-jobs", elapsed=120)
                adaptive = complete_live_summary("adaptive-portfolio", elapsed=60)
                for value in (sequential, adaptive):
                    value["stop_reason"] = reason
                report = self.compare(sequential, adaptive)
                self.assertIsNone(report["warm_diagnostic_speedup"])
                self.assertTrue(any("completion reason" in item for item in report["limitations"]))

    def test_paired_flow_contract_status_and_timestamp_tampering_is_rejected(self):
        sequential = complete_live_summary("sequential-jobs", elapsed=120)
        adaptive = complete_live_summary("adaptive-portfolio", elapsed=60)
        for value in (sequential, adaptive):
            value["jobs"]["task-00"]["flow"]["config"]["config_hash"] = "wrong"
        with self.assertRaisesRegex(ValueError, "config_hash"):
            self.compare(sequential, adaptive)
        sequential = complete_live_summary("sequential-jobs", elapsed=120)
        adaptive = complete_live_summary("adaptive-portfolio", elapsed=60)
        for value in (sequential, adaptive):
            value["jobs"]["task-00"]["certified"] = True
            value["jobs"]["task-00"]["terminal_status"] = "certified"
        with self.assertRaisesRegex(ValueError, "certified flag"):
            self.compare(sequential, adaptive)
        sequential = complete_live_summary("sequential-jobs", elapsed=120)
        adaptive = complete_live_summary("adaptive-portfolio", elapsed=60)
        for value in (sequential, adaptive):
            value["jobs"]["task-00"]["phase_timestamps_seconds"]["apparent_failure"] = 1.0
        with self.assertRaisesRegex(ValueError, "apparent_failure"):
            self.compare(sequential, adaptive)

    def test_contract_limits_and_live_markers_must_match_exactly(self):
        adaptive = complete_live_summary("adaptive-portfolio", elapsed=60)
        adaptive["manifest"].update(task_ids=[1, 0, 2])
        with self.assertRaisesRegex(ValueError, "config_hash"):
            self.compare(adaptive=adaptive)
        for mutate in (lambda value: value["limits"].update(episodes=31),
                       lambda value: value.update(execution_kind="production"),
                       lambda value: value.update(synthetic=True)):
            with self.subTest(mutate=mutate):
                adaptive = complete_live_summary("adaptive-portfolio", elapsed=60); mutate(adaptive)
                self.assertIsNone(self.compare(adaptive=adaptive)["warm_diagnostic_speedup"])

    def test_outcome_decision_or_job_status_drift_refuses_speedup(self):
        adaptive = complete_live_summary("adaptive-portfolio", elapsed=60)
        adaptive["jobs"]["task-00"]["flow"]["decisions"] = [{"tampered": True}]
        with self.assertRaisesRegex(ValueError, "replayed"):
            self.compare(adaptive=adaptive)
        adaptive = complete_live_summary("adaptive-portfolio", elapsed=60)
        adaptive["jobs"]["task-00"]["terminal_status"] = "nominal_gate_failed"
        with self.assertRaisesRegex(ValueError, "terminal_status"):
            self.compare(adaptive=adaptive)

    def test_incomplete_or_unvalidated_accounting_suppresses_speedup(self):
        adaptive = complete_live_summary("adaptive-portfolio", elapsed=60)
        adaptive["waves"][0]["attempt_accounting_validated"] = False
        report = self.compare(adaptive=adaptive)
        self.assertIsNone(report["warm_diagnostic_speedup"])
        self.assertTrue(any("launched accounting" in item for item in report["limitations"]))
        adaptive = complete_live_summary("adaptive-portfolio", elapsed=60)
        adaptive["stop_reason"] = "shared_budget_exhausted"
        from robot_debug.diagnostic_flow import DiagnosticFlow
        from robot_debug.reduce import Rect
        manifest_hash = adaptive["manifest_hash"]
        flow = DiagnosticFlow(search=[("search-02", Rect(.1, .2, .3, .4))], deltas=(.125,),
                              nominal_count=1, candidate_attempt_budget=12, control_count=5,
                              config_hash=f"{manifest_hash}:task-02")
        flow.apply_round({"nominal-01": "success"})
        adaptive["jobs"]["task-02"]["flow"] = flow.snapshot()
        adaptive["jobs"]["task-02"]["terminal_status"] = None
        adaptive["jobs"]["task-02"]["phase_timestamps_seconds"]["terminal"] = None
        report = self.compare(adaptive=adaptive)
        self.assertIsNone(report["warm_diagnostic_speedup"])
        self.assertIn("budget_exhausted", report["job_statuses"]["adaptive"].values())


if __name__ == "__main__":
    unittest.main()
