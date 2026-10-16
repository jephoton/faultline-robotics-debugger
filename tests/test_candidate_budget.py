"""``budget.max_candidates`` must fit the reduce Job's deadline cap, checked before any Job exists."""

from __future__ import annotations

import unittest

from robot_debug import orchestrator as orch
from robot_debug import spec as sp
from tests.test_orchestrator import FakeTools, full_script, make_world, spec_for
from tests.test_paraphrase_pipeline import ParaphraseTools, paraphrase_spec


def with_candidates(spec: sp.Spec, count: int) -> sp.Spec:
    return sp.parse_spec(dict(spec.raw, budget={"max_spend_usd": 10.0, "max_hours": 5, "max_candidates": count}))


class Scenario(unittest.TestCase):
    def test_the_limit_on_libero_10_is_36(self):
        tools = FakeTools()
        self.assertEqual(36, tools.candidate_limit(spec_for()))
        self.assertIsNone(tools.candidate_limit(spec_for("audit")), "an audit has no reduce Job")

    def test_a_budget_over_the_limit_names_the_largest_one_that_fits(self):
        for count, fits in ((1, True), (36, True), (37, False), (60, False)):
            with self.subTest(count=count):
                spec = with_candidates(spec_for(), count)
                if fits:
                    orch.check_candidate_budget(spec, FakeTools())
                    continue
                with self.assertRaises(orch.StopRun) as caught:
                    orch.check_candidate_budget(spec, FakeTools())
                self.assertEqual("candidates_too_large", caught.exception.reason)
                self.assertIn("largest that fits is 36", caught.exception.detail)
                self.assertIn("budget.max_candidates {}".format(count), caught.exception.detail)

    def test_the_default_budget_fits_and_tools_that_cannot_say_are_not_checked(self):
        orch.check_candidate_budget(spec_for(), FakeTools())
        orch.check_candidate_budget(spec_for(), object())

    def test_a_replay_is_not_subject_to_the_budget(self):
        orch.check_candidate_budget(spec_for("replay"), FakeTools())

    def test_the_dry_run_message_names_the_maximum_too(self):
        with self.assertRaises(orch.StopRun) as caught:
            orch.dry_run_lines(with_candidates(spec_for(), 60), FakeTools())
        self.assertIn("largest that fits is 36", caught.exception.detail)

    def test_a_too_large_budget_stops_before_the_backend_is_prepared_or_a_job_submitted(self):
        temp, runner, backend, *_ = make_world(with_candidates(spec_for(), 40), full_script())
        self.addCleanup(temp.cleanup)
        result = runner.diagnose()
        self.assertEqual((result.status, result.reason), ("stopped", "candidates_too_large"))
        self.assertEqual((backend.prepared, backend.submitted), (0, []))
        self.assertEqual(backend.finished, 1)


class Paraphrase(unittest.TestCase):
    def test_the_limit_is_42_and_the_default_of_24_fits(self):
        tools = FakeTools()
        self.assertEqual(42, tools.candidate_limit(paraphrase_spec()))
        orch.check_candidate_budget(paraphrase_spec(), tools)

    def test_a_budget_over_the_limit_names_the_largest_one_that_fits(self):
        orch.check_candidate_budget(with_candidates(paraphrase_spec(), 42), FakeTools())
        with self.assertRaises(orch.StopRun) as caught:
            orch.check_candidate_budget(with_candidates(paraphrase_spec(), 43), FakeTools())
        self.assertIn("largest that fits is 42", caught.exception.detail)

    def test_the_dry_run_message_names_the_maximum_too(self):
        with self.assertRaises(orch.StopRun) as caught:
            orch.dry_run_lines(with_candidates(paraphrase_spec(), 60), FakeTools())
        self.assertIn("largest that fits is 42", caught.exception.detail)

    def test_too_many_candidates_stop_before_the_paraphrases_are_requested(self):
        tools = ParaphraseTools()
        temp, runner, backend, tools, *_ = make_world(with_candidates(paraphrase_spec(), 60), [], tools=tools)
        self.addCleanup(temp.cleanup)
        result = runner.diagnose()
        self.assertEqual("candidates_too_large", result.reason)
        self.assertEqual(([], []), (tools.generated, backend.submitted))


if __name__ == "__main__":
    unittest.main()
