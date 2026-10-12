import json
import random
import unittest

from robot_debug.image_perturbation import physical_value
from robot_debug.threshold_search import (
    DEFAULT_SWEEP,
    STOP_REASONS,
    ThresholdStop,
    run_threshold_search,
)


class Recorder:
    """An evaluator that records the (severity, attempts) calls it receives."""

    def __init__(self, outcomes_for):
        self.outcomes_for = outcomes_for
        self.calls = []

    def __call__(self, severity, attempts):
        self.calls.append((severity, attempts))
        return list(self.outcomes_for(severity, attempts))


def step_at(boundary, failures=5):
    """Deterministic monotone curve: ``failures`` of the attempts fail from ``boundary`` up."""

    def outcomes(severity, attempts):
        failed = failures if severity >= boundary else 0
        return ["policy_failure"] * failed + ["success"] * (attempts - failed)

    return outcomes


class SequenceTests(unittest.TestCase):
    def test_defaults_match_the_adr(self):
        self.assertEqual((0.2, 0.4, 0.6, 0.8, 1.0), DEFAULT_SWEEP)

    def test_sweep_then_bisection_visits_exactly_these_severities(self):
        evaluator = Recorder(step_at(0.35))
        result = run_threshold_search(evaluator)

        self.assertEqual([0.2, 0.4, 0.3, 0.35, 0.325, 0.3375], [call[0] for call in evaluator.calls])
        self.assertEqual({5}, {call[1] for call in evaluator.calls})
        self.assertEqual(result["levels_tried"], [call[0] for call in evaluator.calls])
        self.assertEqual("threshold_found", result["stop_reason"])
        self.assertEqual(0.35, result["threshold_severity"])
        self.assertEqual(0.3375, result["lower_bound"])
        self.assertEqual(4, result["bisection_steps_done"])
        self.assertEqual(30, result["attempts_used"])
        self.assertAlmostEqual(0.0125, result["resolution"], places=6)

    def test_levels_record_phase_outcomes_and_reproducibility(self):
        result = run_threshold_search(Recorder(step_at(0.35)))
        phases = [level["phase"] for level in result["levels"]]
        self.assertEqual(["sweep", "sweep", "bisect", "bisect", "bisect", "bisect"], phases)
        first, second = result["levels"][:2]
        self.assertEqual((0, False, True), (first["failures"], first["reproducible"], first["complete"]))
        self.assertEqual((5, True), (second["failures"], second["reproducible"]))
        self.assertEqual(["success"] * 5, first["outcomes"])

    def test_the_first_sweep_level_failing_bisects_down_from_zero(self):
        evaluator = Recorder(step_at(0.0001))
        result = run_threshold_search(evaluator)

        self.assertEqual([0.2, 0.1, 0.05, 0.025, 0.0125], [call[0] for call in evaluator.calls])
        self.assertEqual(0.0125, result["threshold_severity"])
        self.assertEqual(0.0, result["lower_bound"])
        self.assertEqual("threshold_found", result["stop_reason"])

    def test_failure_only_at_the_top_of_the_sweep(self):
        evaluator = Recorder(step_at(0.95))
        result = run_threshold_search(evaluator)

        self.assertEqual([0.2, 0.4, 0.6, 0.8, 1.0, 0.9, 0.95, 0.925, 0.9375],
                         [call[0] for call in evaluator.calls])
        self.assertEqual(0.95, result["threshold_severity"])
        self.assertEqual(0.9375, result["lower_bound"])

    def test_no_reproducible_failure_is_a_valid_result(self):
        evaluator = Recorder(step_at(2.0))
        result = run_threshold_search(evaluator)

        self.assertEqual(list(DEFAULT_SWEEP), [call[0] for call in evaluator.calls])
        self.assertEqual("no_reproducible_failure", result["stop_reason"])
        self.assertIsNone(result["threshold_severity"])
        self.assertIsNone(result["resolution"])
        self.assertEqual(1.0, result["lower_bound"])
        self.assertEqual(25, result["attempts_used"])
        self.assertEqual(0, result["bisection_steps_done"])

    def test_four_of_five_is_the_reproducibility_gate(self):
        for failures, reproducible in ((3, False), (4, True), (5, True)):
            with self.subTest(failures=failures):
                result = run_threshold_search(
                    Recorder(step_at(0.0001, failures=failures)), bisection_steps=0)
                self.assertEqual(reproducible, result["threshold_severity"] == 0.2)

    def test_custom_gate_sweep_and_steps(self):
        evaluator = Recorder(step_at(0.5, failures=2))
        result = run_threshold_search(
            evaluator, sweep=(0.5, 1.0), attempts=3, required_failures=2, bisection_steps=2)
        self.assertEqual([(0.5, 3), (0.25, 3), (0.375, 3)], evaluator.calls)
        self.assertEqual(0.5, result["threshold_severity"])
        self.assertEqual(0.375, result["lower_bound"])

    def test_zero_bisection_steps_reports_the_coarse_level(self):
        result = run_threshold_search(Recorder(step_at(0.35)), bisection_steps=0)
        self.assertEqual(0.4, result["threshold_severity"])
        self.assertEqual(0.2, result["lower_bound"])
        self.assertEqual("threshold_found", result["stop_reason"])

    def test_severities_are_clean_decimals_not_float_noise(self):
        evaluator = Recorder(step_at(0.0001))
        run_threshold_search(evaluator, sweep=(0.6,), bisection_steps=6)
        for severity, _ in evaluator.calls:
            self.assertEqual(round(severity, 6), severity)

    def test_result_is_json_clean_and_carries_physical_values(self):
        result = run_threshold_search(
            Recorder(step_at(0.35)), physical=lambda severity: physical_value("darken", severity))
        json.dumps(result, allow_nan=False)
        self.assertEqual({"name": "brightness_factor", "value": round(1 - 0.95 * 0.35, 6)},
                         result["threshold_physical"])
        self.assertTrue(all("physical" in level for level in result["levels"]))
        self.assertIn(result["stop_reason"], STOP_REASONS)


