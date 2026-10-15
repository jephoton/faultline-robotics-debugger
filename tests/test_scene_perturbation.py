"""Scene-level perturbation families (camera viewpoint, lighting) on fake MuJoCo-shaped models."""

import ast
import json
import math
from pathlib import Path
import types
import unittest

import numpy as np

from robot_debug import image_perturbation
from robot_debug import scene_perturbation as sp
from robot_debug.scene_perturbation import SceneError, ScenePerturbation, SceneRig


def quat_multiply(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return np.array([
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    ])


def quat_conjugate(q):
    return np.array([q[0], -q[1], -q[2], -q[3]])


def rotation_matrix(q):
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])


def unit(*values):
    q = np.array(values, dtype=np.float64)
    return q / np.linalg.norm(q)


class FakeHeadlight:
    def __init__(self):
        self.ambient = np.array([0.1, 0.1, 0.1])
        self.diffuse = np.array([0.4, 0.4, 0.4])
        self.specular = np.array([0.5, 0.5, 0.5])


class FakeSceneModel:
    """The camera and light arrays of a MuJoCo model, with the name helper robosuite offers."""

    def __init__(self, headlight=True, lights=3):
        self.camera_names = ["frontview", "agentview", "robot0_eye_in_hand"]
        self.cam_pos = np.array([[1.0, 0.0, 1.5], [0.65, 0.0, 1.2], [0.0, 0.0, 0.1]])
        self.cam_quat = np.array([
            unit(0.6, 0.4, 0.3, 0.6), unit(0.56, 0.43, 0.43, 0.56), unit(1.0, 0.0, 0.0, 0.0)])
        self.nlight = lights
        self.light_diffuse = np.tile(np.array([[0.8, 0.7, 0.6]]), (lights, 1))
        self.light_ambient = np.tile(np.array([[0.2, 0.2, 0.3]]), (lights, 1))
        self.light_specular = np.full((lights, 3), 0.3)
        if headlight:
            self.vis = types.SimpleNamespace(headlight=FakeHeadlight())

    def camera_name2id(self, name):
        if name not in self.camera_names:
            raise ValueError("no camera " + name)
        return self.camera_names.index(name)


class FakeSceneSim:
    def __init__(self, model=None):
        self.model = model or FakeSceneModel()
        self.forwards = 0

    def forward(self):
        self.forwards += 1


