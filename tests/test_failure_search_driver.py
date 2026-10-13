import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "run_failure_search.py"
SPEC = importlib.util.spec_from_file_location("run_failure_search", SCRIPT_PATH)
failure_search = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = failure_search
SPEC.loader.exec_module(failure_search)


class WriteConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write_config(self, **occlusion):
        config_path = self.root / "stage.yaml"
        failure_search._write_config(
            config_path=config_path,
            output_dir=self.root / "output",
            project_root=self.root / "project",
            stage_name="stage",
            episode_indices=(0,),
            **occlusion,
        )
        return config_path.read_text(encoding="utf-8")

    def test_square_side_writes_equal_width_and_height(self):
        text = self.write_config(side=.5)

        self.assertIn("        width: 0.500000", text)
        self.assertIn("        height: 0.500000", text)
        self.assertIn("        x: 0.250000", text)
        self.assertIn("        y: 0.250000", text)

    def test_rectangle_writes_exact_geometry(self):
        text = self.write_config(side=None, x=.625, y=0, width=.375, height=.5)

        self.assertIn("        x: 0.625000", text)
        self.assertIn("        y: 0.000000", text)
        self.assertIn("        width: 0.375000", text)
        self.assertIn("        height: 0.500000", text)

    def test_side_cannot_be_mixed_with_rectangle_dimensions(self):
        with self.assertRaises(ValueError):
            self.write_config(side=.5, width=.25, height=.5)

    def test_rectangle_requires_both_dimensions(self):
        with self.assertRaises(ValueError):
            self.write_config(side=None, x=0, y=0, width=.5)

    def test_rectangle_rejects_out_of_bounds_geometry(self):
        with self.assertRaises(ValueError):
            self.write_config(side=None, x=.75, y=.5, width=.5, height=.5)

    def test_writes_exact_portfolio_task_and_seed(self):
        text = self.write_config(task_id=2, seed=11)

        self.assertIn("    max_tasks: 1", text)
        self.assertIn("      task_id: 2", text)
        self.assertIn("      seed: 11", text)
        self.assertIn("      env_seed: 11", text)

    def test_default_configuration_preserves_legacy_first_task(self):
        text = self.write_config()

        self.assertNotIn("task_id:", text)
        self.assertIn("      seed: 7", text)

    def test_rejects_invalid_task_and_seed_values(self):
        for field, value in (("task_id", -1), ("task_id", True), ("seed", -1), ("seed", True)):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.write_config(**{field: value})


    # ---- M6: wrist occlusion and scalar image perturbation ---------------

    def params_block(self, text):
        return text[text.index("    params:"):].replace("\r\n", "\n")

    def test_default_params_block_is_byte_identical_to_the_pre_m6_writer(self):
        self.assertEqual(
            "    params:\n      suite: libero_object\n      seed: 7\n      env_seed: 7\n"
            "      num_steps_wait: 10\n",
            self.params_block(self.write_config()))
        self.assertEqual(
            "    params:\n      suite: libero_object\n      seed: 7\n      env_seed: 7\n"
            "      num_steps_wait: 10\n      agentview_occlusion:\n        enabled: true\n"
            "        x: 0.625000\n        y: 0.000000\n        width: 0.375000\n"
            "        height: 0.375000\n        color: [0, 0, 0]\n        opacity: 1.0\n",
            self.params_block(self.write_config(x=.625, y=0, width=.375, height=.375)))

    def test_explicit_none_options_change_nothing(self):
        self.assertEqual(
            self.write_config(x=.625, y=0, width=.375, height=.375),
            self.write_config(x=.625, y=0, width=.375, height=.375,
                              wrist_occlusion=None, image_perturbation=None))

    def test_wrist_occlusion_is_written_after_the_agentview_block(self):
        text = self.params_block(self.write_config(
            x=.625, y=0, width=.375, height=.375,
            wrist_occlusion={"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}))

        block = ("      wrist_occlusion:\n        enabled: true\n        x: 0.000000\n"
                 "        y: 0.000000\n        width: 1.000000\n        height: 1.000000\n"
                 "        color: [0, 0, 0]\n        opacity: 1.0\n")
        self.assertIn(block, text)
        self.assertTrue(text[text.index(block) + len(block):].startswith("      camera_probe:"))
        self.assertLess(text.index("agentview_occlusion"), text.index("wrist_occlusion"))

    def test_wrist_only_run_has_no_agentview_block(self):
        text = self.write_config(wrist_occlusion={"x": .625, "y": 0, "width": .375, "height": .375})

        self.assertNotIn("agentview_occlusion", text)
        self.assertIn("      wrist_occlusion:", text)
        self.assertIn("        x: 0.625000", text)

    def test_image_perturbation_block(self):
        text = self.params_block(self.write_config(image_perturbation={"kind": "noise", "severity": 0.0125}))

        block = "      image_perturbation:\n        kind: noise\n        severity: 0.012500\n"
        self.assertIn(block, text)
        self.assertTrue(text[text.index(block) + len(block):].startswith("      camera_probe:"))

    def test_blocks_parse_back_as_yaml_for_the_benchmark(self):
        import yaml
        text = self.write_config(
            x=.625, y=0, width=.375, height=.375,
            wrist_occlusion={"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
            image_perturbation={"kind": "blur", "severity": 0.6}, external_reset_candidate=self.root / "c.json")
        params = yaml.safe_load(text)["benchmarks"][0]["params"]

        self.assertEqual({"kind": "blur", "severity": 0.6}, params["image_perturbation"])
        self.assertEqual(1.0, params["wrist_occlusion"]["width"])
        self.assertTrue(params["wrist_occlusion"]["enabled"])
        self.assertEqual(0.625, params["agentview_occlusion"]["x"])
        self.assertIn("external_reset", params)

    def test_the_benchmark_accepts_the_written_blocks(self):
        # The YAML keys must be exactly the adapter's constructor options.
        import yaml
        from robot_debug.image_perturbation import ScalarPerturbation
        from robot_debug.occlusion import RectOcclusion
        text = self.write_config(
            wrist_occlusion={"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
            image_perturbation={"kind": "darken", "severity": 0.2})
        params = yaml.safe_load(text)["benchmarks"][0]["params"]

        self.assertTrue(RectOcclusion.from_mapping(
            dict(params["wrist_occlusion"], color=tuple(params["wrist_occlusion"]["color"]))).enabled)
        self.assertEqual(0.2, ScalarPerturbation.from_mapping(params["image_perturbation"]).severity)

    def test_camera_probe_is_written_beside_the_config_only_for_the_new_perturbations(self):
        import json
        import yaml
        for options in ({"wrist_occlusion": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}},
                        {"image_perturbation": {"kind": "blur", "severity": 0.4}}):
            with self.subTest(options=options):
                text = self.write_config(**options)
                params = yaml.safe_load(text)["benchmarks"][0]["params"]
                self.assertEqual(
                    str(self.root / "stage.camera_probe.json"), params["camera_probe"])
        for options in ({}, {"x": .625, "y": 0, "width": .375, "height": .375},
                        {"wrist_occlusion": None, "image_perturbation": None}):
            with self.subTest(options=options):
                self.assertNotIn("camera_probe", self.write_config(**options))
        text = self.write_config(image_perturbation={"kind": "blur", "severity": 0.4})
        self.assertIn(json.dumps(str(self.root / "stage.camera_probe.json")), text)

    def test_camera_probe_precedes_the_external_reset_block(self):
        text = self.write_config(image_perturbation={"kind": "blur", "severity": 0.4},
                                 external_reset_candidate=self.root / "c.json")
        self.assertLess(text.index("camera_probe"), text.index("external_reset"))

    def test_rejects_invalid_wrist_occlusion(self):
        good = {"x": 0.0, "y": 0.0, "width": 0.5, "height": 0.5}
        bad = (
            {"x": 0.0, "y": 0.0, "width": 0.5},
            dict(good, color=[1, 1, 1]),
            dict(good, width=0.0),
            dict(good, width=-0.1),
            dict(good, x=-0.1),
            dict(good, x=0.75),
            dict(good, height=float("nan")),
            dict(good, y=True),
            dict(good, y="0"),
            [0, 0, 1, 1],
            "full",
        )
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.write_config(wrist_occlusion=value)

    def test_rejects_invalid_image_perturbation(self):
        bad = (
            {"kind": "sepia", "severity": 0.5},
            {"kind": "noise", "severity": -0.1},
            {"kind": "noise", "severity": 1.1},
            {"kind": "noise", "severity": float("nan")},
            {"kind": "noise", "severity": True},
            {"kind": "noise", "severity": 0.1234567},
            {"kind": "noise"},
            {"kind": "noise", "severity": 0.5, "extra": 1},
            "noise",
        )
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.write_config(image_perturbation=value)


class SuiteAndStartConfigTests(unittest.TestCase):
    """M7: the suite and the benchmark start are selectable per stage."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write_config(self, **options):
        config_path = self.root / "stage.yaml"
        failure_search._write_config(
            config_path=config_path,
            output_dir=self.root / "output",
            project_root=self.root / "project",
            stage_name="stage",
            episode_indices=(0,),
            **options,
        )
        return config_path.read_text(encoding="utf-8")

    def test_default_suite_line_is_unchanged(self):
        self.assertIn("      suite: libero_object\n", self.write_config())
        self.assertEqual(self.write_config(), self.write_config(suite="libero_object", init_state_index=None))

    def test_libero_10_suite_is_written(self):
        text = self.write_config(suite="libero_10", task_id=3)
        self.assertIn("      suite: libero_10\n", text)
        self.assertNotIn("libero_object", text.split("params:")[1])

    def test_only_the_supported_suites_are_accepted(self):
        for suite in ("libero_spatial", "libero_goal", "libero_90", "libero_object ", "", None, 10, "x\n"):
            with self.subTest(suite=suite), self.assertRaises(ValueError):
                self.write_config(suite=suite)

    def test_init_state_index_is_written_after_the_task(self):
        import yaml
        text = self.write_config(suite="libero_10", task_id=2, init_state_index=7)
        params = yaml.safe_load(text)["benchmarks"][0]["params"]
        self.assertEqual(7, params["init_state_index"])
        self.assertEqual(2, params["task_id"])
        self.assertLess(text.index("task_id: 2"), text.index("init_state_index: 7"))
        self.assertIn("      init_state_index: 0\n", self.write_config(init_state_index=0))

    def test_rejects_invalid_init_state_index(self):
        for value in (-1, True, 1.5, "3", float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.write_config(init_state_index=value)

    def test_scenario_start_block_names_the_candidate_and_a_sidecar_in_the_output(self):
        import yaml
        candidate = self.root / "start.json"
        text = self.write_config(suite="libero_10", task_id=3, scenario_start=candidate)
        params = yaml.safe_load(text)["benchmarks"][0]["params"]
        self.assertEqual({"candidate": str(candidate),
                          "metadata_out": str(self.root / "output" / "scenario_start.json")},
                         params["scenario_start"])
        self.assertNotIn("init_state_index", params)
        self.assertNotIn("external_reset", params)

    def test_scenario_start_follows_the_camera_probe_like_the_external_reset(self):
        text = self.write_config(image_perturbation={"kind": "blur", "severity": 0.4},
                                 scenario_start=self.root / "start.json")
        self.assertLess(text.index("camera_probe"), text.index("scenario_start"))

    def test_scenario_start_is_exclusive_with_the_other_start_selectors(self):
        start = self.root / "start.json"
        with self.assertRaises(ValueError):
            self.write_config(scenario_start=start, external_reset_candidate=self.root / "c.json")
        with self.assertRaises(ValueError):
            self.write_config(scenario_start=start, init_state_index=2)

    def test_layout_and_state_exports_are_written_as_paths(self):
        import yaml
        text = self.write_config(init_state_index=1, layout_out=self.root / "layout.json",
                                 state_out=self.root / "state.json")
        params = yaml.safe_load(text)["benchmarks"][0]["params"]
        self.assertEqual(str(self.root / "layout.json"), params["layout_out"])
        self.assertEqual(str(self.root / "state.json"), params["state_out"])
        plain = yaml.safe_load(self.write_config(init_state_index=1))["benchmarks"][0]["params"]
        self.assertNotIn("layout_out", plain)
        self.assertNotIn("state_out", plain)

    def test_state_out_cannot_be_combined_with_a_scenario_or_external_start(self):
        with self.assertRaises(ValueError):
            self.write_config(scenario_start=self.root / "s.json", state_out=self.root / "state.json")
        with self.assertRaises(ValueError):
            self.write_config(external_reset_candidate=self.root / "c.json", state_out=self.root / "state.json")
        with self.assertRaises(ValueError):
            self.write_config(external_reset_candidate=self.root / "c.json", layout_out=self.root / "l.json")

    def test_absent_scenario_start_changes_nothing(self):
        self.assertEqual(self.write_config(), self.write_config(scenario_start=None))
        self.assertNotIn("scenario_start", self.write_config(suite="libero_10", init_state_index=1))


if __name__ == "__main__":
    unittest.main()
