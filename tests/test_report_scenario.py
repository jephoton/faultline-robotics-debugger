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
from tests import reduction_fixtures as rf
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
                                             reference=7, bisection_steps=4,
                                             parts=[self.part("akita_black_bowl_1", "rotation", 4)])
        self.assertTrue(sentence.startswith(
            "Rotating akita_black_bowl_1 by 14 degrees (of the original 30) is enough to make the policy fail"))
        self.assertIn("from the passing start 7", sentence)
        self.assertIn("at least 4 of 5 attempts", sentence)
        self.assertIn("within 1/16", sentence)

    @staticmethod
    def part(entity, component, steps_done):
        return {"entity": entity, "component": component, "steps_done": steps_done}

    def test_the_resolution_is_claimed_only_when_every_kept_part_finished_shrinking(self):
        selection = {"akita_black_bowl_1": {"position": 0.5}, "robot": {"joints": 0.25}}
        done = [self.part("akita_black_bowl_1", "position", 4), self.part("robot", "joints", 4)]
        sentence = se.describe_minimal_cause(selection, self.rows(), bisection_steps=4, parts=done)
        self.assertIn("resolved to within 1/16", sentence)
        self.assertNotIn("not fully shrunk", sentence)
        # One part stopped after two of four steps: no resolution claim for any size.
        partial = [self.part("akita_black_bowl_1", "position", 4), self.part("robot", "joints", 2)]
        sentence = se.describe_minimal_cause(selection, self.rows(), bisection_steps=4, parts=partial)
        self.assertNotIn("within 1/16", sentence)
        self.assertIn("sizes not fully shrunk", sentence)
        # A kept part with no shrink summary at all (the budget ended before it) is not shrunk either.
        missing = [self.part("akita_black_bowl_1", "position", 4)]
        sentence = se.describe_minimal_cause(selection, self.rows(), bisection_steps=4, parts=missing)
        self.assertIn("sizes not fully shrunk", sentence)
        sentence = se.describe_minimal_cause(selection, self.rows(), bisection_steps=4)
        self.assertIn("sizes not fully shrunk", sentence)

    def test_no_resolution_wording_when_shrinking_was_off(self):
        sentence = se.describe_minimal_cause({"robot": {"joints": 1.0}}, self.rows(), bisection_steps=0, parts=[])
        self.assertNotIn("1/", sentence)
        self.assertNotIn("shrunk", sentence)

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
        self.assertIn("| alphabet_soup_1 | position | 12.5% | 6.3% | 6.25 points (1/16) | - |", text)
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

    def summary_block(self, text):
        start = text.index("## Summary")
        end = text.index("\n## ", start + 5)
        return text[start:end]

    def test_a_completed_reduction_opens_with_a_summary_of_the_answer(self):
        summary = self.reduce_summary()
        self.assertEqual(0, self.run_cli(summary, "--force")[0])
        text = (summary.parent / "scenario_reduction_report.md").read_text(encoding="utf-8")
        self.assertLess(text.index("# Scenario reduction"), text.index("## Summary"))
        self.assertLess(text.index("## Summary"), text.index("## Result"))
        block = self.summary_block(text)
        self.assertIn("- Verdict: Reproduces. Applying the kept shifts to the passing reference makes the policy "
                      "fail at least 4 of 5 attempts.", block)
        self.assertIn("- Failing start: benchmark start 9.", block)
        self.assertIn("- Reference: benchmark start 4, the nearest start that passed.", block)
        self.assertIn("- Kept shift: alphabet_soup_1 position, 6.3 cm (12.5% of the full difference).", block)
        self.assertIn("- Status: Fully reduced: every kept shift was shrunk to within 1/16 of its original size.",
                      block)


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


