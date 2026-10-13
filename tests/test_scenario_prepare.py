"""Job preparation and workload files for the scenario modes."""

from __future__ import annotations

import importlib.util
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest

from robot_debug import scenario_experiment as se
from robot_debug.job_runtime import validate_workload_config
from tests.test_scenario_experiment import SCREEN, SMOKE, make_plan

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PrepareScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load("prepare_serverless_job_scenario", "scripts/prepare_serverless_job.py")

    def prepare(self, workload):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            os.chdir(temporary)
            try:
                Path("workload.json").write_text(json.dumps(workload), encoding="utf-8")
                return self.module.prepare({
                    "run_id": workload["run_id"], "project_id": "project-example123",
                    "image": "registry.example/robot-debug@sha256:" + "a" * 64,
                    "platform": "gpu-l40s-a", "preset": "1gpu-16vcpu-64gb",
                    "subnet_id": "vpcsubnet-example123", "bucket_id": "storagebucket-example123",
                    "hf_secret": "mbsec-example123@mbsecver-version123", "workload_file": "workload.json"})
            finally:
                os.chdir(previous)

    def test_the_deadline_guard_covers_all_three_scenario_modes(self):
        reduce = se.build_reduce_workload(make_plan(), run_id="scn-reduce-1")
        for base in (SMOKE, SCREEN, reduce):
            with self.subTest(mode=base["mode"]):
                with self.assertRaisesRegex(self.module.ConfigError, "deadline"):
                    self.prepare(dict(base, deadline_seconds=999))
                self.assertIn("--dry-run", self.prepare(dict(base, deadline_seconds=1000)))

    def test_every_scenario_mode_is_a_batch_style_mode(self):
        for mode in se.SCENARIO_MODES:
            self.assertIn(mode, self.module._BATCH_MODES)

    def test_recommended_deadlines_pass_the_guard_and_the_runtime(self):
        reduce = se.build_reduce_workload(make_plan(), run_id="scn-reduce-1")
        for base in (SMOKE, SCREEN, reduce):
            recommended = se.recommended_deadline_seconds(
                base["mode"], validate_workload_config(dict(base)))
            self.assertIn("--dry-run", self.prepare(dict(base, deadline_seconds=recommended)))


class MakeWorkloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load("make_scenario_workload", "scripts/make_scenario_workload.py")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def run_cli(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.module.main([str(item) for item in argv])
        return code, json.loads(out.getvalue().splitlines()[-1])

    def test_index_ranges(self):
        self.assertEqual(list(range(10)), self.module.parse_indices("0-9"))
        self.assertEqual([0, 3, 5, 7, 8], self.module.parse_indices("0,3,5,7-8"))
        with self.assertRaises(self.module.UsageError):
            self.module.parse_indices("a-b")

    def test_smoke_file_gets_the_recommended_deadline(self):
        out = self.root / "smoke.json"
        code, printed = self.run_cli("smoke", "--run-id", "scn-smoke-1", "--out", out)
        self.assertEqual(0, code)
        workload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(se.recommended_deadline_seconds("scenario-smoke", {"task_id": 0}),
                         workload["deadline_seconds"])
        self.assertEqual(printed["deadline_seconds"], workload["deadline_seconds"])
        self.assertEqual(("libero_10", 0), (workload["suite"], workload["task_id"]))

    def test_screen_file_covers_the_requested_tasks_and_starts(self):
        out = self.root / "screen.json"
        code, _ = self.run_cli("screen", "--run-id", "scn-screen-1", "--out", out, "--tasks", "0-9", "--starts", "0-9")
        self.assertEqual(0, code)
        workload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual((list(range(10)), list(range(10)), 4), (
            workload["task_ids"], workload["start_indices"], workload["confirm_attempts"]))
        self.assertEqual(2940, workload["deadline_seconds"])

    def test_reduce_file_comes_from_a_plan(self):
        plan = self.root / "plan.json"
        plan.write_text(json.dumps(make_plan()), encoding="utf-8")
        out = self.root / "reduce.json"
        code, printed = self.run_cli("reduce", "--run-id", "scn-reduce-1", "--out", out, "--plan", plan,
                                     "--max-candidates", 12)
        self.assertEqual(0, code)
        workload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(12, workload["max_candidates"])
        self.assertEqual("scenario-reduce", printed["mode"])
        self.assertLess(workload["deadline_seconds"], se.recommended_deadline_seconds("scenario-reduce", {}) + 1)

    def test_bad_input_is_refused_without_writing(self):
        out = self.root / "bad.json"
        code, printed = self.run_cli("screen", "--run-id", "scn-screen-1", "--out", out, "--tasks", "0", "--starts", "0-99")
        self.assertEqual(2, code)
        self.assertIn("error", printed)
        self.assertFalse(out.exists())
        plan = self.root / "plan.json"
        plan.write_text("{}", encoding="utf-8")
        code, _ = self.run_cli("reduce", "--run-id", "scn-reduce-1", "--out", out, "--plan", plan)
        self.assertEqual(2, code)

    def test_an_existing_file_is_not_overwritten_without_force(self):
        out = self.root / "smoke.json"
        self.run_cli("smoke", "--run-id", "scn-smoke-1", "--out", out)
        code, _ = self.run_cli("smoke", "--run-id", "scn-smoke-1", "--out", out)
        self.assertEqual(2, code)
        code, _ = self.run_cli("smoke", "--run-id", "scn-smoke-2", "--out", out, "--force")
        self.assertEqual(0, code)


if __name__ == "__main__":
    unittest.main()
