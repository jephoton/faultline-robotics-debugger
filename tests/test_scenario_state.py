"""Pure tests for the scenario state model (synthetic layouts only)."""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from robot_debug import scenario_state as ss
from robot_debug.external_reset import _state_sha256
from tests.scenario_fakes import (
    base_state, quat_about_z, synthetic_layout, with_object_pose)

SOUP = 3        # qpos address of soup_1's free joint
DOOR = 10
BOWL = 11


def q(state, adr, count=7):
    return np.asarray(state[1 + adr:1 + adr + count])


class LayoutTests(unittest.TestCase):
    def test_valid_layout_round_trips_through_a_file(self):
        layout = synthetic_layout()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "layout.json"
            path.write_text(json.dumps(layout), encoding="utf-8")
            self.assertEqual(ss.load_layout(path), layout)

    def test_state_length_must_equal_one_plus_nq_plus_nv(self):
        layout = synthetic_layout()
        layout["state_length"] += 1
        with self.assertRaises(ss.ScenarioStateError):
            ss.validate_layout(layout)

    def test_rejects_unknown_type_bad_addresses_and_duplicates(self):
        def mutate(change):
            layout = synthetic_layout()
            change(layout)
            return layout

        bad = {
            "unknown type": mutate(lambda l: l["joints"][0].update(type="cylinder")),
            "qpos out of range": mutate(lambda l: l["joints"][5].update(qpos_adr=14)),
            "qvel out of range": mutate(lambda l: l["joints"][5].update(qvel_adr=12)),
            "overlap": mutate(lambda l: l["joints"][1].update(qpos_adr=0)),
            "duplicate name": mutate(lambda l: l["joints"][1].update(name="robot0_joint1")),
            "bool address": mutate(lambda l: l["joints"][0].update(qpos_adr=True)),
            "empty entity": mutate(lambda l: l["joints"][0].update(entity="")),
            "extra key": mutate(lambda l: l.update(extra=1)),
            "wrong version": mutate(lambda l: l.update(schema_version=2)),
            "no joints": mutate(lambda l: l.update(joints=[])),
            "two free joints in one entity": mutate(
                lambda l: l["joints"][4].update(type="free", entity="soup_1", qpos_adr=10)),
        }
        for name, layout in bad.items():
            with self.subTest(name), self.assertRaises(ss.ScenarioStateError):
                ss.validate_layout(layout)

    def test_unreferenced_dofs_are_rejected(self):
        layout = synthetic_layout()
        layout["joints"].pop()          # bowl removed: qpos 11..17 uncovered
        with self.assertRaises(ss.ScenarioStateError):
            ss.validate_layout(layout)

    def test_entities_are_robot_first_then_objects_in_layout_order(self):
        names = [entity.name for entity in ss.entities(synthetic_layout())]
        self.assertEqual(names, ["robot", "soup_1", "microwave_1", "bowl_1"])
        kinds = {e.name: e.kind for e in ss.entities(synthetic_layout())}
        self.assertEqual(kinds["robot"], "robot")
        self.assertEqual(kinds["soup_1"], "object")

    def test_validate_state_checks_length_and_finiteness(self):
        layout = synthetic_layout()
        ss.validate_state(base_state(layout), layout)
        with self.assertRaises(ss.ScenarioStateError):
            ss.validate_state(base_state(layout)[:-1], layout)
        broken = base_state(layout)
        broken[4] = float("nan")
        with self.assertRaises(ss.ScenarioStateError):
            ss.validate_state(broken, layout)


