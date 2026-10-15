"""M7 breadth pack, simulator side: the instruction override in the LIBERO adapter."""

import json
import os
import unittest

import numpy as np

from robot_debug import scenario_import
from tests.scene_fakes import FakeHarnessCase
from tests.test_libero_scene import SceneHarnessCase


class InstructionOverrideTests(FakeHarnessCase):
    RAW = {"frame": np.full((2, 2, 3), 9, dtype=np.uint8)}
    TASK = {"task_id": 0, "task_obj": object(), "name": "pick up the alphabet soup", "episode_idx": 0}

    def test_the_policy_receives_the_override_instead_of_the_task_name(self):
        benchmark = self.benchmark_type(instruction="grab the soup tin and drop it in the basket")
        observation = benchmark.make_obs(self.RAW, self.TASK)
        self.assertEqual("grab the soup tin and drop it in the basket", observation["task_description"])

    def test_only_the_task_description_changes(self):
        plain = self.benchmark_type().make_obs(self.RAW, self.TASK)
        changed = self.benchmark_type(instruction="x").make_obs(self.RAW, self.TASK)
        self.assertEqual(set(plain), set(changed))
        np.testing.assert_array_equal(plain["images"]["agentview"], changed["images"]["agentview"])
        np.testing.assert_array_equal(plain["images"]["wrist"], changed["images"]["wrist"])
        self.assertEqual("pick up the alphabet soup", plain["task_description"])

    def test_without_the_option_the_observation_is_the_upstream_one(self):
        upstream = self.adapter.LIBEROBenchmark.make_obs(self.benchmark_type(), self.RAW, self.TASK)
        ours = self.benchmark_type().make_obs(self.RAW, self.TASK)
        self.assertEqual(upstream.keys(), ours.keys())
        self.assertEqual(upstream["task_description"], ours["task_description"])
        self.assertIsNone(self.benchmark_type().instruction)

    def test_it_composes_with_the_image_perturbations(self):
        benchmark = self.benchmark_type(
            instruction="move the soup", image_perturbation={"kind": "darken", "severity": 1.0})
        observation = benchmark.make_obs(self.RAW, self.TASK)
        self.assertEqual("move the soup", observation["task_description"])
        self.assertLess(int(observation["images"]["agentview"].max()), 9)

    def test_the_option_is_not_forwarded_upstream(self):
        benchmark = self.benchmark_type(suite="libero_goal", instruction="move the soup")
        self.assertEqual({"suite": "libero_goal", "seed": 7, "send_wrist_image": False, "send_state": False},
                         benchmark.upstream_kwargs)

    def test_accepts_one_to_two_hundred_printable_characters(self):
        for text in ("a", "put the black bowl on the plate", "x" * 200, "déplace la boîte", "a b, c. d-e 'f' \"g\""):
            with self.subTest(length=len(text)):
                self.assertEqual(text, self.benchmark_type(instruction=text).instruction)

    def test_the_config_writer_uses_the_same_length_limit(self):
        from robot_debug import m6_experiment

        self.assertEqual(self.adapter.INSTRUCTION_MAX_CHARS, m6_experiment.INSTRUCTION_MAX_CHARS)

    def test_rejects_other_instructions(self):
        for text in ("", "x" * 201, 5, True, ["a"], "line\nbreak", "tab\there", "nul\x00", "bell\x07"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.benchmark_type(instruction=text)


class InstructionSidecarTests(SceneHarnessCase):
    def make_with(self, **options):
        out = self.root / "case.instruction.json"
        benchmark = self.make(instruction_out=str(out), **options)
        return benchmark, out

    def records(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def test_the_sidecar_is_one_object_with_the_instruction_the_policy_receives(self):
        benchmark, out = self.make_with(instruction="grab the tin")
        for episode in range(3):
            benchmark.reset(self.task(episode))
        self.assertEqual(
            {"schema_version": 1, "instruction_used": "grab the tin", "overridden": True,
             "task_language": "pick the soup"}, self.records(out))
        self.assertEqual([], [name for name in os.listdir(self.root) if "partial" in name])

    def test_without_an_override_the_sidecar_records_the_task_language(self):
        benchmark, out = self.make_with()
        benchmark.reset(self.task())
        self.assertEqual(
            {"schema_version": 1, "instruction_used": "pick the soup", "overridden": False,
             "task_language": "pick the soup"}, self.records(out))

    def test_the_recorded_text_is_what_make_obs_sends(self):
        benchmark, out = self.make_with(instruction="grab the tin")
        task = self.task()
        benchmark.reset(task)
        sent = benchmark.make_obs({"frame": np.zeros((2, 2, 3), dtype=np.uint8)}, task)["task_description"]
        self.assertEqual(sent, self.records(out)["instruction_used"])

    def test_no_sidecar_is_written_unless_asked(self):
        benchmark = self.make(instruction="grab the tin")
        benchmark.reset(self.task())
        self.assertEqual([], os.listdir(self.root))

    def test_it_is_recorded_on_every_reset_path(self):
        state = np.linspace(-0.5, 0.5, self.length)
        candidate = self.root / "candidate.json"
        candidate.write_text(json.dumps(scenario_import.candidate_from_benchmark("libero_10", 0, 4, state)),
                             encoding="utf-8")
        out = self.root / "scenario.instruction.json"
        benchmark = self.make(
            instruction="grab the tin", instruction_out=str(out),
            scenario_start={"candidate": str(candidate), "metadata_out": str(self.root / "scenario_start.json")})
        benchmark.reset(self.task())
        self.assertEqual("grab the tin", self.records(out)["instruction_used"])

    def test_rejects_an_empty_or_non_string_path(self):
        for value in ("", 5, ["a"], True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.benchmark_type(instruction_out=value)


if __name__ == "__main__":
    unittest.main()