class StochasticTests(unittest.TestCase):
    def curve(self, midpoint, rng):
        def outcomes(severity, attempts):
            probability = min(1.0, max(0.0, (severity - midpoint) * 8 + 0.5))
            return ["policy_failure" if rng.random() < probability else "success" for _ in range(attempts)]

        return outcomes

    def test_invariants_hold_for_noisy_monotone_curves(self):
        for seed in range(40):
            rng = random.Random(seed)
            evaluator = Recorder(self.curve(0.1 + 0.015 * seed, rng))
            result = run_threshold_search(evaluator)
            with self.subTest(seed=seed):
                self.assertIn(result["stop_reason"], ("threshold_found", "no_reproducible_failure"))
                tried = {level["severity"]: level for level in result["levels"]}
                self.assertEqual(len(tried), len(result["levels"]), "no level is tried twice")
                if result["stop_reason"] == "no_reproducible_failure":
                    self.assertTrue(all(not level["reproducible"] for level in result["levels"]))
                    continue
                threshold = result["threshold_severity"]
                self.assertTrue(tried[threshold]["reproducible"])
                self.assertLess(result["lower_bound"], threshold)
                if result["lower_bound"] > 0:
                    self.assertFalse(tried[result["lower_bound"]]["reproducible"])
                # four halvings of the first interval, never wider than the coarse step
                self.assertLessEqual(result["resolution"], 0.2 + 1e-9)
                self.assertEqual(4, result["bisection_steps_done"])
                for level in result["levels"]:
                    self.assertEqual(level["failures"] >= 4, level["reproducible"])