class ContinuationSizeTableTests(unittest.TestCase):
    """Regression (October 19, run l10-start14): the table listed only the parts whose size search had
    finished in the last Job and left out milk_1, which the continuation Job shrank to 87.5%."""

    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def report(self, with_history=True):
        from tests.test_scenario_packet import ContinuationShrinkNotesTests, continuation_reductions

        first, second = continuation_reductions()
        summary = {"schema_version": 1, "mode": "scenario-reduce", "reduction": second, "videos": {},
                   "plan": rf.partial_plan(ranking=["robot", "basket_1", "milk_1", "orange_juice_1"]),
                   "differences": ContinuationShrinkNotesTests.DIFFERENCES, "checkpoint": None}
        reductions = [{"reduction": first}, {"reduction": second}] if with_history else None
        return self.script.build_report(summary, None, None, reductions)

    def test_every_kept_part_has_a_row_in_plain_words_with_percentages(self):
        text = self.report()
        self.assertIn("| entity | part | kept size | largest size that passed | precision | invalid sizes |", text)
        self.assertIn("| basket_1 | position | 93.8% | 87.5% | 6.25 points (1/16) | - |", text)
        self.assertIn("| robot | joints | 93.8% | 87.5% | 6.25 points (1/16) | - |", text)
        self.assertIn("| milk_1 | position | 87.5% | 75% | 12.5 points (1/8) | - |", text)
        self.assertIn("| orange_juice_1 | position | 100% | not shrunk | - | - |", text)
        self.assertNotIn("lower bound tested", text)
        self.assertIn("Sizes are shares of the full difference", text)

    def test_the_library_returns_every_rerun_with_the_reports_numbering(self):
        import re
        import tempfile

        from robot_debug.viewer.library import Library
        from tests.test_scenario_packet import ContinuationShrinkNotesTests, continuation_reductions

        first, second = continuation_reductions()
        summary = {"schema_version": 1, "mode": "scenario-reduce", "reduction": second, "videos": {},
                   "plan": rf.partial_plan(ranking=["robot", "basket_1", "milk_1", "orange_juice_1"]),
                   "differences": ContinuationShrinkNotesTests.DIFFERENCES, "checkpoint": None}
        case = se.build_case(summary, [{"reduction": first}, {"reduction": second}])
        self.assertEqual(len(second["candidates"]), len(case["reruns"]))
        self.assertLess(len(case["evidence"]), len(case["reruns"]))        # the key rows are fewer
        with tempfile.TemporaryDirectory() as directory:
            rows = Library(Path(directory))._scenario_block(case)["reruns"]
        self.assertEqual([c["index"] for c in second["candidates"]], [r["index"] for r in rows])
        self.assertEqual({"index", "phase", "role", "selection", "outcomes", "decision"}, set(rows[0]))
        text = self.script.build_report(summary, None, None, [{"reduction": first}, {"reduction": second}])
        table = text[text.index("## Candidates"):]
        numbers = [int(m.group(1)) for m in re.finditer(r"^\| (\d+) \| (?:gate|probe|ddmin|split|shrink) \|", table,
                                                         re.MULTILINE)]
        self.assertEqual(numbers, [r["index"] for r in rows])
        self.assertEqual(second["candidates"][8]["selection"], rows[8]["selection"])
        # a case saved before the full list was kept still shows its key rows
        old = {key: value for key, value in case.items() if key != "reruns"}
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual([e["index"] for e in case["evidence"]],
                             [r["index"] for r in Library(Path(directory))._scenario_block(old)["reruns"]])

    def test_without_the_other_jobs_the_last_jobs_candidates_still_cover_milk(self):
        self.assertIn("| milk_1 | position | 87.5% | 75% |", self.report(with_history=False))

    def test_invalid_sizes_are_listed_as_percentages(self):
        from tests.test_scenario_packet import continuation_reductions

        first, second = continuation_reductions()
        second["candidates"].append(rf.candidate(
            10, "shrink", {"robot": {"joints": 0.9375}, "basket_1": {"position": 0.9375}, "milk_1": {"position": 0.8125},
                           "orange_juice_1": {"position": 1.0}}, "invalid_scene"))
        summary = {"mode": "scenario-reduce", "reduction": second}
        rows = self.script.size_rows(summary, [{"reduction": first}, {"reduction": second}])
        self.assertEqual(["milk_1", "position", "87.5%", "75%", "12.5 points (1/8)", "81.3%"],
                         next(r for r in rows if r[0] == "milk_1"))


