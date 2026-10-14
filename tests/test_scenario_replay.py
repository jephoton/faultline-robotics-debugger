"""Tests for the scenario-replay Job mode: configuration, deadline, gates, verdicts and registration."""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from robot_debug import scenario_experiment as se
from robot_debug.job_runtime import JobRuntimeError, validate_workload_config
from tests.scenario_world import FakeSimulation, ScenarioWorld
from tests.test_scenario_experiment import RunTestCase

ROOT = Path(__file__).resolve().parents[1]
SIM = FakeSimulation()
LAYOUT = SIM.layout(0)
MINIMAL = SIM.state_for(9)       # the policy fails here (soup x = 0.9)
REFERENCE = SIM.state_for(4)     # the policy passes here (soup x = 0.4)


def replay_config(**changes):
    config = {
        "schema_version": 1, "mode": "scenario-replay", "run_id": "scn-replay-1", "deadline_seconds": 1200,
        "suite": "libero_10", "task_id": 0, "layout": copy.deepcopy(LAYOUT),
        "scenes": [{"name": "minimal", "state": list(MINIMAL), "role": "minimal"},
                   {"name": "reference", "state": list(REFERENCE), "role": "reference"}],
    }
    config.update(changes)
    return config


class ReplayConfigTests(unittest.TestCase):
    def test_the_mode_is_registered(self):
        self.assertIn("scenario-replay", se.SCENARIO_MODES)

    def test_defaults_and_round_trip(self):
        config = validate_workload_config(replay_config())
        self.assertEqual((5, 4), (config["attempts"], config["required_failures"]))
        self.assertEqual(["minimal", "reference"], [scene["name"] for scene in config["scenes"]])
        self.assertEqual(json.loads(json.dumps(config)), config)
        explicit = validate_workload_config(replay_config(attempts=3, required_failures=2))
        self.assertEqual((3, 2), (explicit["attempts"], explicit["required_failures"]))

    def test_suite_defaults_to_libero_10(self):
        config = replay_config()
        del config["suite"]
        self.assertEqual("libero_10", validate_workload_config(config)["suite"])

    def test_bad_fields_are_rejected(self):
        scenes = replay_config()["scenes"]

        def with_scene(index, **changes):
            copied = copy.deepcopy(scenes)
            copied[index].update(changes)
            return copied

        bad = (
            {"scenes": []}, {"scenes": "x"}, {"scenes": scenes * 3},
            {"scenes": [scenes[1]]},                                    # no minimal scene
            {"scenes": [dict(scenes[0], name="a"), dict(scenes[1], name="a")]},       # duplicate name
            {"scenes": with_scene(0, name="Bad Name")}, {"scenes": with_scene(0, name="")},
            {"scenes": with_scene(0, name="../x")}, {"scenes": with_scene(0, role="other")},
            {"scenes": with_scene(0, state=[1.0, 2.0])}, {"scenes": with_scene(0, state="x")},
            {"scenes": with_scene(0, source={"kind": "mystery"})},
            {"scenes": [dict(scenes[0], extra=1), scenes[1]]},
            {"attempts": 0}, {"attempts": 9}, {"attempts": True}, {"required_failures": 6},
            {"required_failures": 0}, {"task_id": 10}, {"task_id": -1}, {"suite": "libero_goal"},
            {"layout": {}}, {"surprise": 1},
        )
        for changes in bad:
            with self.subTest(changes=str(changes)[:80]), self.assertRaises(JobRuntimeError):
                validate_workload_config(replay_config(**changes))

    def test_a_layout_of_another_task_is_rejected(self):
        with self.assertRaises(JobRuntimeError):
            validate_workload_config(replay_config(task_id=1))

    def test_missing_required_fields_are_rejected(self):
        for key in ("layout", "scenes", "task_id"):
            config = replay_config()
            del config[key]
            with self.subTest(missing=key), self.assertRaises(JobRuntimeError):
                validate_workload_config(config)

    def test_a_reference_is_optional(self):
        config = replay_config(scenes=[replay_config()["scenes"][0]])
        self.assertEqual(1, len(validate_workload_config(config)["scenes"]))

    def test_an_optional_source_is_validated_and_kept(self):
        scenes = replay_config()["scenes"]
        scenes[0]["source"] = {"kind": "benchmark", "init_state_index": 9}
        self.assertEqual({"kind": "benchmark", "init_state_index": 9},
                         validate_workload_config(replay_config(scenes=scenes))["scenes"][0]["source"])

    def test_the_deadline_is_capped_by_the_runtime(self):
        with self.assertRaises(JobRuntimeError):
            validate_workload_config(replay_config(deadline_seconds=3001))


