"""Tests for the pure workload builders behind faultline diagnose and faultline replay."""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
import unittest
from unittest import mock

from robot_debug import scenario_experiment as se
from robot_debug import job_runtime
from robot_debug.job_runtime import validate_workload_config
from robot_debug.scenario_import import build_candidate, candidate_from_benchmark
from robot_debug.workloads import WorkloadError, audit_workload, reference_inputs, replay_workload
from tests.scenario_world import FakeSimulation
from tests.test_scenario_experiment import make_plan

SIM = FakeSimulation()


def spec(**audit):
    return {"faultline": 1, "name": "x", "mode": "audit", "policy": {"suite": "libero_object"},
            "audit": dict({"task": 0, "start": 0, "families": ["blur", "noise"]}, **audit)}


class AuditWorkloadTests(unittest.TestCase):
    def test_a_spec_becomes_a_valid_threshold_workload(self):
        workload = audit_workload(spec(), "diag-audit-1")
        self.assertEqual(workload, validate_workload_config(workload))
        self.assertEqual(("m6-threshold", "diag-audit-1"), (workload["mode"], workload["run_id"]))
        self.assertEqual(["noise", "blur"], workload["families"], "families keep the canonical order")
        self.assertEqual(("libero_object", 0, 0), (
            workload["suite"], workload["task_id"], workload["init_state_index"]))
        self.assertEqual(([0.2, 0.4, 0.6, 0.8, 1.0], 5, 4, 4), (
            workload["sweep"], workload["attempts"], workload["required_failures"], workload["bisection_steps"]))
        self.assertGreaterEqual(workload["deadline_seconds"], 1000)

    def test_the_deadline_is_the_recommended_one(self):
        from robot_debug import m6_experiment

        workload = audit_workload(spec(), "a")
        config = {key: workload[key] for key in ("families", "sweep", "attempts", "required_failures",
                                                 "bisection_steps", "suite")}
        self.assertEqual(m6_experiment.recommended_deadline_seconds("m6-threshold", config),
                         workload["deadline_seconds"])

    def test_defaults_are_all_four_families_on_libero_object(self):
        workload = audit_workload({"audit": {}}, "a")
        self.assertEqual(["darken", "noise", "blur", "contrast"], workload["families"])
        self.assertEqual(("libero_object", 0), (workload["suite"], workload["task_id"]))
        self.assertNotIn("init_state_index", workload)

    def test_libero_10_uses_the_suite_and_its_longer_deadline(self):
        base = spec(families=["darken"])
        long_ = dict(base, policy={"suite": "libero_10"})
        self.assertEqual("libero_10", audit_workload(long_, "a")["suite"])
        self.assertGreater(audit_workload(long_, "a")["deadline_seconds"],
                           audit_workload(base, "a")["deadline_seconds"])

    def test_every_suite_of_the_breadth_pack_is_accepted_and_carried(self):
        # The Job-side validator (job_runtime, owned by the language unit) lists the suites; accept all four here.
        suites = ("libero_object", "libero_10", "libero_spatial", "libero_goal")
        with mock.patch.object(job_runtime, "M6_SUITES", suites):
            for suite in suites:
                with self.subTest(suite=suite):
                    workload = audit_workload(dict(spec(families=["darken"]), policy={"suite": suite}), "a")
                    self.assertEqual(suite, workload["suite"])
                    self.assertEqual(workload, validate_workload_config(workload))

    def test_spatial_and_goal_deadlines_follow_the_step_limits(self):
        suites = ("libero_object", "libero_10", "libero_spatial", "libero_goal")
        with mock.patch.object(job_runtime, "M6_SUITES", suites):
            deadline = {suite: audit_workload(dict(spec(families=["darken"]), policy={"suite": suite}),
                                              "a")["deadline_seconds"] for suite in suites}
        self.assertEqual(deadline["libero_object"], deadline["libero_spatial"])
        self.assertGreaterEqual(deadline["libero_goal"], deadline["libero_object"])
        self.assertGreater(deadline["libero_10"], deadline["libero_goal"])

    def test_a_search_too_big_for_libero_10_is_refused_with_advice(self):
        big = dict(spec(families=["darken", "noise", "blur", "contrast"]), policy={"suite": "libero_10"})
        with self.assertRaisesRegex(WorkloadError, "shrink"):
            audit_workload(big, "a")
        narrowed = dict(big, audit=dict(big["audit"], attempts=3, required_failures=2, bisection_steps=2,
                                        sweep=[0.5, 1.0]))
        self.assertLessEqual(audit_workload(narrowed, "a")["deadline_seconds"], 3000)

    def test_bad_specs_are_refused(self):
        bad = (
            {"audit": {"families": []}}, {"audit": {"families": ["sepia"]}},
            {"audit": {"families": ["blur", "blur"]}}, {"audit": {"families": "blur"}},
            {"audit": {"task": 10}}, {"audit": {"task": -1}}, {"audit": {"start": 50}},
            {"audit": {"sweep": [0.5, 0.2]}}, {"audit": {"attempts": 0}},
            {"audit": {"attempts": 3, "required_failures": 4}},
            {"audit": {}, "policy": {"suite": "libero_90"}}, {}, {"audit": "x"},
        )
        for item in bad:
            with self.subTest(spec=item), self.assertRaises(WorkloadError):
                audit_workload(item, "a")

    def test_a_bad_run_id_is_refused(self):
        with self.assertRaises(WorkloadError):
            audit_workload(spec(), "Bad Id")

    def test_a_lower_attempt_count_lowers_the_default_gate(self):
        workload = audit_workload(spec(attempts=3), "a")
        self.assertEqual((3, 3), (workload["attempts"], workload["required_failures"]))

    def test_the_spec_is_not_modified(self):
        original = spec()
        before = copy.deepcopy(original)
        audit_workload(original, "a")
        self.assertEqual(before, original)

    def test_the_breadth_pack_families_are_accepted_in_canonical_order(self):
        from robot_debug import m6_experiment

        with mock.patch.object(job_runtime, "M6_FAMILIES", m6_experiment.FAMILIES):
            workload = audit_workload(
                spec(families=["lighting", "jpeg", "viewpoint", "dead_pixels", "colour_cast", "motion_blur"],
                     attempts=3, required_failures=2, bisection_steps=2, sweep=[0.5, 1.0]), "a")
        self.assertEqual(["jpeg", "colour_cast", "motion_blur", "dead_pixels", "viewpoint", "lighting"],
                         workload["families"])
        with mock.patch.object(job_runtime, "M6_FAMILIES", m6_experiment.FAMILIES):
            self.assertEqual(workload, validate_workload_config(workload))

    def test_each_new_family_alone_gives_a_valid_workload_with_a_sensible_deadline(self):
        from robot_debug import m6_experiment

        legacy = audit_workload(spec(families=["blur"]), "a")["deadline_seconds"]
        with mock.patch.object(job_runtime, "M6_FAMILIES", m6_experiment.FAMILIES):
            for family in ("jpeg", "colour_cast", "motion_blur", "dead_pixels", "viewpoint", "lighting"):
                with self.subTest(family=family):
                    workload = audit_workload(spec(families=[family]), "a")
                    self.assertEqual([family], workload["families"])
                    self.assertGreaterEqual(workload["deadline_seconds"], legacy)
                    self.assertLessEqual(workload["deadline_seconds"], 2400)

    def test_all_ten_families_exceed_the_episode_bound_unless_the_search_is_narrowed(self):
        from robot_debug import m6_experiment

        everything = spec(families=list(m6_experiment.FAMILIES))
        with mock.patch.object(job_runtime, "M6_FAMILIES", m6_experiment.FAMILIES):
            with self.assertRaises(WorkloadError):
                audit_workload(everything, "a")
            narrowed = spec(families=list(m6_experiment.FAMILIES), attempts=3, required_failures=2,
                            bisection_steps=2, sweep=[0.5, 1.0])
            self.assertEqual(10, len(audit_workload(narrowed, "a")["families"]))

    def test_unknown_names_and_scene_names_in_the_wrong_place_are_refused(self):
        from robot_debug import m6_experiment

        with mock.patch.object(job_runtime, "M6_FAMILIES", m6_experiment.FAMILIES):
            for families in (["sepia"], ["viewpoint", "viewpoint"], ["Jpeg"], ["jpeg", None]):
                with self.subTest(families=families), self.assertRaises(WorkloadError):
                    audit_workload(spec(families=families), "a")

    def test_the_default_stays_the_four_recorded_families_even_when_the_runtime_knows_more(self):
        from robot_debug import m6_experiment

        with mock.patch.object(job_runtime, "M6_FAMILIES", m6_experiment.FAMILIES):
            workload = audit_workload({"audit": {}}, "a")
        self.assertEqual(["darken", "noise", "blur", "contrast"], workload["families"])

    def test_a_spec_for_a_breadth_suite_and_family_carries_both(self):
        from robot_debug import m6_experiment

        goal = dict(spec(families=["viewpoint"]), policy={"suite": "libero_goal"})
        with mock.patch.object(job_runtime, "M6_FAMILIES", m6_experiment.FAMILIES), \
                mock.patch.object(job_runtime, "M6_SUITES", m6_experiment.SUITES):
            workload = audit_workload(goal, "a")
        self.assertEqual(("libero_goal", ["viewpoint"]), (workload["suite"], workload["families"]))


