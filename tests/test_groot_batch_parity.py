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


class FakeDecodeStep:
    """Mirrors GrootN17ActionDecodeStep: the LIBERO gripper rounding hangs off one attribute."""

    def __init__(self, transform="libero") -> None:
        self.action_decode_transform = transform


class FakeUnpackStep:
    """Mirrors the fallback GrootActionUnpackUnnormalizeStep flag."""

    def __init__(self, enabled=True) -> None:
        self.libero_gripper_action = enabled


class FakeServer:
    """Action = per-item noise + that item's own state, so routing mistakes are visible.

    The last dimension is the gripper; like the real postprocessor it is turned into
    ``-sign(2g - 1)`` as the final step unless the rounding attribute is switched off.
    """

    def __init__(self, torch, *, swap_batch_states: bool = False, scale: float = 1.0, wobble: float = 0.0,
                 gripper=None, steps=None) -> None:
        self.torch = torch
        self.swap = swap_batch_states
        self.scale = scale
        self.wobble = wobble
        self.gripper = gripper  # (value for single calls, value for batched calls) before rounding
        self._postprocess = types.SimpleNamespace(steps=[FakeDecodeStep()] if steps is None else steps)

    def _rounding_active(self) -> bool:
        return any(
            getattr(step, "action_decode_transform", None) or getattr(step, "libero_gripper_action", False)
            for step in self._postprocess.steps
        )

    def _finish(self, chunk, batched: bool):
        chunk = chunk.copy()
        if self.gripper is not None:
            chunk[..., -1] = self.gripper[1 if batched else 0]
        if self._rounding_active():
            chunk[..., -1] = -np.sign(2.0 * chunk[..., -1] - 1.0)
        return chunk.astype(np.float32)

    def predict(self, obs, ctx):
        noise = self.torch.randn((1, 3, 7))
        return {"actions": self._finish(noise + obs["states"][None][:, None, :1] * self.scale, False)[0]}

    def predict_batch(self, obs_batch, ctx_batch):
        noise = self.torch.randn((len(obs_batch), 3, 7))
        states = np.stack([obs["states"] for obs in obs_batch])
        if self.swap:
            states = states[::-1]
        chunk = self._finish(noise + states[:, None, :1] * self.scale + self.wobble, True)
        return [{"actions": chunk[i]} for i in range(len(obs_batch))]


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

    def isolate(self, server):
        return lambda: self.module.gripper_rounding_disabled(server._postprocess)

    def run_parity(self, server, per_item=True, tolerance=0.05):
        return self.module.run_parity(
            server, self.observations, noise=self.noise, isolate=self.isolate(server),
            per_item=per_item, tolerance=tolerance,
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

    # -- D1: judged before gripper rounding -------------------------------------------

    def test_parity_is_judged_before_the_gripper_rounding_on_every_dimension(self) -> None:
        # Pre-rounding gripper 0.505 (single) vs 0.495 (batch): 0.01 apart, but the sign
        # step turns that into a full flip. It must pass, and the flip is only reported.
        result = self.run_parity(FakeServer(self.torch, gripper=(0.505, 0.495)))
        self.assertTrue(result["passed"], result)
        self.assertTrue(result["compared_before_gripper_rounding"])
        self.assertAlmostEqual(0.01, result["per_dim_max_abs_diff"][-1], places=5)
        self.assertEqual(12, result["gripper_flips_after_rounding"])  # 3 chunk steps x 4 checks
        self.assertLessEqual(result["max_abs_diff"], 0.05)
        for check in (v for k, v in result["checks"].items() if k.startswith("batch_")):
            self.assertEqual(7, len(check["per_dim_max_abs_diff"]))
            self.assertEqual(3, check["gripper_flips_after_rounding"])

    def test_a_gripper_difference_beyond_tolerance_before_rounding_fails_even_if_rounded_values_match(self) -> None:
        # Both round to the same sign, but the underlying values are 0.2 apart.
        result = self.run_parity(FakeServer(self.torch, gripper=(0.9, 0.7)))
        self.assertFalse(result["passed"])
        self.assertEqual(0, result["gripper_flips_after_rounding"])
        self.assertAlmostEqual(0.2, result["per_dim_max_abs_diff"][-1], places=5)
        self.assertFalse(result["checks"]["batch_ab_item0_vs_single_a"]["passed"])

    def test_non_gripper_dimensions_are_gated_too(self) -> None:
        result = self.run_parity(FakeServer(self.torch, wobble=0.06))
        self.assertFalse(result["passed"])
        self.assertGreater(max(result["per_dim_max_abs_diff"][:-1]), 0.05)

    def test_rounding_is_restored_after_every_isolated_call(self) -> None:
        server = FakeServer(self.torch, steps=[FakeDecodeStep(), FakeUnpackStep()])
        self.run_parity(server)
        self.assertEqual("libero", server._postprocess.steps[0].action_decode_transform)
        self.assertTrue(server._postprocess.steps[1].libero_gripper_action)

    def test_isolation_switches_each_known_step_kind_off_only_inside_the_context(self) -> None:
        steps = [FakeDecodeStep(), FakeUnpackStep(), types.SimpleNamespace(other=1)]
        post = types.SimpleNamespace(steps=steps)
        with self.module.gripper_rounding_disabled(post) as count:
            self.assertEqual(2, count)
            self.assertIsNone(steps[0].action_decode_transform)
            self.assertFalse(steps[1].libero_gripper_action)
            self.assertEqual(1, steps[2].other)
        self.assertEqual("libero", steps[0].action_decode_transform)
        self.assertTrue(steps[1].libero_gripper_action)

    def test_isolation_restores_the_steps_when_the_call_raises(self) -> None:
        step = FakeDecodeStep()
        with self.assertRaises(RuntimeError):
            with self.module.gripper_rounding_disabled(types.SimpleNamespace(steps=[step])):
                raise RuntimeError("model call failed")
        self.assertEqual("libero", step.action_decode_transform)

    def test_a_postprocessor_that_cannot_be_isolated_is_an_error_not_a_pass(self) -> None:
        for post in (types.SimpleNamespace(steps=[]), types.SimpleNamespace(steps=[types.SimpleNamespace()]),
                     types.SimpleNamespace()):
            with self.assertRaisesRegex(RuntimeError, "cannot isolate"):
                with self.module.gripper_rounding_disabled(post):
                    pass

    def test_without_active_rounding_the_flip_count_is_zero(self) -> None:
        result = self.run_parity(FakeServer(self.torch, steps=[FakeDecodeStep(transform=None)]))
        self.assertTrue(result["passed"])
        self.assertEqual(0, result["gripper_flips_after_rounding"])

    def test_per_dim_helpers(self) -> None:
        left = np.zeros((2, 3, 4))
        right = left.copy()
        right[1, 2, 3] = 0.5
        right[0, 0, 0] = -0.25
        self.assertEqual([0.25, 0.0, 0.0, 0.5], self.module.per_dim_max_abs_diff(left, right))
        self.assertEqual([float("inf")], self.module.per_dim_max_abs_diff(np.zeros(3), np.zeros(4)))
        a = np.array([[1.0, -1.0]])
        b = np.array([[1.0, 1.0]])
        self.assertEqual(1, self.module.gripper_flips(a, b))
        self.assertEqual(0, self.module.gripper_flips(a, a))

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

        server = FakeServer(self.torch)
        result = self.module.run_parity(
            server, self.observations, noise=seeded, isolate=self.isolate(server), per_item=False
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