class SpecTests(unittest.TestCase):
    def test_module_syntax_remains_compatible_with_python_38(self) -> None:
        module = Path(__file__).parents[1] / "src" / "robot_debug" / "scene_perturbation.py"
        ast.parse(module.read_text(encoding="utf-8"), filename=str(module), feature_version=(3, 8))

    def test_the_bounds_are_module_constants_for_calibration(self) -> None:
        self.assertEqual(("viewpoint", "lighting"), sp.SCENE_KINDS)
        self.assertEqual(0.10, sp.VIEWPOINT_MAX_SHIFT_M)
        self.assertEqual(10.0, sp.VIEWPOINT_MAX_YAW_DEG)
        self.assertEqual(0.9, sp.LIGHTING_MAX_REDUCTION)
        self.assertEqual("agentview", sp.AGENTVIEW_CAMERA)

    def test_validates_kind_and_severity(self) -> None:
        for kind, severity in (
            ("sepia", 0.5), ("", 0.5), (None, 0.5), ("blur", 0.5), ("viewpoint", -0.01), ("lighting", 1.01),
            ("lighting", float("nan")), ("viewpoint", True), ("lighting", "0.5"), ("viewpoint", None),
        ):
            with self.subTest(kind=kind, severity=severity), self.assertRaises((TypeError, ValueError)):
                ScenePerturbation(kind, severity)
        for kind in sp.SCENE_KINDS:
            for severity in (0, 1, 0.25):
                ScenePerturbation(kind, severity)

    def test_builds_from_a_mapping_and_rejects_extra_or_missing_keys(self) -> None:
        spec = ScenePerturbation.from_mapping({"kind": "lighting", "severity": 0.5})
        self.assertEqual(("lighting", 0.5), (spec.kind, spec.severity))
        self.assertEqual({"kind": "lighting", "severity": 0.5}, spec.to_mapping())
        self.assertIsNone(ScenePerturbation.from_mapping(None))
        for bad in ({"kind": "lighting"}, {"severity": 0.5}, {"kind": "lighting", "severity": 0.5, "x": 1}, "x", []):
            with self.subTest(bad=bad), self.assertRaises((TypeError, ValueError)):
                ScenePerturbation.from_mapping(bad)

    def test_enabled_only_above_zero(self) -> None:
        self.assertFalse(ScenePerturbation("viewpoint", 0).enabled)
        self.assertTrue(ScenePerturbation("viewpoint", 0.0125).enabled)

    def test_physical_values(self) -> None:
        self.assertEqual({"name": "camera_shift_m", "value": 0.05}, ScenePerturbation("viewpoint", 0.5).physical())
        self.assertEqual({"name": "light_scale", "value": 0.55}, ScenePerturbation("lighting", 0.5).physical())
        self.assertEqual({"name": "light_scale", "value": 1.0}, sp.physical_value("lighting", 0.0))
        self.assertAlmostEqual(0.1, sp.physical_value("lighting", 1.0)["value"], places=6)
        with self.assertRaises(ValueError):
            sp.physical_value("blur", 0.5)

    def test_the_image_module_reports_scene_physical_values_too(self) -> None:
        # The threshold search and the report script ask one function for any family.
        self.assertEqual(sp.physical_value("viewpoint", 0.4), image_perturbation.physical_value("viewpoint", 0.4))
        self.assertEqual(sp.physical_value("lighting", 0.4), image_perturbation.physical_value("lighting", 0.4))
        with self.assertRaises(ValueError):
            image_perturbation.ScalarPerturbation("viewpoint", 0.5)


class ViewpointTests(unittest.TestCase):
    def apply(self, severity, **kwargs):
        sim = FakeSceneSim(FakeSceneModel(**kwargs))
        before = (sim.model.cam_pos.copy(), sim.model.cam_quat.copy())
        record = SceneRig().apply(sim, ScenePerturbation("viewpoint", severity))
        return sim, before, record

    def test_full_severity_moves_the_camera_ten_centimetres_sideways_and_turns_it_ten_degrees(self) -> None:
        sim, (pos, quat), record = self.apply(1.0)
        index = sim.model.camera_name2id("agentview")
        shift = sim.model.cam_pos[index] - pos[index]
        self.assertAlmostEqual(0.10, float(np.linalg.norm(shift)), places=9)
        right_axis = rotation_matrix(quat[index])[:, 0]  # the camera's own x axis, in the world frame
        np.testing.assert_allclose(shift, 0.10 * right_axis, atol=1e-9)
        relative = quat_multiply(quat_conjugate(quat[index]), sim.model.cam_quat[index])
        angle = 2 * math.degrees(math.atan2(np.linalg.norm(relative[1:]), relative[0]))
        self.assertAlmostEqual(10.0, angle, places=6)
        np.testing.assert_allclose(relative[[1, 3]], 0.0, atol=1e-12)  # a pure rotation about the camera's own y (up) axis
        self.assertAlmostEqual(1.0, float(np.linalg.norm(sim.model.cam_quat[index])), places=12)
        self.assertEqual(1, sim.forwards)

    def test_the_view_turns_back_toward_the_scene_as_the_camera_moves_aside(self) -> None:
        sim, (pos, quat), _record = self.apply(1.0)
        index = 1
        before = rotation_matrix(quat[index])[:, 2] * -1.0  # a MuJoCo camera looks along its own -z
        after = rotation_matrix(sim.model.cam_quat[index])[:, 2] * -1.0
        right = rotation_matrix(quat[index])[:, 0]
        self.assertLess(float(np.dot(after - before, right)), 0.0, "the view direction swings back against the sideways shift")

    def test_half_severity_halves_both_the_shift_and_the_turn(self) -> None:
        sim, (pos, quat), record = self.apply(0.5)
        index = 1
        self.assertAlmostEqual(0.05, float(np.linalg.norm(sim.model.cam_pos[index] - pos[index])), places=9)
        self.assertAlmostEqual(0.05, record["shift_m"], places=9)
        self.assertAlmostEqual(5.0, record["yaw_deg"], places=9)

    def test_only_the_agent_view_camera_changes(self) -> None:
        sim, (pos, quat), _record = self.apply(1.0)
        for index in (0, 2):
            np.testing.assert_array_equal(pos[index], sim.model.cam_pos[index])
            np.testing.assert_array_equal(quat[index], sim.model.cam_quat[index])

    def test_the_record_lists_the_applied_values_as_plain_json(self) -> None:
        sim, _before, record = self.apply(0.8)
        self.assertEqual("viewpoint", record["kind"])
        self.assertEqual(0.8, record["severity"])
        self.assertEqual("agentview", record["camera"])
        self.assertAlmostEqual(0.08, record["shift_m"], places=9)
        self.assertAlmostEqual(8.0, record["yaw_deg"], places=9)
        np.testing.assert_allclose(record["cam_pos"], sim.model.cam_pos[1])
        np.testing.assert_allclose(record["cam_quat"], sim.model.cam_quat[1])
        json.dumps(record, allow_nan=False)

    def test_an_unknown_camera_fails_closed(self) -> None:
        model = FakeSceneModel()
        model.camera_names.remove("agentview")
        with self.assertRaises(SceneError):
            SceneRig().apply(FakeSceneSim(model), ScenePerturbation("viewpoint", 1.0))

    def test_a_negative_camera_id_fails_closed(self) -> None:
        model = FakeSceneModel()
        model.camera_name2id = lambda name: -1  # the older MuJoCo bindings return -1
        with self.assertRaises(SceneError):
            SceneRig().apply(FakeSceneSim(model), ScenePerturbation("viewpoint", 1.0))


