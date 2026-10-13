"""The scenario report and the case record."""

from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest

from robot_debug import scenario_experiment as se
from robot_debug.scenario_import import load_scenario_candidate
from tests.scenario_world import ScenarioWorld
from tests.test_scenario_experiment import SCREEN, RunTestCase, make_plan

ROOT = Path(__file__).resolve().parents[1]


def load_script():
    spec = importlib.util.spec_from_file_location("report_scenario_reduction", ROOT / "scripts" / "report_scenario_reduction.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DescribeTests(unittest.TestCase):
    def rows(self):
        return [
            {"entity": "akita_black_bowl_1", "position": {"distance_m": 0.08}, "rotation": {"angle_deg": 30.0},
             "joints": []},
            {"entity": "robot", "position": None, "rotation": None,
             "joints": [{"name": "j1", "offset": 0.1, "unit": "rad"}, {"name": "j2", "offset": 0.2, "unit": "rad"}]},
        ]

    def test_a_rotation_reads_like_the_plan_example(self):
        sentence = se.describe_minimal_cause({"akita_black_bowl_1": {"rotation": 14 / 30}}, self.rows(),
                                             reference=7, bisection_steps=4)
        self.assertTrue(sentence.startswith(
            "Rotating akita_black_bowl_1 by 14 degrees (of the original 30) is enough to make the policy fail"))
        self.assertIn("from the passing start 7", sentence)
        self.assertIn("at least 4 of 5 attempts", sentence)
        self.assertIn("within 1/16", sentence)

    def test_position_and_joints_and_several_parts(self):
        sentence = se.describe_minimal_cause(
            {"akita_black_bowl_1": {"position": 0.5}, "robot": {"joints": 0.25}}, self.rows())
        self.assertIn("Moving akita_black_bowl_1 by 4 cm (of the original 8 cm) and moving 2 joints of robot "
                      "25% of the way", sentence)
        self.assertIn(" are enough ", sentence)

    def test_an_unfinished_reduction_says_so_and_an_empty_one_claims_nothing(self):
        self.assertIn("stopped early", se.describe_minimal_cause(
            {"akita_black_bowl_1": {"position": 1.0}}, self.rows(), reduced=False))
        self.assertIn("No smaller cause", se.describe_minimal_cause({}, self.rows()))


class ReportTests(RunTestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def reduce_summary(self, **world_options):
        (self.root / "model-resolution.json").write_text(json.dumps({"schema_version": 1, "repositories": {
            "nvidia/gr00t17-lerobot-libero_10-640": {"revision": "5ee08ab" + "0" * 33, "pinned": True}}}),
            encoding="utf-8")
        world = ScenarioWorld(item_seconds=0.0, **world_options)
        self.run_mode(world, "scenario-reduce", se.build_reduce_workload(make_plan(), run_id="scn-reduce-1"))
        return self.root / "scenario" / se.SUMMARY_NAME

    def screen_summary(self):
        world = ScenarioWorld(item_seconds=0.0)
        self.run_mode(world, "scenario-screen", SCREEN)
        target = self.root / "screen-summary.json"
        target.write_text((self.root / "scenario" / se.SUMMARY_NAME).read_text(encoding="utf-8"), encoding="utf-8")
        return target

    def run_cli(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.script.main([str(item) for item in argv])
        return code, json.loads(out.getvalue().splitlines()[-1])

    def test_the_reduction_report_has_every_section_and_the_plain_sentence(self):
        summary = self.reduce_summary()
        code, printed = self.run_cli(summary, "--force")
        self.assertEqual(0, code)
        text = (summary.parent / "scenario_reduction_report.md").read_text(encoding="utf-8")
        for heading in ("# Scenario reduction: put the soup in the basket", "### Minimal cause",
                        "## Differences between the failing start and the reference", "## Hypothesis",
                        "## Candidates", "## Effort", "## Videos"):
            self.assertIn(heading, text)
        self.assertIn("Moving alphabet_soup_1 by 6.2 cm (of the original 50 cm) is enough to make the policy fail "
                      "from the passing start 4 (at least 4 of 5 attempts)", text)
        self.assertIn("Verdict (top-ranked entity against the surviving entities): **not applicable (the fixed "
                      "order is a search order, not a model hypothesis)**", text)
        self.assertIn("fixed order", text)
        self.assertIn("local minimum", text)
        self.assertIn("| alphabet_soup_1 | 50.0 | - |", text)
        self.assertIn("| alphabet_soup_1 | position | 0.125 | 0.0625 | 0.0625 | - |", text)
        # Four failures fix the decision; a fifth, already running attempt may or may not be
        # recorded in time, so the exact outcome string depends on thread timing.
        self.assertRegex(text, r"\| 0 \| gate \| failing \| - \| (F ){3}F( F)? \| reproduces \| True \|")
        self.assertIn("Invalid scenes (never counted as failures): none", text)
        self.assertIn("a modelled count, not a measured saving", text)

    def test_the_case_record_holds_the_replay_recipe_videos_and_hypothesis(self):
        summary = self.reduce_summary()
        code, printed = self.run_cli(summary, "--force", "--candidate-out", summary.parent / "replay.json")
        self.assertEqual(0, code)
        case = json.loads((summary.parent / printed["case"]).read_text(encoding="utf-8"))
        self.assertRegex(case["case_id"], r"^[0-9a-f]{64}$")
        self.assertEqual(case["case_id"], printed["case_id"])
        self.assertEqual(("libero_10", 0, 9, 4), (case["suite"], case["task_id"], case["failing_start"],
                                                 case["reference_start"]))
        self.assertEqual({"alphabet_soup_1": {"position": 0.125}}, case["minimal"]["selection"])
        self.assertEqual({"original", "minimal", "reference"}, set(case["videos"]))
        self.assertIsNone(case["hypothesis"]["verdict"])
        self.assertEqual("fixed_order", case["hypothesis"]["source"])
        self.assertIsNone(case["explanation"])
        self.assertEqual(case["replay"]["candidate"], load_scenario_candidate(summary.parent / "replay.json"))
        self.assertEqual("hybrid", case["replay"]["candidate"]["source"]["kind"])
        self.assertEqual({"attempts": 5, "required_failures": 4}, case["replay"]["gate"])
        self.assertEqual("nvidia/gr00t17-lerobot-libero_10-640", case["checkpoint"]["id"])
        self.assertEqual("5ee08ab" + "0" * 33, case["checkpoint"]["revision"])
        text = (summary.parent / "scenario_reduction_report.md").read_text(encoding="utf-8")
        self.assertIn("- Checkpoint: `nvidia/gr00t17-lerobot-libero_10-640` at revision `5ee08ab", text)

    def test_a_model_order_is_reported_with_its_verdict(self):
        plan = make_plan()
        plan["order_source"] = "model"
        plan["hypothesis"].update(source="model", model="test/model", tier="ultra", text="The soup matters.",
                                  fallback_reason=None)
        world = ScenarioWorld(item_seconds=0.0)
        self.run_mode(world, "scenario-reduce", se.build_reduce_workload(plan, run_id="scn-reduce-1"))
        summary = self.root / "scenario" / se.SUMMARY_NAME
        code, printed = self.run_cli(summary, "--force")
        text = (summary.parent / "scenario_reduction_report.md").read_text(encoding="utf-8")
        self.assertIn("Verdict (top-ranked entity against the surviving entities): **confirmed**", text)
        self.assertIn("Model: test/model", text)
        case = json.loads((summary.parent / printed["case"]).read_text(encoding="utf-8"))
        self.assertEqual("confirmed", case["hypothesis"]["verdict"])

    def test_the_case_id_is_stable_for_the_same_result(self):
        first = se.build_case(json.loads(self.reduce_summary().read_text(encoding="utf-8")))
        second = se.build_case(json.loads(self.reduce_summary().read_text(encoding="utf-8")))
        self.assertEqual(first["case_id"], second["case_id"])

    def test_an_unreduced_run_reports_honestly(self):
        from tests.scenario_world import FakeSimulation

        sim = FakeSimulation(flaky=lambda state, params, count: "success" if abs(state[4] - 0.9) < 1e-9 else None)
        world = ScenarioWorld(sim, item_seconds=0.0)
        self.run_mode(world, "scenario-reduce", se.build_reduce_workload(make_plan(), run_id="scn-reduce-1"))
        summary = self.root / "scenario" / se.SUMMARY_NAME
        code, printed = self.run_cli(summary, "--force")
        self.assertEqual(0, code)
        text = (summary.parent / "scenario_reduction_report.md").read_text(encoding="utf-8")
        self.assertIn("No minimal cause was established (stop reason `failing_not_reproducible`)", text)
        self.assertIn("**not applicable (the fixed order", text)
        case = json.loads((summary.parent / printed["case"]).read_text(encoding="utf-8"))
        self.assertFalse(case["reduced"])
        self.assertIsNone(case["replay"]["candidate"])
        self.assertIsNone(case["hypothesis"]["verdict"])
        code, _ = self.run_cli(summary, "--force", "--candidate-out", summary.parent / "x.json")
        self.assertEqual(2, code)

    def test_the_screen_report_lists_outcomes_and_reproducible_failures(self):
        screen = self.screen_summary()
        code, _ = self.run_cli(screen, "--force")
        self.assertEqual(0, code)
        text = (screen.parent / "scenario_screen_report.md").read_text(encoding="utf-8")
        self.assertIn("| 0 | 9 | F F F F F | reproduces | 520 |", text)
        self.assertIn("| 0 | 2 | S | passed | 100 |", text)
        self.assertIn("task 0 start 9", text)
        self.assertIn("- task 0: put the alphabet soup in the basket", text)

    def test_a_reduction_report_can_include_its_screen(self):
        screen = self.screen_summary()
        summary = self.reduce_summary()
        code, _ = self.run_cli(summary, "--force", "--screen", screen)
        self.assertEqual(0, code)
        text = (summary.parent / "scenario_reduction_report.md").read_text(encoding="utf-8")
        self.assertIn("## Screen", text)
        self.assertLess(text.index("## Screen"), text.index("## Result"))

    def test_bad_inputs_are_refused(self):
        bad = self.root / "bad.json"
        bad.write_text("{}", encoding="utf-8")
        self.assertEqual(2, self.run_cli(bad)[0])
        self.assertEqual(2, self.run_cli(self.root / "absent.json")[0])
        smoke = self.root / "smoke.json"
        smoke.write_text(json.dumps({"schema_version": 1, "mode": "scenario-smoke"}), encoding="utf-8")
        self.assertEqual(2, self.run_cli(smoke)[0])
        summary = self.reduce_summary()
        self.assertEqual(2, self.run_cli(summary, "--screen", summary)[0])
        out = summary.parent / "scenario_reduction_report.md"
        out.write_text("x", encoding="utf-8")
        self.assertEqual(2, self.run_cli(summary)[0], "an existing report is not overwritten without --force")

    def test_pipes_in_text_do_not_break_tables(self):
        self.assertEqual("a/b", self.script._cell("a|b"))


if __name__ == "__main__":
    unittest.main()
