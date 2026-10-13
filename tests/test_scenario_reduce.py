"""Scenario reducer tests against synthetic worlds with a known culprit."""

from __future__ import annotations

import json
import random
import unittest

import numpy as np

from robot_debug import scenario_reduce as sr
from robot_debug import scenario_state as ss
from tests.scenario_fakes import (
    FakeExecutor, base_state, synthetic_layout, with_object_pose)

S, F, INVALID = "success", "policy_failure", "invalid_scene"


def row(entity, *, position=None, rotation=None, joints=None, kind="object"):
    """A difference-table row; sizes are centimetres / degrees for readability."""

    result = {
        "entity": entity, "kind": kind,
        "position": None if position is None else
        {"offset_m": [position / 100.0, 0.0, 0.0], "distance_m": position / 100.0},
        "rotation": None if rotation is None else {"angle_deg": float(rotation)},
        "joints": [] if joints is None else
        [{"name": entity + "_j", "type": "hinge", "offset": joints, "unit": "deg"}],
    }
    result["distance"] = (position or 0.0) + (rotation or 0.0) / 10.0 + (joints or 0.0) / 10.0
    return result


def standard_table():
    return [
        row("robot", joints=8.0, kind="robot"),
        row("soup_1", position=3.0, rotation=40.0),
        row("microwave_1", joints=12.0),
        row("bowl_1", position=6.0),
    ]


ORDER = ["soup_1", "bowl_1", "robot", "microwave_1"]


class World:
    """Synthetic truth: ``fails(selection)`` says whether a hybrid reproduces."""

    def __init__(self, fails, *, invalid=None, flaky=False, reference_fail=None, failing_fails=True):
        self.fails = fails
        self.invalid = invalid or (lambda selection: False)
        self.flaky = flaky
        self.reference_fail = reference_fail or {}
        self.failing_fails = failing_fails
        self.broken = lambda spec: False

    def outcome(self, item):
        spec, attempt = item["spec"], item["attempt"]
        if self.broken(spec):
            return {"status": "infrastructure_error", "error": "worker_lost"}
        if spec["role"] == "failing":
            failing = self.failing_fails
        elif spec["role"] == "reference":
            first_fail = self.reference_fail.get(spec["reference"])
            if first_fail is not None:
                return F if attempt == first_fail else S
            return S
        else:
            if self.invalid(spec["selection"]):
                return INVALID
            failing = self.fails(spec["selection"])
        if self.flaky:
            return F if (failing and attempt != 1) or (not failing and attempt == 1) else S
        return F if failing else S


def prepare(spec):
    key = json.dumps(spec, sort_keys=True)
    return key, {"spec": spec}


def reduce(world, table=None, *, order=ORDER, workers=12, references=None, **kwargs):
    executor = FakeExecutor(world.outcome, workers=workers)
    refs = references or [{"id": "r0", "differences": table or standard_table()}]
    result = sr.run_scenario_reduction(executor, prepare, refs, order=order, **kwargs)
    return result, executor


def comp(selection, entity, name):
    return selection.get(entity, {}).get(name, 0.0)


def candidate_trace(result):
    return [(c["phase"], c["role"], c["selection"]) for c in result["candidates"]]


