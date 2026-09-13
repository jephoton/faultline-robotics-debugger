import importlib
import inspect
import sys
import types
import unittest

import numpy as np


class FakeLIBEROBenchmark:
    def __init__(self, **kwargs) -> None:
        self.upstream_kwargs = kwargs

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


if __name__ == "__main__":
    unittest.main()