class StopTests(unittest.TestCase):
    def test_an_invalid_attempt_stops_the_family_and_is_not_a_policy_failure(self):
        calls = []

        def evaluator(severity, attempts):
            calls.append(severity)
            return ["policy_failure"] * 4 + ["infrastructure_error"]

        result = run_threshold_search(evaluator)

        self.assertEqual([0.2], calls)
        self.assertEqual("infrastructure_error", result["stop_reason"])
        self.assertIsNone(result["threshold_severity"])
        level = result["levels"][0]
        self.assertFalse(level["complete"])
        self.assertIsNone(level["reproducible"])
        self.assertIsNone(level["failures"])

    def test_an_invalid_attempt_mid_bisection_keeps_the_best_reproducible_level(self):
        def evaluator(severity, attempts):
            if severity == 0.3:
                return ["success", "cancelled", "success", "success", "success"]
            return step_at(0.35)(severity, attempts)

        result = run_threshold_search(evaluator)

        self.assertEqual("infrastructure_error", result["stop_reason"])
        self.assertEqual(0.4, result["threshold_severity"])
        self.assertEqual(0.2, result["lower_bound"])
        self.assertEqual([0.2, 0.4, 0.3], result["levels_tried"])

    def test_wrong_attempt_counts_and_non_sequences_are_infrastructure_errors(self):
        for returned in ([], ["policy_failure"] * 4, ["policy_failure"] * 6, None, "policy_failure", 5):
            with self.subTest(returned=returned):
                result = run_threshold_search(lambda severity, attempts: returned)
                self.assertEqual("infrastructure_error", result["stop_reason"])
                self.assertIsNone(result["threshold_severity"])

    def test_an_evaluator_exception_is_recorded_by_type_only(self):
        def evaluator(severity, attempts):
            raise RuntimeError("secret path /tmp/x")

        result = run_threshold_search(evaluator)

        self.assertEqual("infrastructure_error", result["stop_reason"])
        self.assertEqual("RuntimeError", result["error"])
        self.assertNotIn("secret", json.dumps(result))

    def test_threshold_stop_ends_the_search_with_its_reason_and_keeps_partial_attempts(self):
        def evaluator(severity, attempts):
            if severity == 0.4:
                raise ThresholdStop("deadline_exhausted", ["policy_failure", "policy_failure"])
            return ["success"] * attempts

        result = run_threshold_search(evaluator)

        self.assertEqual("deadline_exhausted", result["stop_reason"])
        self.assertIsNone(result["threshold_severity"])
        self.assertEqual(0.2, result["lower_bound"])
        partial = result["levels"][-1]
        self.assertEqual((0.4, ["policy_failure", "policy_failure"], False), (
            partial["severity"], partial["outcomes"], partial["complete"]))
        self.assertEqual(7, result["attempts_used"])

    def test_threshold_stop_rejects_unknown_reasons(self):
        with self.assertRaises(ValueError):
            ThresholdStop("threshold_found")

    def test_can_start_false_before_the_first_level(self):
        evaluator = Recorder(step_at(0.35))
        result = run_threshold_search(evaluator, can_start=lambda: False)
        self.assertEqual([], evaluator.calls)
        self.assertEqual("deadline_exhausted", result["stop_reason"])
        self.assertEqual([], result["levels"])
        self.assertIsNone(result["threshold_severity"])
        self.assertEqual(0.0, result["lower_bound"])

    def test_can_start_false_during_bisection_keeps_the_coarse_threshold(self):
        evaluator = Recorder(step_at(0.35))
        answers = iter([True, True, True, False])
        result = run_threshold_search(evaluator, can_start=lambda: next(answers, False))

        self.assertEqual([0.2, 0.4, 0.3], [call[0] for call in evaluator.calls])
        self.assertEqual("deadline_exhausted", result["stop_reason"])
        self.assertEqual(0.4, result["threshold_severity"])
        self.assertEqual(0.3, result["lower_bound"])
        self.assertEqual(1, result["bisection_steps_done"])

    def test_attempt_budget_is_checked_before_each_level(self):
        evaluator = Recorder(step_at(0.35))
        result = run_threshold_search(evaluator, max_attempts=12)

        self.assertEqual([0.2, 0.4], [call[0] for call in evaluator.calls])
        self.assertEqual("budget_exhausted", result["stop_reason"])
        self.assertEqual(10, result["attempts_used"])
        self.assertEqual(0.4, result["threshold_severity"])
        self.assertEqual(0.2, result["lower_bound"])

    def test_an_exactly_sufficient_budget_completes(self):
        result = run_threshold_search(Recorder(step_at(0.35)), max_attempts=30)
        self.assertEqual("threshold_found", result["stop_reason"])

    def test_budget_exhausted_inside_the_sweep_has_no_threshold(self):
        result = run_threshold_search(Recorder(step_at(0.9)), max_attempts=10)
        self.assertEqual("budget_exhausted", result["stop_reason"])
        self.assertIsNone(result["threshold_severity"])
        self.assertEqual(0.4, result["lower_bound"])


class ValidationTests(unittest.TestCase):
    def test_rejects_invalid_parameters(self):
        evaluator = Recorder(step_at(0.5))
        bad = (
            dict(sweep=()),
            dict(sweep=(0.4, 0.2)),
            dict(sweep=(0.2, 0.2)),
            dict(sweep=(0.0, 0.5)),
            dict(sweep=(0.5, 1.5)),
            dict(sweep=(float("nan"),)),
            dict(sweep=(True,)),
            dict(sweep="0.5"),
            dict(attempts=0),
            dict(attempts=5.0),
            dict(attempts=True),
            dict(required_failures=0),
            dict(required_failures=6),
            dict(bisection_steps=-1),
            dict(bisection_steps=2.0),
            dict(max_attempts=-1),
            dict(max_attempts=1.5),
        )
        for kwargs in bad:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                run_threshold_search(evaluator, **kwargs)
        self.assertEqual([], evaluator.calls)


if __name__ == "__main__":
    unittest.main()