class SingleCulpritTests(unittest.TestCase):
    def setUp(self):
        # soup rotation of at least 0.4 of the difference is the whole cause
        self.world = World(lambda sel: comp(sel, "soup_1", "rotation") >= 0.4)

    def test_reduces_to_the_rotation_of_one_object_with_a_stated_tolerance(self):
        result, _ = reduce(self.world)
        self.assertEqual(result["stop_reason"], "reduced")
        self.assertTrue(result["reduced"])
        self.assertEqual(result["reference"], "r0")
        self.assertEqual(result["surviving_entities"], ["soup_1"])
        self.assertEqual(result["final_selection"], {"soup_1": {"rotation": 0.4375}})
        (part,) = result["parts"]
        self.assertEqual((part["entity"], part["component"]), ("soup_1", "rotation"))
        self.assertEqual((part["t"], part["lower"], part["resolution"]), (0.4375, 0.375, 0.0625))
        self.assertEqual(part["steps_done"], 4)
        self.assertIsNotNone(result["final_candidate"])
        self.assertEqual(result["candidates"][result["final_candidate"]]["selection"],
                         result["final_selection"])

    def test_exact_candidate_sequence_for_a_fixed_order(self):
        result, _ = reduce(self.world)
        full = {"robot": {"joints": 1.0}, "soup_1": {"position": 1.0, "rotation": 1.0},
                "microwave_1": {"joints": 1.0}, "bowl_1": {"position": 1.0}}
        soup = {"soup_1": {"position": 1.0, "rotation": 1.0}}
        bowl = {"bowl_1": {"position": 1.0}}
        expected = [
            ("gate", "failing", None),
            ("gate", "reference", None),
            ("gate", "hybrid", full),
            ("probe", "hybrid", soup),
            ("probe", "hybrid", bowl),                      # shares the round with soup
            ("split", "hybrid", {"soup_1": {"position": 1.0}}),
            ("split", "hybrid", {"soup_1": {"rotation": 1.0}}),
            ("shrink", "hybrid", {"soup_1": {"rotation": 0.5}}),
            ("shrink", "hybrid", {"soup_1": {"rotation": 0.25}}),
            ("shrink", "hybrid", {"soup_1": {"rotation": 0.375}}),
            ("shrink", "hybrid", {"soup_1": {"rotation": 0.4375}}),
        ]
        self.assertEqual(candidate_trace(result), expected)
        self.assertEqual(result["candidates_tested"], 9)

    def test_the_ranked_probe_skips_ddmin_and_reports_what_it_modelled(self):
        result, _ = reduce(self.world, concurrency=1)
        probe = result["ranked_probe"]
        self.assertEqual((probe["hit"], probe["rank"]), ("soup_1", 1))
        self.assertEqual(probe["candidates_run"], 1)
        self.assertEqual(probe["modelled_ddmin_candidates"], 2)
        self.assertEqual(probe["modelled_candidates_avoided"], 1)
        self.assertTrue(result["entity_minimal"])
        self.assertNotIn("ddmin", {c["phase"] for c in result["candidates"]})

    def test_culprit_ranked_last_still_found_by_the_probe(self):
        result, _ = reduce(self.world, order=["microwave_1", "robot", "bowl_1", "soup_1"])
        self.assertEqual(result["ranked_probe"]["rank"], 4)
        self.assertEqual(result["ranked_probe"]["candidates_run"], 4)
        self.assertEqual(result["surviving_entities"], ["soup_1"])

    def test_missing_unknown_and_duplicate_names_in_the_order_are_repaired(self):
        result, _ = reduce(self.world, order=["nothing", "bowl_1", "bowl_1"])
        self.assertEqual(result["order"][0], "bowl_1")
        self.assertEqual(sorted(result["order"]), sorted(ORDER))
        # the remainder follows largest difference first: soup 3 + 4, bowl 6, microwave 1.2, robot 0.8
        self.assertEqual(result["order"], ["bowl_1", "soup_1", "microwave_1", "robot"])
        none = reduce(self.world, order=None)[0]
        self.assertEqual(none["order"], ["soup_1", "bowl_1", "microwave_1", "robot"])


