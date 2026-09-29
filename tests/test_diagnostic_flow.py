"""Ordered, side-effect-free diagnostic decisions."""

import math
import unittest

from robot_debug.diagnostic_flow import DiagnosticFlow
from robot_debug.reduce import Rect


class DiagnosticFlowTests(unittest.TestCase):
    def make_flow(self, **overrides):
        values = dict(
            search=(("search-a", Rect(0, 0, .5, .5)),
                    ("search-b", Rect(.5, 0, .5, .5))),
            deltas=(.125,),
            nominal_count=2,
            candidate_attempt_budget=12,
            control_count=2,
            config_hash="frozen-test-config",
        )
        values.update(overrides)
        return DiagnosticFlow(**values)

    def advance_to_confirmation(self, flow):
        flow.apply_round({"nominal-01": "success", "nominal-02": "success"})
        flow.apply_round({"search-b": "policy_failure", "search-a": "success"})

    def test_nominal_gate_precedes_ordered_search(self):
        flow = self.make_flow()
        self.assertEqual(flow.pending(), ("nominal-01", "nominal-02"))
        flow.apply_round({"nominal-02": "success", "nominal-01": "success"})
        self.assertEqual(flow.pending(), ("search-a", "search-b"))
        flow.apply_round({"search-b": "policy_failure", "search-a": "success"})
        self.assertEqual(flow.selected_search_id, "search-b")
        self.assertEqual(flow.pending(), tuple(f"confirm-{i:02d}" for i in range(1, 6)))

    def test_confirmation_requires_exactly_five_valid_replays(self):
        flow = self.make_flow()
        self.advance_to_confirmation(flow)
        with self.assertRaises(ValueError):
            flow.apply_round({f"confirm-{i:02d}": "policy_failure" for i in range(1, 5)})
        self.assertEqual(flow.phase, "confirm")
        flow.apply_round({f"confirm-{i:02d}": "policy_failure" for i in range(1, 5)} |
                         {"confirm-05": "success"})
        self.assertEqual(flow.phase, "reduction_sentinel")

    def test_reduction_gate_can_pass_after_four_failures(self):
        flow = self.make_flow()
        self.advance_to_confirmation(flow)
        flow.apply_round({f"confirm-{i:02d}": "policy_failure" for i in range(1, 6)})
        flow.apply_round({"reduction-sentinel": "success"})
        self.assertEqual(len(flow.pending()), 4)
        flow.apply_round({case_id: "policy_failure" for case_id in flow.pending()})
        self.assertEqual(flow.phase, "reduce_candidate")
        self.assertIn("left", flow.pending()[0])
        flow.apply_round({case_id: "policy_failure" for case_id in flow.pending()})
        self.assertEqual(flow.current_rect, Rect(.625, 0, .375, .5))

    def test_reducer_rejects_two_non_failures_and_keeps_parent(self):
        flow = self.make_flow()
        self.advance_to_confirmation(flow)
        flow.apply_round({f"confirm-{i:02d}": "policy_failure" for i in range(1, 6)})
        flow.apply_round({"reduction-sentinel": "success"})
        flow.apply_round({case_id: "policy_failure" for case_id in flow.pending()})
        original = flow.current_rect
        first = flow.pending()
        flow.apply_round({first[0]: "success", first[1]: "success",
                          first[2]: "policy_failure", first[3]: "policy_failure"})
        self.assertEqual(flow.current_rect, original)
        self.assertIn("bottom", flow.pending()[0])

    def test_invalid_outcome_stops_without_certification(self):
        flow = self.make_flow()
        flow.apply_round({"nominal-01": "success", "nominal-02": "infrastructure_error"})
        self.assertEqual(flow.phase, "stopped")
        self.assertFalse(flow.certified)

    def test_restore_rejects_mismatched_configuration(self):
        flow = self.make_flow()
        snapshot = flow.snapshot()
        with self.assertRaises(ValueError):
            DiagnosticFlow.restore(snapshot, search=(("different", Rect(0, 0, .5, .5)),),
                                   deltas=(.125,), nominal_count=2,
                                   candidate_attempt_budget=12, control_count=2,
                                   config_hash="another-config")

    def test_restore_round_trip_keeps_pending_order(self):
        flow = self.make_flow()
        self.advance_to_confirmation(flow)
        restored = DiagnosticFlow.restore(flow.snapshot(),
                                          search=flow.search, deltas=flow.deltas,
                                          nominal_count=flow.nominal_count,
                                          candidate_attempt_budget=flow.candidate_attempt_budget,
                                          control_count=flow.control_count,
                                          config_hash=flow.config_hash)
        self.assertEqual(restored.pending(), flow.pending())

    def test_nonfinite_delta_is_rejected(self):
        for bad in (math.nan, math.inf, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.make_flow(deltas=(bad,))

    def test_candidate_budget_stops_reduction_before_controls(self):
        flow = self.make_flow(candidate_attempt_budget=4)
        self.advance_to_confirmation(flow)
        flow.apply_round({f"confirm-{i:02d}": "policy_failure" for i in range(1, 6)})
        flow.apply_round({"reduction-sentinel": "success"})
        flow.apply_round({case_id: "policy_failure" for case_id in flow.pending()})
        flow.apply_round({case_id: "policy_failure" for case_id in flow.pending()})
        self.assertEqual(flow.phase, "controls")
        self.assertEqual(flow.candidate_attempts, 4)
        flow.apply_round({case_id: "success" for case_id in flow.pending()})
        self.assertTrue(flow.certified)

    def test_budget_exhausted_without_accepted_smaller_mask_cannot_certify(self):
        flow = self.make_flow(candidate_attempt_budget=1)
        self.advance_to_confirmation(flow)
        flow.apply_round({f"confirm-{i:02d}": "policy_failure" for i in range(1, 6)})
        flow.apply_round({"reduction-sentinel": "success"})
        flow.apply_round({case_id: "policy_failure" for case_id in flow.pending()})
        flow.apply_round({case_id: "policy_failure" for case_id in flow.pending()})
        self.assertEqual(flow.phase, "stopped")
        self.assertFalse(flow.certified)

    def test_all_rejected_candidates_cannot_certify(self):
        flow = self.make_flow(candidate_attempt_budget=20)
        self.advance_to_confirmation(flow)
        flow.apply_round({f"confirm-{i:02d}": "policy_failure" for i in range(1, 6)})
        flow.apply_round({"reduction-sentinel": "success"})
        flow.apply_round({case_id: "policy_failure" for case_id in flow.pending()})
        for _ in range(4):
            flow.apply_round({case_id: "success" for case_id in flow.pending()})
        self.assertEqual(flow.phase, "stopped")
        self.assertFalse(flow.certified)

    def test_restore_rejects_phase_jump_without_recorded_gates(self):
        flow = self.make_flow()
        forged = flow.snapshot()
        forged["phase"] = "controls"
        with self.assertRaises(ValueError):
            DiagnosticFlow.restore(forged, search=flow.search, deltas=flow.deltas,
                                   nominal_count=flow.nominal_count,
                                   candidate_attempt_budget=flow.candidate_attempt_budget,
                                   control_count=flow.control_count,
                                   config_hash=flow.config_hash)


if __name__ == "__main__":
    unittest.main()
