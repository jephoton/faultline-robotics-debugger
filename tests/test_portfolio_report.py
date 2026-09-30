"""Contract tests for conservative portfolio comparison claims."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))


def summary(mode: str, *, elapsed: float, dry_run: bool | None = False) -> dict:
    from robot_debug.portfolio_manifest import PortfolioManifest

    manifest = PortfolioManifest(suite="libero_object", task_ids=(0, 1, 2), seed=7,
                                 family="agentview_rect_occlusion")
    jobs = {}
    results = []
    for task_id in manifest.task_ids:
        job_id = f"task-{task_id:02d}"
        global_id = f"{job_id}--confirm-01"
        jobs[job_id] = {
            "job_id": job_id,
            "flow": {"phase": "certified", "selected_search_id": f"search-{task_id:02d}",
                     "decisions": [{"phase": "reduce_candidate", "decision": "pass"}]},
            "certified": True,
            "terminal_status": "certified",
            "phase_timestamps_seconds": {"apparent_failure": 10.0 + task_id,
                                          "reproducible_failure": 20.0 + task_id,
                                          "reduced_failure": 30.0 + task_id,
                                          "terminal": 40.0 + task_id},
        }
        results.append({"case_id": global_id, "status": "valid", "outcome": "policy_failure",
                        "evidence_paths": [f"waves/0001/{global_id}.json"]})
    value = {
        "schema_version": 1,
        "session_id": mode,
        "mode": mode,
        "manifest": manifest.to_mapping(),
        "manifest_hash": manifest.config_hash,
        "accounting_incomplete": False,
        "physical_attempts": 12,
        "valid_episodes": 12,
        "invalid_attempts": 0,
        "uncertain_attempts": 0,
        "elapsed_seconds": elapsed,
        "warm_diagnostic_estimate_usd": elapsed / 3600,
        "stop_reason": "all_jobs_terminal",
        "jobs": jobs,
        "waves": [{"wave_id": 1, "results": results}],
    }
    if dry_run is not None:
        value["dry_run"] = dry_run
    return value


class PortfolioReportTests(unittest.TestCase):
    def compare(self, sequential=None, adaptive=None):
        from robot_debug.portfolio_report import compare_portfolios
        return compare_portfolios(sequential or summary("sequential-jobs", elapsed=120),
                                  adaptive or summary("adaptive-portfolio", elapsed=60))

    def test_matched_live_contract_reports_coverage_and_warm_speedup(self):
        report = self.compare()
        self.assertTrue(report["same_manifest"])
        self.assertTrue(report["comparable"])
        self.assertEqual(2.0, report["warm_diagnostic_speedup"])
        self.assertEqual(3, sum(report["job_status_counts"].values()))
        self.assertEqual(3, report["successful_reports"]["adaptive"])
        self.assertEqual({"sequential": 12, "adaptive": 12}, report["physical_attempts"])
        self.assertEqual({"sequential": 3, "adaptive": 3}, report["task_coverage"])
        self.assertEqual({"sequential": 20.0, "adaptive": 20.0},
                         report["time_to_first_reproducible_report_seconds"])
        self.assertIsNone(report["full_vm_allocation_estimated_compute_usd"])
        self.assertIsNone(report["billed_cost_usd"])

    def test_task_order_or_frozen_config_mismatch_is_not_comparable(self):
        for mutate in (
            lambda value: value["manifest"].update(task_ids=[1, 0, 2]),
            lambda value: value["manifest"].update(seed=8),
            lambda value: value["manifest"].update(family="lighting"),
            lambda value: value["manifest"].update(checkpoint_revision="other"),
        ):
            with self.subTest(mutate=mutate):
                adaptive = summary("adaptive-portfolio", elapsed=60)
                mutate(adaptive)
                report = self.compare(adaptive=adaptive)
                self.assertFalse(report["same_manifest"])
                self.assertFalse(report["comparable"])
                self.assertIsNone(report["warm_diagnostic_speedup"])

    def test_missing_evidence_for_a_terminal_job_is_rejected(self):
        adaptive = summary("adaptive-portfolio", elapsed=60)
        adaptive["waves"][0]["results"][1]["evidence_paths"] = []
        with self.assertRaises(ValueError):
            self.compare(adaptive=adaptive)

    def test_invalid_or_uncertain_results_refuse_a_speedup(self):
        adaptive = summary("adaptive-portfolio", elapsed=60)
        adaptive["waves"][0]["results"][0]["status"] = "invalid_evidence"
        adaptive["invalid_attempts"] = 1
        report = self.compare(adaptive=adaptive)
        self.assertIsNone(report["warm_diagnostic_speedup"])
        self.assertTrue(any("invalid" in item for item in report["limitations"]))

    def test_no_failure_and_budget_exhausted_jobs_remain_in_status_report(self):
        sequential = summary("sequential-jobs", elapsed=120)
        adaptive = summary("adaptive-portfolio", elapsed=60)
        for value in (sequential, adaptive):
            value["jobs"]["task-01"].update(
                certified=False, terminal_status="no_apparent_failure",
                flow={"phase": "stopped", "stop_reason": "no_apparent_failure", "decisions": []},
            )
            value["jobs"]["task-02"].update(
                certified=False, terminal_status=None,
                flow={"phase": "search", "stop_reason": None, "decisions": []},
            )
            value["stop_reason"] = "shared_budget_exhausted"
        report = self.compare(sequential, adaptive)
        self.assertEqual("no_failure", report["job_statuses"]["adaptive"]["task-01"])
        self.assertEqual("budget_exhausted", report["job_statuses"]["adaptive"]["task-02"])
        self.assertEqual(1, report["job_status_counts"]["no_failure"])
        self.assertEqual(1, report["job_status_counts"]["budget_exhausted"])

    def test_fake_or_unknown_synthetic_state_refuses_a_speedup(self):
        for dry_run in (True, None):
            with self.subTest(dry_run=dry_run):
                adaptive = summary("adaptive-portfolio", elapsed=60, dry_run=dry_run)
                report = self.compare(adaptive=adaptive)
                self.assertIsNone(report["warm_diagnostic_speedup"])
                self.assertTrue(any("dry_run" in item for item in report["limitations"]))

    def test_outcome_or_decision_drift_is_exposed_and_refuses_speedup(self):
        adaptive = summary("adaptive-portfolio", elapsed=60)
        adaptive["waves"][0]["results"][0]["outcome"] = "success"
        adaptive["jobs"]["task-01"]["flow"]["decisions"] = []
        report = self.compare(adaptive=adaptive)
        self.assertIsNone(report["warm_diagnostic_speedup"])
        self.assertEqual(["task-00--confirm-01"], report["outcome_drift_case_ids"])
        self.assertEqual(["task-01"], report["decision_drift_job_ids"])


if __name__ == "__main__":
    unittest.main()
