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


if __name__ == "__main__":
    unittest.main()
