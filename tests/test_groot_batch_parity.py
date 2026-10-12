"""Tests for the seeded batch parity check (pure parts; the GPU run is image-only)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
PARITY_PATH = ROOT / "scripts" / "model_servers" / "groot_batch_parity.py"


def load_parity():
    spec = importlib.util.spec_from_file_location("groot_batch_parity_under_test", PARITY_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeGenerator:
    def __init__(self) -> None:
        self.rng = np.random.RandomState(0)

    def manual_seed(self, seed: int) -> None:
        self.rng = np.random.RandomState(seed)


def fake_torch() -> types.SimpleNamespace:
    state = {"global": np.random.RandomState(0)}

    def randn(*size, generator=None, **kwargs):
        shape = tuple(size[0]) if size and isinstance(size[0], (tuple, list)) else tuple(size or kwargs["size"])
        rng = generator.rng if generator is not None else state["global"]
        return rng.standard_normal(shape).astype(np.float32)

    def manual_seed(seed):
        state["global"] = np.random.RandomState(seed)

    return types.SimpleNamespace(
        randn=randn,
        Generator=FakeGenerator,
        cat=lambda values, dim=0: np.concatenate(values, axis=dim),
        manual_seed=manual_seed,
    )


class FakeServer:
    """Action = per-item noise + that item's own state, so routing mistakes are visible."""

    def __init__(self, torch, *, swap_batch_states: bool = False, scale: float = 1.0, wobble: float = 0.0) -> None:
        self.torch = torch
        self.swap = swap_batch_states
        self.scale = scale
        self.wobble = wobble

    def _chunk(self, noise, states):
        return noise + states[:, None, :1] * self.scale

    def predict(self, obs, ctx):
        noise = self.torch.randn((1, 3, 7))
        return {"actions": self._chunk(noise, obs["states"][None])[0].astype(np.float32)}

    def predict_batch(self, obs_batch, ctx_batch):
        noise = self.torch.randn((len(obs_batch), 3, 7))
        states = np.stack([obs["states"] for obs in obs_batch])
        if self.swap:
            states = states[::-1]
        chunk = self._chunk(noise, states) + self.wobble
        return [{"actions": chunk[i].astype(np.float32)} for i in range(len(obs_batch))]


class ParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_parity()

    def setUp(self) -> None:
        self.torch = fake_torch()
        self.observations = self.module.build_observations(image_size=4, state_dim=8)
        self.counter = {}

    def noise(self, offsets):
        self.torch.manual_seed(1234)
        return self.module.per_item_noise(self.torch, 1234, offsets, self.counter)

    def run_parity(self, server, per_item=True, tolerance=0.05):
        return self.module.run_parity(
            server, self.observations, noise=self.noise, per_item=per_item, tolerance=tolerance
        )

    def test_observations_are_fixed_distinct_and_in_harness_format(self) -> None:
        again = self.module.build_observations(image_size=4, state_dim=8)
        a, b = self.observations
        np.testing.assert_array_equal(a["images"]["agentview"], again[0]["images"]["agentview"])
        self.assertFalse(np.array_equal(a["states"], b["states"]))
        self.assertFalse(np.array_equal(a["images"]["wrist"], b["images"]["wrist"]))
        self.assertEqual(np.uint8, a["images"]["agentview"].dtype)
        self.assertEqual((4, 4, 3), a["images"]["agentview"].shape)
        self.assertEqual(np.float32, a["states"].dtype)
        self.assertIn("alphabet soup", a["task_description"])

    def test_correct_batching_passes_all_checks_including_item_one(self) -> None:
        result = self.run_parity(FakeServer(self.torch))
        self.assertTrue(result["passed"], result)
        self.assertEqual(
            {"batch_ab_item0_vs_single_a", "batch_ba_item0_vs_single_b", "batch_ab_item1_vs_single_b",
             "batch_ba_item1_vs_single_a", "single_a_vs_single_b_differ", "shapes_and_dtypes_match"},
            set(result["checks"]),
        )
        self.assertLessEqual(result["max_abs_diff"], 1e-6)
        self.assertGreater(result["observed_distinct_diff"], 0.05)
        self.assertGreater(self.counter["calls"], 0)

    def test_manual_seed_mode_checks_only_item_zero(self) -> None:
        def seeded(offsets):
            self.torch.manual_seed(1234)
            return self.module._null_context()

        result = self.module.run_parity(
            FakeServer(self.torch), self.observations, noise=seeded, per_item=False
        )
        self.assertNotIn("batch_ab_item1_vs_single_b", result["checks"])
        # With a generator whose batched draw starts with the single draw, item 0 matches.
        self.assertTrue(result["passed"], result)

    def test_state_routing_bug_is_detected(self) -> None:
        result = self.run_parity(FakeServer(self.torch, swap_batch_states=True))
        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["batch_ab_item0_vs_single_a"]["passed"])

    def test_difference_within_tolerance_passes_and_beyond_fails(self) -> None:
        within = self.run_parity(FakeServer(self.torch, wobble=0.04))
        self.assertTrue(within["passed"])
        self.assertAlmostEqual(0.04, within["max_abs_diff"], places=4)
        beyond = self.run_parity(FakeServer(self.torch, wobble=0.06))
        self.assertFalse(beyond["passed"])

    def test_an_insensitive_policy_makes_the_check_vacuous_and_fails(self) -> None:
        result = self.run_parity(FakeServer(self.torch, scale=0.0))
        # With identical per-item noise and no state dependence A and B coincide.
        self.assertFalse(result["checks"]["single_a_vs_single_b_differ"]["passed"])
        self.assertFalse(result["passed"])

    def test_shape_or_dtype_mismatch_fails(self) -> None:
        class WrongDtype(FakeServer):
            def predict_batch(self, obs_batch, ctx_batch):
                return [{"actions": r["actions"].astype(np.float64)} for r in super().predict_batch(obs_batch, ctx_batch)]

        result = self.run_parity(WrongDtype(self.torch))
        self.assertFalse(result["dtypes_match"])
        self.assertFalse(result["passed"])

    def test_per_item_noise_gives_each_batch_item_its_own_stable_draw(self) -> None:
        with self.module.per_item_noise(self.torch, 7, [0, 1], self.counter):
            batch = self.torch.randn((2, 3))
        with self.module.per_item_noise(self.torch, 7, [0], self.counter):
            first = self.torch.randn((1, 3))
        with self.module.per_item_noise(self.torch, 7, [1], self.counter):
            second = self.torch.randn((1, 3))
        np.testing.assert_array_equal(batch[0], first[0])
        np.testing.assert_array_equal(batch[1], second[0])
        self.assertFalse(np.array_equal(batch[0], batch[1]))

    def test_per_item_noise_restores_randn_and_ignores_other_shapes(self) -> None:
        original = self.torch.randn
        with self.module.per_item_noise(self.torch, 7, [0, 1], self.counter):
            self.assertIsNot(original, self.torch.randn)
            self.torch.randn((5, 2))  # leading dim does not match the batch: untouched
        self.assertIs(original, self.torch.randn)
        self.assertEqual({}, self.counter)

    def test_max_abs_diff_handles_shape_mismatch(self) -> None:
        self.assertEqual(float("inf"), self.module.max_abs_diff(np.zeros(3), np.zeros(4)))
        self.assertEqual(0.5, self.module.max_abs_diff(np.zeros(3), np.array([0, 0.5, -0.25])))

    def test_result_file_has_verdict_and_maxima_only(self) -> None:
        result = self.run_parity(FakeServer(self.torch))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "out" / "parity.json"
            self.module.write_result(path, result)
            loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(loaded["passed"])
        text = json.dumps(loaded)
        self.assertNotIn("alphabet", text)
        self.assertNotIn("actions", loaded)

    def test_failure_result_records_error_class_and_clipped_message(self) -> None:
        result = self.module.failure_result(
            RuntimeError("x" * 1000), tolerance=0.05, noise_mode="per-item", seed=1
        )
        self.assertFalse(result["passed"])
        self.assertTrue(result["error"].startswith("RuntimeError: x"))
        self.assertLess(len(result["error"]), 330)


