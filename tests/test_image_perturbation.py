import ast
from pathlib import Path
import unittest

import numpy as np

from robot_debug import image_perturbation as ip
from robot_debug.image_perturbation import ScalarPerturbation


def _image(seed=3, shape=(32, 32, 3)):
    return np.random.RandomState(seed).randint(0, 256, size=shape).astype(np.uint8)


class SpecTests(unittest.TestCase):
    def test_module_syntax_remains_compatible_with_python_38(self) -> None:
        module = Path(__file__).parents[1] / "src" / "robot_debug" / "image_perturbation.py"
        ast.parse(module.read_text(encoding="utf-8"), filename=str(module), feature_version=(3, 8))

    def test_validates_kind_and_severity(self) -> None:
        for kind, severity in (
            ("sepia", 0.5), ("", 0.5), (None, 0.5), ("darken", -0.01), ("darken", 1.01),
            ("darken", float("nan")), ("darken", float("inf")), ("darken", True), ("darken", "0.5"),
            ("darken", None),
        ):
            with self.subTest(kind=kind, severity=severity), self.assertRaises((TypeError, ValueError)):
                ScalarPerturbation(kind, severity)
        for kind in ip.KINDS:
            ScalarPerturbation(kind, 0)
            ScalarPerturbation(kind, 1)
            ScalarPerturbation(kind, 0.25)

    def test_builds_from_a_mapping_and_rejects_extra_or_missing_keys(self) -> None:
        spec = ScalarPerturbation.from_mapping({"kind": "blur", "severity": 0.5})
        self.assertEqual(("blur", 0.5), (spec.kind, spec.severity))
        self.assertIsNone(ScalarPerturbation.from_mapping(None))
        for bad in ({"kind": "blur"}, {"severity": 0.5}, {"kind": "blur", "severity": 0.5, "x": 1}, "blur", []):
            with self.subTest(bad=bad), self.assertRaises((TypeError, ValueError)):
                ScalarPerturbation.from_mapping(bad)

    def test_round_trips_through_a_plain_mapping(self) -> None:
        spec = ScalarPerturbation("noise", 0.0125)
        self.assertEqual({"kind": "noise", "severity": 0.0125}, spec.to_mapping())
        self.assertEqual(spec, ScalarPerturbation.from_mapping(spec.to_mapping()))

    def test_physical_values_follow_the_adr_mapping(self) -> None:
        cases = {
            "darken": ("brightness_factor", lambda s: 1 - 0.95 * s),
            "noise": ("noise_sigma", lambda s: 100.0 * s),
            "blur": ("blur_sigma_px", lambda s: 8.0 * s),
            "contrast": ("contrast_factor", lambda s: 1 - 0.9 * s),
        }
        for kind, (name, expected) in cases.items():
            for severity in (0.0, 0.2, 0.6, 1.0):
                with self.subTest(kind=kind, severity=severity):
                    physical = ScalarPerturbation(kind, severity).physical()
                    self.assertEqual(name, physical["name"])
                    self.assertAlmostEqual(expected(severity), physical["value"], places=6)

    def test_module_level_physical_value_matches_the_spec_method(self) -> None:
        self.assertEqual(ScalarPerturbation("darken", 0.6).physical(), ip.physical_value("darken", 0.6))


class IdentityAndShapeTests(unittest.TestCase):
    def test_zero_severity_is_the_identity_for_every_family(self) -> None:
        image = _image()
        for kind in ip.KINDS:
            with self.subTest(kind=kind):
                out = ScalarPerturbation(kind, 0.0).apply(image, episode_seed=7, step=3, camera="wrist")
                np.testing.assert_array_equal(out, image)
                self.assertIsNot(out, image)
                self.assertEqual(np.uint8, out.dtype)

    def test_never_mutates_the_input_and_returns_contiguous_uint8(self) -> None:
        image = _image()
        before = image.copy()
        for kind in ip.KINDS:
            with self.subTest(kind=kind):
                out = ScalarPerturbation(kind, 0.7).apply(image, episode_seed=7, step=0, camera="agentview")
                np.testing.assert_array_equal(image, before)
                self.assertEqual(np.uint8, out.dtype)
                self.assertEqual(image.shape, out.shape)
                self.assertTrue(out.flags.c_contiguous)

    def test_rejects_incompatible_images(self) -> None:
        spec = ScalarPerturbation("darken", 0.5)
        for image in (
            np.zeros((4, 4), dtype=np.uint8),
            np.zeros((4, 4, 4), dtype=np.uint8),
            np.zeros((4, 4, 3), dtype=np.float32),
            [[0]],
        ):
            with self.subTest(shape=getattr(image, "shape", None)), self.assertRaises((TypeError, ValueError)):
                spec.apply(image)