class LightingTests(unittest.TestCase):
    def test_every_light_and_the_headlight_scale_by_one_minus_point_nine_s(self) -> None:
        sim = FakeSceneSim()
        model = sim.model
        diffuse, ambient = model.light_diffuse.copy(), model.light_ambient.copy()
        specular = model.light_specular.copy()
        record = SceneRig().apply(sim, ScenePerturbation("lighting", 0.5))
        np.testing.assert_allclose(model.light_diffuse, diffuse * 0.55)
        np.testing.assert_allclose(model.light_ambient, ambient * 0.55)
        np.testing.assert_array_equal(model.light_specular, specular)
        np.testing.assert_allclose(model.vis.headlight.diffuse, 0.4 * 0.55)
        np.testing.assert_allclose(model.vis.headlight.ambient, 0.1 * 0.55)
        np.testing.assert_array_equal(model.vis.headlight.specular, 0.5)
        self.assertEqual(1, sim.forwards)
        self.assertEqual(("lighting", 0.55, 3, True), (record["kind"], record["scale"], record["lights"], record["headlight"]))
        json.dumps(record, allow_nan=False)

    def test_full_severity_leaves_a_tenth_of_the_light(self) -> None:
        sim = FakeSceneSim()
        before = sim.model.light_diffuse.copy()
        SceneRig().apply(sim, ScenePerturbation("lighting", 1.0))
        np.testing.assert_allclose(sim.model.light_diffuse, before * 0.1)

    def test_a_model_without_a_headlight_or_lights_is_fine(self) -> None:
        sim = FakeSceneSim(FakeSceneModel(headlight=False, lights=0))
        record = SceneRig().apply(sim, ScenePerturbation("lighting", 0.5))
        self.assertEqual((0, False), (record["lights"], record["headlight"]))
        sim = FakeSceneSim(FakeSceneModel(headlight=False))
        self.assertFalse(SceneRig().apply(sim, ScenePerturbation("lighting", 0.5))["headlight"])

    def test_the_viewpoint_does_not_touch_the_lights(self) -> None:
        sim = FakeSceneSim()
        before = sim.model.light_diffuse.copy()
        SceneRig().apply(sim, ScenePerturbation("viewpoint", 1.0))
        np.testing.assert_array_equal(before, sim.model.light_diffuse)


