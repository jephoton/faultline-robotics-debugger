import json
import math
import unittest

import numpy as np

from robot_debug import scene_inspect as si
from tests.scene_fakes import FREE, GEOM, HINGE, SLIDE, FakeContact, FakeData, FakeEnv, FakeModel, standard_model


def layout_for(model, suite="libero_10", task_id=3):
    return si.build_layout(suite, task_id, model, model.state_length)


class LayoutTests(unittest.TestCase):
    def test_layout_schema_and_entities(self):
        model = standard_model()
        layout = layout_for(model)
        self.assertEqual({"schema_version", "suite", "task_id", "state_length", "nq", "nv", "joints"},
                         set(layout))
        self.assertEqual(1, layout["schema_version"])
        self.assertEqual(("libero_10", 3), (layout["suite"], layout["task_id"]))
        self.assertEqual((35, 18, 16), (layout["state_length"], layout["nq"], layout["nv"]))
        self.assertEqual(model.state_length, 1 + layout["nq"] + layout["nv"])
        joints = {joint["name"]: joint for joint in layout["joints"]}
        self.assertEqual([joint["name"] for joint in layout["joints"]],
                         ["robot0_joint1", "gripper0_finger_joint1", "gripper0_finger_joint2",
                          "alphabet_soup_1_joint0", "basket_1_joint0", "microwave_1_door_joint"])
        for joint in layout["joints"]:
            self.assertEqual({"name", "type", "qpos_adr", "qvel_adr", "entity"}, set(joint))
        self.assertEqual({"name": "alphabet_soup_1_joint0", "type": "free", "qpos_adr": 3, "qvel_adr": 3,
                          "entity": "alphabet_soup_1"}, joints["alphabet_soup_1_joint0"])
        self.assertEqual({"name": "basket_1_joint0", "type": "free", "qpos_adr": 10, "qvel_adr": 9,
                          "entity": "basket_1"}, joints["basket_1_joint0"])
        self.assertEqual(("hinge", "robot"), (joints["robot0_joint1"]["type"], joints["robot0_joint1"]["entity"]))
        self.assertEqual("slide", joints["gripper0_finger_joint2"]["type"])
        self.assertEqual("robot", joints["gripper0_finger_joint2"]["entity"])

    def test_layout_is_json_serialisable_plain_python(self):
        text = json.dumps(layout_for(standard_model()), allow_nan=False)
        self.assertEqual(3, json.loads(text)["task_id"])

    def test_a_joint_of_a_child_body_belongs_to_the_top_level_object(self):
        layout = layout_for(standard_model())
        entities = {joint["name"]: joint["entity"] for joint in layout["joints"]}
        self.assertEqual("microwave_1", entities["microwave_1_door_joint"])

    def test_all_joints_of_one_object_share_its_entity(self):
        bodies = [("world", 0), ("robot0_base", 0), ("tray_1_main", 0), ("tray_1_lid", 2), ("tray_1_latch", 3)]
        joints = [("robot0_joint1", HINGE, 1), ("tray_1_joint0", FREE, 2),
                  ("tray_1_lid_hinge", HINGE, 3), ("tray_1_latch_slide", SLIDE, 4)]
        layout = layout_for(FakeModel(bodies, joints, [0]))
        self.assertEqual({"robot", "tray_1"}, {joint["entity"] for joint in layout["joints"]})
        self.assertEqual(3, sum(joint["entity"] == "tray_1" for joint in layout["joints"]))

    def test_robot_is_recognised_by_joint_name_or_top_level_body(self):
        bodies = [("world", 0), ("robot0_base", 0), ("robot0_link1", 1), ("gripper0_hand", 2), ("cup_1_main", 0)]
        joints = [("arm_joint", HINGE, 2), ("hand_joint", SLIDE, 3), ("cup_1_joint0", FREE, 4)]
        layout = layout_for(FakeModel(bodies, joints, [0]))
        self.assertEqual(["robot", "robot", "cup_1"], [joint["entity"] for joint in layout["joints"]])

    def test_main_suffix_is_dropped_unless_that_would_collide(self):
        bodies = [("world", 0), ("a_main", 0), ("a", 0), ("b_main", 0)]
        joints = [("j_a_main", FREE, 1), ("j_a", FREE, 2), ("j_b", FREE, 3)]
        layout = layout_for(FakeModel(bodies, joints, [0]))
        self.assertEqual(["a_main", "a", "b"], [joint["entity"] for joint in layout["joints"]])

    def test_state_length_must_equal_one_plus_nq_plus_nv(self):
        model = standard_model()
        with self.assertRaises(si.SceneInspectError):
            si.build_layout("libero_10", 3, model, model.state_length + 1)
        with self.assertRaises(si.SceneInspectError):
            si.build_layout("libero_10", 3, model, model.state_length - 1)

    def test_unknown_joint_types_fail_closed(self):
        bodies = [("world", 0), ("thing", 0)]
        model = FakeModel(bodies, [("j", HINGE, 1)], [0])
        model.jnt_type = np.array([9])
        with self.assertRaises(si.SceneInspectError):
            si.build_layout("libero_10", 0, model, model.state_length)

    def test_layout_matches_for_mujoco_py_style_name_lists(self):
        model = standard_model()
        names = [model.body_id2name(i) for i in range(model.nbody)]
        joint_names = [model.joint_id2name(i) for i in range(model.njnt)]
        model.body_id2name = None
        model.joint_id2name = None
        model.body_names = tuple(names)
        model.joint_names = tuple(joint_names)
        self.assertEqual(layout_for(standard_model()), layout_for(model))