class PairAndSplitTests(unittest.TestCase):
    def setUp(self):
        def fails(sel):
            return comp(sel, "soup_1", "rotation") >= 0.5 and comp(sel, "bowl_1", "position") >= 0.25
        self.world = World(fails)

    def test_a_pair_is_found_by_delta_debugging_and_is_one_minimal(self):
        result, _ = reduce(self.world)
        self.assertEqual(result["stop_reason"], "reduced")
        self.assertEqual(result["surviving_entities"], ["soup_1", "bowl_1"])
        self.assertEqual(result["final_selection"],
                         {"soup_1": {"rotation": 0.5}, "bowl_1": {"position": 0.25}})
        self.assertIsNone(result["ranked_probe"]["hit"])
        phases = [c["phase"] for c in result["candidates"]]
        self.assertIn("ddmin", phases)
        # removing either survivor makes the task pass
        for entity in result["surviving_entities"]:
            rest = {k: v for k, v in result["final_selection"].items() if k != entity}
            self.assertFalse(self.world.fails(rest))

    def test_splitting_keeps_only_the_sufficient_part(self):
        result, _ = reduce(self.world)
        self.assertEqual(list(result["final_selection"]["soup_1"]), ["rotation"])
        splits = [c for c in result["candidates"] if c["phase"] == "split"]
        self.assertEqual(len(splits), 2)
        self.assertEqual([c["gate_met"] for c in splits], [False, True])

    def test_each_part_is_bisected_with_the_others_at_their_current_values(self):
        result, _ = reduce(self.world)
        shrink = [c for c in result["candidates"] if c["phase"] == "shrink"]
        # bowl is shrunk after soup reached 0.5, so its candidates carry soup rotation 0.5
        bowl_rounds = [c for c in shrink if "bowl_1" in c["selection"]
                       and c["selection"]["bowl_1"]["position"] < 1.0]
        self.assertTrue(bowl_rounds)
        self.assertTrue(all(c["selection"]["soup_1"]["rotation"] == 0.5 for c in bowl_rounds))
        parts = {(p["entity"], p["component"]): p for p in result["parts"]}
        self.assertEqual(parts[("soup_1", "rotation")]["t"], 0.5)
        self.assertEqual(parts[("bowl_1", "position")]["t"], 0.25)

    def test_both_parts_are_kept_when_neither_alone_reproduces(self):
        world = World(lambda sel: comp(sel, "soup_1", "rotation") > 0 and comp(sel, "soup_1", "position") > 0)
        result, _ = reduce(world, bisection_steps=0)
        self.assertEqual(result["final_selection"], {"soup_1": {"position": 1.0, "rotation": 1.0}})

    def test_both_sufficient_keeps_the_smaller_and_says_so(self):
        # soup: 3 cm position (3.0) versus 40 degrees rotation (4.0): position is smaller
        world = World(lambda sel: "soup_1" in sel)
        result, _ = reduce(world, bisection_steps=0)
        self.assertEqual(result["final_selection"], {"soup_1": {"position": 1.0}})
        self.assertEqual(result["also_sufficient"],
                         [{"entity": "soup_1", "kept": "position", "also": "rotation"}])

    def test_position_only_cause(self):
        world = World(lambda sel: comp(sel, "soup_1", "position") >= 0.3)
        result, _ = reduce(world)
        self.assertEqual(list(result["final_selection"]["soup_1"]), ["position"])
        self.assertEqual(result["final_selection"]["soup_1"]["position"], 0.3125)