class ReplayDeadlineTests(unittest.TestCase):
    def test_recommended_deadline_respects_the_floor_and_the_cap(self):
        deadline = se.recommended_deadline_seconds("scenario-replay", {})
        self.assertGreaterEqual(deadline, se.MIN_DEADLINE_SECONDS)
        self.assertLessEqual(deadline, se.MAX_DEADLINE_SECONDS)
        validate_workload_config(replay_config(deadline_seconds=deadline))

    def test_more_scenes_or_attempts_never_shorten_it(self):
        base = se.recommended_deadline_seconds("scenario-replay", {"attempts": 5, "scenes": [1, 2]})
        self.assertGreaterEqual(se.recommended_deadline_seconds(
            "scenario-replay", {"attempts": 8, "scenes": [1, 2, 3, 4]}), base)

    def test_planned_episodes(self):
        self.assertEqual(10, se.planned_episodes("scenario-replay", {"scenes": [1, 2], "attempts": 5}))
        self.assertEqual(10, se.planned_episodes("scenario-replay", {}))


class ReplayRunTests(RunTestCase):
    def run_replay(self, world=None, **changes):
        world = world or ScenarioWorld(item_seconds=0.0)
        return world, self.run_mode(world, "scenario-replay", replay_config(**changes))

    @staticmethod
    def scene(summary, name):
        return next(item for item in summary["scenes"] if item["name"] == name)

    def test_a_failure_that_still_reproduces(self):
        world, summary = self.run_replay()
        self.assertIsNone(summary["stop_reason"])
        self.assertTrue(summary["complete"])
        self.assertEqual("still_reproduces", summary["verdict"])
        minimal, reference = self.scene(summary, "minimal"), self.scene(summary, "reference")
        self.assertEqual(("reproduces", "passes"), (minimal["decision"], reference["decision"]))
        self.assertEqual(["policy_failure"] * 4, minimal["outcomes"])      # the fifth attempt is skipped
        self.assertEqual(["success"] * 5, reference["outcomes"])
        self.assertEqual(("minimal", "reference"), (minimal["role"], reference["role"]))
        self.assertEqual("policy_failure", minimal["expected"])
        self.assertEqual("success", reference["expected"])
        self.assertEqual(1, minimal["skipped_attempts"])
        self.assertEqual(4, len(minimal["attempts"]))
        self.assertEqual(["rp-minimal-a01", "rp-minimal-a02", "rp-minimal-a03", "rp-minimal-a04"],
                         [a["case_id"] for a in minimal["attempts"]])
        self.assertTrue(all(a["video"] for a in reference["attempts"]))
        self.assertEqual(self.saved(), json.loads(json.dumps(summary, sort_keys=True)))
        self.assertEqual("libero_10", summary["suite"])

    def test_scenes_run_through_scenario_start_not_benchmark_starts(self):
        world, _summary = self.run_replay()
        replayed = [params for case, params in world.by_case.items() if not case.startswith("warmup")]
        self.assertEqual(9, len(replayed))
        self.assertTrue(all("scenario_start" in params and "init_state_index" not in params
                            for params in replayed))
        files = sorted((self.root / "scenario" / "candidates").glob("*.json"))
        self.assertEqual(2, len(files))

    def test_a_fix_means_no_longer_reproduces(self):
        _world, summary = self.run_replay(scenes=[
            {"name": "minimal", "state": list(REFERENCE), "role": "minimal"},
            {"name": "reference", "state": list(REFERENCE), "role": "reference"}])
        self.assertEqual("no_longer_reproduces", summary["verdict"])
        self.assertEqual("does_not_reproduce", self.scene(summary, "minimal")["decision"])
        self.assertTrue(summary["complete"], "the run finished; the failure is simply gone")

    def test_a_failing_reference_voids_the_comparison(self):
        _world, summary = self.run_replay(scenes=[
            {"name": "minimal", "state": list(MINIMAL), "role": "minimal"},
            {"name": "reference", "state": list(MINIMAL), "role": "reference"}])
        self.assertEqual("reference_fails", summary["verdict"])
        self.assertEqual("fails", self.scene(summary, "reference")["decision"])

    def test_a_flaky_policy_below_the_gate_does_not_reproduce(self):
        def flaky(state, params, count):
            if state[4] >= 0.45:
                return "policy_failure" if count <= 3 else "success"
            return None

        world = ScenarioWorld(FakeSimulation(flaky=flaky), item_seconds=0.0)
        _world, summary = self.run_replay(world)
        self.assertEqual("no_longer_reproduces", summary["verdict"])
        self.assertEqual("does_not_reproduce", self.scene(summary, "minimal")["decision"])

    def test_an_overlapping_scene_is_an_invalid_scene_not_a_failure(self):
        bad = list(REFERENCE)
        bad[1 + 10:1 + 13] = bad[1 + 3:1 + 6]       # the basket onto the soup
        _world, summary = self.run_replay(scenes=[
            {"name": "minimal", "state": bad, "role": "minimal"},
            {"name": "reference", "state": list(REFERENCE), "role": "reference"}])
        self.assertEqual("invalid_scene", summary["verdict"])
        self.assertEqual("invalid_scene", self.scene(summary, "minimal")["decision"])
        self.assertNotIn("policy_failure", self.scene(summary, "minimal")["outcomes"])

    def test_the_summary_records_timings_checkpoint_gate_and_instruction(self):
        (self.root / "model-resolution.json").write_text(json.dumps({"schema_version": 1, "repositories": {
            "nvidia/gr00t17-lerobot-libero_10-640": {"revision": "5ee08ab" + "0" * 33, "pinned": True}}}),
            encoding="utf-8")
        _world, summary = self.run_replay()
        self.assertEqual("5ee08ab" + "0" * 33, summary["checkpoint"]["revision"])
        self.assertEqual({"attempts": 5, "required_failures": 4}, summary["gate"])
        self.assertEqual(0, summary["task_id"])
        self.assertEqual("put the alphabet soup in the basket", summary["instruction"])
        self.assertIsNotNone(summary["total_seconds"])
        self.assertIsNotNone(summary["startup_seconds"])
        for scene in summary["scenes"]:
            for attempt in scene["attempts"]:
                self.assertIsInstance(attempt["seconds"], float)
        self.assertNotIn("scenes", summary["config"], "states stay out of the config echo")
        self.assertNotIn("layout", summary["config"])

    def test_fewer_attempts_and_a_lower_gate(self):
        _world, summary = self.run_replay(attempts=3, required_failures=2)
        self.assertEqual(["policy_failure"] * 2, self.scene(summary, "minimal")["outcomes"])
        self.assertEqual(["success"] * 3, self.scene(summary, "reference")["outcomes"])
        self.assertEqual("still_reproduces", summary["verdict"])

    def test_an_infrastructure_failure_leaves_no_verdict(self):
        world = ScenarioWorld(item_seconds=0.0, fail_case="rp-reference-a02")
        _world, summary = self.run_replay(world)
        self.assertEqual("evaluator_failed", summary["stop_reason"])
        self.assertFalse(summary["complete"])
        self.assertIsNone(summary["verdict"])
        self.assertEqual(self.saved(), json.loads(json.dumps(summary, sort_keys=True)))

    def test_a_deadline_stop_leaves_no_verdict(self):
        self.remaining_value[0] = 100.0
        world = ScenarioWorld(item_seconds=0.0)
        _world, summary = self.run_replay(world)
        self.assertIsNone(summary["verdict"])
        self.assertFalse(summary["complete"])
        self.assertIsNotNone(summary["stop_reason"])


