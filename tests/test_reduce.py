"""Deterministic tests for the pure bounded-reduction kernel."""

import math
import unittest
from dataclasses import FrozenInstanceError

from robot_debug.reduce import Candidate, GateDecision, Rect, candidates, classify_attempts


class RectTests(unittest.TestCase):
    def test_area_is_width_times_height(self) -> None:
        self.assertAlmostEqual(Rect(0.25, 0.5, 0.5, 0.25).area, 0.125)

    def test_rect_is_immutable(self) -> None:
        rect = Rect(0.5, 0.0, 0.5, 0.5)

        with self.assertRaises(FrozenInstanceError):
            rect.x = 0.25

    def test_rect_accepts_bounds_touching_edges(self) -> None:
        for values in ((0.0, 0.0, 1.0, 1.0), (0.5, 0.5, 0.5, 0.5), (0.0, 0.0, 0.125, 0.125)):
            with self.subTest(values=values):
                self.assertEqual(Rect(*values).area, values[2] * values[3])

    def test_rect_rejects_out_of_bounds_or_empty_geometry(self) -> None:
        cases = (
            (-0.1, 0.0, 0.5, 0.5),
            (0.0, -0.1, 0.5, 0.5),
            (0.5, 0.0, 0.0, 0.5),
            (0.5, 0.0, 0.5, 0.0),
            (-0.5, 0.0, 0.5, 0.5),
            (0.8, 0.0, 0.3, 0.5),
            (0.0, 0.8, 0.5, 0.3),
        )

        for values in cases:
            with self.subTest(values=values), self.assertRaises(ValueError):
                Rect(*values)

    def test_rect_rejects_non_finite_values(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            for index in range(4):
                values = [0.5, 0.0, 0.5, 0.5]
                values[index] = value
                with self.subTest(value=value, index=index), self.assertRaises(ValueError):
                    Rect(*values)

    def test_rect_rejects_non_numeric_values(self) -> None:
        with self.assertRaises((TypeError, ValueError)):
            Rect("0.5", 0.0, 0.5, 0.5)


class CandidateTests(unittest.TestCase):
    def test_candidates_follow_deterministic_edge_order(self) -> None:
        parent = Rect(0.5, 0.0, 0.5, 0.5)

        actual = candidates(parent, delta=0.125)

        self.assertEqual([item.edge for item in actual], ["left", "bottom", "right", "top"])

    def test_candidates_have_exact_geometry(self) -> None:
        parent = Rect(0.5, 0.0, 0.5, 0.5)

        actual = candidates(parent, delta=0.125)

        self.assertEqual(
            [item.rect for item in actual],
            [
                Rect(0.625, 0.0, 0.375, 0.5),
                Rect(0.5, 0.0, 0.5, 0.375),
                Rect(0.5, 0.0, 0.375, 0.5),
                Rect(0.5, 0.125, 0.5, 0.375),
            ],
        )

    def test_candidates_are_strictly_smaller(self) -> None:
        parent = Rect(0.5, 0.0, 0.5, 0.5)

        for item in candidates(parent, delta=0.125):
            with self.subTest(edge=item.edge):
                self.assertLess(item.rect.area, parent.area)

    def test_candidates_are_strict_nested_subsets(self) -> None:
        parent = Rect(0.125, 0.125, 0.75, 0.5)

        for delta in (0.125, 0.0625):
            for item in candidates(parent, delta=delta):
                with self.subTest(edge=item.edge, delta=delta):
                    self.assertGreaterEqual(item.rect.x, parent.x)
                    self.assertGreaterEqual(item.rect.y, parent.y)
                    self.assertLessEqual(item.rect.x + item.rect.width, parent.x + parent.width)
                    self.assertLessEqual(item.rect.y + item.rect.height, parent.y + parent.height)
                    self.assertLess(item.rect.area, parent.area)
                    self.assertNotEqual(item.rect, parent)

    def test_candidates_omit_impossible_edge_removal(self) -> None:
        self.assertEqual(candidates(Rect(0.0, 0.0, 0.125, 0.125), delta=0.125), ())

        wide = Rect(0.0, 0.0, 0.5, 0.125)
        self.assertEqual([item.edge for item in candidates(wide, delta=0.125)], ["left", "right"])

        tall = Rect(0.0, 0.0, 0.125, 0.5)
        self.assertEqual([item.edge for item in candidates(tall, delta=0.125)], ["bottom", "top"])

    def test_candidates_omit_edges_thinner_than_delta(self) -> None:
        thin = Rect(0.0, 0.0, 0.0625, 0.5)

        self.assertEqual([item.edge for item in candidates(thin, delta=0.125)], ["bottom", "top"])

    def test_candidates_reject_invalid_delta(self) -> None:
        parent = Rect(0.5, 0.0, 0.5, 0.5)

        for delta in (0.0, -0.125, math.nan, math.inf, -math.inf):
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                candidates(parent, delta=delta)

    def test_candidates_require_keyword_delta(self) -> None:
        with self.assertRaises(TypeError):
            candidates(Rect(0.5, 0.0, 0.5, 0.5), 0.125)

    def test_candidate_is_immutable(self) -> None:
        item = Candidate("left", Rect(0.5, 0.0, 0.375, 0.5))

        with self.assertRaises(FrozenInstanceError):
            item.edge = "right"


class GateDecisionTests(unittest.TestCase):
    def test_gate_decisions_use_stable_string_values(self) -> None:
        self.assertEqual(
            (GateDecision.PENDING.value, GateDecision.PASS.value, GateDecision.REJECT.value),
            ("pending", "pass", "reject"),
        )

    def test_gate_passes_at_four_failures(self) -> None:
        self.assertEqual(classify_attempts(["policy_failure"] * 4), GateDecision.PASS)

    def test_gate_stays_pending_at_three_failures(self) -> None:
        self.assertEqual(classify_attempts(["policy_failure"] * 3), GateDecision.PENDING)

    def test_gate_rejects_at_two_successes(self) -> None:
        self.assertEqual(classify_attempts(["success", "success"]), GateDecision.REJECT)

    def test_gate_rejects_at_two_valid_non_failures(self) -> None:
        self.assertEqual(
            classify_attempts(["policy_failure", "success", "success"]),
            GateDecision.REJECT,
        )

    def test_gate_is_pending_before_either_boundary(self) -> None:
        self.assertEqual(classify_attempts(["policy_failure", "success"]), GateDecision.PENDING)

    def test_gate_is_pending_without_attempts(self) -> None:
        self.assertEqual(classify_attempts([]), GateDecision.PENDING)

    def test_gate_passes_on_the_fifth_attempt_boundary(self) -> None:
        self.assertEqual(classify_attempts(tuple(["policy_failure"] * 5)), GateDecision.PASS)

    def test_gate_rejects_more_than_five_attempts(self) -> None:
        with self.assertRaises(ValueError):
            classify_attempts(["policy_failure"] * 6)

    def test_gate_rejects_unknown_outcomes(self) -> None:
        for outcome in ("infrastructure_error", "invalid_evidence", "task_failure", "SUCCESS", ""):
            with self.subTest(outcome=outcome), self.assertRaises(ValueError):
                classify_attempts([outcome])

    def test_gate_rejects_unknown_outcome_among_valid_attempts(self) -> None:
        with self.assertRaises(ValueError):
            classify_attempts(["policy_failure", "infrastructure_error", "policy_failure"])

    def test_gate_does_not_modify_attempts(self) -> None:
        outcomes = ["policy_failure", "success"]

        classify_attempts(outcomes)

        self.assertEqual(outcomes, ["policy_failure", "success"])


if __name__ == "__main__":
    unittest.main()