class GateAndStopTests(unittest.TestCase):
    def test_failing_start_that_does_not_reproduce_stops_early(self):
        world = World(lambda sel: True, failing_fails=False)
        result, executor = reduce(world)
        self.assertEqual(result["stop_reason"], "failing_not_reproducible")
        self.assertEqual(result["candidates_tested"], 1)          # only the full-hybrid gate ran
        self.assertIsNone(result["final_selection"])
        self.assertFalse(result["reduced"])

    def test_a_full_hybrid_that_does_not_reproduce_is_reported_as_such(self):
        world = World(lambda sel: False)
        result, _ = reduce(world)
        self.assertEqual(result["stop_reason"], "failing_not_reproducible")
        self.assertEqual(result["note"], "full_hybrid_does_not_reproduce")
        self.assertIsNone(result["final_selection"])

    def test_invalid_full_hybrid_is_not_a_policy_failure(self):
        world = World(lambda sel: True, invalid=lambda sel: len(sel) == 4)
        result, _ = reduce(world)
        self.assertEqual(result["stop_reason"], "failing_not_reproducible")
        self.assertEqual(result["note"], "full_hybrid_invalid_scene")
        self.assertEqual(len(result["invalid_scenes"]), 1)

    def test_reference_fallback_uses_the_next_nearest_passing_start(self):
        world = World(lambda sel: comp(sel, "soup_1", "rotation") >= 0.4, reference_fail={"r0": 2})
        second = [row("soup_1", rotation=25.0), row("bowl_1", position=2.0)]
        refs = [{"id": "r0", "differences": standard_table()}, {"id": "r1", "differences": second}]
        result, _ = reduce(world, references=refs)
        self.assertEqual(result["stop_reason"], "reduced")
        self.assertEqual(result["reference"], "r1")
        self.assertEqual([t["id"] for t in result["references_tried"]], ["r0", "r1"])
        self.assertEqual(result["references_tried"][0]["decision"], "fails")
        self.assertEqual(result["references_tried"][1]["decision"], "passes")
        hybrids = [c for c in result["candidates"] if c["role"] == "hybrid"]
        self.assertTrue(all(c["reference"] in ("r0", "r1") for c in hybrids))
        self.assertTrue(all(c["reference"] == "r1" for c in hybrids if c["phase"] != "gate"))
        self.assertEqual(result["order"], ["soup_1", "bowl_1"])
        self.assertEqual(list(result["final_selection"]), ["soup_1"])

    def test_no_passing_reference_stops_with_reference_not_passing(self):
        world = World(lambda sel: True, reference_fail={"r0": 0, "r1": 4, "r2": 1, "r3": 0})
        refs = [{"id": "r{}".format(i), "differences": standard_table()} for i in range(4)]
        result, _ = reduce(world, references=refs)
        self.assertEqual(result["stop_reason"], "reference_not_passing")
        self.assertEqual([t["id"] for t in result["references_tried"]], ["r0", "r1", "r2"])   # at most 3
        self.assertIsNone(result["final_selection"])

    def test_candidate_budget_ends_with_a_reproducing_selection(self):
        world = World(lambda sel: "soup_1" in sel and "bowl_1" in sel)
        result, _ = reduce(world, max_candidates=3)
        self.assertEqual(result["stop_reason"], "budget_exhausted")
        self.assertEqual(result["candidates_tested"], 3)
        self.assertEqual(set(result["final_selection"]), set(ORDER))     # the full set still reproduces
        self.assertFalse(result["reduced"])

    def test_budget_during_shrink_keeps_the_best_so_far(self):
        world = World(lambda sel: comp(sel, "soup_1", "rotation") >= 0.4)
        result, _ = reduce(world, max_candidates=8)
        self.assertEqual(result["stop_reason"], "budget_exhausted")
        self.assertTrue(world.fails(result["final_selection"]))
        self.assertEqual(result["parts"], [])          # the stop came before the part summary

    def test_deadline_stops_cleanly(self):
        world = World(lambda sel: "soup_1" in sel and "bowl_1" in sel)
        executor = FakeExecutor(world.outcome, workers=12)
        result = sr.run_scenario_reduction(
            executor, prepare, [{"id": "r0", "differences": standard_table()}], order=ORDER,
            remaining=lambda: 60.0 - len(executor.executed))
        self.assertEqual(result["stop_reason"], "deadline_exhausted")
        self.assertFalse(result["reduced"])
        self.assertTrue(world.fails(result["final_selection"]))

    def test_deadline_before_anything_runs(self):
        world = World(lambda sel: True)
        result, executor = reduce(world, remaining=lambda: 0.0)
        self.assertEqual(result["stop_reason"], "deadline_exhausted")
        self.assertEqual(executor.submitted, [])
        self.assertIsNone(result["final_selection"])

    def test_infrastructure_error_stops_and_is_never_a_failure(self):
        world = World(lambda sel: comp(sel, "soup_1", "rotation") >= 0.4)
        world.broken = lambda spec: spec["role"] == "hybrid" and set(spec["selection"]) == {"bowl_1"}
        result, _ = reduce(world)
        self.assertEqual(result["stop_reason"], "infrastructure_error")
        self.assertEqual(result["error"], "infrastructure_error")
        self.assertFalse(result["reduced"])
        self.assertTrue(world.fails(result["final_selection"]))


class InvalidSceneTests(unittest.TestCase):
    def test_invalid_candidates_are_reported_and_never_count_as_failures(self):
        world = World(lambda sel: "soup_1" in sel and "robot" in sel,
                      invalid=lambda sel: set(sel) == {"bowl_1", "microwave_1"})
        result, _ = reduce(world, order=["bowl_1", "microwave_1", "soup_1", "robot"])
        self.assertEqual(result["stop_reason"], "reduced")
        self.assertEqual(result["surviving_entities"], ["soup_1", "robot"])
        invalid = [result["candidates"][i] for i in result["invalid_scenes"]]
        self.assertEqual(len(invalid), 1)
        self.assertEqual(set(invalid[0]["selection"]), {"bowl_1", "microwave_1"})
        self.assertFalse(invalid[0]["gate_met"])
        self.assertEqual(invalid[0]["decision"], "invalid_scene")