class RigStateTests(unittest.TestCase):
    def test_applying_twice_is_not_cumulative(self) -> None:
        sim = FakeSceneSim()
        rig = SceneRig()
        rig.apply(sim, ScenePerturbation("viewpoint", 1.0))
        once = sim.model.cam_pos.copy(), sim.model.cam_quat.copy()
        rig.apply(sim, ScenePerturbation("viewpoint", 1.0))
        np.testing.assert_array_equal(once[0], sim.model.cam_pos)
        np.testing.assert_array_equal(once[1], sim.model.cam_quat)
        sim = FakeSceneSim()
        light = sim.model.light_diffuse.copy()
        rig = SceneRig()
        rig.apply(sim, ScenePerturbation("lighting", 0.5))
        rig.apply(sim, ScenePerturbation("lighting", 0.5))
        np.testing.assert_allclose(sim.model.light_diffuse, light * 0.55)

    def test_restore_returns_every_original_value_exactly(self) -> None:
        sim = FakeSceneSim()
        pos, quat = sim.model.cam_pos.copy(), sim.model.cam_quat.copy()
        diffuse, ambient = sim.model.light_diffuse.copy(), sim.model.light_ambient.copy()
        headlight = sim.model.vis.headlight.diffuse.copy()
        rig = SceneRig()
        rig.apply(sim, ScenePerturbation("viewpoint", 1.0))
        rig.apply(sim, ScenePerturbation("lighting", 1.0))
        rig.restore()
        np.testing.assert_array_equal(pos, sim.model.cam_pos)
        np.testing.assert_array_equal(quat, sim.model.cam_quat)
        np.testing.assert_array_equal(diffuse, sim.model.light_diffuse)
        np.testing.assert_array_equal(ambient, sim.model.light_ambient)
        np.testing.assert_array_equal(headlight, sim.model.vis.headlight.diffuse)
        rig.restore()  # a second restore changes nothing and does not fail

    def test_restore_before_any_apply_is_a_no_op(self) -> None:
        SceneRig().restore()

    def test_changing_severity_starts_from_the_originals(self) -> None:
        sim = FakeSceneSim()
        pos = sim.model.cam_pos.copy()
        rig = SceneRig()
        rig.apply(sim, ScenePerturbation("viewpoint", 1.0))
        rig.apply(sim, ScenePerturbation("viewpoint", 0.25))
        self.assertAlmostEqual(0.025, float(np.linalg.norm(sim.model.cam_pos[1] - pos[1])), places=9)

    def test_a_rebuilt_model_gets_fresh_originals(self) -> None:
        rig = SceneRig()
        first = FakeSceneSim()
        rig.apply(first, ScenePerturbation("lighting", 1.0))
        second = FakeSceneSim(FakeSceneModel())
        second.model.light_diffuse[:] = 0.5
        rig.apply(second, ScenePerturbation("lighting", 0.5))
        np.testing.assert_allclose(second.model.light_diffuse, 0.5 * 0.55)
        rig.restore()
        np.testing.assert_allclose(second.model.light_diffuse, 0.5)

    def test_a_disabled_perturbation_changes_nothing(self) -> None:
        sim = FakeSceneSim()
        pos = sim.model.cam_pos.copy()
        record = SceneRig().apply(sim, ScenePerturbation("viewpoint", 0.0))
        np.testing.assert_array_equal(pos, sim.model.cam_pos)
        self.assertEqual(0.0, record["shift_m"])

    def test_the_result_is_deterministic(self) -> None:
        results = []
        for _ in range(2):
            sim = FakeSceneSim()
            SceneRig().apply(sim, ScenePerturbation("viewpoint", 0.7))
            results.append((sim.model.cam_pos.copy(), sim.model.cam_quat.copy()))
        np.testing.assert_array_equal(results[0][0], results[1][0])
        np.testing.assert_array_equal(results[0][1], results[1][1])


if __name__ == "__main__":
    unittest.main()
