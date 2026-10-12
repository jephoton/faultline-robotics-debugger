import importlib
import inspect
import sys
import types
import unittest

import numpy as np


class FakeLIBEROBenchmark:
    def __init__(self, **kwargs) -> None:
        self.upstream_kwargs = kwargs

    def get_tasks(self):
        return [
            {"task_id": task_id, "task_obj": object(), "name": f"task {task_id}"}
            for task_id in range(3)
        ]

    def make_obs(self, raw_obs, task):
        return {
            "images": {
                "agentview": raw_obs["agentview"].copy(),
                "wrist": raw_obs["wrist"],
            },
            "states": raw_obs["states"],
            "task_description": task["name"],
        }

    @staticmethod
    def _extract_frame(raw_obs):
        if not isinstance(raw_obs, dict):
            return None
        return raw_obs.get("frame")


class DiagnosticLIBEROBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.saved_modules = {
            name: sys.modules.get(name)
            for name in (
                "vla_eval",
                "vla_eval.benchmarks",
                "vla_eval.benchmarks.libero",
                "vla_eval.benchmarks.libero.benchmark",
                "robot_debug.libero",
            )
        }
        for name in self.saved_modules:
            sys.modules.pop(name, None)

        module_names = (
            "vla_eval",
            "vla_eval.benchmarks",
            "vla_eval.benchmarks.libero",
            "vla_eval.benchmarks.libero.benchmark",
        )
        for name in module_names:
            sys.modules[name] = types.ModuleType(name)
        sys.modules[
            "vla_eval.benchmarks.libero.benchmark"
        ].LIBEROBenchmark = FakeLIBEROBenchmark

        adapter = importlib.import_module("robot_debug.libero")
        self.benchmark_type = adapter.DiagnosticLIBEROBenchmark

    def tearDown(self) -> None:
        for name, original in self.saved_modules.items():
            sys.modules.pop(name, None)
            if original is not None:
                sys.modules[name] = original

    def test_forwards_upstream_configuration_and_parses_occlusion(self) -> None:
        benchmark = self.benchmark_type(
            suite="libero_object",
            seed=7,
            agentview_occlusion={
                "x": 0.25,
                "y": 0.25,
                "width": 0.5,
                "height": 0.5,
                "color": [0, 0, 0],
            },
        )

        self.assertEqual(
            benchmark.upstream_kwargs,
            {
                "suite": "libero_object",
                "seed": 7,
                "send_wrist_image": False,
                "send_state": False,
            },
        )
        self.assertEqual(benchmark.agentview_occlusion.color, (0, 0, 0))

    def test_exposes_model_required_inputs_in_constructor_signature(self) -> None:
        parameters = inspect.signature(self.benchmark_type.__init__).parameters

        self.assertIn("send_wrist_image", parameters)
        self.assertIn("send_state", parameters)

    def test_selects_exact_task_without_renumbering_it(self) -> None:
        benchmark = self.benchmark_type(task_id=2, suite="libero_object")

        self.assertEqual([task["task_id"] for task in benchmark.get_tasks()], [2])
        self.assertNotIn("task_id", benchmark.upstream_kwargs)
        self.assertIn("task_obj", benchmark.get_tasks()[0])

    def test_legacy_configuration_keeps_all_tasks(self) -> None:
        benchmark = self.benchmark_type()

        self.assertEqual([task["task_id"] for task in benchmark.get_tasks()], [0, 1, 2])

    def test_missing_task_id_fails_closed(self) -> None:
        benchmark = self.benchmark_type(task_id=9)

        with self.assertRaisesRegex(ValueError, "task_id 9"):
            benchmark.get_tasks()

    def test_rejects_invalid_task_ids(self) -> None:
        for task_id in (-1, True, 1.5, "1"):
            with self.subTest(task_id=task_id), self.assertRaises(ValueError):
                self.benchmark_type(task_id=task_id)

    def test_masks_only_policy_agentview(self) -> None:
        agentview = np.full((4, 4, 3), 255, dtype=np.uint8)
        wrist = np.full((4, 4, 3), 19, dtype=np.uint8)
        state = np.array([1.0, 2.0])
        raw_obs = {"agentview": agentview, "wrist": wrist, "states": state}
        benchmark = self.benchmark_type(
            agentview_occlusion={
                "x": 0.25,
                "y": 0.25,
                "width": 0.5,
                "height": 0.5,
            }
        )

        observation = benchmark.make_obs(raw_obs, {"name": "pick up object"})

        self.assertEqual(int(observation["images"]["agentview"][1, 1, 0]), 0)
        self.assertIs(observation["images"]["wrist"], wrist)
        self.assertIs(observation["states"], state)
        np.testing.assert_array_equal(agentview, np.full((4, 4, 3), 255, dtype=np.uint8))

    def test_masks_recorded_frame_with_the_same_spec(self) -> None:
        frame = np.full((4, 4, 3), 255, dtype=np.uint8)
        benchmark = self.benchmark_type(
            agentview_occlusion={
                "x": 0.25,
                "y": 0.25,
                "width": 0.5,
                "height": 0.5,
            }
        )

        recorded = benchmark._extract_frame({"frame": frame})

        self.assertEqual(int(recorded[1, 1, 0]), 0)
        np.testing.assert_array_equal(frame, np.full((4, 4, 3), 255, dtype=np.uint8))

    def test_preserves_missing_frames(self) -> None:
        benchmark = self.benchmark_type()

        self.assertIsNone(benchmark._extract_frame(None))

    def _external_benchmark(self, directory):
        import json
        from pathlib import Path
        candidate = Path(directory) / "candidate.json"
        candidate.write_text(json.dumps({"task_id": 0, "model_xml": "<mujoco/>"}), encoding="utf-8")
        benchmark = self.benchmark_type(
            suite="libero_object",
            external_reset={"candidate": str(candidate),
                            "metadata_out": str(Path(directory) / "external_reset.json")})
        frames = []
        benchmark._recorder = types.SimpleNamespace(record_video=frames.append)
        benchmark._env = None
        benchmark._current_task_id = None
        benchmark.absolute_action = False
        env = types.SimpleNamespace(robots=[])
        benchmark._make_env = lambda task: env
        benchmark._asset_roots = lambda: {}
        return benchmark, env, frames

    def test_external_reset_restores_instead_of_upstream_and_records_hashes(self) -> None:
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from robot_debug import external_reset as kernel

        calls = []
        settled = np.full((4, 4, 3), 7, dtype=np.uint8)

        def restore(env, candidate, resolved):
            calls.append((env, candidate["task_id"], resolved))
            return {"observation": {"frame": settled},
                    "reset_metadata": {"state_sha256": "abc", "restoration_verified": False}}

        with tempfile.TemporaryDirectory() as directory:
            benchmark, env, frames = self._external_benchmark(directory)
            with patch.object(kernel, "validate_external_reset", side_effect=lambda value: value), \
                    patch.object(kernel, "resolve_external_assets", return_value={"xml": "ok"}) as resolve, \
                    patch.object(kernel, "restore_external_reset", side_effect=restore):
                task = {"task_id": 0, "task_obj": object(), "name": "task 0"}
                self.assertIs(benchmark.reset(task)["frame"], settled)
                benchmark.reset(task)
            self.assertEqual(len(calls), 2)
            self.assertIs(calls[0][0], env)
            self.assertEqual(resolve.call_count, 1)
            self.assertEqual(len(frames), 2)
            self.assertTrue(all(np.array_equal(frame, settled) for frame in frames))
            records = json.loads((Path(directory) / "external_reset.json").read_text(encoding="utf-8"))
            self.assertEqual([record["state_sha256"] for record in records], ["abc", "abc"])

    def test_external_reset_rejects_task_mismatch_and_bad_config(self) -> None:
        import tempfile
        from unittest.mock import patch
        from robot_debug import external_reset as kernel

        with tempfile.TemporaryDirectory() as directory:
            benchmark, _env, _frames = self._external_benchmark(directory)
            with patch.object(kernel, "validate_external_reset", side_effect=lambda value: value):
                with self.assertRaises(kernel.ExternalResetError):
                    benchmark.reset({"task_id": 1, "task_obj": object(), "name": "task 1"})
        for bad in ({"candidate": "a"}, {"candidate": "", "metadata_out": "b"}, "path",
                    {"candidate": "a", "metadata_out": "b", "extra": "c"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.benchmark_type(suite="libero_object", external_reset=bad)

    def test_without_external_reset_upstream_reset_is_used(self) -> None:
        benchmark = self.benchmark_type(suite="libero_object")
        self.assertIsNone(benchmark.external_reset)

    # ---- M6: wrist occlusion and scalar image families -------------------

    @staticmethod
    def _raw(value_agent=120, value_wrist=60, frame=None):
        agentview = np.full((8, 8, 3), value_agent, dtype=np.uint8)
        return {"agentview": agentview, "wrist": np.full((8, 8, 3), value_wrist, dtype=np.uint8),
                "states": np.array([1.0]), "frame": agentview.copy() if frame is None else frame}

    def _without_wrist(self):
        original = FakeLIBEROBenchmark.make_obs

        def no_wrist(self_, raw_obs, task):
            observation = original(self_, raw_obs, task)
            del observation["images"]["wrist"]
            return observation

        FakeLIBEROBenchmark.make_obs = no_wrist
        self.addCleanup(setattr, FakeLIBEROBenchmark, "make_obs", original)

    def test_new_options_are_not_forwarded_upstream(self) -> None:
        benchmark = self.benchmark_type(
            suite="libero_object", seed=7,
            wrist_occlusion={"x": 0.0, "y": 0.0, "width": 0.5, "height": 0.5},
            image_perturbation={"kind": "blur", "severity": 0.4})

        self.assertEqual({"suite": "libero_object", "seed": 7, "send_wrist_image": False,
                          "send_state": False}, benchmark.upstream_kwargs)
        self.assertTrue(benchmark.wrist_occlusion.enabled)
        self.assertEqual(("blur", 0.4), (benchmark.image_perturbation.kind, benchmark.image_perturbation.severity))

    def test_defaults_disable_both_new_features(self) -> None:
        benchmark = self.benchmark_type()
        self.assertFalse(benchmark.wrist_occlusion.enabled)
        self.assertIsNone(benchmark.image_perturbation)

    def test_invalid_new_options_are_rejected(self) -> None:
        for kwargs in (
            {"wrist_occlusion": {"x": 0.9, "y": 0.0, "width": 0.5, "height": 0.5}},
            {"image_perturbation": {"kind": "sepia", "severity": 0.5}},
            {"image_perturbation": {"kind": "blur", "severity": 1.5}},
            {"image_perturbation": {"kind": "blur"}},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises((TypeError, ValueError)):
                self.benchmark_type(**kwargs)

    def test_wrist_occlusion_masks_only_the_wrist_view(self) -> None:
        raw = self._raw()
        benchmark = self.benchmark_type(
            wrist_occlusion={"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0})

        observation = benchmark.make_obs(raw, {"name": "t"})

        self.assertTrue((observation["images"]["wrist"] == 0).all())
        np.testing.assert_array_equal(observation["images"]["agentview"], raw["agentview"])
        self.assertTrue((raw["wrist"] == 60).all())

    def test_wrist_and_agentview_occlusions_are_independent(self) -> None:
        raw = self._raw()
        benchmark = self.benchmark_type(
            agentview_occlusion={"x": 0.5, "y": 0.0, "width": 0.5, "height": 0.5},
            wrist_occlusion={"x": 0.0, "y": 0.5, "width": 0.5, "height": 0.5})

        images = benchmark.make_obs(raw, {"name": "t"})["images"]

        self.assertTrue((images["agentview"][:4, 4:] == 0).all())
        self.assertTrue((images["agentview"][4:, :4] == 120).all())
        self.assertTrue((images["wrist"][4:, :4] == 0).all())
        self.assertTrue((images["wrist"][:4, 4:] == 60).all())

    def test_wrist_occlusion_without_a_wrist_image_fails_closed(self) -> None:
        benchmark = self.benchmark_type(
            wrist_occlusion={"x": 0.0, "y": 0.0, "width": 0.5, "height": 0.5})
        self._without_wrist()
        with self.assertRaisesRegex(ValueError, "wrist"):
            benchmark.make_obs(self._raw(), {"name": "t"})

    def test_scalar_family_perturbs_both_cameras_and_keeps_state(self) -> None:
        for kind in ("darken", "noise", "blur", "contrast"):
            raw = self._raw()
            raw["agentview"][::2] = 255  # give blur and contrast something to act on
            raw["wrist"][::2] = 255
            benchmark = self.benchmark_type(seed=7, image_perturbation={"kind": kind, "severity": 0.6})

            observation = benchmark.make_obs(raw, {"name": "t"})

            with self.subTest(kind=kind):
                self.assertFalse(np.array_equal(observation["images"]["agentview"], raw["agentview"]))
                self.assertFalse(np.array_equal(observation["images"]["wrist"], raw["wrist"]))
                self.assertIs(observation["states"], raw["states"])

    def test_zero_severity_leaves_both_cameras_identical(self) -> None:
        raw = self._raw()
        benchmark = self.benchmark_type(image_perturbation={"kind": "noise", "severity": 0.0})
        observation = benchmark.make_obs(raw, {"name": "t"})
        np.testing.assert_array_equal(observation["images"]["agentview"], raw["agentview"])
        np.testing.assert_array_equal(observation["images"]["wrist"], raw["wrist"])

    def test_the_scalar_family_runs_before_the_occlusion(self) -> None:
        raw = self._raw()
        benchmark = self.benchmark_type(
            agentview_occlusion={"x": 0.0, "y": 0.0, "width": 0.5, "height": 0.5},
            wrist_occlusion={"x": 0.0, "y": 0.0, "width": 0.5, "height": 0.5},
            image_perturbation={"kind": "noise", "severity": 1.0})

        images = benchmark.make_obs(raw, {"name": "t"})["images"]

        for camera in ("agentview", "wrist"):
            self.assertTrue((images[camera][:4, :4] == 0).all(), camera)
            self.assertFalse((images[camera][4:, 4:] == raw[camera][4:, 4:]).all(), camera)

    def test_noise_is_deterministic_per_step_and_episode_and_seed(self) -> None:
        task = {"name": "t", "task_id": 0}

        def episode(benchmark, steps=3):
            benchmark._begin_episode()
            return [benchmark.make_obs(self._raw(), task)["images"] for _ in range(steps)]

        spec = {"kind": "noise", "severity": 0.5}
        first = self.benchmark_type(seed=7, image_perturbation=spec)
        a = episode(first)
        b = episode(first)  # second episode in the same process
        replay = episode(self.benchmark_type(seed=7, image_perturbation=spec))
        other_seed = episode(self.benchmark_type(seed=8, image_perturbation=spec))

        for camera in ("agentview", "wrist"):
            self.assertFalse(np.array_equal(a[0][camera], a[1][camera]), "steps differ")
            self.assertFalse(np.array_equal(a[0][camera], b[0][camera]), "episodes differ")
            for step in range(3):
                np.testing.assert_array_equal(a[step][camera], replay[step][camera])
                self.assertFalse(np.array_equal(a[step][camera], other_seed[step][camera]))

    def test_cameras_get_independent_noise(self) -> None:
        raw = self._raw(value_agent=100, value_wrist=100)
        benchmark = self.benchmark_type(seed=7, image_perturbation={"kind": "noise", "severity": 0.5})
        benchmark._begin_episode()
        images = benchmark.make_obs(raw, {"name": "t"})["images"]
        self.assertFalse(np.array_equal(images["agentview"], images["wrist"]))

    def test_a_reset_restarts_the_step_counter(self) -> None:
        benchmark = self.benchmark_type(seed=7, image_perturbation={"kind": "noise", "severity": 0.5})
        benchmark._begin_episode()
        first = benchmark.make_obs(self._raw(), {"name": "t"})["images"]["agentview"]
        benchmark.make_obs(self._raw(), {"name": "t"})
        # Rewind to the same episode index: the next first observation matches the first one.
        benchmark._episode_index -= 1
        benchmark._begin_episode()
        again = benchmark.make_obs(self._raw(), {"name": "t"})["images"]["agentview"]
        np.testing.assert_array_equal(first, again)

    def test_reset_begins_a_new_episode_through_the_upstream_reset(self) -> None:
        calls = []
        FakeLIBEROBenchmark.reset = lambda self_, task: calls.append(task) or "obs"
        self.addCleanup(delattr, FakeLIBEROBenchmark, "reset")
        benchmark = self.benchmark_type(seed=7, image_perturbation={"kind": "noise", "severity": 0.5})
        benchmark.make_obs(self._raw(), {"name": "t"})
        self.assertEqual("obs", benchmark.reset({"task_id": 0}))
        self.assertEqual(1, len(calls))
        self.assertEqual(0, benchmark._episode_index)
        self.assertEqual(0, benchmark._obs_step)

    def test_recorded_frame_shows_the_perturbed_agentview_the_policy_saw(self) -> None:
        for kind in ("darken", "noise", "blur", "contrast"):
            benchmark = self.benchmark_type(
                seed=7,
                agentview_occlusion={"x": 0.0, "y": 0.0, "width": 0.25, "height": 0.25},
                image_perturbation={"kind": kind, "severity": 0.7})
            benchmark._begin_episode()
            raw = self._raw()
            raw["agentview"][::2] = 255
            raw["frame"] = raw["agentview"].copy()
            for step in range(3):
                policy = benchmark.make_obs(raw, {"name": "t"})["images"]["agentview"]
                frame = benchmark._extract_frame(raw)
                with self.subTest(kind=kind, step=step):
                    np.testing.assert_array_equal(policy, frame)
                    self.assertFalse(np.array_equal(frame, raw["frame"]))
            np.testing.assert_array_equal(raw["frame"][::2], np.full((4, 8, 3), 255, dtype=np.uint8))

    def test_frames_are_unchanged_without_a_scalar_family(self) -> None:
        benchmark = self.benchmark_type(wrist_occlusion={"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0})
        frame = np.full((4, 4, 3), 99, dtype=np.uint8)
        np.testing.assert_array_equal(benchmark._extract_frame({"frame": frame}), frame)

    def test_missing_wrist_image_with_a_scalar_family_fails_closed(self) -> None:
        benchmark = self.benchmark_type(image_perturbation={"kind": "darken", "severity": 0.5})
        self._without_wrist()
        with self.assertRaisesRegex(ValueError, "wrist"):
            benchmark.make_obs(self._raw(), {"name": "t"})

    def test_perturbation_record_describes_the_replay_spec(self) -> None:
        self.assertIsNone(self.benchmark_type(seed=7).perturbation_record())
        benchmark = self.benchmark_type(
            seed=7,
            wrist_occlusion={"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
            image_perturbation={"kind": "contrast", "severity": 0.5})
        record = benchmark.perturbation_record()
        self.assertEqual({"kind": "contrast", "severity": 0.5,
                          "physical": {"name": "contrast_factor", "value": 0.55}},
                         record["image_perturbation"])
        self.assertEqual(1.0, record["wrist_occlusion"]["width"])
        self.assertEqual([0, 0, 0], record["wrist_occlusion"]["color"])
        self.assertEqual(7, record["seed"])
        import json
        json.dumps(record)

    def test_external_reset_sidecar_records_the_perturbation_only_when_configured(self) -> None:
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from robot_debug import external_reset as kernel
        from robot_debug.image_perturbation import ScalarPerturbation

        def restore(env, candidate, resolved):
            return {"observation": {"frame": np.zeros((4, 4, 3), dtype=np.uint8)},
                    "reset_metadata": {"state_sha256": "abc"}}

        with tempfile.TemporaryDirectory() as directory:
            benchmark, _env, _frames = self._external_benchmark(directory)
            with patch.object(kernel, "validate_external_reset", side_effect=lambda value: value), \
                    patch.object(kernel, "resolve_external_assets", return_value={}), \
                    patch.object(kernel, "restore_external_reset", side_effect=restore):
                task = {"task_id": 0, "task_obj": object(), "name": "task 0"}
                benchmark.reset(task)
                benchmark.image_perturbation = ScalarPerturbation("blur", 0.4)
                benchmark.reset(task)
            records = json.loads((Path(directory) / "external_reset.json").read_text(encoding="utf-8"))
            self.assertEqual({"state_sha256": "abc"}, records[0])
            self.assertEqual("blur", records[1]["perturbation"]["image_perturbation"]["kind"])

    # ---- M6: per-camera perturbation probe --------------------------------

    def _probe_benchmark(self, directory, **options):
        from pathlib import Path
        path = Path(directory) / "case.camera_probe.json"
        options.setdefault("image_perturbation", {"kind": "darken", "severity": 0.5})
        return self.benchmark_type(seed=7, camera_probe=str(path), **options), path

    def _drive(self, benchmark, steps, raw=None):
        benchmark._begin_episode()
        for _ in range(steps):
            benchmark.make_obs(raw or self._raw(), {"name": "t"})

    @staticmethod
    def _load(path):
        import json
        return json.loads(path.read_text(encoding="utf-8"))

    def test_probe_samples_the_first_observation_and_every_40th_step_to_280(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            benchmark, path = self._probe_benchmark(directory)
            self._drive(benchmark, 300)
            episode = self._load(path)["episodes"][0]
            self.assertEqual([0, 40, 80, 120, 160, 200, 240, 280], [s["step"] for s in episode["samples"]])
            self.assertEqual(0, episode["episode_index"])

    def test_probe_records_perturbed_and_unperturbed_statistics_per_camera(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            benchmark, path = self._probe_benchmark(directory)
            self._drive(benchmark, 1)
            document = self._load(path)
            sample = document["episodes"][0]["samples"][0]
            self.assertEqual(1, document["schema_version"])
            self.assertEqual("darken", document["perturbation"]["image_perturbation"]["kind"])
            self.assertEqual(7, document["perturbation"]["seed"])
            for camera, value in (("agentview", 120), ("wrist", 60)):
                with self.subTest(camera=camera):
                    stats = sample[camera]
                    self.assertAlmostEqual(float(value), stats["unperturbed_mean"], places=3)
                    self.assertAlmostEqual(0.0, stats["unperturbed_std"], places=3)
                    self.assertAlmostEqual(round(value * 0.525), stats["perturbed_mean"], places=3)
                    self.assertAlmostEqual(0.0, stats["perturbed_std"], places=3)

    def test_probe_sees_the_final_policy_image_including_occlusion(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            benchmark, path = self._probe_benchmark(
                directory, image_perturbation=None,
                wrist_occlusion={"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0})
            self._drive(benchmark, 1)
            sample = self._load(path)["episodes"][0]["samples"][0]
            self.assertEqual(0.0, sample["wrist"]["perturbed_mean"])
            self.assertEqual(60.0, sample["wrist"]["unperturbed_mean"])
            self.assertEqual(sample["agentview"]["unperturbed_mean"], sample["agentview"]["perturbed_mean"])

    def test_probe_is_not_written_without_a_path_or_without_a_new_perturbation(self) -> None:
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            no_path = self.benchmark_type(seed=7, image_perturbation={"kind": "darken", "severity": 0.5})
            self._drive(no_path, 3)
            path = Path(directory) / "p.json"
            for options in (
                {},
                {"agentview_occlusion": {"x": 0.0, "y": 0.0, "width": 0.5, "height": 0.5}},
                {"image_perturbation": {"kind": "blur", "severity": 0.0}},
            ):
                with self.subTest(options=options):
                    benchmark = self.benchmark_type(seed=7, camera_probe=str(path), **options)
                    self._drive(benchmark, 3)
                    self.assertFalse(path.exists())
            self.assertEqual([], list(Path(directory).iterdir()))

    def test_probe_file_is_replaced_atomically_and_updates_as_the_episode_runs(self) -> None:
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            benchmark, path = self._probe_benchmark(directory)
            benchmark._begin_episode()
            benchmark.make_obs(self._raw(), {"name": "t"})
            self.assertEqual(1, len(self._load(path)["episodes"][0]["samples"]))
            for _ in range(40):
                benchmark.make_obs(self._raw(), {"name": "t"})
            self.assertEqual(2, len(self._load(path)["episodes"][0]["samples"]))
            self.assertEqual([path.name], [p.name for p in Path(directory).iterdir()])

    def test_each_episode_gets_its_own_record(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            benchmark, path = self._probe_benchmark(directory)
            self._drive(benchmark, 2)
            self._drive(benchmark, 2)
            episodes = self._load(path)["episodes"]
            self.assertEqual([0, 1], [e["episode_index"] for e in episodes])

    def test_probe_size_is_bounded_and_marked_truncated(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            benchmark, path = self._probe_benchmark(directory)
            for _ in range(60):
                self._drive(benchmark, 300)
            document = self._load(path)
            self.assertLessEqual(path.stat().st_size, 16 * 1024)
            self.assertTrue(document["truncated"])
            self.assertGreaterEqual(len(document["episodes"]), 3)

    def test_untruncated_probe_has_no_truncated_flag_and_is_small(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            benchmark, path = self._probe_benchmark(directory)
            self._drive(benchmark, 300)
            self.assertNotIn("truncated", self._load(path))
            self.assertLess(path.stat().st_size, 4096)

    def test_an_unwritable_probe_never_breaks_the_episode(self) -> None:
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            blocker = Path(directory) / "file"
            blocker.write_text("x", encoding="utf-8")
            benchmark = self.benchmark_type(
                seed=7, camera_probe=str(blocker / "child.json"),
                image_perturbation={"kind": "darken", "severity": 0.5})
            self._drive(benchmark, 2)

    def test_invalid_probe_paths_are_rejected(self) -> None:
        for value in ("", 3, ["a"]):
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                self.benchmark_type(camera_probe=value, image_perturbation={"kind": "darken", "severity": 0.5})

    def test_probe_does_not_change_the_policy_observation(self) -> None:
        import tempfile
        spec = {"kind": "noise", "severity": 0.5}
        with tempfile.TemporaryDirectory() as directory:
            probed, _path = self._probe_benchmark(directory, image_perturbation=spec)
            plain = self.benchmark_type(seed=7, image_perturbation=spec)
            probed._begin_episode()
            plain._begin_episode()
            for _ in range(3):
                a = probed.make_obs(self._raw(), {"name": "t"})["images"]
                b = plain.make_obs(self._raw(), {"name": "t"})["images"]
                for camera in ("agentview", "wrist"):
                    np.testing.assert_array_equal(a[camera], b[camera])


if __name__ == "__main__":
    unittest.main()