class ContactTests(unittest.TestCase):
    def setUp(self):
        self.model = standard_model()
        self.data = FakeData()

    def scan(self, *contacts, **options):
        self.data.contacts = [FakeContact(GEOM[a], GEOM[b], dist) for a, b, dist in contacts]
        return si.scan_contacts(self.model, self.data, **options)

    def test_no_contacts_is_valid(self):
        result = self.scan()
        self.assertEqual((True, 0.0, None, 0), (result["valid"], result["deepest_penetration_m"],
                                               result["deepest_pair"], result["invalid_contacts"]))

    def test_robot_pressing_into_an_object_is_invalid(self):
        result = self.scan(("finger", "soup", -0.006))
        self.assertFalse(result["valid"])
        self.assertAlmostEqual(0.006, result["deepest_penetration_m"])
        self.assertEqual(["alphabet_soup_1", "robot"], result["deepest_pair"])
        self.assertEqual(1, result["invalid_contacts"])

    def test_object_into_object_is_invalid_in_either_geom_order(self):
        for first, second in (("soup", "basket"), ("basket", "soup")):
            result = self.scan((first, second, -0.01))
            self.assertFalse(result["valid"])
            self.assertEqual(["alphabet_soup_1", "basket_1"], result["deepest_pair"])

    def test_threshold_edge(self):
        self.assertTrue(self.scan(("soup", "basket", -0.005))["valid"])
        self.assertFalse(self.scan(("soup", "basket", -0.0050001))["valid"])
        self.assertTrue(self.scan(("soup", "basket", -0.004999))["valid"])
        self.assertAlmostEqual(0.005, self.scan(("soup", "basket", -0.005))["deepest_penetration_m"])
        self.assertTrue(self.scan(("soup", "basket", -0.006), limit=0.01)["valid"])
        self.assertFalse(self.scan(("soup", "basket", -0.006), limit=0.001)["valid"])

    def test_the_robot_against_static_scene_bodies_is_ignored(self):
        for geom in ("table", "stove", "floor"):
            result = self.scan(("robot_link", geom, -0.2), ("finger", geom, -0.2))
            self.assertTrue(result["valid"], geom)
            self.assertEqual(0.0, result["deepest_penetration_m"])
            self.assertEqual(0, result["invalid_contacts"])

    def test_static_bodies_against_each_other_are_ignored(self):
        self.assertTrue(self.scan(("table", "floor", -0.3), ("stove", "table", -0.3))["valid"])

    def test_static_scene_contacts_are_recorded_but_never_decide_validity(self):
        # Real LIBERO-10 starts rest an object 14.6 mm inside the table's collision geometry.
        for geom, label in (("table", "scene:main_table"), ("stove", "scene:flat_stove_1_main"),
                            ("floor", "scene:world")):
            with self.subTest(geom=geom):
                result = self.scan(("soup", geom, -0.02))
                self.assertTrue(result["valid"])
                self.assertEqual(0.0, result["deepest_penetration_m"])
                self.assertIsNone(result["deepest_pair"])
                self.assertEqual(0, result["invalid_contacts"])
                self.assertAlmostEqual(0.02, result["deepest_static_penetration_m"])
                self.assertEqual(sorted(["alphabet_soup_1", label]), result["deepest_static_pair"])

    def test_an_articulated_fixture_against_the_table_is_recorded_only(self):
        result = self.scan(("microwave", "table", -0.01))
        self.assertTrue(result["valid"])
        self.assertAlmostEqual(0.01, result["deepest_static_penetration_m"])

    def test_static_contacts_do_not_hide_a_deeper_entity_contact(self):
        result = self.scan(("soup", "table", -0.04), ("finger", "soup", -0.03))
        self.assertEqual(["alphabet_soup_1", "robot"], result["deepest_pair"])
        self.assertAlmostEqual(0.03, result["deepest_penetration_m"])
        self.assertEqual(1, result["invalid_contacts"])
        self.assertAlmostEqual(0.04, result["deepest_static_penetration_m"])

    def test_contacts_inside_one_entity_are_ignored(self):
        for pair in (("robot_link", "finger"), ("robot_base", "finger"), ("basket", "basket_lid"),
                     ("microwave", "microwave_door"), ("soup", "soup")):
            self.assertTrue(self.scan((pair[0], pair[1], -0.1))["valid"], pair)

    def test_separated_and_touching_contacts_do_not_count(self):
        result = self.scan(("soup", "basket", 0.01), ("finger", "soup", 0.0))
        self.assertTrue(result["valid"])
        self.assertEqual(0.0, result["deepest_penetration_m"])
        self.assertIsNone(result["deepest_pair"])

    def test_deepest_pair_is_reported_across_several_contacts(self):
        result = self.scan(("soup", "basket", -0.007), ("finger", "soup", -0.02), ("basket", "microwave", -0.001),
                           ("finger", "table", -0.5))   # the robot against the table is ignored
        self.assertFalse(result["valid"])
        self.assertAlmostEqual(0.02, result["deepest_penetration_m"])
        self.assertEqual(["alphabet_soup_1", "robot"], result["deepest_pair"])
        self.assertEqual(2, result["invalid_contacts"])
        self.assertEqual(3, result["contacts_checked"])

    def test_shallow_overlap_is_reported_but_valid(self):
        result = self.scan(("soup", "basket", -0.003))
        self.assertTrue(result["valid"])
        self.assertAlmostEqual(0.003, result["deepest_penetration_m"])
        self.assertEqual(["alphabet_soup_1", "basket_1"], result["deepest_pair"])

    def test_a_non_finite_distance_fails_closed(self):
        for bad in (float("nan"), float("inf")):
            with self.assertRaises(si.SceneInspectError):
                self.scan(("soup", "basket", bad))

    def test_result_is_plain_json(self):
        json.dumps(self.scan(("soup", "basket", -0.01)), allow_nan=False)

    def test_numpy_scalars_in_contacts_are_accepted(self):
        self.data.contacts = [FakeContact(np.int32(GEOM["soup"]), np.int32(GEOM["basket"]), np.float64(-0.01))]
        result = si.scan_contacts(self.model, self.data)
        self.assertFalse(result["valid"])
        self.assertIs(float, type(result["deepest_penetration_m"]))


