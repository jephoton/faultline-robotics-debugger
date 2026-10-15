"""M7 breadth pack, simulator side: the scene families in the LIBERO adapter."""

import json
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

from robot_debug import external_reset, scenario_import
from tests.scene_fakes import FakeEnv, FakeHarnessCase, FakeTaskSuite
from tests.test_scene_perturbation import FakeSceneModel


def _states(length, count=6):
    return [np.full(length, float(index)) for index in range(count)]


class SceneHarnessCase(FakeHarnessCase):
    """A fake LIBERO env whose model also carries the camera and light arrays."""

    WAIT = 3

    def setUp(self):
        super().setUp()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.env = FakeEnv()
        scene = FakeSceneModel()
        model = self.env.sim.model
        for name in ("cam_pos", "cam_quat", "camera_name2id", "light_diffuse", "light_ambient", "vis", "nlight"):
            setattr(model, name, getattr(scene, name))
        self.original_pos = model.cam_pos.copy()
        self.original_quat = model.cam_quat.copy()
        self.original_diffuse = model.light_diffuse.copy()
        self.length = model.state_length
        # Record the camera and light values as seen by every simulator call.
        self.seen = []
        real_reset, real_set, real_step = self.env.reset, self.env.set_init_state, self.env.step

        def snapshot(name):
            self.seen.append((name, model.cam_pos[1].copy(), model.cam_quat[1].copy(), model.light_diffuse[0].copy(),
                              self.env.sim.forwards))

        def reset():
            snapshot("reset")
            return real_reset()

        def set_init_state(state):
            result = real_set(state)
            snapshot("set_init_state")
            return result

        def step(action):
            snapshot("step")
            return real_step(action)

        self.env.reset, self.env.set_init_state, self.env.step = reset, set_init_state, step

    def make(self, **options):
        benchmark = self.benchmark_type(suite="libero_10", num_steps_wait=self.WAIT, **options)
        benchmark._make_env = lambda task: self.env
        benchmark._task_suite = FakeTaskSuite({0: _states(self.length)})
        return benchmark

    @staticmethod
    def task(episode_idx=0):
        return {"task_id": 0, "task_obj": object(), "name": "pick the soup", "episode_idx": episode_idx}

    def names(self):
        return [entry[0] for entry in self.seen]


