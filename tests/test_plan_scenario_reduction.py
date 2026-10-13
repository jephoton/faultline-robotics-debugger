"""Planning CLI: references, order and hypothesis into a reduce config (no network)."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from robot_debug import scenario_state as ss
from robot_debug.token_factory import TokenFactoryError
from tests.scenario_fakes import base_state, synthetic_layout, with_object_pose

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "plan_scenario_reduction.py"
KEY = "TEST-SECRET-DO-NOT-LOG"
INSTRUCTION = "put the soup in the basket"


def load_script():
    spec = importlib.util.spec_from_file_location("plan_scenario_reduction_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def make_summary():
    layout = synthetic_layout()
    failing = base_state(layout)
    failing = with_object_pose(failing, 3, dxyz=(0.05, 0.0, 0.0), z_degrees=40.0)
    near = with_object_pose(failing, 3, dxyz=(-0.03, 0.0, 0.0), z_degrees=-10.0)      # soup 2 cm, 10 degrees
    far = base_state(layout)
    same = failing.copy()
    starts = {
        "0": {"outcomes": ["policy_failure"] * 5, "state": failing.tolist(), "steps": 520},
        "1": {"outcomes": ["success"], "state": near.tolist()},
        "2": {"outcomes": ["success"], "state": far.tolist()},
        "3": {"outcomes": ["policy_failure", "success", "success", "success", "success"],
              "state": near.tolist()},
        "4": {"outcomes": ["success"], "state": same.tolist()},          # identical to the failing start
        "5": {"outcomes": ["success"], "state": with_object_pose(
            failing, 11, dxyz=(0.0, 0.2, 0.0)).tolist()},
    }
    return {"suite": "libero_10", "tasks": {"3": {
        "instruction": INSTRUCTION, "layout": layout, "starts": starts}}}


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.script = load_script()
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.summary_path = self.root / "screen.json"
        self.summary_path.write_text(json.dumps(make_summary()), encoding="utf-8")
        self.out = self.root / "reduce-config.json"

    def run_main(self, *extra, request=None, load_key=None, task=3, start=0):
        argv = [str(self.summary_path), "--task", str(task), "--start", str(start),
                "--out", str(self.out), *extra]
        kwargs = {}
        if request is not None:
            kwargs["request"] = request
        if load_key is not None:
            kwargs["load_key"] = load_key
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = self.script.main(argv, **kwargs)
        return code, json.loads(buffer.getvalue()), buffer.getvalue()

    def fake_request(self, calls, ranking=None):
        def request(instruction, differences, api_key, **kwargs):
            calls.append((instruction, differences, api_key, kwargs))
            order = ranking or [row["entity"] for row in differences]
            return {"source": "model", "ranking": order, "hypothesis": "The soup turn matters.",
                    "completed": [], "model": "test/model", "tier": "ultra", "fallback_reason": None,
                    "provenance": {"model": "test/model"}, "raw_content": "{}"}
        return request

    def test_no_llm_plan_uses_the_fixed_order_and_nearest_references(self):
        code, report, _ = self.run_main("--no-llm")
        self.assertEqual(code, 0)
        config = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(config["schema_version"], 1)
        self.assertEqual((config["suite"], config["task_id"], config["instruction"]),
                         ("libero_10", 3, INSTRUCTION))
        self.assertEqual(config["failing"]["start_index"], 0)
        self.assertEqual(len(config["failing"]["state"]), config["layout"]["state_length"])
        # start 4 equals the failing start, start 3 failed an attempt: neither is a reference
        self.assertEqual([r["start_index"] for r in config["references"]], [1, 2, 5])
        self.assertLess(config["references"][0]["distance"], config["references"][1]["distance"])
        self.assertTrue(all(r["differences"] for r in config["references"]))
        primary = config["references"][0]["differences"]
        self.assertEqual(config["order"], ss.fixed_order(primary))
        self.assertEqual(config["order_source"], "fixed_order")
        self.assertEqual(config["hypothesis"]["fallback_reason"], "llm_disabled")
        self.assertIsNone(config["hypothesis"]["text"])
        self.assertEqual(report["order_source"], "fixed_order")
        self.assertNotIn("state", report)

    def test_the_model_ranking_becomes_the_order_and_the_request_is_minimal(self):
        calls = []
        code, report, _ = self.run_main(request=self.fake_request(calls, ranking=["soup_1"]),
                                        load_key=lambda path: KEY)
        self.assertEqual(code, 0)
        (instruction, differences, api_key, kwargs), = calls
        self.assertEqual(instruction, INSTRUCTION)
        self.assertEqual(api_key, KEY)
        self.assertEqual(kwargs["fixed_order"], ss.fixed_order(differences))
        config = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(config["order"], ["soup_1"])
        self.assertEqual(config["order_source"], "model")
        self.assertEqual(config["hypothesis"]["text"], "The soup turn matters.")
        self.assertEqual(config["hypothesis"]["model"], "test/model")
        self.assertEqual(report["model"], "test/model")

    def test_the_key_is_never_written_or_printed(self):
        calls = []
        _, _, printed = self.run_main(request=self.fake_request(calls), load_key=lambda path: KEY)
        self.assertNotIn(KEY, printed)
        self.assertNotIn(KEY, self.out.read_text(encoding="utf-8"))

    def test_the_env_file_path_is_passed_to_the_loader_and_not_stored(self):
        seen = []
        env = self.root / ".env"
        calls = []
        self.run_main("--env-file", str(env), request=self.fake_request(calls),
                      load_key=lambda path: seen.append(path) or KEY)
        self.assertEqual(seen, [env])
        self.assertNotIn(str(self.root), self.out.read_text(encoding="utf-8"))

    def test_a_missing_key_falls_back_and_says_so(self):
        def missing(path):
            raise TokenFactoryError("missing_api_key")
        calls = []
        code, report, _ = self.run_main(request=self.fake_request(calls), load_key=missing)
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])
        self.assertEqual(report["fallback_reason"], "missing_api_key")
        self.assertEqual(report["order_source"], "fixed_order")

    def test_a_model_fallback_is_recorded(self):
        def fallback(instruction, differences, api_key, **kwargs):
            return {"source": "fixed_order", "ranking": kwargs["fixed_order"], "hypothesis": None,
                    "completed": [], "model": "test/model", "tier": "ultra",
                    "fallback_reason": "invalid_json", "provenance": None, "raw_content": "oops"}
        code, report, _ = self.run_main(request=fallback, load_key=lambda path: KEY)
        self.assertEqual(code, 0)
        self.assertEqual(report["fallback_reason"], "invalid_json")
        config = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(config["hypothesis"]["raw_content"], "oops")

    def test_reference_count_is_honoured(self):
        self.run_main("--no-llm", "--references", "1")
        config = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual([r["start_index"] for r in config["references"]], [1])

    def test_a_start_that_does_not_fail_four_of_five_is_refused(self):
        for start in (1, 3, 4):
            with self.subTest(start=start):
                code, report, _ = self.run_main("--no-llm", start=start)
                self.assertEqual(code, 2)
                self.assertIn("error", report)
                self.assertFalse(self.out.exists())

    def test_unknown_task_or_start_and_bad_arguments(self):
        self.assertEqual(self.run_main("--no-llm", task=9)[0], 2)
        self.assertEqual(self.run_main("--no-llm", start=99)[0], 2)
        self.assertEqual(self.run_main("--no-llm", "--references", "0")[0], 2)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(self.script.main(["--nonsense"]), 2)

    def test_no_passing_start_is_an_error(self):
        summary = make_summary()
        for key in ("1", "2", "3", "4", "5"):
            del summary["tasks"]["3"]["starts"][key]
        self.summary_path.write_text(json.dumps(summary), encoding="utf-8")
        code, report, _ = self.run_main("--no-llm")
        self.assertEqual(code, 2)
        self.assertIn("no passing start", report["error"])

    def test_bad_layout_or_state_is_an_error(self):
        summary = make_summary()
        summary["tasks"]["3"]["starts"]["1"]["state"] = [0.0, 1.0]
        self.summary_path.write_text(json.dumps(summary), encoding="utf-8")
        code, report, _ = self.run_main("--no-llm")
        self.assertEqual(code, 2)
        summary = make_summary()
        summary["tasks"]["3"]["layout"]["state_length"] += 1
        self.summary_path.write_text(json.dumps(summary), encoding="utf-8")
        self.assertEqual(self.run_main("--no-llm")[0], 2)

    def test_existing_output_is_not_replaced_without_force(self):
        self.out.write_text("keep", encoding="utf-8")
        code, _, _ = self.run_main("--no-llm")
        self.assertEqual(code, 2)
        self.assertEqual(self.out.read_text(encoding="utf-8"), "keep")
        self.assertEqual(self.run_main("--no-llm", "--force")[0], 0)
        self.assertNotEqual(self.out.read_text(encoding="utf-8"), "keep")

    def test_unreadable_summary(self):
        self.summary_path.write_text("{", encoding="utf-8")
        self.assertEqual(self.run_main("--no-llm")[0], 2)

    def test_the_script_runs_end_to_end_without_network_when_the_model_is_skipped(self):
        env = dict(os.environ)
        env.pop("NEBIUS_API_KEY", None)
        completed = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), str(self.summary_path), "--task", "3", "--start", "0",
             "--no-llm", "--out", str(self.out)],
            capture_output=True, text=True, cwd=self.root, env=env, check=False, timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(self.out.exists())
        self.assertNotIn("\r", self.out.read_bytes().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