class DeterminismAndCostTests(unittest.TestCase):
    def test_same_inputs_same_record(self):
        world = World(lambda sel: comp(sel, "soup_1", "rotation") >= 0.5 and "bowl_1" in sel)
        first, _ = reduce(world)
        second, _ = reduce(world)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        json.dumps(first, allow_nan=False)

    def test_stochastic_four_of_five_failures_reduce_the_same_way(self):
        def fails(sel):
            return comp(sel, "soup_1", "rotation") >= 0.5 and "bowl_1" in sel
        steady, _ = reduce(World(fails))
        flaky, _ = reduce(World(fails, flaky=True))
        self.assertEqual(flaky["final_selection"], steady["final_selection"])
        self.assertEqual(flaky["stop_reason"], "reduced")

    def test_identical_hybrids_are_never_rerun(self):
        # one differing entity: the full hybrid, the probe singleton and later repeats coincide
        world = World(lambda sel: comp(sel, "soup_1", "rotation") >= 0.4)
        table = [row("soup_1", position=3.0, rotation=40.0)]
        result, executor = reduce(world, table)
        keys = [(c["kind"], c["key"]) for c in result["candidates"]]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(result["candidates_tested"], 1 + 2 + 4)       # full, split pair, 4 bisection steps
        self.assertEqual(result["final_selection"], {"soup_1": {"rotation": 0.4375}})
        self.assertEqual(len(executor.executed), result["attempts_run"])

    def test_early_decisions_save_attempts_when_workers_are_shared(self):
        world = World(lambda sel: comp(sel, "soup_1", "rotation") >= 0.4 and "bowl_1" in sel)
        eager, eager_exec = reduce(world, workers=2, max_in_flight=2)
        upfront, up_exec = reduce(world, workers=2)
        self.assertEqual(eager["final_selection"], upfront["final_selection"])
        self.assertGreater(eager["attempts_skipped"], 0)
        self.assertLessEqual(eager["attempts_run"], upfront["attempts_run"])
        self.assertEqual(eager["attempts_run"] + eager["attempts_skipped"],
                         sum(5 for c in eager["candidates"]))

    def test_concurrency_does_not_change_the_answer(self):
        world = World(lambda sel: comp(sel, "soup_1", "rotation") >= 0.5 and comp(sel, "bowl_1", "position") >= 0.25)
        answers = {n: reduce(world, concurrency=n)[0]["final_selection"] for n in (1, 2, 3, 4)}
        self.assertEqual(len({json.dumps(a, sort_keys=True) for a in answers.values()}), 1)

    def test_speculative_bisection_reaches_the_same_tolerance_with_extra_candidates(self):
        world = World(lambda sel: comp(sel, "soup_1", "rotation") >= 0.4)
        plain, _ = reduce(world)
        fast, _ = reduce(world, speculative_bisection=True)
        (a,), (b,) = plain["parts"], fast["parts"]
        self.assertLessEqual(b["resolution"], 0.0625)
        self.assertTrue(b["lower"] < 0.4 <= b["t"])
        self.assertEqual(a["steps_done"], b["steps_done"])
        shrink = lambda r: sum(1 for c in r["candidates"] if c["phase"] == "shrink")  # noqa: E731
        self.assertGreaterEqual(shrink(fast), shrink(plain))

    def test_bisection_can_be_switched_off(self):
        world = World(lambda sel: comp(sel, "soup_1", "rotation") >= 0.4)
        result, _ = reduce(world, bisection_steps=0)
        self.assertEqual(result["final_selection"], {"soup_1": {"rotation": 1.0}})


class OneMinimalityProperty(unittest.TestCase):
    def test_random_monotone_causes_reduce_to_one_minimal_sets(self):
        names = ["a", "b", "c", "d", "e", "f"]
        table = [row(n, position=1.0 + i, rotation=10.0 * (i + 1)) for i, n in enumerate(names)]
        for seed in range(40):
            rng = random.Random(seed)
            causes = [frozenset(rng.sample(names, rng.randint(1, 3))) for _ in range(rng.randint(1, 3))]

            def fails(selection, causes=causes):
                return any(cause <= set(selection) for cause in causes)

            for concurrency, workers, in_flight in ((1, 12, None), (2, 12, None), (3, 4, 4), (2, 2, 2)):
                with self.subTest(seed=seed, causes=sorted(map(sorted, causes)), concurrency=concurrency):
                    world = World(fails, flaky=bool(seed % 2))
                    result, _ = reduce(world, table, order=rng.sample(names, len(names)),
                                       concurrency=concurrency, workers=workers, max_in_flight=in_flight,
                                       max_candidates=200, bisection_steps=2)
                    survivors = set(result["surviving_entities"])
                    self.assertEqual(result["stop_reason"], "reduced")
                    self.assertTrue(fails(survivors))
                    for entity in survivors:
                        self.assertFalse(fails(survivors - {entity}), entity)
                    # every survivor belongs to one of the smallest causes only if it is minimal
                    self.assertIn(frozenset(survivors), causes)


