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


if __name__ == "__main__":
    unittest.main()