class DifferencesTests(unittest.TestCase):
    def setUp(self):
        self.layout = synthetic_layout()
        self.reference = base_state(self.layout)

    def test_identical_states_have_no_differences(self):
        self.assertEqual(ss.differences(self.reference, self.reference, self.layout), [])

    def test_position_offset_vector_and_norm_in_metres(self):
        failing = with_object_pose(self.reference, SOUP, dxyz=(0.03, 0.04, 0.0))
        table = ss.differences(failing, self.reference, self.layout)
        self.assertEqual([row["entity"] for row in table], ["soup_1"])
        position = table[0]["position"]
        np.testing.assert_allclose(position["offset_m"], [0.03, 0.04, 0.0], atol=1e-12)
        self.assertAlmostEqual(position["distance_m"], 0.05)
        self.assertIsNone(table[0]["rotation"])
        self.assertEqual(table[0]["joints"], [])

    def test_rotation_angle_in_degrees(self):
        failing = with_object_pose(self.reference, SOUP, z_degrees=30.0)
        row = ss.differences(failing, self.reference, self.layout)[0]
        self.assertAlmostEqual(row["rotation"]["angle_deg"], 30.0, places=9)
        self.assertIsNone(row["position"])

    def test_quaternion_sign_flip_is_the_same_rotation(self):
        failing = np.array(self.reference)
        failing[1 + SOUP + 3:1 + SOUP + 7] = -np.asarray([1.0, 0.0, 0.0, 0.0])
        self.assertEqual(ss.differences(failing, self.reference, self.layout), [])

    def test_small_rotation_is_numerically_stable(self):
        failing = with_object_pose(self.reference, SOUP, z_degrees=1.5)
        row = ss.differences(failing, self.reference, self.layout)[0]
        self.assertAlmostEqual(row["rotation"]["angle_deg"], 1.5, places=9)

    def test_noise_floor_per_component(self):
        below = with_object_pose(self.reference, SOUP, dxyz=(0.0019, 0, 0), z_degrees=0.9)
        self.assertEqual(ss.differences(below, self.reference, self.layout), [])
        above_position = with_object_pose(self.reference, SOUP, dxyz=(0.0021, 0, 0), z_degrees=0.9)
        row = ss.differences(above_position, self.reference, self.layout)[0]
        self.assertIsNotNone(row["position"])
        self.assertIsNone(row["rotation"])
        above_rotation = with_object_pose(self.reference, SOUP, dxyz=(0.0019, 0, 0), z_degrees=1.1)
        row = ss.differences(above_rotation, self.reference, self.layout)[0]
        self.assertIsNone(row["position"])
        self.assertIsNotNone(row["rotation"])

    def test_joint_offsets_use_degrees_for_hinges_and_metres_for_slides(self):
        failing = np.array(self.reference)
        failing[1 + 0] += math.radians(2.0)       # robot hinge, 2 degrees
        failing[1 + 1] += math.radians(0.4)       # below the 0.5 degree floor
        failing[1 + 2] += 0.005                   # slide, 5 mm
        failing[1 + DOOR] += math.radians(5.0)    # door hinge
        table = {row["entity"]: row for row in ss.differences(failing, self.reference, self.layout)}
        self.assertEqual(list(table), ["robot", "microwave_1"])
        robot_joints = {j["name"]: j for j in table["robot"]["joints"]}
        self.assertEqual(sorted(robot_joints), ["gripper0_finger", "robot0_joint1"])
        self.assertAlmostEqual(robot_joints["robot0_joint1"]["offset"], 2.0)
        self.assertEqual(robot_joints["robot0_joint1"]["unit"], "deg")
        self.assertAlmostEqual(robot_joints["gripper0_finger"]["offset"], 0.005)
        self.assertEqual(robot_joints["gripper0_finger"]["unit"], "m")
        self.assertAlmostEqual(table["microwave_1"]["joints"][0]["offset"], 5.0)
        self.assertEqual(table["robot"]["kind"], "robot")
        self.assertEqual(table["microwave_1"]["kind"], "object")

    def test_rows_are_in_layout_order_and_carry_a_distance_score(self):
        failing = with_object_pose(self.reference, BOWL, dxyz=(0.0, 0.10, 0.0))
        failing = with_object_pose(failing, SOUP, dxyz=(0.02, 0.0, 0.0), z_degrees=20.0)
        table = ss.differences(failing, self.reference, self.layout)
        self.assertEqual([row["entity"] for row in table], ["soup_1", "bowl_1"])
        self.assertAlmostEqual(table[0]["distance"], 2.0 + 20.0 / 10.0)
        self.assertAlmostEqual(table[1]["distance"], 10.0)

    def test_fixed_order_is_largest_difference_first_with_name_tiebreak(self):
        failing = with_object_pose(self.reference, BOWL, dxyz=(0.0, 0.10, 0.0))
        failing = with_object_pose(failing, SOUP, dxyz=(0.02, 0.0, 0.0))
        table = ss.differences(failing, self.reference, self.layout)
        self.assertEqual(ss.fixed_order(table), ["bowl_1", "soup_1"])
        tie = [{"entity": "b", "distance": 1.0}, {"entity": "a", "distance": 1.0}]
        self.assertEqual(ss.fixed_order(tie), ["a", "b"])

    def test_output_is_json_clean_and_does_not_mutate_inputs(self):
        failing = with_object_pose(self.reference, SOUP, dxyz=(0.03, 0, 0), z_degrees=12.0)
        before = (failing.copy(), self.reference.copy())
        table = ss.differences(failing, self.reference, self.layout)
        json.dumps(table, allow_nan=False)
        np.testing.assert_array_equal(failing, before[0])
        np.testing.assert_array_equal(self.reference, before[1])

    def test_ball_joint_offset_is_a_rotation_in_degrees(self):
        layout = {
            "schema_version": 1, "suite": "s", "task_id": 0, "state_length": 1 + 4 + 3 + 0,
            "nq": 4, "nv": 3,
            "joints": [{"name": "j", "type": "ball", "qpos_adr": 0, "qvel_adr": 0, "entity": "thing"}],
        }
        reference = np.array([0.0, 1, 0, 0, 0, 0, 0, 0])
        failing = np.array(reference)
        failing[1:5] = quat_about_z(40.0)
        row = ss.differences(failing, reference, layout)[0]
        self.assertAlmostEqual(row["joints"][0]["offset"], 40.0)
        self.assertEqual(row["joints"][0]["unit"], "deg")