class RealStateIntegrationTests(unittest.TestCase):
    """The reducer on real hybrid states, keyed by their hash."""

    def test_candidates_are_cached_and_replayable_by_state_hash(self):
        layout = synthetic_layout()
        reference = base_state(layout)
        failing = with_object_pose(reference, 3, dxyz=(0.04, 0.0, 0.0), z_degrees=60.0)
        failing = with_object_pose(failing, 11, dxyz=(0.0, 0.08, 0.0))
        table = ss.differences(failing, reference, layout)
        self.assertEqual([r["entity"] for r in table], ["soup_1", "bowl_1"])

        def state_for(spec):
            if spec["role"] == "failing":
                return failing
            if spec["role"] == "reference":
                return reference
            return ss.hybrid(reference, failing, spec["selection"], layout)

        def prepare_state(spec):
            state = state_for(spec)
            return ss.state_hash(state), {"spec": spec, "state": state.tolist()}

        def truth(item):
            spec = item["spec"]
            if spec["role"] == "failing":
                return F
            if spec["role"] == "reference":
                return S
            # fails when the soup is turned more than 29 degrees from the reference
            state = np.array(item["state"])
            angle = ss.rotation_angle_deg(state[1 + 3 + 3:1 + 3 + 7], reference[1 + 3 + 3:1 + 3 + 7])
            return F if angle > 29.0 else S

        executor = FakeExecutor(truth, workers=12)
        result = sr.run_scenario_reduction(
            executor, prepare_state, [{"id": 7, "differences": table}], order=["soup_1", "bowl_1"])
        self.assertEqual(result["stop_reason"], "reduced")
        self.assertEqual(list(result["final_selection"]), ["soup_1"])
        self.assertEqual(list(result["final_selection"]["soup_1"]), ["rotation"])
        keys = [c["key"] for c in result["candidates"]]
        self.assertTrue(all(len(k) == 64 for k in keys))
        self.assertEqual(len(keys), len(set(keys)))
        final = result["candidates"][result["final_candidate"]]
        expected = ss.hybrid(reference, failing, result["final_selection"], layout)
        self.assertEqual(final["key"], ss.state_hash(expected))
        # 29 degrees of a 60 degree difference: the bisection brackets t = 0.4833
        (part,) = result["parts"]
        self.assertEqual((part["t"], part["lower"]), (0.5, 0.4375))

    def test_a_selection_equal_to_the_reference_is_the_reference_state(self):
        layout = synthetic_layout()
        reference = base_state(layout)
        failing = with_object_pose(reference, 3, dxyz=(0.04, 0.0, 0.0))
        zero = ss.hybrid(reference, failing, {"soup_1": {"position": 0.0}}, layout)
        self.assertEqual(ss.state_hash(zero), ss.state_hash(reference))


class ValidationTests(unittest.TestCase):
    def test_bad_parameters_and_references_are_rejected(self):
        world = World(lambda sel: True)
        executor = FakeExecutor(world.outcome)
        ok = [{"id": "r0", "differences": standard_table()}]
        bad_kwargs = [
            {"attempts": 0}, {"required_failures": 6}, {"bisection_steps": -1},
            {"max_candidates": 0}, {"concurrency": 0}, {"max_references": 0}, {"attempts": True},
        ]
        for kwargs in bad_kwargs:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                sr.run_scenario_reduction(executor, prepare, ok, **kwargs)
        bad_references = [
            [],
            [{"id": "r0", "differences": []}],
            [{"id": "r0", "differences": [{"entity": "x", "position": None, "rotation": None, "joints": []}]}],
            [{"id": "r0", "differences": standard_table() + standard_table()}],
            [{"id": "r0"}],
            "nope",
        ]
        for references in bad_references:
            with self.subTest(references=str(references)[:60]), self.assertRaises(ValueError):
                sr.run_scenario_reduction(executor, prepare, references)

    def test_ddmin_helper_on_its_own(self):
        needed = {"b", "d"}
        calls = []

        def find_first(sets):
            calls.append([list(s) for s in sets])
            for index, items in enumerate(sets):
                if needed <= set(items):
                    return index
            return None

        self.assertEqual(sr.ddmin(list("abcdefgh"), find_first), ["b", "d"])
        self.assertTrue(all(len(s) >= 1 for call in calls for s in call))     # never the empty set


if __name__ == "__main__":
    unittest.main()
