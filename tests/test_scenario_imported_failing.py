"""A reduction whose failing start was imported (``failing.start_index`` null) instead of screened."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest

from robot_debug import scenario_experiment as se
from robot_debug.job_runtime import JobRuntimeError, validate_workload_config
from robot_debug.scenario_import import candidate_from_benchmark, load_scenario_candidate
from scripts import plan_scenario_reduction as planner
from tests.scenario_world import FakeSimulation, ScenarioWorld
from tests.test_scenario_experiment import RunTestCase, make_plan

FILE_SHA = hashlib.sha256(b"an imported file").hexdigest()


def screen_summary():
    sim = FakeSimulation()
    return {"suite": "libero_10",
            "tasks": {"0": {"instruction": "put the soup in the basket", "layout": sim.layout(0),
                            "starts": {str(i): {"outcomes": ["success"], "state": sim.state_for(i)}
                                       for i in range(5)}}}}


def imported_candidate(index=9):
    return candidate_from_benchmark("libero_10", 0, index, FakeSimulation().state_for(index))


def imported_plan(candidate=None, **kwargs):
    candidate = candidate or imported_candidate()
    imported = {"state": candidate["state"], "source": candidate["source"], "file_sha256": FILE_SHA,
                "state_sha256": candidate["state_sha256"]}
    config, _raw = planner.build_plan_with_reply(
        screen_summary(), 0, None, use_llm=False, imported=imported, **kwargs)
    return config


class Planner(unittest.TestCase):
    def test_the_plan_carries_the_imported_start_and_picks_the_nearest_passing_reference(self):
        plan = imported_plan()
        failing = plan["failing"]
        self.assertIsNone(failing["start_index"])
        self.assertEqual([], failing["outcomes"])
        self.assertEqual(imported_candidate()["state"], failing["state"])
        self.assertEqual({"kind": "benchmark", "init_state_index": 9}, failing["source"])
        self.assertEqual({"file_sha256": FILE_SHA, "state_sha256": imported_candidate()["state_sha256"]},
                         failing["import"])
        self.assertEqual(4, plan["references"][0]["start_index"], "start 4 is the nearest passing start")
        self.assertEqual(make_plan()["order"], plan["order"], "the same fixed order as for the benchmark start")

    def test_the_plan_becomes_a_valid_workload(self):
        workload = se.build_reduce_workload(imported_plan(), run_id="scn-reduce-1")
        config = validate_workload_config(workload)
        self.assertIsNone(config["failing"]["start_index"])
        self.assertEqual(workload["failing"]["import"], config["failing"]["import"])
        self.assertLessEqual(len(json.dumps(workload)), 64 * 1024)

    def test_a_state_of_the_wrong_scene_is_a_plan_error(self):
        candidate = imported_candidate()
        bad = dict(candidate, state=candidate["state"][:-3])
        with self.assertRaises(planner.PlanError) as caught:
            planner.build_plan_with_reply(screen_summary(), 0, None, use_llm=False, imported={
                "state": bad["state"], "source": bad["source"], "file_sha256": FILE_SHA,
                "state_sha256": candidate["state_sha256"]})
        self.assertIn("imported start", str(caught.exception))

    def test_an_imported_start_has_no_index_and_a_benchmark_start_still_needs_one(self):
        candidate = imported_candidate()
        with self.assertRaises(planner.PlanError):
            planner.build_plan_with_reply(screen_summary(), 0, 9, use_llm=False, imported={
                "state": candidate["state"], "source": candidate["source"], "file_sha256": FILE_SHA,
                "state_sha256": candidate["state_sha256"]})
        with self.assertRaises(planner.PlanError):
            planner.build_plan_with_reply(screen_summary(), 0, 9, use_llm=False)      # 9 was not screened

    def test_a_pool_with_no_passing_start_has_no_reference(self):
        summary = screen_summary()
        for record in summary["tasks"]["0"]["starts"].values():
            record["outcomes"] = ["policy_failure"] * 5
        candidate = imported_candidate()
        with self.assertRaises(planner.PlanError):
            planner.build_plan_with_reply(summary, 0, None, use_llm=False, imported={
                "state": candidate["state"], "source": candidate["source"], "file_sha256": FILE_SHA,
                "state_sha256": candidate["state_sha256"]})


class FailingBlockValidation(unittest.TestCase):
    def workload(self, mutate):
        workload = se.build_reduce_workload(imported_plan(), run_id="scn-reduce-1")
        mutate(workload["failing"])
        return workload

    def test_the_rules_for_an_imported_start(self):
        digest = "ab" * 32
        cases = {
            "missing source": lambda f: f.pop("source"),
            "missing import": lambda f: f.pop("import"),
            "index with source": lambda f: f.update(start_index=3),
            "short digest": lambda f: f["import"].update(file_sha256="abc"),
            "uppercase digest": lambda f: f["import"].update(state_sha256=digest.upper()),
            "extra import key": lambda f: f["import"].update(path="x.json"),
            "bad source": lambda f: f.update(source={"kind": "hybrid"}),
        }
        for name, mutate in cases.items():
            with self.subTest(name), self.assertRaises(JobRuntimeError):
                validate_workload_config(self.workload(mutate))

    def test_a_benchmark_start_must_not_carry_source_or_import(self):
        plan = copy.deepcopy(imported_plan())
        plan["failing"]["start_index"] = 9
        with self.assertRaises(JobRuntimeError):
            validate_workload_config(se.build_reduce_workload(plan, run_id="scn-reduce-1"))

    def test_a_reference_may_have_any_index_when_the_start_is_imported(self):
        validate_workload_config(se.build_reduce_workload(imported_plan(), run_id="scn-reduce-1"))


class ImportedRun(RunTestCase):
    def run_imported(self):
        workload = se.build_reduce_workload(imported_plan(), run_id="scn-reduce-1")
        return self.run_mode(ScenarioWorld(item_seconds=0.0), "scenario-reduce", workload)

    def test_the_reduction_finds_the_same_cause_as_for_a_benchmark_start(self):
        summary = self.run_imported()
        reduction = summary["reduction"]
        self.assertEqual("reduced", reduction["stop_reason"])
        self.assertEqual({"alphabet_soup_1": {"position": 0.125}}, reduction["final_selection"])
        self.assertEqual(4, reduction["reference"])

    def test_the_plan_in_the_summary_names_the_import_instead_of_an_index(self):
        plan = self.run_imported()["plan"]
        self.assertIsNone(plan["failing_start"])
        self.assertEqual(FILE_SHA, plan["failing_import"]["file_sha256"])
        self.assertEqual({"kind": "benchmark", "init_state_index": 9}, plan["failing_source"])

    def test_candidate_files_keep_the_imported_provenance(self):
        summary = self.run_imported()
        files = sorted((self.root / "scenario" / "candidates").glob("*.json"))
        by_role = {path.name.split("-")[0]: load_scenario_candidate(path) for path in files}
        self.assertEqual({"kind": "benchmark", "init_state_index": 9}, by_role["failing"]["source"])
        hybrid = summary["minimal_candidate"]["source"]
        self.assertEqual(("hybrid", 4, None), (hybrid["kind"], hybrid["reference"], hybrid["failing"]))

    def test_the_case_records_the_import_and_has_no_failing_start_index(self):
        case = se.build_case(self.run_imported())
        self.assertIsNone(case["failing_start"])
        self.assertEqual(FILE_SHA, case["failing_import"]["file_sha256"])
        self.assertEqual(imported_candidate()["state_sha256"], case["failing_import"]["state_sha256"])
        self.assertEqual("hybrid", case["replay"]["candidate"]["source"]["kind"])

    def test_the_case_id_depends_on_the_imported_state_and_differs_from_the_benchmark_case(self):
        imported = se.build_case(self.run_imported())
        other = imported_candidate(8)
        plan = imported_plan(other)
        summary = self.run_mode(ScenarioWorld(item_seconds=0.0), "scenario-reduce",
                                se.build_reduce_workload(plan, run_id="scn-reduce-2"), batch_root=self.root / "other")
        self.assertNotEqual(imported["case_id"], se.build_case(summary)["case_id"])
        benchmark = se.build_case(self.run_mode(
            ScenarioWorld(item_seconds=0.0), "scenario-reduce",
            se.build_reduce_workload(make_plan(), run_id="scn-reduce-3"), batch_root=self.root / "third"))
        self.assertNotIn("failing_import", benchmark)
        self.assertNotEqual(imported["case_id"], benchmark["case_id"])

    def test_a_replay_workload_can_be_built_from_the_case(self):
        from robot_debug.workloads import replay_workload

        case = se.build_case(self.run_imported())
        workload = replay_workload(case, "diag-replay-1", layout=FakeSimulation().layout(0))
        self.assertEqual("scenario-replay", workload["mode"])


class ExplanationPacket(unittest.TestCase):
    def test_the_evidence_packet_accepts_a_case_without_a_failing_start_index(self):
        from robot_debug import scenario_packet as sp
        from tests import reduction_fixtures as rf
        from tests.test_scenario_packet import DIFFERENCES

        plan = dict(rf.partial_plan(), failing_start=None, failing_source={"kind": "benchmark", "init_state_index": 9},
                    failing_import={"file_sha256": FILE_SHA, "state_sha256": "c" * 64})
        summary = {"mode": "scenario-reduce", "plan": plan, "reduction": rf.partial_reduction(),
                   "differences": DIFFERENCES, "videos": {}, "minimal_candidate": None}
        case = se.build_case(summary)
        self.assertIsNone(case["failing_start"])
        packet = sp.make_scenario_packet(case)
        self.assertIsNone(packet["task"]["failing_start"])
        self.assertEqual(packet, sp.validate_scenario_packet(packet))


if __name__ == "__main__":
    unittest.main()
