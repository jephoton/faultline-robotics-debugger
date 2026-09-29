"""Fail-closed comparison contracts for completed diagnostic sessions."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))


def complete_summary(policy: str, *, elapsed_seconds: float = 120.0,
                     confirmation_first_success: bool = False) -> dict:
    """A smallest complete, certified driver summary with durable evidence."""
    from robot_debug.diagnostic_flow import DiagnosticFlow
    from robot_debug.reduce import Rect

    flow = DiagnosticFlow(search=(("search-01", Rect(.5, 0, .5, .5)),), deltas=(.125,),
                          nominal_count=1, candidate_attempt_budget=4, control_count=1,
                          config_hash="a" * 64)
    flow.apply_round({"nominal-01": "success"})
    flow.apply_round({"search-01": "policy_failure"})
    flow.apply_round({f"confirm-{number:02d}": "success" if number == (1 if confirmation_first_success else 5) else "policy_failure"
                      for number in range(1, 6)})
    flow.apply_round({"reduction-sentinel": "success"})
    flow.apply_round({case_id: "policy_failure" for case_id in flow.pending()})
    flow.apply_round({case_id: "policy_failure" for case_id in flow.pending()})
    flow.apply_round({"control-01": "success"})
    durable_rounds = [{
        "round_id": index,
        "case_ids": record["case_ids"],
        "worker_choice": {"workers": 1, "reason": "fixture", "predicted_seconds": 20.0,
                          "predicted_cost_usd": 0.02},
        "ledger_path": f"round-{index:02d}/ledger.json",
        "manifest_hash": f"{index:064x}",
        "results": [{"case_id": case_id, "status": "valid", "outcome": outcome,
                     "evidence_paths": [f"round-{index:02d}/{case_id}.json"]}
                    for case_id, outcome in zip(record["case_ids"], record["outcomes"])],
    } for index, record in enumerate(flow.snapshot()["rounds"], start=1)]
    return {
        "schema_version": 1,
        "session_id": f"{policy}-session",
        "policy": policy,
        "status": "complete",
        "stop_reason": None,
        "full_vm_hourly_rate_usd": 3.6,
        "scenario_contract": {
            "config_hash": "a" * 64,
            "model_id": "groot-n1",
            "task_id": 0,
            "seed": 7,
            "perturbation_family": "occlusion",
            "search": [["search-01", {"x": .5, "y": 0, "width": .5, "height": .5}]],
            "deltas": [0.125],
            "gate_rules": {"confirmation": "4 of 5", "reduction": "4 failures"},
        },
        "flow": flow.snapshot(),
        "rounds": durable_rounds,
        "certified": True,
        "certified_rectangle": {"x": .625, "y": 0, "width": .375, "height": .5},
        "controls_passed": True,
        "valid_episodes": sum(len(round_record["results"]) for round_record in durable_rounds),
        "physical_attempts": sum(len(round_record["results"]) for round_record in durable_rounds),
        "invalid_attempts": 0,
        "uncertain_attempts": 0,
        "elapsed_seconds": elapsed_seconds,
        "estimated_compute_usd": 999.0,  # Reporter must recompute rather than trust this.
        "phase_timestamps_seconds": {
            "apparent_failure": 20.0,
            "reproducible_failure": elapsed_seconds - 30.0,
            "reduced_failure": elapsed_seconds - 10.0,
        },
        "config_paths": ["config.json"],
        "evidence_paths": [path for round_record in durable_rounds for result in round_record["results"]
                           for path in result["evidence_paths"]],
    }


class DiagnosticReportTests(unittest.TestCase):
    def compare(self, sequential: dict | None = None, adaptive: dict | None = None):
        from robot_debug.diagnostic_report import compare_sessions
        return compare_sessions(sequential or complete_summary("sequential"),
                                adaptive or complete_summary("adaptive", elapsed_seconds=80.0))

    def test_matched_complete_sessions_produce_an_honest_comparison(self):
        report = self.compare()
        self.assertTrue(report["comparable"])
        self.assertTrue(report["same_terminal_result"])
        self.assertEqual(1.5, report["warm_diagnostic_speedup"])
        self.assertEqual({"sequential": 20.0, "adaptive": 20.0},
                         report["time_to_apparent_failure_seconds"])
        self.assertEqual({"sequential": 120.0, "adaptive": 80.0}, report["end_to_end_seconds"])
        self.assertEqual({"sequential": 0.12, "adaptive": 0.08}, report["warm_diagnostic_estimated_compute_usd"])
        self.assertIsNone(report["full_vm_allocation_estimated_compute_usd"])
        self.assertIsNone(report["billed_cost_usd"])
        self.assertGreaterEqual(report["physical_attempts"]["adaptive"], report["valid_episodes"]["adaptive"])
        self.assertEqual({"sequential": 18.75, "adaptive": 18.75}, report["final_area_percent"])
        self.assertTrue(any("allocation" in limitation for limitation in report["limitations"]))

    def test_contract_mismatch_is_rejected_for_each_frozen_field(self):
        for field, changed in (
            ("model_id", "other-model"), ("task_id", 1), ("seed", 8),
            ("perturbation_family", "lighting"), ("search", {"candidate_ids": ["other"]}),
            ("deltas", [.25]), ("gate_rules", {"confirmation": "other"}),
        ):
            with self.subTest(field=field):
                adaptive = complete_summary("adaptive", elapsed_seconds=80)
                adaptive["scenario_contract"][field] = changed
                with self.assertRaisesRegex(ValueError, "scenario_contract"):
                    self.compare(adaptive=adaptive)

    def test_partial_or_uncertain_or_missing_evidence_is_rejected(self):
        mutations = (
            lambda summary: summary.update(status="partial"),
            lambda summary: summary.update(uncertain_attempts=1),
            lambda summary: summary["rounds"][0]["results"][0].update(status="uncertain"),
            lambda summary: summary.update(evidence_paths=[]),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                adaptive = complete_summary("adaptive", elapsed_seconds=80)
                mutate(adaptive)
                with self.assertRaises(ValueError):
                    self.compare(adaptive=adaptive)

    def test_terminal_result_drift_is_visible_but_has_no_speedup_claim(self):
        adaptive = complete_summary("adaptive", elapsed_seconds=80)
        adaptive["certified_rectangle"] = {"x": .5, "y": 0, "width": .5, "height": .375}
        with self.assertRaises(ValueError):
            self.compare(adaptive=adaptive)

    def test_missing_phase_timestamps_are_null_with_an_explicit_limitation(self):
        adaptive = complete_summary("adaptive", elapsed_seconds=80)
        adaptive.pop("phase_timestamps_seconds")
        report = self.compare(adaptive=adaptive)
        self.assertIsNone(report["time_to_apparent_failure_seconds"]["adaptive"])
        self.assertTrue(any("phase timestamps" in limitation for limitation in report["limitations"]))

    def test_invalid_counts_and_rate_are_rejected(self):
        for field, value in (("physical_attempts", 0), ("physical_attempts", 100),
                             ("valid_episodes", True),
                             ("full_vm_hourly_rate_usd", float("inf"))):
            with self.subTest(field=field):
                adaptive = complete_summary("adaptive", elapsed_seconds=80)
                adaptive[field] = value
                with self.assertRaises(ValueError):
                    self.compare(adaptive=adaptive)

    def test_missing_durable_summary_fields_or_malformed_contract_are_rejected(self):
        mutations = (
            lambda summary: summary.pop("flow"),
            lambda summary: summary.update(config_paths=[]),
            lambda summary: summary["rounds"][0].pop("ledger_path"),
            lambda summary: summary["rounds"][0].pop("worker_choice"),
            lambda summary: summary["scenario_contract"].update(task_id=True),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                adaptive = complete_summary("adaptive", elapsed_seconds=80)
                mutate(adaptive)
                with self.assertRaises(ValueError):
                    self.compare(adaptive=adaptive)

    def test_round_results_must_match_case_ids_and_valid_episode_count(self):
        mutations = (
            lambda summary: summary["rounds"][0].update(case_ids=["other-case"]),
            lambda summary: summary["rounds"][0]["results"][0].update(outcome="unknown"),
            lambda summary: summary.update(valid_episodes=2),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                adaptive = complete_summary("adaptive", elapsed_seconds=80)
                mutate(adaptive)
                with self.assertRaises(ValueError):
                    self.compare(adaptive=adaptive)

    def test_complete_certified_summary_requires_no_stop_and_ordered_phase_times(self):
        mutations = (
            lambda summary: summary.update(stop_reason="launch_cutoff_reached"),
            lambda summary: summary["phase_timestamps_seconds"].update(
                reproducible_failure=10.0),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                adaptive = complete_summary("adaptive", elapsed_seconds=80)
                mutate(adaptive)
                with self.assertRaises(ValueError):
                    self.compare(adaptive=adaptive)

    def test_ordered_search_contract_from_the_driver_is_comparable(self):
        sequential = complete_summary("sequential")
        adaptive = complete_summary("adaptive", elapsed_seconds=80)
        contract_search = [["search-01", {"x": .5, "y": 0, "width": .5, "height": .5}]]
        sequential["scenario_contract"]["search"] = contract_search
        adaptive["scenario_contract"]["search"] = contract_search
        self.assertTrue(self.compare(sequential, adaptive)["comparable"])

    def test_ordered_result_outcome_drift_is_exposed_and_refuses_warm_speedup(self):
        adaptive = complete_summary("adaptive", elapsed_seconds=80, confirmation_first_success=True)
        report = self.compare(adaptive=adaptive)
        self.assertFalse(report["comparable"])
        self.assertIsNone(report["warm_diagnostic_speedup"])
        self.assertEqual(["confirm-01", "confirm-05"], report["outcome_drift_case_ids"])

    def test_fake_sessions_are_logically_comparable_but_not_speedup_evidence(self):
        sequential = complete_summary("sequential")
        adaptive = complete_summary("adaptive", elapsed_seconds=80)
        sequential["dry_run"] = adaptive["dry_run"] = True
        report = self.compare(sequential, adaptive)
        self.assertTrue(report["comparable"])
        self.assertIsNone(report["warm_diagnostic_speedup"])
        self.assertTrue(any("fake" in item or "dry-run" in item for item in report["limitations"]))

    def test_flow_snapshot_must_be_certified_and_match_top_level_rectangle(self):
        mutations = (
            lambda summary: summary["flow"].update(phase="stopped"),
            lambda summary: summary["flow"].update(current_rect={"x": 0, "y": 0, "width": .5, "height": .5}),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                adaptive = complete_summary("adaptive", elapsed_seconds=80)
                mutate(adaptive)
                with self.assertRaises(ValueError):
                    self.compare(adaptive=adaptive)


if __name__ == "__main__":
    unittest.main()