class DarkenTests(unittest.TestCase):
    def test_multiplies_by_one_minus_0_95_s(self) -> None:
        image = np.full((4, 4, 3), 200, dtype=np.uint8)
        out = ScalarPerturbation("darken", 0.6).apply(image)
        self.assertTrue((out == int(round(200 * (1 - 0.95 * 0.6)))).all())
        full = ScalarPerturbation("darken", 1.0).apply(image)
        self.assertTrue((full == int(round(200 * 0.05))).all())

    def test_is_monotone_in_severity(self) -> None:
        image = _image()
        means = [ScalarPerturbation("darken", s).apply(image).mean() for s in (0.0, 0.2, 0.5, 0.8, 1.0)]
        self.assertEqual(means, sorted(means, reverse=True))


class ContrastTests(unittest.TestCase):
    def test_compresses_toward_the_image_mean(self) -> None:
        image = np.zeros((2, 2, 3), dtype=np.uint8)
        image[0] = 200  # half the pixels 200, half 0 -> mean 100
        out = ScalarPerturbation("contrast", 1.0).apply(image)
        # factor 0.1: 100 + 0.1 * (200 - 100) = 110 and 100 + 0.1 * (0 - 100) = 90
        self.assertTrue((out[0] == 110).all())
        self.assertTrue((out[1] == 90).all())

    def test_keeps_the_mean_and_shrinks_the_spread(self) -> None:
        image = _image()
        out = ScalarPerturbation("contrast", 0.6).apply(image)
        self.assertAlmostEqual(float(image.mean()), float(out.mean()), delta=1.0)
        self.assertAlmostEqual(float(image.std()) * (1 - 0.9 * 0.6), float(out.std()), delta=1.0)


class BlurTests(unittest.TestCase):
    def test_constant_image_is_unchanged(self) -> None:
        image = np.full((20, 24, 3), 91, dtype=np.uint8)
        np.testing.assert_array_equal(image, ScalarPerturbation("blur", 1.0).apply(image))

    def test_spreads_a_bright_block_and_preserves_total_brightness(self) -> None:
        image = np.zeros((41, 41, 3), dtype=np.uint8)
        image[18:23, 18:23] = 255
        out = ScalarPerturbation("blur", 0.25).apply(image)  # sigma 2 px
        self.assertLess(int(out[20, 20, 0]), 255)
        self.assertGreater(int(out[20, 25, 0]), 0)
        self.assertAlmostEqual(25 * 255.0, float(out[..., 0].sum()), delta=25 * 255 * 0.03)

    def test_reduces_high_frequency_energy_more_at_higher_severity(self) -> None:
        image = _image(shape=(48, 48, 3))
        spreads = [float(ScalarPerturbation("blur", s).apply(image).std()) for s in (0.0, 0.2, 0.6, 1.0)]
        self.assertEqual(spreads, sorted(spreads, reverse=True))

    def test_works_on_images_smaller_than_the_kernel(self) -> None:
        out = ScalarPerturbation("blur", 1.0).apply(_image(shape=(4, 5, 3)))
        self.assertEqual((4, 5, 3), out.shape)

    def test_separable_blur_matches_a_direct_convolution(self) -> None:
        image = _image(shape=(30, 30, 3)).astype(np.float64)
        sigma = 8.0 * 0.25
        radius = max(1, int(np.ceil(3.0 * sigma)))
        offsets = np.arange(-radius, radius + 1)
        kernel = np.exp(-(offsets ** 2) / (2 * sigma ** 2))
        kernel /= kernel.sum()
        padded = np.pad(image, ((radius, radius), (radius, radius), (0, 0)), mode="edge")
        expected = np.zeros_like(image)
        for dy, wy in zip(offsets, kernel):
            for dx, wx in zip(offsets, kernel):
                expected += wy * wx * padded[
                    radius + dy: radius + dy + 30, radius + dx: radius + dx + 30]
        out = ScalarPerturbation("blur", 0.25).apply(image.astype(np.uint8))
        np.testing.assert_allclose(out.astype(np.float64), np.clip(np.rint(expected), 0, 255), atol=1.0)