class SummaryTests(unittest.TestCase):
    """The summary section for results a Job can stop with, built from stored summaries."""

    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def summary(self, reduction=None, plan=None):
        reduction = dict(rf.partial_reduction(), **(reduction or {}))
        plan = dict(rf.partial_plan(), **(plan or {}))
        return {
            "schema_version": 1, "mode": "scenario-reduce", "plan": plan, "reduction": reduction,
            "differences": [
                {"entity": "soup", "kind": "object", "position": {"distance_m": 0.0289}, "rotation": None,
                 "joints": [], "distance": 2.89},
                {"entity": "cream", "kind": "object", "position": {"distance_m": 0.01},
                 "rotation": {"angle_deg": 20.0}, "joints": [], "distance": 3.0},
                {"entity": "milk", "kind": "object", "position": {"distance_m": 0.052}, "rotation": None,
                 "joints": [], "distance": 5.2},
                {"entity": "robot", "kind": "robot", "position": None, "rotation": None, "distance": 1.0,
                 "joints": [{"name": "j%d" % i, "offset": 0.0 if i else 2.6, "unit": "deg"} for i in range(6)]}],
            "videos": {}, "checkpoint": None}

    def block(self, **changes):
        text = self.script.build_report(self.summary(**changes))
        start = text.index("## Summary")
        return text[start:text.index("\n## ", start + 5)]

    def test_a_budget_stop_says_entity_minimal_and_sizes_not_fully_shrunk(self):
        block = self.block()
        self.assertIn("- Status: Stopped at the candidate budget: entity-minimal (each kept entity is needed), "
                      "sizes not fully shrunk.", block)
        self.assertIn("- Failing start: benchmark start 7.", block)
        self.assertIn("- Reference: benchmark start 28, the nearest start that passed.", block)

    def test_each_kept_shift_has_a_size_in_people_units_and_a_share(self):
        block = self.block()
        self.assertIn("- Kept shift: soup position, 2.5 cm (87.5% of the full difference).", block)
        self.assertIn("- Kept shift: cream position, 1.0 cm (100% of the full difference).", block)
        self.assertIn("- Kept shift: milk position, 5.2 cm (100% of the full difference).", block)
        self.assertIn("- Kept shift: robot joints, 6 joints, up to 2.3° (87.5% of the full difference).", block)

    def test_sizes_and_shares_use_the_case_pages_rounding(self):
        # 2.89 cm x 0.5 = 1.445 cm, shown with one decimal; 0.125 is 12.5%, 1/3 is 33.3%.
        reduction = {"final_selection": {"soup": {"position": 0.5}}}
        self.assertIn("soup position, 1.4 cm (50% of the full difference)", self.block(reduction=reduction))
        reduction = {"final_selection": {"soup": {"position": 0.125}, "cream": {"position": 1 / 3}}}
        block = self.block(reduction=reduction)
        self.assertIn("soup position, 0.4 cm (12.5% of the full difference)", block)
        self.assertIn("cream position, 0.3 cm (33.3% of the full difference)", block)

    def test_an_imported_start_is_named_by_its_file_hash_and_the_start_it_came_from(self):
        plan = {"failing_start": None, "failing_import": {"file_sha256": "f00dfeed" * 8, "state_sha256": "ab" * 32},
                "failing_source": {"kind": "benchmark", "init_state_index": 14}}
        self.assertIn("- Failing start: imported file f00dfeedf00d (from benchmark start 14).",
                      self.block(plan=plan))
        plan["failing_source"] = {"kind": "file"}
        self.assertIn("- Failing start: imported file f00dfeedf00d.", self.block(plan=plan))

    def test_a_fully_reduced_run_says_so(self):
        block = self.block(reduction={"stop_reason": "reduced", "reduced": True, "bisection_steps": 3})
        self.assertIn("- Status: Fully reduced: every kept shift was shrunk to within 1/8 of its original size.",
                      block)

    def test_a_run_cut_short_before_entity_minimal_is_not_called_minimal(self):
        block = self.block(reduction={"entity_minimal": False, "stop_reason": "deadline_exhausted"})
        self.assertIn("- Status: Stopped at the time limit: not yet entity-minimal; this is the smallest cause "
                      "found so far.", block)

    def test_a_run_without_a_cause_says_not_reproduced(self):
        block = self.block(reduction={"stop_reason": "failing_not_reproducible", "final_selection": None,
                                      "entity_minimal": False, "reference": None})
        self.assertIn("- Verdict: Not reproduced.", block)
        self.assertIn("- Reference: none was established.", block)
        self.assertNotIn("Kept shift", block)
        self.assertIn("- Status: Stopped because the failing start did not fail reliably: no minimal cause was "
                      "established.", block)