class HybridTests(unittest.TestCase):
    def setUp(self):
        self.layout = synthetic_layout()
        self.reference = base_state(self.layout)
        failing = with_object_pose(self.reference, SOUP, dxyz=(0.04, -0.02, 0.0), z_degrees=60.0)
        failing = with_object_pose(failing, BOWL, dxyz=(0.0, 0.1, 0.0))
        failing[1 + 0] += math.radians(10.0)
        failing[1 + DOOR] += math.radians(20.0)
        failing[1 + self.layout["nq"]:] = 0.7          # nonzero velocities
        failing[0] = 9.0
        self.failing = failing

    def test_empty_selection_is_the_reference_with_zero_velocity(self):
        out = ss.hybrid(self.reference, self.failing, {}, self.layout)
        np.testing.assert_array_equal(out, self.reference)

    def test_full_selection_reproduces_failing_poses_but_not_velocity_or_time(self):
        selection = {
            "robot": {"joints": 1.0}, "soup_1": {"position": 1.0, "rotation": 1.0},
            "microwave_1": {"joints": 1.0}, "bowl_1": {"position": 1.0, "rotation": 1.0},
        }
        out = ss.hybrid(self.reference, self.failing, selection, self.layout)
        nq = self.layout["nq"]
        np.testing.assert_array_equal(out[1:1 + nq], self.failing[1:1 + nq])
        self.assertTrue(np.all(out[1 + nq:] == 0.0))
        self.assertEqual(out[0], self.reference[0])

    def test_position_and_rotation_apply_independently(self):
        pos_only = ss.hybrid(self.reference, self.failing, {"soup_1": {"position": 1.0}}, self.layout)
        np.testing.assert_array_equal(q(pos_only, SOUP)[:3], q(self.failing, SOUP)[:3])
        np.testing.assert_array_equal(q(pos_only, SOUP)[3:], q(self.reference, SOUP)[3:])
        rot_only = ss.hybrid(self.reference, self.failing, {"soup_1": {"rotation": 1.0}}, self.layout)
        np.testing.assert_array_equal(q(rot_only, SOUP)[:3], q(self.reference, SOUP)[:3])
        np.testing.assert_array_equal(q(rot_only, SOUP)[3:], q(self.failing, SOUP)[3:])

    def test_unselected_entities_keep_the_reference(self):
        out = ss.hybrid(self.reference, self.failing, {"soup_1": {"position": 1.0}}, self.layout)
        np.testing.assert_array_equal(q(out, BOWL), q(self.reference, BOWL))
        np.testing.assert_array_equal(out[1:4], self.reference[1:4])
        self.assertEqual(out[1 + DOOR], self.reference[1 + DOOR])

    def test_position_and_joints_interpolate_linearly(self):
        out = ss.hybrid(self.reference, self.failing,
                        {"soup_1": {"position": 0.25}, "robot": {"joints": 0.5}}, self.layout)
        expected = q(self.reference, SOUP)[:3] + 0.25 * (q(self.failing, SOUP)[:3] - q(self.reference, SOUP)[:3])
        np.testing.assert_allclose(q(out, SOUP)[:3], expected, atol=1e-15)
        self.assertAlmostEqual(out[1], self.reference[1] + 0.5 * (self.failing[1] - self.reference[1]))

    def test_rotation_slerps_through_half_the_angle_and_stays_unit(self):
        out = ss.hybrid(self.reference, self.failing, {"soup_1": {"rotation": 0.5}}, self.layout)
        quaternion = q(out, SOUP)[3:]
        self.assertAlmostEqual(float(np.linalg.norm(quaternion)), 1.0, places=12)
        np.testing.assert_allclose(quaternion, quat_about_z(30.0), atol=1e-12)
        third = ss.hybrid(self.reference, self.failing, {"soup_1": {"rotation": 0.25}}, self.layout)
        np.testing.assert_allclose(q(third, SOUP)[3:], quat_about_z(15.0), atol=1e-12)

    def test_slerp_takes_the_shortest_path_when_the_signs_differ(self):
        failing = np.array(self.failing)
        failing[1 + SOUP + 3:1 + SOUP + 7] = -np.asarray(quat_about_z(60.0))
        out = ss.hybrid(self.reference, failing, {"soup_1": {"rotation": 0.5}}, self.layout)
        np.testing.assert_allclose(q(out, SOUP)[3:], quat_about_z(30.0), atol=1e-12)

    def test_endpoints_are_exact(self):
        zero = ss.hybrid(self.reference, self.failing, {"soup_1": {"rotation": 0.0, "position": 0.0}},
                         self.layout)
        np.testing.assert_array_equal(zero, self.reference)
        one = ss.hybrid(self.reference, self.failing, {"soup_1": {"rotation": 1.0}}, self.layout)
        np.testing.assert_array_equal(q(one, SOUP)[3:], q(self.failing, SOUP)[3:])

    def test_nearly_parallel_quaternions_do_not_blow_up(self):
        failing = np.array(self.reference)
        failing[1 + SOUP + 3:1 + SOUP + 7] = quat_about_z(0.001)
        out = ss.hybrid(self.reference, failing, {"soup_1": {"rotation": 0.5}}, self.layout)
        np.testing.assert_allclose(q(out, SOUP)[3:], quat_about_z(0.0005), atol=1e-12)

    def test_inputs_are_not_mutated_and_result_is_a_new_array(self):
        reference, failing = self.reference.copy(), self.failing.copy()
        out = ss.hybrid(self.reference, self.failing, {"robot": {"joints": 1.0}}, self.layout)
        np.testing.assert_array_equal(self.reference, reference)
        np.testing.assert_array_equal(self.failing, failing)
        self.assertIsNot(out, self.reference)

    def test_selection_is_validated(self):
        bad = [
            {"nothing": {"position": 1.0}},
            {"soup_1": {"joints": 1.0}},              # free object has no plain joints
            {"robot": {"position": 1.0}},
            {"microwave_1": {"position": 1.0}},
            {"soup_1": {"position": 1.5}},
            {"soup_1": {"position": -0.1}},
            {"soup_1": {"position": float("nan")}},
            {"soup_1": {"position": True}},
            {"soup_1": {"colour": 1.0}},
            {"soup_1": 1.0},
            [],
        ]
        for selection in bad:
            with self.subTest(selection=selection), self.assertRaises(ss.ScenarioStateError):
                ss.hybrid(self.reference, self.failing, selection, self.layout)

    def test_state_length_mismatch_is_rejected(self):
        with self.assertRaises(ss.ScenarioStateError):
            ss.hybrid(self.reference[:-1], self.failing, {}, self.layout)

    def test_normalise_selection_drops_zero_parts_and_canonicalises(self):
        selection = {"soup_1": {"rotation": 0.0, "position": 0.5}, "bowl_1": {"position": 0.0}}
        self.assertEqual(ss.normalise_selection(selection, self.layout),
                         {"soup_1": {"position": 0.5}})
        a = ss.normalise_selection({"bowl_1": {"position": 1}, "soup_1": {"position": 1}}, self.layout)
        # Entities come out in layout order, whatever order the caller used.
        self.assertEqual(list(a), ["soup_1", "bowl_1"])