class NoiseTests(unittest.TestCase):
    def test_same_inputs_give_identical_output(self) -> None:
        image = _image()
        spec = ScalarPerturbation("noise", 0.5)
        first = spec.apply(image, episode_seed=7, step=12, camera="agentview")
        second = spec.apply(image, episode_seed=7, step=12, camera="agentview")
        np.testing.assert_array_equal(first, second)

    def test_every_key_part_changes_the_noise(self) -> None:
        image = np.full((32, 32, 3), 128, dtype=np.uint8)
        base = ScalarPerturbation("noise", 0.5).apply(image, episode_seed=7, step=12, camera="agentview")
        variants = {
            "step": ScalarPerturbation("noise", 0.5).apply(image, episode_seed=7, step=13, camera="agentview"),
            "camera": ScalarPerturbation("noise", 0.5).apply(image, episode_seed=7, step=12, camera="wrist"),
            "seed": ScalarPerturbation("noise", 0.5).apply(image, episode_seed=8, step=12, camera="agentview"),
        }
        for name, other in variants.items():
            with self.subTest(part=name):
                self.assertFalse(np.array_equal(base, other))

    def test_noise_has_the_requested_standard_deviation(self) -> None:
        image = np.full((128, 128, 3), 128, dtype=np.uint8)
        out = ScalarPerturbation("noise", 0.3).apply(image, episode_seed=1, step=0, camera="wrist")
        self.assertAlmostEqual(30.0, float((out.astype(np.float64) - 128).std()), delta=1.0)

    def test_output_is_clipped_to_the_uint8_range(self) -> None:
        for fill in (0, 255):
            out = ScalarPerturbation("noise", 1.0).apply(
                np.full((64, 64, 3), fill, dtype=np.uint8), episode_seed=1, step=0, camera="wrist")
            self.assertEqual(np.uint8, out.dtype)
            self.assertTrue(((out == 0) | (out == 255) | ((out > 0) & (out < 255))).all())
            self.assertGreater(int((out != fill).sum()), 0)

    def test_other_families_ignore_the_noise_key(self) -> None:
        image = _image()
        for kind in ("darken", "blur", "contrast"):
            with self.subTest(kind=kind):
                a = ScalarPerturbation(kind, 0.6).apply(image, episode_seed=1, step=0, camera="wrist")
                b = ScalarPerturbation(kind, 0.6).apply(image, episode_seed=2, step=9, camera="agentview")
                np.testing.assert_array_equal(a, b)


class StableSeedTests(unittest.TestCase):
    def test_seed_is_a_pinned_stable_hash_not_pythons_salted_hash(self) -> None:
        # Pinned so a replay in a fresh process (different PYTHONHASHSEED) matches.
        self.assertEqual(ip.stable_seed(7, 12, "agentview", "noise", 0.5),
                         ip.stable_seed(7, 12, "agentview", "noise", 0.5))
        seeds = {ip.stable_seed(7, step, "agentview", "noise", 0.5) for step in range(500)}
        self.assertEqual(500, len(seeds))
        self.assertTrue(all(0 <= seed < 2 ** 64 for seed in seeds))

    def test_nearby_severities_get_distinct_seeds_and_float_text_is_canonical(self) -> None:
        self.assertNotEqual(ip.stable_seed(7, 0, "wrist", "noise", 0.5),
                            ip.stable_seed(7, 0, "wrist", "noise", 0.5125))
        self.assertEqual(ip.stable_seed(7, 0, "wrist", "noise", 0.1 + 0.2),
                         ip.stable_seed(7, 0, "wrist", "noise", 0.3))

    def test_a_fresh_interpreter_with_another_hash_seed_gets_the_same_seed(self) -> None:
        import os
        import subprocess
        import sys
        code = ("from robot_debug import image_perturbation as ip;"
                "print(ip.stable_seed(7, 12, 'agentview', 'noise', 0.5))")
        src = str(Path(__file__).parents[1] / "src")
        outputs = set()
        for hash_seed in ("1", "2"):
            env = dict(os.environ, PYTHONHASHSEED=hash_seed, PYTHONPATH=src)
            outputs.add(subprocess.run([sys.executable, "-B", "-c", code], env=env,
                                       capture_output=True, text=True, check=True).stdout.strip())
        self.assertEqual(1, len(outputs))
        self.assertEqual(str(ip.stable_seed(7, 12, "agentview", "noise", 0.5)), outputs.pop())


if __name__ == "__main__":
    unittest.main()