class PartialReductionReportTests(unittest.TestCase):
    """A budget-exhausted, entity-minimal run: the summary stored no verdict, the report recomputes it."""

    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write_summary(self, **changes):
        summary = {
            "schema_version": 1, "mode": "scenario-reduce", "plan": rf.partial_plan(),
            "reduction": rf.partial_reduction(), "differences": [
                {"entity": "soup", "kind": "object", "position": {"distance_m": 0.0289}, "rotation": None,
                 "joints": [], "distance": 2.89},
                {"entity": "sauce", "kind": "object", "position": {"distance_m": 0.007}, "rotation": None,
                 "joints": [], "distance": 0.7}],
            "hypothesis_verdict": None, "videos": {}, "minimal_candidate": None, "checkpoint": None,
            "total_seconds": 1000, "startup_seconds": 100}
        summary.update(changes)
        path = self.root / "scenario_summary.json"
        path.write_text(json.dumps(summary), encoding="utf-8")
        return path

    def report(self, **changes):
        summary = self.write_summary(**changes)
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.script.main([str(summary), "--force"])
        self.assertEqual(0, code, out.getvalue())
        printed = json.loads(out.getvalue().splitlines()[-1])
        text = (self.root / "scenario_reduction_report.md").read_text(encoding="utf-8")
        return text, json.loads((self.root / printed["case"]).read_text(encoding="utf-8"))

    def section(self, text):
        start = text.index("## Hypothesis vs result")
        end = text.find("\n## ", start + 5)
        return text[start:end if end != -1 else None]

    def test_the_section_is_recomputed_when_the_summary_has_no_verdict(self):
        text, case = self.report()
        section = self.section(text)
        self.assertIn("Scope: entity-minimal, sizes only partly shrunk (stop reason `budget_exhausted`)", section)
        self.assertIn("Measured label for the top-ranked entity (soup): **necessary_not_sufficient**", section)
        self.assertIn("recomputed from the candidates in this summary", section)
        self.assertIn("Reverting only the soup restores success", section)
        self.assertIn("Ranking: soup, sauce, robot, cream, milk", section)
        self.assertIn("| 1 | soup | yes | yes | no | necessary_not_sufficient |", section)
        self.assertIn("| 2 | sauce | no | no | no | not_in_final |", section)
        self.assertIn("| 3 | robot | yes | not tested | no | inconclusive |", section)

    def test_the_evidence_shows_the_reruns_behind_each_cell(self):
        section = self.section(self.report()[0])
        self.assertIn("soup, sufficient: no. Candidate #2 (probe) changed only soup (position 1): S S S S, "
                      "did not reproduce.", section)
        self.assertIn("soup, necessary: yes. Candidate #7 (ddmin) kept cream (position 1); milk (position 1); "
                      "robot (joints 1): S S S S, did not reproduce (same entities and parts as the final "
                      "selection without soup, other sizes).", section)
        self.assertIn("sauce, necessary: no. Not in the final selection; candidate #10 without it still "
                      "reproduced: S F F F F.", section)

    def test_it_says_plainly_what_the_model_got_right_and_missed(self):
        section = self.section(self.report()[0])
        self.assertIn("Right: the top-ranked entity (soup) is needed. The final selection without it did not "
                      "reproduce the failure.", section)
        self.assertIn("Missed: soup alone does not reproduce the failure, so it is necessary but not "
                      "sufficient.", section)
        self.assertIn("Also in the final selection but not in the top 3: cream, milk.", section)
        self.assertIn("2 of the top 3 ranked entities are in the final selection (4 entities survive).", section)
        self.assertIn("does not interpret the prose", section)

    def test_the_case_record_gets_the_measurement_and_scope(self):
        _, case = self.report()
        self.assertIsNone(case["hypothesis"]["verdict"])
        self.assertEqual("necessary_not_sufficient", case["hypothesis"]["measured_verdict"])
        self.assertEqual("entity_minimal_sizes_partial", case["hypothesis"]["result_scope"])
        self.assertEqual("necessary_not_sufficient", case["hypothesis"]["measurement"]["verdict"])

    def test_a_stored_measurement_that_disagrees_is_flagged(self):
        stored = dict(se.measurement_for(rf.partial_plan(), rf.partial_reduction()), verdict="confirmed")
        text, _ = self.report(hypothesis_measurement=stored)
        section = self.section(text)
        self.assertIn("Warning: the Job recorded measured label `confirmed`", section)
        self.assertNotIn("recomputed from the candidates", section)

    def test_a_plan_file_fills_what_the_summary_plan_lacks(self):
        plan = rf.partial_plan()
        bare = {key: plan[key] for key in ("suite", "task_id", "instruction", "failing_start")}
        summary = self.write_summary(plan=bare)
        plan_path = self.root / "plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.script.main([str(summary), "--force", "--plan", str(plan_path)])
        self.assertEqual(0, code, out.getvalue())
        text = (self.root / "scenario_reduction_report.md").read_text(encoding="utf-8")
        self.assertIn("Measured label for the top-ranked entity (soup): **necessary_not_sufficient**", text)

    def test_a_plan_for_another_task_is_refused(self):
        summary = self.write_summary()
        other = dict(rf.partial_plan(), task_id=9)
        plan_path = self.root / "plan.json"
        plan_path.write_text(json.dumps(other), encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.script.main([str(summary), "--force", "--plan", str(plan_path)])
        self.assertEqual(2, code)
        self.assertIn("does not match", out.getvalue())

    def test_a_fixed_order_run_has_no_comparison(self):
        text, case = self.report(plan=rf.partial_plan(order_source="fixed_order"))
        section = self.section(text)
        self.assertIn("not applicable", section)
        self.assertNotIn("Measured label", section)
        self.assertIsNone(case["hypothesis"]["measurement"])

    def test_a_run_that_is_not_entity_minimal_has_no_comparison(self):
        reduction = dict(rf.partial_reduction(), entity_minimal=False)
        text, _ = self.report(reduction=reduction)
        self.assertIn("not available", self.section(text))


if __name__ == "__main__":
    unittest.main()