def reduce_workload():
    return se.build_reduce_workload(make_plan(), run_id="scn-reduce-1")


def case_record(reference_start=4):
    state = SIM.state_for(9)
    candidate = build_candidate("libero_10", 0, state, {
        "kind": "hybrid", "reference": reference_start, "failing": 9,
        "applied": [{"entity": "alphabet_soup_1", "component": "position", "t": 0.125}]})
    return {"schema_version": 1, "kind": "scenario_reduction", "case_id": "c" * 64, "suite": "libero_10",
            "task_id": 0, "instruction": "put the alphabet soup in the basket", "failing_start": 9,
            "reference_start": reference_start,
            "replay": {"candidate": candidate, "gate": {"attempts": 5, "required_failures": 4}}}


class ReplayWorkloadTests(unittest.TestCase):
    def inputs(self, case=None):
        return reference_inputs(reduce_workload(), case or case_record())

    def test_a_case_becomes_a_valid_replay_workload(self):
        case = case_record()
        workload = replay_workload(case, "diag-replay-1", **self.inputs(case))
        self.assertEqual(workload, validate_workload_config(workload))
        self.assertEqual(("scenario-replay", "libero_10", 0, 5, 4), (
            workload["mode"], workload["suite"], workload["task_id"], workload["attempts"],
            workload["required_failures"]))
        minimal, reference = workload["scenes"]
        self.assertEqual(("minimal", "minimal", "reference", "reference"), (
            minimal["name"], minimal["role"], reference["name"], reference["role"]))
        self.assertEqual(case["replay"]["candidate"]["state"], minimal["state"])
        self.assertEqual(SIM.state_for(4), reference["state"])
        self.assertEqual(case["replay"]["candidate"]["source"], minimal["source"])
        self.assertEqual({"kind": "benchmark", "init_state_index": 4}, reference["source"])
        self.assertEqual(se.recommended_deadline_seconds("scenario-replay", {"scenes": [1, 2], "attempts": 5}),
                         workload["deadline_seconds"])
        self.assertLessEqual(len(json.dumps(workload)), 64 * 1024)

    def test_attempts_and_gate_can_be_set(self):
        case = case_record()
        workload = replay_workload(case, "a", 3, **self.inputs(case))
        self.assertEqual((3, 3), (workload["attempts"], workload["required_failures"]),
                         "the case's gate of 4 is capped at the attempt count")
        workload = replay_workload(case, "a", 5, required_failures=2, **self.inputs(case))
        self.assertEqual(2, workload["required_failures"])

    def test_without_a_reference_only_the_minimal_scene_runs(self):
        case = case_record()
        workload = replay_workload(case, "a", layout=self.inputs(case)["layout"])
        self.assertEqual(["minimal"], [scene["name"] for scene in workload["scenes"]])

    def test_reference_inputs_read_the_reduce_workload(self):
        case = case_record(reference_start=4)
        inputs = self.inputs(case)
        self.assertEqual(reduce_workload()["layout"], inputs["layout"])
        self.assertEqual(candidate_from_benchmark("libero_10", 0, 4, SIM.state_for(4)),
                         inputs["reference_candidate"])
        self.assertIsNone(reference_inputs(reduce_workload(), dict(case, reference_start=None))[
            "reference_candidate"])
        with self.assertRaises(WorkloadError):
            reference_inputs(reduce_workload(), dict(case, reference_start=7))
        with self.assertRaises(WorkloadError):
            reference_inputs({}, case)

    def test_a_case_without_a_replay_candidate_is_refused(self):
        case = case_record()
        inputs = self.inputs(case)
        for broken in ({"replay": None}, {"replay": {"candidate": None}},
                       {"replay": {"candidate": {"state": [1.0]}}}):
            with self.subTest(broken=broken), self.assertRaises(WorkloadError):
                replay_workload(dict(case, **broken), "a", **inputs)

    def test_scenes_from_another_suite_or_task_are_refused(self):
        case = case_record()
        inputs = self.inputs(case)
        with self.assertRaises(WorkloadError):
            replay_workload(dict(case, task_id=1), "a", **inputs)
        other = build_candidate("libero_object", 0, SIM.state_for(4), {"kind": "benchmark", "init_state_index": 4})
        with self.assertRaises(WorkloadError):
            replay_workload(case, "a", layout=inputs["layout"], reference_candidate=other)

    def test_a_layout_that_does_not_fit_is_refused(self):
        case = case_record()
        with self.assertRaises(WorkloadError):
            replay_workload(case, "a", layout={"nonsense": True})

    def test_attempts_are_validated_like_the_job_does(self):
        case = case_record()
        for attempts in (0, 9, True):
            with self.subTest(attempts=attempts), self.assertRaises(WorkloadError):
                replay_workload(case, "a", attempts, **self.inputs(case))

    def test_the_inputs_are_not_modified(self):
        case = case_record()
        inputs = self.inputs(case)
        before = copy.deepcopy((case, inputs))
        replay_workload(case, "a", **inputs)
        self.assertEqual(before, (case, inputs))


class PythonCompatibilityTests(unittest.TestCase):
    def test_workloads_module_parses_as_python_38(self):
        path = Path(__file__).parents[1] / "src" / "robot_debug" / "workloads.py"
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 8))


if __name__ == "__main__":
    unittest.main()