class SceneBenchmarkResetTests(SceneHarnessCase):
    def test_the_viewpoint_is_applied_after_the_start_state_and_before_settling(self):
        benchmark = self.make(scene_perturbation={"kind": "viewpoint", "severity": 1.0})
        benchmark.reset(self.task())
        self.assertEqual(["reset", "set_init_state"] + ["step"] * self.WAIT, self.names())
        reset, set_state, first_step = self.seen[0], self.seen[1], self.seen[2]
        np.testing.assert_array_equal(self.original_pos[1], reset[1])
        np.testing.assert_array_equal(self.original_pos[1], set_state[1], "the start state is set first")
        self.assertAlmostEqual(0.10, float(np.linalg.norm(first_step[1] - self.original_pos[1])), places=9)
        self.assertGreater(first_step[4], set_state[4], "the simulator state was refreshed after the change")
        for entry in self.seen[2:]:
            np.testing.assert_array_equal(first_step[1], entry[1])

    def test_the_replayed_reset_matches_the_upstream_one_apart_from_the_scene(self):
        plain = self.make()
        plain.reset(self.task(2))
        plain_calls = list(self.env.calls)
        plain_state = self.env.state.copy()
        self.env.calls.clear()
        scene = self.make(scene_perturbation={"kind": "lighting", "severity": 0.5})
        scene.reset(self.task(2))
        self.assertEqual(plain_calls, self.env.calls)
        np.testing.assert_array_equal(plain_state, self.env.state)
        self.assertEqual([], scene.upstream_reset_tasks, "the replayed reset does not call the upstream reset")
        self.assertEqual(1, len(plain.upstream_reset_tasks))
        self.assertEqual(1, len(scene._recorder.frames))

    def test_lighting_scales_the_scene_lights(self):
        benchmark = self.make(scene_perturbation={"kind": "lighting", "severity": 0.5})
        benchmark.reset(self.task())
        np.testing.assert_allclose(self.seen[2][3], self.original_diffuse[0] * 0.55)

    def test_the_scene_is_restored_before_the_next_reset(self):
        benchmark = self.make(scene_perturbation={"kind": "viewpoint", "severity": 1.0})
        benchmark.reset(self.task())
        benchmark.reset(self.task())
        resets = [entry for entry in self.seen if entry[0] == "reset"]
        self.assertEqual(2, len(resets))
        np.testing.assert_array_equal(self.original_pos[1], resets[1][1])
        np.testing.assert_array_equal(self.original_quat[1], resets[1][2])
        steps = [entry for entry in self.seen if entry[0] == "step"]
        np.testing.assert_array_equal(steps[0][1], steps[-1][1], "the second episode sees the same viewpoint")

    def test_the_selected_init_state_is_used_and_the_callers_task_is_untouched(self):
        benchmark = self.make(init_state_index=3, scene_perturbation={"kind": "viewpoint", "severity": 0.4})
        task = self.task(5)
        benchmark.reset(task)
        self.assertEqual(3.0, self.env.state[0])
        self.assertEqual(5, task["episode_idx"])
        benchmark = self.make(scene_perturbation={"kind": "viewpoint", "severity": 0.4})
        benchmark.reset(self.task(4))
        self.assertEqual(4.0, self.env.state[0], "the harness episode index is the start when none is chosen")

    def test_absolute_action_mode_still_switches_after_settling(self):
        import types

        controller = types.SimpleNamespace(use_delta=True)
        self.env.robots = [types.SimpleNamespace(controller=controller)]
        benchmark = self.make(scene_perturbation={"kind": "viewpoint", "severity": 0.4})
        benchmark.absolute_action = True
        benchmark.reset(self.task())
        self.assertFalse(controller.use_delta)

    def test_a_disabled_scene_perturbation_uses_the_upstream_reset_untouched(self):
        benchmark = self.make(scene_perturbation={"kind": "viewpoint", "severity": 0})
        benchmark.reset(self.task())
        self.assertEqual(1, len(benchmark.upstream_reset_tasks))
        np.testing.assert_array_equal(self.original_pos, self.env.sim.model.cam_pos)
        self.assertIsNone(benchmark.perturbation_record())

    def test_the_replay_record_lists_the_scene_spec_with_its_physical_value(self):
        benchmark = self.make(seed=11, scene_perturbation={"kind": "viewpoint", "severity": 0.5})
        record = benchmark.perturbation_record()
        self.assertEqual(11, record["seed"])
        self.assertEqual({"kind": "viewpoint", "severity": 0.5,
                          "physical": {"name": "camera_shift_m", "value": 0.05}}, record["scene_perturbation"])
        self.assertNotIn("image_perturbation", record)
        both = self.make(scene_perturbation={"kind": "lighting", "severity": 0.5},
                         image_perturbation={"kind": "blur", "severity": 0.5}).perturbation_record()
        self.assertEqual({"image_perturbation", "scene_perturbation", "seed"}, set(both))

    def test_the_option_is_not_forwarded_upstream(self):
        benchmark = self.make(scene_perturbation={"kind": "viewpoint", "severity": 0.5})
        self.assertEqual({"suite": "libero_10", "seed": 7, "send_wrist_image": False, "send_state": False},
                         benchmark.upstream_kwargs)

    def test_rejects_bad_options(self):
        for value in ({"kind": "viewpoint"}, {"kind": "tilt", "severity": 0.5}, {"kind": "viewpoint", "severity": 2},
                      {"kind": "lighting", "severity": True}, "viewpoint", [], {"kind": "viewpoint", "severity": 0.5, "x": 1}):
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                self.benchmark_type(scene_perturbation=value)

    def test_cannot_be_combined_with_an_external_reset_or_skipped_settling(self):
        with self.assertRaises(ValueError):
            self.benchmark_type(scene_perturbation={"kind": "viewpoint", "severity": 0.5},
                                external_reset={"candidate": "a", "metadata_out": "b"})
        with self.assertRaises(ValueError):
            self.benchmark_type(scene_perturbation={"kind": "viewpoint", "severity": 0.5}, num_steps_wait=0)

    def test_observations_are_not_changed_by_a_scene_perturbation(self):
        raw = {"frame": np.full((2, 2, 3), 9, dtype=np.uint8)}
        plain = self.make().make_obs(raw, self.task())
        scene = self.make(scene_perturbation={"kind": "viewpoint", "severity": 1.0}).make_obs(raw, self.task())
        np.testing.assert_array_equal(plain["images"]["agentview"], scene["images"]["agentview"])
        self.assertEqual(plain["task_description"], scene["task_description"])

    def test_state_out_still_exports_the_start_when_a_scene_is_perturbed(self):
        out = self.root / "start.json"
        benchmark = self.make(state_out=str(out), scene_perturbation={"kind": "lighting", "severity": 0.5})
        benchmark.reset(self.task(2))
        self.assertTrue(out.exists())
        self.assertEqual(["reset", "set_init_state"] + ["step"] * self.WAIT, self.names())

    def test_the_camera_probe_records_the_applied_values_without_image_samples(self):
        probe = self.root / "case.camera_probe.json"
        benchmark = self.make(camera_probe=str(probe), scene_perturbation={"kind": "viewpoint", "severity": 0.5})
        benchmark.reset(self.task())
        document = json.loads(probe.read_text(encoding="utf-8"))
        self.assertEqual(1, document["schema_version"])
        self.assertEqual([], document["episodes"])
        self.assertEqual("viewpoint", document["perturbation"]["scene_perturbation"]["kind"])
        (applied,) = document["scene_applied"]
        self.assertEqual(0, applied["episode_index"])
        self.assertAlmostEqual(0.05, applied["shift_m"], places=9)
        self.assertAlmostEqual(5.0, applied["yaw_deg"], places=9)
        np.testing.assert_allclose(applied["cam_pos"], self.env.sim.model.cam_pos[1])
        self.assertEqual([], [name for name in os.listdir(self.root) if "partial" in name])

    def test_one_applied_record_per_episode_and_the_probe_stays_small(self):
        probe = self.root / "case.camera_probe.json"
        benchmark = self.make(camera_probe=str(probe), scene_perturbation={"kind": "viewpoint", "severity": 0.5})
        for _ in range(3):
            benchmark.reset(self.task())
        document = json.loads(probe.read_text(encoding="utf-8"))
        self.assertEqual([0, 1, 2], [entry["episode_index"] for entry in document["scene_applied"]])
        self.assertAlmostEqual(0.05, document["scene_applied"][0]["shift_m"], places=9)
        self.assertLess(probe.stat().st_size, 16 * 1024)
        for _ in range(100):
            benchmark.reset(self.task())
        self.assertLessEqual(probe.stat().st_size, 16 * 1024)
        self.assertTrue(json.loads(probe.read_text(encoding="utf-8")).get("truncated"))