class ReplayWorkloadRunTests(unittest.TestCase):
    def test_the_deadline_guard_covers_the_replay_mode(self):
        spec = importlib.util.spec_from_file_location(
            "prepare_serverless_job_replay", ROOT / "scripts" / "prepare_serverless_job.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self.assertIn("scenario-replay", module._BATCH_MODES)
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            os.chdir(temporary)
            try:
                for deadline, ok in ((999, False), (1000, True)):
                    Path("workload.json").write_text(
                        json.dumps(replay_config(deadline_seconds=deadline)), encoding="utf-8")
                    config = {
                        "run_id": "scn-replay-1", "project_id": "project-example123",
                        "image": "registry.example/robot-debug@sha256:" + "a" * 64,
                        "platform": "gpu-l40s-a", "preset": "1gpu-16vcpu-64gb",
                        "subnet_id": "vpcsubnet-example123", "bucket_id": "storagebucket-example123",
                        "hf_secret": "mbsec-example123@mbsecver-version123", "workload_file": "workload.json"}
                    if ok:
                        self.assertIn("--dry-run", module.prepare(config))
                    else:
                        with self.assertRaisesRegex(module.ConfigError, "deadline"):
                            module.prepare(config)
            finally:
                os.chdir(previous)


class PythonCompatibilityTests(unittest.TestCase):
    def test_modules_parse_as_python_38(self):
        for name in ("scenario_experiment", "job_runtime", "job_workload"):
            path = ROOT / "src" / "robot_debug" / (name + ".py")
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 8))


if __name__ == "__main__":
    unittest.main()