class DisplacementTests(unittest.TestCase):
    def test_free_joint_objects_report_their_position_change_in_metres(self):
        model = standard_model()
        layout = layout_for(model)
        before = np.zeros(model.state_length)
        after = before.copy()
        # soup free joint: qpos_adr 3 -> flat index 1 + 3
        after[1 + 3:1 + 6] = [0.003, 0.004, 0.0]
        after[1 + 10:1 + 13] = [0.0, 0.0, -0.001]
        result = si.settle_displacement(layout, before, after)
        self.assertEqual({"alphabet_soup_1", "basket_1"}, set(result))
        self.assertAlmostEqual(0.005, result["alphabet_soup_1"])
        self.assertAlmostEqual(0.001, result["basket_1"])
        self.assertTrue(all(type(value) is float for value in result.values()))

    def test_robot_and_jointed_fixtures_without_a_free_joint_are_not_reported(self):
        model = standard_model()
        layout = layout_for(model)
        before = np.zeros(model.state_length)
        after = np.ones(model.state_length)
        self.assertNotIn("robot", si.settle_displacement(layout, before, after))
        self.assertNotIn("microwave_1", si.settle_displacement(layout, before, after))

    def test_rejects_states_of_the_wrong_length(self):
        layout = layout_for(standard_model())
        with self.assertRaises(si.SceneInspectError):
            si.settle_displacement(layout, np.zeros(3), np.zeros(3))


class SimAccessTests(unittest.TestCase):
    def test_sim_is_found_on_the_env_or_its_inner_env(self):
        env = FakeEnv()
        self.assertIs(env.sim, si.sim_of(env))

        class Wrapper:
            pass

        wrapper = Wrapper()
        wrapper.env = env
        self.assertIs(env.sim, si.sim_of(wrapper))
        with self.assertRaises(si.SceneInspectError):
            si.sim_of(Wrapper())

    def test_state_vector_is_a_finite_flat_float_array_of_the_expected_length(self):
        env = FakeEnv()
        vector = si.state_vector(env, env.model.state_length)
        self.assertEqual((env.model.state_length,), vector.shape)
        with self.assertRaises(si.SceneInspectError):
            si.state_vector(env, env.model.state_length + 1)
        env.state[2] = math.nan
        with self.assertRaises(si.SceneInspectError):
            si.state_vector(env, env.model.state_length)


if __name__ == "__main__":
    unittest.main()