class SceneScenarioStartTests(SceneHarnessCase):
    def setUp(self):
        super().setUp()
        self.state = np.linspace(-0.5, 0.5, self.length)
        self.candidate_path = self.root / "candidate.json"
        self.sidecar = self.root / "scenario_start.json"
        candidate = scenario_import.candidate_from_benchmark("libero_10", 0, 4, self.state)
        self.candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    def make_scenario(self, **options):
        return self.make(
            scenario_start={"candidate": str(self.candidate_path), "metadata_out": str(self.sidecar)}, **options)

    def test_the_scene_is_applied_after_the_restore_and_before_settling(self):
        benchmark = self.make_scenario(scene_perturbation={"kind": "viewpoint", "severity": 1.0})
        benchmark.reset(self.task())
        self.assertEqual(["reset", "set_init_state"] + ["step"] * self.WAIT, self.names())
        self.assertAlmostEqual(
            0.10, float(np.linalg.norm(self.seen[2][1] - self.original_pos[1])), places=9)
        np.testing.assert_array_equal(self.original_pos[1], self.seen[1][1])
        np.testing.assert_array_equal(self.state, self.env.state)

    def test_the_sidecar_records_the_spec_and_the_applied_values(self):
        benchmark = self.make_scenario(scene_perturbation={"kind": "lighting", "severity": 0.5})
        benchmark.reset(self.task())
        (record,) = json.loads(self.sidecar.read_text(encoding="utf-8"))
        self.assertEqual("lighting", record["perturbation"]["scene_perturbation"]["kind"])
        self.assertEqual(0.55, record["scene_applied"]["scale"])
        self.assertEqual("valid", record["validity"])

    def test_without_a_scene_perturbation_the_record_is_unchanged(self):
        benchmark = self.make_scenario()
        benchmark.reset(self.task())
        (record,) = json.loads(self.sidecar.read_text(encoding="utf-8"))
        self.assertNotIn("scene_applied", record)
        self.assertNotIn("perturbation", record)


if __name__ == "__main__":
    unittest.main()