class MainTests(unittest.TestCase):
    """``main`` with the model stack replaced: exit codes and the verdict file."""

    def setUp(self) -> None:
        self.module = load_parity()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name) / "parity.json"
        self.torch = fake_torch()
        self.torch.cuda = types.SimpleNamespace(is_available=lambda: False)

    def run_main(self, server_factory):
        class Args:
            def as_dict(self):
                return {}

        config = types.SimpleNamespace(
            output=self.output, tolerance=0.05, seed=1234, noise="per-item",
            image_size=4, state_dim=8, args=Args(),
        )
        server_module = types.ModuleType("faultline_groot_server")
        server_module.FaultlineGrootServer = server_factory
        torch = self.torch
        with mock.patch.dict(sys.modules, {"faultline_groot_server": server_module, "torch": torch}), \
                mock.patch.object(self.module, "_parse", return_value=config):
            return self.module.main([])

    def test_pass_exits_zero_and_writes_the_verdict(self) -> None:
        code = self.run_main(lambda **_kwargs: FakeServer(self.torch))
        self.assertEqual(0, code)
        loaded = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertTrue(loaded["passed"])
        self.assertEqual("per-item", loaded["noise_mode"])
        self.assertGreater(loaded["noise_draws_intercepted"], 0)

    def test_server_construction_failure_exits_one_with_an_error_verdict(self) -> None:
        def broken(**_kwargs):
            raise RuntimeError("could not load")

        self.assertEqual(1, self.run_main(broken))
        loaded = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertFalse(loaded["passed"])
        self.assertIn("could not load", loaded["error"])

    def test_processor_rejection_exits_one(self) -> None:
        class Rejecting(FakeServer):
            def predict_batch(self, obs_batch, ctx_batch):
                raise RuntimeError("GR00T processor rejected a batched input")

        self.assertEqual(1, self.run_main(lambda **_kwargs: Rejecting(self.torch)))
        loaded = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertIn("rejected a batched input", loaded["error"])

    def test_noise_shim_that_never_engages_fails_the_check(self) -> None:
        class NoDraw(FakeServer):
            def predict(self, obs, ctx):
                return {"actions": np.zeros((3, 7), dtype=np.float32) + obs["states"][0]}

            def predict_batch(self, obs_batch, ctx_batch):
                return [{"actions": np.zeros((3, 7), dtype=np.float32) + o["states"][0]} for o in obs_batch]

        self.assertEqual(1, self.run_main(lambda **_kwargs: NoDraw(self.torch)))
        loaded = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertIn("never engaged", loaded["error"])


class SourceContractTests(unittest.TestCase):
    def test_script_is_lf_only_and_does_not_import_the_runtime_package(self) -> None:
        data = PARITY_PATH.read_bytes()
        self.assertNotIn(b"\r\n", data)
        text = data.decode("utf-8")
        self.assertNotIn("robot_debug", text)
        self.assertIn("from faultline_groot_server import FaultlineGrootServer", text)


if __name__ == "__main__":
    unittest.main()