class HashAndDistanceTests(unittest.TestCase):
    def test_state_hash_matches_the_external_reset_kernel(self):
        state = base_state()
        self.assertEqual(ss.state_hash(state), _state_sha256(state.tolist()))
        self.assertEqual(ss.state_hash(state.tolist()), ss.state_hash(state))

    def test_state_hash_is_sensitive_and_rejects_non_finite(self):
        state = base_state()
        other = state.copy()
        other[5] += 1e-12
        self.assertNotEqual(ss.state_hash(state), ss.state_hash(other))
        other[5] = float("inf")
        with self.assertRaises(ss.ScenarioStateError):
            ss.state_hash(other)

    def test_equal_hybrids_share_a_hash(self):
        layout = synthetic_layout()
        reference = base_state(layout)
        failing = with_object_pose(reference, SOUP, dxyz=(0.04, 0, 0))
        first = ss.hybrid(reference, failing, {"soup_1": {"position": 0.0}}, layout)
        self.assertEqual(ss.state_hash(first), ss.state_hash(reference))

    def test_scenario_distance_sums_object_position_cm_and_rotation_tenth_degrees(self):
        layout = synthetic_layout()
        a = base_state(layout)
        b = with_object_pose(a, SOUP, dxyz=(0.03, 0.04, 0.0), z_degrees=20.0)
        b = with_object_pose(b, BOWL, dxyz=(0.0, 0.0, 0.01))
        b[1 + 0] += math.radians(30.0)     # robot joints are ignored
        self.assertAlmostEqual(ss.scenario_distance(a, b, layout), 5.0 + 2.0 + 1.0)
        self.assertAlmostEqual(ss.scenario_distance(a, a, layout), 0.0)
        self.assertAlmostEqual(ss.scenario_distance(a, b, layout), ss.scenario_distance(b, a, layout))

    def test_scenario_distance_counts_object_joints(self):
        layout = synthetic_layout()
        a = base_state(layout)
        b = a.copy()
        b[1 + DOOR] += math.radians(10.0)
        self.assertAlmostEqual(ss.scenario_distance(a, b, layout), 1.0)


if __name__ == "__main__":
    unittest.main()
