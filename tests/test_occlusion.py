import unittest

import numpy as np

from robot_debug.occlusion import RectOcclusion, apply_agentview_occlusion


class RectOcclusionTests(unittest.TestCase):
    def test_applies_opaque_normalized_rectangle_without_mutating_input(self) -> None:
        image = np.full((4, 4, 3), 255, dtype=np.uint8)
        spec = RectOcclusion(x=0.25, y=0.25, width=0.5, height=0.5)

        transformed = spec.apply(image)

        expected = image.copy()
        expected[1:3, 1:3] = 0
        np.testing.assert_array_equal(transformed, expected)
        np.testing.assert_array_equal(image, np.full((4, 4, 3), 255, dtype=np.uint8))
        self.assertTrue(transformed.flags.c_contiguous)
        self.assertIsNot(transformed, image)

    def test_blends_color_at_requested_opacity(self) -> None:
        image = np.full((2, 2, 3), 255, dtype=np.uint8)
        spec = RectOcclusion(
            x=0.0,
            y=0.0,
            width=1.0,
            height=1.0,
            color=(0, 0, 0),
            opacity=0.5,
        )

        transformed = spec.apply(image)

        np.testing.assert_array_equal(
            transformed, np.full((2, 2, 3), 128, dtype=np.uint8)
        )

    def test_disabled_transform_returns_an_independent_copy(self) -> None:
        image = np.arange(12, dtype=np.uint8).reshape(2, 2, 3)

        transformed = RectOcclusion(enabled=False).apply(image)

        np.testing.assert_array_equal(transformed, image)
        self.assertIsNot(transformed, image)

    def test_builds_from_serialized_mapping(self) -> None:
        spec = RectOcclusion.from_mapping(
            {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4, "color": [1, 2, 3]}
        )

        self.assertEqual(spec.color, (1, 2, 3))
        self.assertFalse(RectOcclusion.from_mapping(None).enabled)

    def test_rejects_invalid_specs(self) -> None:
        invalid_specs = (
            {"x": -0.1},
            {"width": 0.0},
            {"x": 0.8, "width": 0.3},
            {"y": float("nan")},
            {"opacity": 1.1},
            {"color": (0, 0)},
            {"color": (0, 0, 256)},
            {"color": (0, 0, 1.5)},
        )

        for values in invalid_specs:
            with self.subTest(values=values), self.assertRaises((TypeError, ValueError)):
                RectOcclusion(**values)

    def test_rejects_incompatible_images(self) -> None:
        spec = RectOcclusion()

        for image in (
            np.zeros((4, 4), dtype=np.uint8),
            np.zeros((4, 4, 4), dtype=np.uint8),
            np.zeros((4, 4, 3), dtype=np.float32),
        ):
            with self.subTest(shape=image.shape, dtype=image.dtype), self.assertRaises(
                (TypeError, ValueError)
            ):
                spec.apply(image)


class AgentViewObservationTests(unittest.TestCase):
    def test_changes_only_agentview_and_preserves_original_observation(self) -> None:
        agentview = np.full((4, 4, 3), 255, dtype=np.uint8)
        wrist = np.full((4, 4, 3), 17, dtype=np.uint8)
        state = np.array([1.0, 2.0])
        observation = {
            "images": {"agentview": agentview, "wrist": wrist},
            "states": state,
            "task_description": "pick up the object",
        }

        transformed = apply_agentview_occlusion(
            observation,
            RectOcclusion(x=0.25, y=0.25, width=0.5, height=0.5),
        )

        self.assertIs(transformed["images"]["wrist"], wrist)
        self.assertIs(transformed["states"], state)
        self.assertIs(observation["images"]["agentview"], agentview)
        np.testing.assert_array_equal(agentview, np.full((4, 4, 3), 255, dtype=np.uint8))
        self.assertEqual(int(transformed["images"]["agentview"][1, 1, 0]), 0)


if __name__ == "__main__":
    unittest.main()
