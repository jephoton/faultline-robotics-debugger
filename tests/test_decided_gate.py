"""Early-decided repeatability gates (ADR 0029, M3): equivalence and scheduling."""

from __future__ import annotations

import itertools
import unittest

from robot_debug import decided_gate as dg
from tests.scenario_fakes import FakeExecutor

S, F = "success", "policy_failure"
ALL_SEQUENCES = list(itertools.product((S, F), repeat=5))


def first_decision(decide, sequence):
    """(attempts needed, decision) from the first prefix that decides."""
    for count in range(1, len(sequence) + 1):
        decision = decide(list(sequence[:count]))
        if decision is not None:
            return count, decision
    return len(sequence), None


class DecideTests(unittest.TestCase):
    def test_failure_gate_early_decision_equals_the_five_attempt_decision(self):
        self.assertEqual(len(ALL_SEQUENCES), 32)
        for sequence in ALL_SEQUENCES:
            with self.subTest(sequence=sequence):
                full = dg.decide(list(sequence))
                self.assertIn(full, ("reproduces", "does_not_reproduce"))
                self.assertEqual(full, "reproduces" if sequence.count(F) >= 4 else "does_not_reproduce")
                needed, early = first_decision(dg.decide, sequence)
                self.assertEqual(early, full)
                # decided exactly at the 4th failure or the 2nd success
                failures = successes = 0
                for position, outcome in enumerate(sequence, start=1):
                    failures += outcome == F
                    successes += outcome == S
                    if failures == 4 or successes == 2:
                        break
                self.assertEqual(needed, position)

    def test_failure_gate_skip_counts_over_all_sequences(self):
        skipped = [5 - first_decision(dg.decide, sequence)[0] for sequence in ALL_SEQUENCES]
        # 4 failures need 4 attempts at best; 2 successes can come as early as attempt 2.
        for amount in (0, 1, 2, 3):
            self.assertEqual(skipped.count(amount), 8)
        self.assertEqual(sum(skipped), 48)

    def test_pass_gate_early_decision_equals_the_five_attempt_decision(self):
        for sequence in ALL_SEQUENCES:
            with self.subTest(sequence=sequence):
                full = dg.decide_pass(list(sequence))
                self.assertEqual(full, "passes" if sequence.count(S) == 5 else "fails")
                needed, early = first_decision(dg.decide_pass, sequence)
                self.assertEqual(early, full)
                if full == "fails":
                    self.assertEqual(needed, sequence.index(F) + 1)
                else:
                    self.assertEqual(needed, 5)

    def test_undecided_until_the_outcome_is_fixed(self):
        self.assertIsNone(dg.decide([]))
        self.assertIsNone(dg.decide([F, F, F]))
        self.assertIsNone(dg.decide([F, S, F, F]))
        self.assertEqual(dg.decide([F, F, F, F]), "reproduces")
        self.assertEqual(dg.decide([S, F, S]), "does_not_reproduce")
        self.assertIsNone(dg.decide_pass([]))
        self.assertIsNone(dg.decide_pass([S, S, S, S]))
        self.assertEqual(dg.decide_pass([S, S, F]), "fails")

    def test_custom_gate_sizes(self):
        self.assertEqual(dg.decide([S], required_failures=3, attempts=3), "does_not_reproduce")
        self.assertIsNone(dg.decide([F, F], required_failures=3, attempts=3))
        self.assertEqual(dg.decide([F, F, F], required_failures=3, attempts=3), "reproduces")
        self.assertEqual(dg.decide_pass([S, S, S], attempts=3), "passes")

    def test_invalid_scene_is_decided_at_once_and_is_never_a_failure(self):
        self.assertEqual(dg.decide(["invalid_scene"]), "invalid_scene")
        self.assertEqual(dg.decide([F, F, F, "invalid_scene"]), "invalid_scene")
        self.assertEqual(dg.decide_pass(["invalid_scene"]), "invalid_scene")
        self.assertEqual(dg.decide_pass([S, "invalid_scene"]), "invalid_scene")

    def test_rejects_unknown_outcomes_too_many_attempts_and_bad_parameters(self):
        with self.assertRaises(ValueError):
            dg.decide(["timeout"])
        with self.assertRaises(ValueError):
            dg.decide([S] * 6)
        with self.assertRaises(ValueError):
            dg.decide_pass([S] * 6)
        for kwargs in ({"required_failures": 0}, {"required_failures": 6}, {"attempts": 0},
                       {"attempts": True}, {"required_failures": 4.0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                dg.decide([S], **kwargs)


def sequence_executor(sequences, workers=1):
    """Executor whose attempt ``i`` of candidate ``key`` yields ``sequences[key][i]``."""

    return FakeExecutor(lambda item: sequences[item["key"]][item["attempt"]], workers=workers)


def candidate(key, kind="failure"):
    return {"key": key, "item": {"key": key}, "kind": kind}


class RunGatesTests(unittest.TestCase):
    def test_every_sequence_matches_the_full_decision_and_counts_skips(self):
        # One slot in flight: the decided candidate's later attempts are never submitted.
        for sequence in ALL_SEQUENCES:
            with self.subTest(sequence=sequence):
                executor = sequence_executor({"c": sequence})
                run = dg.run_gates(executor, [candidate("c")], max_in_flight=1)
                needed, expected = first_decision(dg.decide, sequence)
                self.assertEqual(run.decisions["c"], dg.decide(list(sequence)))
                self.assertEqual(run.decisions["c"], expected)
                self.assertEqual(len(executor.executed), needed)
                self.assertEqual(len(executor.submitted), needed)
                self.assertEqual(run.skipped["c"], 5 - needed)
                self.assertEqual(run.skipped_total, 5 - needed)
                self.assertEqual(run.outcomes["c"], list(sequence[:needed]))
                self.assertIsNone(run.stop)
                self.assertEqual(run.late, [])

    def test_upfront_submission_loses_at_most_the_attempt_already_started(self):
        # Only the first wave of four is submitted up front; a freed worker takes the next queued
        # attempt of that wave before the gate can withdraw it. The fifth is held back.
        for sequence in ALL_SEQUENCES:
            with self.subTest(sequence=sequence):
                executor = sequence_executor({"c": sequence}, workers=1)
                run = dg.run_gates(executor, [candidate("c")], drain=True)
                needed, expected = first_decision(dg.decide, sequence)
                self.assertEqual(run.decisions["c"], expected)
                self.assertEqual(len(executor.executed), 5 if needed == 5 else min(4, needed + 1))
                self.assertEqual(run.skipped_total, 5 - len(executor.executed))
                self.assertEqual(len(executor.withdrawn), len(executor.submitted) - len(executor.executed))
                self.assertEqual(run.outcomes["c"][:needed], list(sequence[:needed]))

    def test_the_fifth_attempt_is_held_until_the_first_four_are_back_and_only_run_if_needed(self):
        for sequence in ALL_SEQUENCES:
            for workers in (1, 2, 4, 12):
                for in_flight in (None, 12):
                    with self.subTest(sequence=sequence, workers=workers, in_flight=in_flight):
                        executor = sequence_executor({"c": sequence}, workers=workers)
                        back_at_submit = []
                        original = executor.submit

                        def watching(item, original=original, executor=executor, back=back_at_submit):
                            back.append(sum(1 for t in executor.submitted if t.done()))
                            return original(item)

                        executor.submit = watching
                        run = dg.run_gates(executor, [candidate("c")], max_in_flight=in_flight, drain=True)
                        self.assertEqual(run.decisions["c"], dg.decide(list(sequence)),
                                         "same decision as running all five")
                        needs_fifth = sequence[:4].count(F) == 3
                        self.assertEqual(list(range(5 if needs_fifth else 4)),
                                         [t.item["attempt"] for t in executor.submitted])
                        if needs_fifth:
                            self.assertEqual(4, back_at_submit[4], "the fifth waited for the first four")
                        self.assertEqual(run.skipped_total, 5 - len(executor.executed))

    def test_a_pass_gate_keeps_all_five_in_flight(self):
        executor = sequence_executor({"r": (S,) * 5}, workers=5)
        run = dg.run_gates(executor, [candidate("r", "pass")], drain=True)
        self.assertEqual(5, len(executor.submitted))
        self.assertEqual("passes", run.decisions["r"])

    def test_only_required_failures_tickets_are_in_flight_until_they_are_back(self):
        executor = sequence_executor({"c": (F, F, F, S, F)}, workers=12)
        peaks = []
        original = executor.submit

        def watching(item):
            ticket = original(item)
            peaks.append(sum(1 for t in executor.submitted if not t.done()))
            return ticket

        executor.submit = watching
        dg.run_gates(executor, [candidate("c")], max_in_flight=12, drain=True)
        self.assertEqual(4, max(peaks[:4]))
        self.assertEqual(1, peaks[4], "the fifth is alone in flight")

    def test_the_cap_of_in_flight_tickets_still_holds(self):
        sequences = {k: (F, F, F, S, F) for k in "abcde"}
        executor = sequence_executor(sequences, workers=12)
        peaks = []
        original = executor.submit

        def watching(item):
            ticket = original(item)
            peaks.append(sum(1 for t in executor.submitted if not t.done()))
            return ticket

        executor.submit = watching
        run = dg.run_gates(executor, [candidate(k) for k in "abcde"], max_in_flight=6, drain=True)
        self.assertLessEqual(max(peaks), 6)
        self.assertEqual({k: "reproduces" for k in "abcde"}, run.decisions)

    def test_pass_gate_stops_at_the_first_failure(self):
        for sequence in ALL_SEQUENCES:
            with self.subTest(sequence=sequence):
                executor = sequence_executor({"r": sequence})
                run = dg.run_gates(executor, [candidate("r", "pass")], max_in_flight=1)
                needed, expected = first_decision(dg.decide_pass, sequence)
                self.assertEqual(run.decisions["r"], expected)
                self.assertEqual(len(executor.executed), needed)
                self.assertEqual(run.skipped_total, 5 - needed)

    def test_started_attempts_finish_and_never_change_the_decision(self):
        sequence = (S, S, F, F, F)
        executor = sequence_executor({"c": sequence}, workers=5)
        run = dg.run_gates(executor, [candidate("c")], drain=True)
        self.assertEqual(run.decisions["c"], "does_not_reproduce")
        self.assertEqual(run.skipped_total, 1)           # the first wave of four had all started
        self.assertEqual(len(executor.executed), 4)
        self.assertEqual(run.outcomes["c"], list(sequence[:4]))
        self.assertEqual(run.decisions["c"], dg.decide(list(sequence)))

    def test_freed_workers_take_attempts_of_other_candidates(self):
        sequences = {"a": (S, S, F, F, F), "b": (F, F, F, F, S), "c": (S, F, S, F, F)}
        executor = sequence_executor(sequences, workers=2)
        run = dg.run_gates(executor, [candidate("a"), candidate("b"), candidate("c")], drain=True)
        self.assertEqual(run.decisions,
                         {"a": "does_not_reproduce", "b": "reproduces", "c": "does_not_reproduce"})
        for key, sequence in sequences.items():
            self.assertEqual(run.decisions[key], dg.decide(list(sequence)))
        self.assertGreater(run.skipped_total, 0)
        self.assertEqual(len(executor.executed) + run.skipped_total, 15)
        self.assertEqual(sum(run.skipped.values()), run.skipped_total)

    def test_lazy_submission_never_submits_attempts_of_decided_candidates(self):
        sequences = {"a": (S, S, F, F, F), "b": (F, F, F, F, S)}
        executor = sequence_executor(sequences, workers=2)
        run = dg.run_gates(executor, [candidate("a"), candidate("b")], max_in_flight=2, drain=True)
        self.assertEqual(run.decisions, {"a": "does_not_reproduce", "b": "reproduces"})
        # a decides after 2 attempts and its other three are never submitted; b's first four are
        # in flight together and decide it, so its fifth is never submitted either
        self.assertEqual(len(executor.submitted), 6)
        self.assertEqual(run.skipped["a"], 3)
        self.assertEqual(run.skipped["b"], 1)
        self.assertEqual(executor.withdrawn, [])
        # attempt-major round robin over candidates
        self.assertEqual([(t.item["key"], t.item["attempt"]) for t in executor.submitted][:4],
                         [("a", 0), ("b", 0), ("a", 1), ("b", 1)])

    def test_items_get_an_attempt_index_without_mutating_the_candidate(self):
        base = {"key": "c", "payload": {"x": 1}}
        executor = sequence_executor({"c": (F, F, F, S, F)})
        dg.run_gates(executor, [{"key": "c", "item": base, "kind": "failure"}])
        self.assertEqual(base, {"key": "c", "payload": {"x": 1}})
        self.assertEqual([t.item["attempt"] for t in executor.submitted], [0, 1, 2, 3, 4])
        self.assertTrue(all(t.item["payload"] == {"x": 1} for t in executor.submitted))

    def test_invalid_scene_decides_at_once_and_withdraws_the_rest(self):
        executor = FakeExecutor(lambda item: "invalid_scene", workers=1)
        run = dg.run_gates(executor, [candidate("c")])
        self.assertEqual(run.decisions["c"], "invalid_scene")
        self.assertEqual(len(executor.executed), 1)
        # the single worker had already taken the second attempt; the other three are withdrawn
        self.assertEqual(run.skipped_total, 3)
        self.assertEqual(len(run.late), 1)
        lazy = FakeExecutor(lambda item: "invalid_scene", workers=1)
        run = dg.run_gates(lazy, [candidate("c")], max_in_flight=1)
        self.assertEqual((len(lazy.executed), run.skipped_total), (1, 4))

    def test_infrastructure_error_stops_the_whole_batch(self):
        def outcome(item):
            if item["key"] == "bad" and item["attempt"] == 0:
                return {"status": "infrastructure_error", "error": "worker_lost"}
            return F
        executor = FakeExecutor(outcome, workers=1)
        run = dg.run_gates(executor, [candidate("bad"), candidate("good")])
        self.assertEqual(run.stop, "infrastructure_error")
        self.assertEqual(run.detail, "infrastructure_error")
        self.assertIsNone(run.decisions["bad"])
        self.assertIsNone(run.decisions["good"])
        self.assertEqual(executor.queue, [])           # nothing left waiting in the pool

    def test_attempts_withdrawn_because_the_batch_stopped_are_not_early_decision_savings(self):
        def outcome(item):
            if item["key"] == "bad" and item["attempt"] == 0:
                return {"status": "infrastructure_error", "error": "worker_lost"}
            return F

        executor = FakeExecutor(outcome, workers=1)
        run = dg.run_gates(executor, [candidate("bad"), candidate("good")])
        self.assertEqual("infrastructure_error", run.stop)
        self.assertGreater(run.stop_withdrawn_total, 0)
        self.assertEqual(0, run.skipped_total, "nothing was decided, so nothing was saved")
        self.assertEqual(len(executor.withdrawn), run.stop_withdrawn_total + 0)
        for key in ("bad", "good"):
            withdrawn = [r for r in run.records[key] if r.get("status") == "stop_withdrawn"]
            self.assertEqual(run.stop_withdrawn[key], len(withdrawn))
        self.assertEqual(run.stop_withdrawn_total, run.to_dict()["stop_withdrawn_total"])

    def test_a_stop_after_a_decision_keeps_the_decided_savings_separate(self):
        def outcome(item):
            # submission is attempt-major round robin: done0 late0 done1 late1 ...
            if item["key"] == "late" and item["attempt"] == 1:
                return {"status": "infrastructure_error"}
            return S if item["key"] == "done" else F

        executor = FakeExecutor(outcome, workers=1)
        run = dg.run_gates(executor, [candidate("done"), candidate("late")])
        self.assertEqual("infrastructure_error", run.stop)
        self.assertEqual("does_not_reproduce", run.decisions["done"])
        self.assertGreater(run.skipped["done"], 0)
        self.assertEqual(0, run.skipped["late"])
        self.assertGreater(run.stop_withdrawn["late"], 0)
        self.assertEqual(0, run.stop_withdrawn["done"])

    def test_cancelled_records_are_infrastructure_errors(self):
        executor = FakeExecutor(lambda item: {"status": "cancelled"}, workers=1)
        run = dg.run_gates(executor, [candidate("c")])
        self.assertEqual((run.stop, run.detail), ("infrastructure_error", "cancelled"))

    def test_deadline_skipped_record_means_deadline_exhausted(self):
        executor = FakeExecutor(lambda item: {"status": "deadline_skipped"}, workers=1)
        run = dg.run_gates(executor, [candidate("c")])
        self.assertEqual(run.stop, "deadline_exhausted")

    def test_remaining_time_is_checked_before_and_while_running(self):
        executor = sequence_executor({"c": (F,) * 5})
        run = dg.run_gates(executor, [candidate("c")], remaining=lambda: 0.0)
        self.assertEqual(run.stop, "deadline_exhausted")
        self.assertEqual(executor.submitted, [])

        calls = []

        def running_out():
            calls.append(1)
            return 10.0 if len(calls) <= 3 else 0.0

        executor = sequence_executor({"c": (F,) * 5})
        run = dg.run_gates(executor, [candidate("c")], remaining=running_out)
        self.assertEqual(run.stop, "deadline_exhausted")
        self.assertIsNone(run.decisions["c"])
        self.assertEqual(executor.queue, [])

    def test_without_drain_started_attempts_are_returned_as_late(self):
        sequences = {"a": (S, S, F, F, F)}
        executor = sequence_executor(sequences, workers=5)
        run = dg.run_gates(executor, [candidate("a")], drain=False)
        self.assertEqual(run.decisions["a"], "does_not_reproduce")
        self.assertEqual(len(run.late), 2, "the first wave of four was in flight; two were still running")
        collected = dg.collect_late(executor, run.late)
        self.assertEqual([record["outcome"] for _, record in collected], [F, F])
        self.assertTrue(all(key == "a" for key, _ in collected))

    def test_mixed_kinds_in_one_batch(self):
        sequences = {"f": (F, F, F, F, S), "r": (S, S, S, S, S)}
        executor = sequence_executor(sequences, workers=12)
        run = dg.run_gates(executor, [candidate("f"), candidate("r", "pass")], drain=True)
        self.assertEqual(run.decisions, {"f": "reproduces", "r": "passes"})

    def test_records_are_returned_for_every_candidate(self):
        sequences = {"a": (F,) * 5, "b": (S, S, F, F, F)}
        executor = sequence_executor(sequences, workers=1)
        run = dg.run_gates(executor, [candidate("a"), candidate("b")], drain=True)
        statuses = [record["status"] for record in run.records["b"]]
        self.assertEqual(statuses.count("valid"), 2)
        self.assertEqual(statuses.count("decided_skipped"), 2, "two submitted attempts were withdrawn")
        self.assertEqual(run.skipped["b"], 3, "and the held fifth was never submitted")

    def test_validation(self):
        executor = sequence_executor({})
        bad = [
            [candidate("a"), candidate("a")],
            [{"key": "a", "item": {}, "kind": "other"}],
            [{"key": "", "item": {}, "kind": "failure"}],
            [{"key": "a", "item": [], "kind": "failure"}],
            [{"key": "a", "item": {}}],
        ]
        for candidates in bad:
            with self.subTest(candidates=candidates), self.assertRaises(ValueError):
                dg.run_gates(executor, candidates)
        with self.assertRaises(ValueError):
            dg.run_gates(executor, [candidate("a")], max_in_flight=0)
        self.assertEqual(dg.run_gates(executor, []).decisions, {})

    def test_to_dict_is_json_clean(self):
        import json
        executor = sequence_executor({"c": (F,) * 5}, workers=1)
        run = dg.run_gates(executor, [candidate("c")])
        json.dumps(run.to_dict(), allow_nan=False)


if __name__ == "__main__":
    unittest.main()
