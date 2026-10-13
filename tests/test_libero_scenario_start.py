"""M7: choosing the benchmark start (A) and starting from validated scenario states (B)."""

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

import numpy as np

from robot_debug import external_reset, scenario_import, scene_inspect
from tests.scene_fakes import GEOM, FakeContact, FakeEnv, FakeHarnessCase, FakeTaskSuite


def _states(model_length, count=6):
    """``count`` distinct start states of the fake scene (row i is filled with i)."""
    return [np.full(model_length, float(index)) for index in range(count)]


class InitStateIndexTests(FakeHarnessCase):
    def make(self, **options):
        benchmark = self.benchmark_type(suite="libero_10", **options)
        env = FakeEnv()
        benchmark._make_env = lambda task: env
        benchmark._task_suite = FakeTaskSuite({0: _states(env.model.state_length)})
        return benchmark, env

    def task(self, episode_idx=0):
        return {"task_id": 0, "task_obj": object(), "name": "task 0", "episode_idx": episode_idx}

    def test_every_episode_starts_from_the_configured_init_state(self):
        benchmark, env = self.make(init_state_index=3)
        for episode in (0, 1, 2, 7):
            benchmark.reset(self.task(episode))
            self.assertEqual(3.0, env.state[0])
        self.assertTrue(all(call["episode_idx"] == 3 for call in benchmark.upstream_reset_tasks))

    def test_without_the_option_the_harness_episode_index_is_used(self):
        benchmark, env = self.make()
        task = self.task(4)
        benchmark.reset(task)
        self.assertIs(task, benchmark.upstream_reset_tasks[0])
        self.assertEqual(4.0, env.state[0])

    def test_the_callers_task_is_not_modified(self):
        benchmark, _env = self.make(init_state_index=2)
        task = self.task(5)
        benchmark.reset(task)
        self.assertEqual(5, task["episode_idx"])

    def test_index_zero_is_a_real_selection(self):
        benchmark, env = self.make(init_state_index=0)
        benchmark.reset(self.task(5))
        self.assertEqual(0.0, env.state[0])

    def test_option_is_not_forwarded_upstream_and_keeps_the_suite(self):
        benchmark, _env = self.make(init_state_index=1)
        self.assertEqual({"suite": "libero_10", "seed": 7, "send_wrist_image": False,
                          "send_state": False}, benchmark.upstream_kwargs)
        self.assertEqual(1, benchmark.init_state_index)
        self.assertIsNone(self.benchmark_type().init_state_index)

    def test_rejects_invalid_values(self):
        for value in (-1, True, 1.5, "2", float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.benchmark_type(init_state_index=value)

    def test_cannot_be_combined_with_an_external_reset(self):
        with self.assertRaises(ValueError):
            self.benchmark_type(init_state_index=1,
                                external_reset={"candidate": "a", "metadata_out": "b"})


def _contact(env, first, second, dist):
    env.sim.data.contacts = [FakeContact(GEOM[first], GEOM[second], dist)]


class ScenarioStartTests(FakeHarnessCase):
    """The scenario_start option: validated state, validity before settling, sidecar."""

    WAIT = 3

    def setUp(self):
        super().setUp()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.env = FakeEnv()
        self.length = self.env.model.state_length
        self.state = np.linspace(-0.5, 0.5, self.length)
        self.candidate_path = self.root / "candidate.json"
        self.sidecar = self.root / "scenario_start.json"
        self.write_candidate()

    def write_candidate(self, **changes):
        candidate = scenario_import.candidate_from_benchmark("libero_10", 0, 4, self.state)
        candidate.update(changes)
        self.candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    def make(self, **options):
        benchmark = self.benchmark_type(
            suite="libero_10", num_steps_wait=self.WAIT,
            scenario_start={"candidate": str(self.candidate_path), "metadata_out": str(self.sidecar)},
            **options)
        benchmark._make_env = lambda task: self.env
        return benchmark

    @staticmethod
    def task(task_id=0):
        return {"task_id": task_id, "task_obj": object(), "name": "task {}".format(task_id), "episode_idx": 0}

    def records(self):
        return json.loads(self.sidecar.read_text(encoding="utf-8"))

    # ---- valid scenes ----------------------------------------------------

    def test_a_valid_scenario_is_restored_then_settled_like_upstream(self):
        benchmark = self.make()
        observation = benchmark.reset(self.task())
        self.assertEqual([], benchmark.upstream_reset_tasks)
        self.assertEqual(["reset", "set_init_state"] + ["step"] * self.WAIT, self.env.calls)
        self.assertEqual("step", observation["from"])
        self.assertEqual(1, len(benchmark._recorder.frames))
        self.assertFalse(benchmark._invalid_scene)
        self.assertGreaterEqual(self.env.sim.forwards, 1)

    def test_the_restored_state_is_the_candidates_exactly(self):
        benchmark = self.make()
        self.env.drift = np.zeros(self.length)
        benchmark.reset(self.task())
        np.testing.assert_array_equal(self.state, self.env.state)

    def test_sidecar_records_hashes_validity_and_settling(self):
        self.env.drift = np.zeros(self.length)
        self.env.drift[1 + 3 + 2] = 0.001  # the soup falls 1 mm per settling step
        benchmark = self.make()
        benchmark.reset(self.task())
        (record,) = self.records()
        self.assertEqual(1, record["schema_version"])
        self.assertEqual(0, record["episode_index"])
        self.assertEqual(("libero_10", 0), (record["suite"], record["task_id"]))
        self.assertEqual({"kind": "benchmark", "init_state_index": 4}, record["source"])
        candidate_hash = external_reset.state_sha256(self.state.tolist())
        self.assertEqual(candidate_hash, record["candidate_state_sha256"])
        self.assertEqual(candidate_hash, record["pre_settle_state_sha256"])
        self.assertEqual(external_reset.state_sha256(self.env.state.tolist()), record["post_settle_state_sha256"])
        self.assertNotEqual(record["pre_settle_state_sha256"], record["post_settle_state_sha256"])
        self.assertEqual(self.WAIT, record["settling_steps"])
        self.assertEqual("valid", record["validity"])
        self.assertEqual(0.005, record["penetration_limit_m"])
        self.assertEqual((0.0, None, 0), (record["deepest_penetration_m"], record["deepest_pair"],
                                         record["invalid_contacts"]))
        self.assertAlmostEqual(0.003, record["settle_displacement_m"]["alphabet_soup_1"])
        self.assertAlmostEqual(0.0, record["settle_displacement_m"]["basket_1"])
        self.assertNotIn("robot", record["settle_displacement_m"])
        self.assertNotIn("perturbation", record)

    def test_a_shallow_overlap_is_recorded_but_the_scene_stays_valid(self):
        self.env.after_set = lambda env: _contact(env, "soup", "basket", -0.003)
        benchmark = self.make()
        benchmark.reset(self.task())
        (record,) = self.records()
        self.assertEqual("valid", record["validity"])
        self.assertAlmostEqual(0.003, record["deepest_penetration_m"])
        self.assertEqual(["alphabet_soup_1", "basket_1"], record["deepest_pair"])
        self.assertEqual(self.WAIT, self.env.calls.count("step"))

    def test_each_episode_appends_a_record_atomically(self):
        benchmark = self.make()
        for _ in range(3):
            benchmark.reset(self.task())
        self.assertEqual([0, 1, 2], [record["episode_index"] for record in self.records()])
        self.assertEqual([], [name for name in os.listdir(self.root) if "partial" in name])

    def test_perturbation_spec_is_recorded_only_when_configured(self):
        benchmark = self.make(seed=7, image_perturbation={"kind": "blur", "severity": 0.4})
        benchmark.reset(self.task())
        (record,) = self.records()
        self.assertEqual("blur", record["perturbation"]["image_perturbation"]["kind"])

    def test_absolute_action_mode_switches_after_settling_like_upstream(self):
        controller = types.SimpleNamespace(use_delta=True)
        self.env.robots = [types.SimpleNamespace(controller=controller)]
        benchmark = self.make()
        benchmark.absolute_action = True
        benchmark.reset(self.task())
        self.assertFalse(controller.use_delta)

    def test_the_candidate_is_read_once(self):
        benchmark = self.make()
        benchmark.reset(self.task())
        self.candidate_path.write_text("{", encoding="utf-8")
        benchmark.reset(self.task())
        self.assertEqual(2, len(self.records()))

    # ---- fail closed -----------------------------------------------------

    def test_wrong_state_length_is_rejected_before_anything_is_set(self):
        self.state = np.zeros(self.length + 2)
        self.write_candidate()
        benchmark = self.make()
        with self.assertRaisesRegex(scenario_import.ScenarioImportError, "state length"):
            benchmark.reset(self.task())
        self.assertNotIn("set_init_state", self.env.calls)

    def test_task_or_suite_mismatch_is_rejected(self):
        benchmark = self.make()
        with self.assertRaises(scenario_import.ScenarioImportError):
            benchmark.reset(self.task(task_id=1))
        self.write_candidate(suite="libero_object")
        self.candidate_path.write_text(json.dumps(scenario_import.candidate_from_benchmark(
            "libero_object", 0, 4, self.state)), encoding="utf-8")
        with self.assertRaises(scenario_import.ScenarioImportError):
            self.make().reset(self.task())

    def test_an_invalid_candidate_file_is_rejected(self):
        self.candidate_path.write_text(json.dumps(dict(
            scenario_import.candidate_from_benchmark("libero_10", 0, 4, self.state), state_sha256="0" * 64)),
            encoding="utf-8")
        with self.assertRaises(scenario_import.ScenarioImportError):
            self.make().reset(self.task())
        self.assertEqual([], self.env.calls)

    def test_a_state_that_does_not_restore_exactly_is_an_error(self):
        def corrupt(env):
            env.state[3] += 1e-9
        self.env.after_set = corrupt
        with self.assertRaises(scenario_import.ScenarioStartError):
            self.make().reset(self.task())
        self.assertFalse(self.sidecar.exists())

    # ---- invalid scenes --------------------------------------------------

    def invalid_benchmark(self, dist=-0.01):
        self.env.after_set = lambda env: _contact(env, "finger", "soup", dist)
        return self.make()

    def test_a_penetrating_scene_is_not_settled(self):
        benchmark = self.invalid_benchmark()
        observation = benchmark.reset(self.task())
        self.assertEqual(["reset", "set_init_state"], self.env.calls)
        self.assertEqual("set_init_state", observation["from"])
        self.assertTrue(benchmark._invalid_scene)
        self.assertEqual(1, len(benchmark._recorder.frames))

    def test_the_sidecar_marks_the_episode_invalid_scene(self):
        self.invalid_benchmark().reset(self.task())
        (record,) = self.records()
        self.assertEqual("invalid_scene", record["validity"])
        self.assertAlmostEqual(0.01, record["deepest_penetration_m"])
        self.assertEqual(["alphabet_soup_1", "robot"], record["deepest_pair"])
        self.assertEqual(1, record["invalid_contacts"])
        self.assertIsNone(record["post_settle_state_sha256"])
        self.assertEqual(0, record["settling_steps"])
        self.assertEqual({}, record["settle_displacement_m"])
        self.assertEqual(record["candidate_state_sha256"], record["pre_settle_state_sha256"])

    def test_the_threshold_edge_decides_validity(self):
        for dist, expected in ((-0.005, "valid"), (-0.0050001, "invalid_scene")):
            self.sidecar.unlink() if self.sidecar.exists() else None
            self.invalid_benchmark(dist).reset(self.task())
            self.assertEqual(expected, self.records()[-1]["validity"], dist)

    def test_the_next_step_ends_the_episode_without_success_or_a_simulator_step(self):
        benchmark = self.invalid_benchmark()
        benchmark.reset(self.task())
        result = benchmark.step({"actions": [0.0] * 7})
        self.assertTrue(result.done)
        self.assertTrue(benchmark.check_done(result))
        self.assertEqual({"success": False, "invalid_scene": True}, benchmark.get_step_result(result))
        self.assertEqual(["reset", "set_init_state"], self.env.calls)
        self.assertEqual([{"reward": 0.0, "done": True, "success": False}], benchmark._recorder.steps)

    def test_valid_scenes_step_and_score_exactly_as_upstream(self):
        benchmark = self.make()
        benchmark.reset(self.task())
        result = benchmark.step({"actions": [0.0] * 7})
        self.assertFalse(result.done)
        self.assertEqual({"success": False}, benchmark.get_step_result(result))
        self.assertEqual("step", self.env.calls[-1])

    def test_the_invalid_flag_clears_on_the_next_reset(self):
        benchmark = self.invalid_benchmark()
        benchmark.reset(self.task())
        self.assertTrue(benchmark._invalid_scene)
        self.env.after_set = None
        self.env.sim.data.contacts = []
        benchmark.reset(self.task())
        self.assertFalse(benchmark._invalid_scene)
        self.assertEqual(["invalid_scene", "valid"], [record["validity"] for record in self.records()])

    # ---- configuration ---------------------------------------------------

    def test_option_shape_is_validated_like_external_reset(self):
        for bad in ({"candidate": "a"}, {"candidate": "", "metadata_out": "b"}, "path", 3,
                    {"candidate": "a", "metadata_out": "b", "extra": "c"},
                    {"candidate": "a", "metadata_out": 3}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.benchmark_type(suite="libero_10", scenario_start=bad)

    def test_it_is_exclusive_with_external_reset_and_init_state_index(self):
        good = {"candidate": "a", "metadata_out": "b"}
        with self.assertRaises(ValueError):
            self.benchmark_type(scenario_start=good, external_reset=good)
        with self.assertRaises(ValueError):
            self.benchmark_type(scenario_start=good, init_state_index=1)

    def test_option_is_not_forwarded_upstream(self):
        benchmark = self.make()
        self.assertEqual({"suite": "libero_10", "seed": 7, "send_wrist_image": False, "send_state": False},
                         benchmark.upstream_kwargs)
        self.assertIsNone(self.benchmark_type().scenario_start)


class ExportTests(FakeHarnessCase):
    """layout_out and state_out: what the pure side needs to name and rebuild starts."""

    def setUp(self):
        super().setUp()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.env = FakeEnv()
        self.length = self.env.model.state_length
        self.layout_path = self.root / "out" / "layout.json"
        self.state_path = self.root / "out" / "state.json"

    def make(self, **options):
        benchmark = self.benchmark_type(suite="libero_10", num_steps_wait=2, **options)
        benchmark._make_env = lambda task: self.env
        benchmark._task_suite = FakeTaskSuite({0: _states(self.length), 1: _states(self.length)})
        return benchmark

    @staticmethod
    def task(task_id=0, episode_idx=0):
        return {"task_id": task_id, "task_obj": object(), "name": "task {}".format(task_id),
                "episode_idx": episode_idx}

    def expected_layout(self, task_id=0):
        return scene_inspect.build_layout("libero_10", task_id, self.env.model, self.length)

    def read(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    # ---- layout ----------------------------------------------------------

    def test_layout_is_written_after_a_benchmark_reset(self):
        self.make(layout_out=str(self.layout_path)).reset(self.task())
        self.assertEqual(self.expected_layout(), self.read(self.layout_path))
        self.assertEqual(35, self.read(self.layout_path)["state_length"])

    def test_layout_is_written_with_init_state_index_and_with_scenario_starts(self):
        self.make(layout_out=str(self.layout_path), init_state_index=2).reset(self.task())
        self.assertEqual(self.expected_layout(), self.read(self.layout_path))
        self.layout_path.unlink()
        candidate = self.root / "candidate.json"
        scenario_import.write_scenario_candidate(
            candidate, scenario_import.candidate_from_benchmark("libero_10", 0, 1, np.zeros(self.length)))
        benchmark = self.make(
            layout_out=str(self.layout_path),
            scenario_start={"candidate": str(candidate), "metadata_out": str(self.root / "sidecar.json")})
        benchmark.reset(self.task())
        self.assertEqual(self.expected_layout(), self.read(self.layout_path))

    def test_layout_is_written_once_per_task_and_replaced_by_the_next_task(self):
        benchmark = self.make(layout_out=str(self.layout_path))
        benchmark.reset(self.task())
        self.layout_path.unlink()
        benchmark.reset(self.task())
        self.assertFalse(self.layout_path.exists())
        benchmark.reset(self.task(task_id=1))
        self.assertEqual(1, self.read(self.layout_path)["task_id"])

    def test_layout_writes_are_atomic_and_leave_no_partial_file(self):
        self.make(layout_out=str(self.layout_path)).reset(self.task())
        self.assertEqual(["layout.json"], os.listdir(self.layout_path.parent))

    def test_a_state_that_is_not_time_qpos_qvel_fails_the_export(self):
        benchmark = self.make(layout_out=str(self.layout_path))
        original = self.env.set_init_state

        def odd(state):
            observation = original(state)
            self.env.state = np.zeros(self.length + 3)
            self.env.drift = np.zeros(self.length + 3)
            return observation

        self.env.set_init_state = odd
        with self.assertRaises(scene_inspect.SceneInspectError):
            benchmark.reset(self.task())

    def test_no_layout_or_state_files_without_the_options(self):
        self.make().reset(self.task())
        self.assertEqual([], list(self.root.iterdir()))

    # ---- start state -----------------------------------------------------

    def test_state_out_is_a_scenario_candidate_for_the_selected_init_state(self):
        self.make(state_out=str(self.state_path), init_state_index=3).reset(self.task(episode_idx=9))
        candidate = scenario_import.load_scenario_candidate(self.state_path)
        self.assertEqual({"kind": "benchmark", "init_state_index": 3}, candidate["source"])
        self.assertEqual(("libero_10", 0), (candidate["suite"], candidate["task_id"]))
        self.assertEqual([3.0] * self.length, candidate["state"])
        self.assertEqual(external_reset.state_sha256(candidate["state"]), candidate["state_sha256"])

    def test_state_out_without_init_state_index_uses_the_harness_episode_index(self):
        self.make(state_out=str(self.state_path)).reset(self.task(episode_idx=4))
        candidate = scenario_import.load_scenario_candidate(self.state_path)
        self.assertEqual({"kind": "benchmark", "init_state_index": 4}, candidate["source"])
        self.assertEqual([4.0] * self.length, candidate["state"])

    def test_state_out_is_written_before_settling_changes_the_state(self):
        self.env.drift = np.ones(self.length)
        self.make(state_out=str(self.state_path), init_state_index=1).reset(self.task())
        self.assertEqual([1.0] * self.length, self.read(self.state_path)["state"])

    def test_the_benchmark_start_is_scanned_before_settling_and_the_episode_runs_on(self):
        self.env.after_set = lambda env: _contact(env, "finger", "soup", -0.02)
        benchmark = self.make(state_out=str(self.state_path), init_state_index=2)
        observation = benchmark.reset(self.task())
        self.assertEqual("step", observation["from"], "a benchmark start is never cut short")
        self.assertEqual(["reset", "set_init_state", "step", "step"], self.env.calls)
        self.assertEqual([], benchmark.upstream_reset_tasks, "the upstream reset is replayed to scan in between")
        self.assertFalse(benchmark._invalid_scene)
        validity = self.read(self.root / "out" / "state.validity.json")
        self.assertEqual("invalid_scene", validity["validity"])
        self.assertAlmostEqual(0.02, validity["deepest_penetration_m"])
        self.assertEqual(["alphabet_soup_1", "robot"], validity["deepest_pair"])
        self.assertEqual((2, 0, "libero_10"), (validity["init_state_index"], validity["task_id"], validity["suite"]))
        self.assertEqual(1, len(benchmark._recorder.frames))

    def test_a_clean_benchmark_start_is_valid(self):
        self.make(state_out=str(self.state_path), init_state_index=2).reset(self.task())
        validity = self.read(self.root / "out" / "state.validity.json")
        self.assertEqual(("valid", 0.0, None, 0), (validity["validity"], validity["deepest_penetration_m"],
                                                  validity["deepest_pair"], validity["invalid_contacts"]))
        self.assertEqual(0.005, validity["penetration_limit_m"])

    def test_the_replayed_reset_matches_the_upstream_order_and_absolute_mode(self):
        controller = types.SimpleNamespace(use_delta=True)
        self.env.robots = [types.SimpleNamespace(controller=controller)]
        benchmark = self.make(state_out=str(self.state_path), init_state_index=1)
        benchmark.absolute_action = True
        benchmark.reset(self.task())
        self.assertEqual(["reset", "set_init_state", "step", "step"], self.env.calls)
        self.assertFalse(controller.use_delta)
        self.assertEqual([1.0] * self.length, list(self.env.state), "the benchmark state, then zero drift")

    def test_without_state_out_the_upstream_reset_is_used_unchanged(self):
        benchmark = self.make(layout_out=str(self.layout_path), init_state_index=1)
        benchmark.reset(self.task())
        self.assertEqual(1, len(benchmark.upstream_reset_tasks))
        self.assertFalse((self.root / "out" / "state.validity.json").exists())

    def test_state_out_is_written_once_per_task(self):
        benchmark = self.make(state_out=str(self.state_path), init_state_index=1)
        benchmark.reset(self.task())
        self.state_path.unlink()
        benchmark.reset(self.task())
        self.assertFalse(self.state_path.exists())

    def test_state_of_the_wrong_length_is_not_exported(self):
        benchmark = self.make(state_out=str(self.state_path), init_state_index=1)
        benchmark._task_suite = FakeTaskSuite({0: _states(self.length + 1)})
        with self.assertRaises(scenario_import.ScenarioImportError):
            benchmark.reset(self.task())
        self.assertFalse(self.state_path.exists())
        self.assertNotIn("set_init_state", self.env.calls)

    # ---- options ---------------------------------------------------------

    def test_options_are_validated_and_not_forwarded_upstream(self):
        for name in ("layout_out", "state_out"):
            for bad in ("", 3, ["x"], True):
                with self.subTest(name=name, bad=bad), self.assertRaises(ValueError):
                    self.benchmark_type(**{name: bad})
        benchmark = self.make(layout_out="a.json", state_out="b.json")
        self.assertEqual({"suite": "libero_10", "seed": 7, "send_wrist_image": False, "send_state": False},
                         benchmark.upstream_kwargs)

    def test_exports_are_not_available_with_the_external_demo_start(self):
        external = {"candidate": "a", "metadata_out": "b"}
        for option in ({"layout_out": "x.json"}, {"state_out": "x.json"}):
            with self.subTest(option=option), self.assertRaises(ValueError):
                self.benchmark_type(external_reset=external, **option)

    def test_state_out_is_not_available_with_a_scenario_start(self):
        with self.assertRaises(ValueError):
            self.benchmark_type(scenario_start={"candidate": "a", "metadata_out": "b"}, state_out="x.json")

    def test_every_written_config_key_is_a_constructor_option(self):
        import importlib.util
        import yaml
        script = Path(__file__).parents[1] / "scripts" / "run_failure_search.py"
        spec = importlib.util.spec_from_file_location("run_failure_search_for_options", script)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(module)
        for options in (dict(init_state_index=3, layout_out=self.layout_path, state_out=self.state_path),
                        dict(scenario_start=self.root / "c.json", layout_out=self.layout_path)):
            config = self.root / "stage.yaml"
            module._write_config(config_path=config, output_dir=self.root / "run", project_root=self.root,
                                 stage_name="s", episode_indices=(0,), suite="libero_10", task_id=1, **options)
            params = yaml.safe_load(config.read_text(encoding="utf-8"))["benchmarks"][0]["params"]
            benchmark = self.benchmark_type(**params)
            self.assertEqual("libero_10", benchmark.upstream_kwargs["suite"])
            self.assertEqual(1, benchmark.task_id)


if __name__ == "__main__":
    unittest.main()
