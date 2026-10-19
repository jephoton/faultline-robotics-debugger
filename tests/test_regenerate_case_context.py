"""scripts/regenerate_case_context.py with fakes only: no Token Factory, no Tavily, no cloud Job."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

from robot_debug import pipeline_research as pr
from robot_debug import scenario_experiment as se
from robot_debug.viewer.library import Library
from tests import reduction_fixtures as rf
from tests.test_next_steps import GOOD
from tests.test_scenario_packet import ContinuationShrinkNotesTests, continuation_reductions

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "regenerate_case_context.py"
KEY = "TEST-SECRET-DO-NOT-LOG"


def load_script():
    spec = importlib.util.spec_from_file_location("regenerate_case_context_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value, indent=1, sort_keys=True), encoding="utf-8")


QUERIES = [{"query": "q", "retrieved_at": "2026-10-19T01:00:00Z", "results": [
    {"source_id": "S{}".format(i), "title": "Paper {}".format(i), "url": "https://example.invalid/{}".format(i),
     "snippet": "Studies robustness of robot policies.", "score": 0.9 - i / 20} for i in (1, 2, 3)]}]
OLD_RESEARCH = {"schema_version": 1, "kind": "diagnosis_research", "created_at": "2026-10-19T01:00:00Z",
                "queries": QUERIES, "summary": {"status": "rejected", "related_work": [], "limitations": [],
                                                "provenance": {"model": "nano"}}}


class Fakes:
    """Token Factory and registration fakes that count their calls."""

    def __init__(self, next_steps_text=None, explain_status="validated-structure"):
        self.explain_calls, self.steps_calls, self.keys = [], [], 0
        self.next_steps_text, self.explain_status = next_steps_text, explain_status

    def explain(self, case_path, out_path, env_file, label):
        self.explain_calls.append((Path(case_path).name, label))
        write(out_path, {"kind": "scenario_explanation", "interpretation_status": self.explain_status,
                         "interpretation": {"observations": ["new"]}, "provenance": {"model": "ultra"}})
        return {"interpretation_status": self.explain_status}

    def load_nebius_key(self, env_file=None):
        self.keys += 1
        return KEY

    def request_next_steps(self, context, key):
        assert key == KEY
        self.steps_calls.append(context)
        return {"response_json": self.next_steps_text if self.next_steps_text is not None else GOOD_FOR(context),
                "provenance": {"model": "ultra", "request_status": "completed"}}

    def deps(self, script, registered=None):
        research = pr.ResearchDeps(lambda *a, **k: self.fail(), lambda *a, **k: self.fail(), self.load_nebius_key,
                                   self.request_next_steps, Path("l"), Path("c"))
        import datetime as dt

        def reregister(run_dir, root):
            from robot_debug.case_register import reregister_run

            ids = reregister_run(run_dir, root)
            if registered is not None:
                registered.append((run_dir, root))
            return ids

        return script.Deps(self.explain, research, reregister, lambda: dt.datetime(2026, 10, 19, 12, 0, 0))

    def fail(self):
        raise AssertionError("no Tavily call may be made")


def GOOD_FOR(context):
    ids = [s["source_id"] for s in context["sources"]]
    return json.dumps({"next_steps": [{"text": "Rerun nearby starts to see how wide the failing region is.",
                                       "cites": [ids[0]]},
                                      {"text": "Add this case to the evaluation suite as a regression test.",
                                       "cites": [ids[-1]]}]})


class RunFolderTests(unittest.TestCase):
    def setUp(self):
        self.script = load_script()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.artifacts = Path(directory.name)
        self.run = self.artifacts / "runs" / "l10-start14-20261019T032219Z"
        self.diagnoses = self.artifacts / "diagnoses"

    def scenario_run(self, research=OLD_RESEARCH):
        first, second = continuation_reductions()
        plan = rf.partial_plan(ranking=["robot", "basket_1", "milk_1", "orange_juice_1"])
        for name, reduction in (("reduce", first), ("reduce2", second)):
            write(self.run / "jobs" / name / "evidence" / "scenario" / "scenario_summary.json",
                  {"mode": "scenario-reduce", "reduction": reduction, "plan": plan, "videos": {},
                   "differences": ContinuationShrinkNotesTests.DIFFERENCES})
        write(self.run / "jobs" / "screen" / "evidence" / "scenario" / "scenario_summary.json",
              {"mode": "scenario-screen", "suite": "libero_10", "tasks": {}, "stop_reason": None})
        steps = {name: {"summary": "jobs/{}/evidence/scenario/scenario_summary.json".format(
            "screen" if name == "screen" else name)} for name in ("screen", "reduce", "reduce2")}
        write(self.run / "steps.json", {"mode": "diagnose", "name": "l10", "run": {"route": "layout"},
                                        "steps": steps, "schema_version": 1})
        write(self.run / "ledger.json", {"hourly_usd": 1.7})
        summary = {"mode": "scenario-reduce", "reduction": second, "videos": {}, "differences":
                   ContinuationShrinkNotesTests.DIFFERENCES,
                   "plan": rf.partial_plan(ranking=["robot", "basket_1", "milk_1", "orange_juice_1"])}
        case = se.build_case(summary)                                   # as an earlier run wrote it
        case["minimal"].pop("shrink_history")
        case.pop("reruns")
        write(self.run / "case.json", case)
        write(self.run / "report.md", "# old report\n")
        write(self.run / "explanation.json", {"kind": "scenario_explanation", "interpretation_status":
                                              "validated-structure", "interpretation": {"observations": ["old"]}})
        if research is not None:
            write(self.run / "research.json", dict(research, case_id=case["case_id"]))
        return case

    def snapshot(self):
        return {str(p.relative_to(self.run)): p.read_bytes() for p in sorted(self.run.rglob("*")) if p.is_file()}

    def go(self, fakes, **kwargs):
        lines = []
        status = self.script.regenerate(self.run, deps=fakes.deps(self.script), diagnoses_root=self.diagnoses,
                                        out=lines.append, **kwargs)
        return status, "\n".join(lines)

    def test_a_dry_run_lists_the_calls_and_the_cost_and_changes_nothing(self):
        self.scenario_run()
        before = self.snapshot()
        fakes = Fakes()
        status, text = self.go(fakes, dry_run=True)
        self.assertEqual(0, status)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(self.diagnoses.exists())
        self.assertEqual((0, [], []), (fakes.keys, fakes.explain_calls, fakes.steps_calls))
        self.assertIn("explanation: 1 Token Factory call, nvidia/Nemotron-3-Ultra-550b-a55b", text)
        self.assertIn("next steps: 1 call per case (2 if the first answer needs repair), "
                      "nvidia/Nemotron-3-Ultra-550b-a55b", text)
        self.assertIn("3 cached source(s)", text)
        self.assertIn("Token Factory: 2 call(s). Estimated cost about US$0.02", text)
        self.assertIn("ceiling US$0.06", text)
        self.assertIn("No cloud Job and no Tavily call", text)
        self.assertIn("Dry run: nothing was called", text)
        self.assertNotIn(KEY, text)

    def test_a_dry_run_through_the_command_line_needs_no_key(self):
        self.scenario_run()
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            status = self.script.main([str(self.run), "--dry-run"])
        self.assertEqual(0, status)
        self.assertIn("Token Factory: 2 call(s)", stdout.getvalue())

    def test_a_scenario_case_gets_history_explanation_next_steps_report_and_the_same_id(self):
        case = self.scenario_run()
        fakes = Fakes()
        status, text = self.go(fakes)
        self.assertEqual(0, status, text)
        rebuilt = json.loads((self.run / "case.json").read_text(encoding="utf-8"))
        self.assertEqual(case["case_id"], rebuilt["case_id"])
        self.assertTrue(any(h["entity"] == "milk_1" for h in rebuilt["minimal"]["shrink_history"]))
        self.assertEqual(len(continuation_reductions()[1]["candidates"]), len(rebuilt["reruns"]))
        explanation = json.loads((self.run / "explanation.json").read_text(encoding="utf-8"))
        self.assertEqual(["new"], explanation["interpretation"]["observations"])
        self.assertTrue((self.run / "explanation.previous.json").is_file())
        research = json.loads((self.run / "research.json").read_text(encoding="utf-8"))
        self.assertEqual("interpreted", research["next_steps"]["status"])
        self.assertNotIn("summary", research)
        self.assertEqual(QUERIES, research["queries"])
        self.assertIn("summary", json.loads((self.run / "research.previous.json").read_text(encoding="utf-8")))
        report = (self.run / "report.md").read_text(encoding="utf-8")
        self.assertIn("| milk_1 | position | 87.5% | 75% |", report)
        self.assertEqual(1, len(fakes.explain_calls))
        self.assertEqual(1, len(fakes.steps_calls))
        self.assertIn("milk position", json.dumps(fakes.steps_calls[0]["facts"]["sizes_already_tested"]))
        self.assertNotIn(KEY, text)
        library = Library(self.artifacts, runs_root=self.artifacts / "runs", diagnoses_root=self.diagnoses)
        detail = library.detail("d-" + case["case_id"])
        self.assertEqual("interpreted", detail["next_steps"]["status"])
        self.assertEqual(len(rebuilt["reruns"]), len(detail["scenario"]["reruns"]))

    def test_a_second_run_still_works_and_labels_each_attempt(self):
        self.scenario_run()
        fakes = Fakes()
        self.go(fakes)
        self.go(fakes)
        self.assertEqual(2, len(fakes.explain_calls))

    def test_a_rejected_answer_does_not_replace_a_good_one(self):
        case = self.scenario_run()
        good = {"status": "interpreted", "items": [{"text": "Old.", "cites": ["S1"]}], "provenance": {"model": "u"}}
        write(self.run / "research.json", dict(OLD_RESEARCH, case_id=case["case_id"], next_steps=good))
        fakes = Fakes(next_steps_text="not json", explain_status="rejected")
        status, text = self.go(fakes)
        self.assertEqual(0, status)
        self.assertEqual(good, json.loads((self.run / "research.json").read_text(encoding="utf-8"))["next_steps"])
        self.assertIn("old next steps are kept", text)
        self.assertIn("old explanation is kept", text)
        old = json.loads((self.run / "explanation.json").read_text(encoding="utf-8"))
        self.assertEqual(["old"], old["interpretation"]["observations"])
        self.assertFalse((self.run / "explanation.json.new").exists())

    def test_a_first_rejected_answer_is_stored_as_rejected_with_no_items(self):
        self.scenario_run()
        status, _ = self.go(Fakes(next_steps_text="not json"))
        self.assertEqual(0, status)
        research = json.loads((self.run / "research.json").read_text(encoding="utf-8"))
        self.assertEqual(("rejected", []), (research["next_steps"]["status"], research["next_steps"]["items"]))

    def test_a_case_without_research_only_gets_the_explanation_and_the_report(self):
        self.scenario_run(research=None)
        fakes = Fakes()
        status, text = self.go(fakes)
        self.assertEqual(0, status)
        self.assertEqual((1, 0), (len(fakes.explain_calls), len(fakes.steps_calls)))
        self.assertIn("no research record", text)
        self.assertFalse((self.run / "research.json").exists())

    def test_a_failing_call_is_reported_by_type_and_the_other_steps_still_run(self):
        self.scenario_run()
        fakes = Fakes()

        def broken(*args, **kwargs):
            raise RuntimeError("secret detail " + KEY)

        fakes.explain = broken
        status, text = self.go(fakes)
        self.assertEqual(1, status)
        self.assertIn("explanation: FAILED (RuntimeError)", text)
        self.assertNotIn("secret detail", text)
        self.assertEqual(1, len(fakes.steps_calls))

    def test_a_run_without_a_case_is_rejected(self):
        write(self.run / "steps.json", {"steps": {}})
        with self.assertRaises(self.script.RegenerateError):
            self.script.regenerate(self.run, dry_run=True, out=lambda line: None)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(2, self.script.main([str(self.run), "--dry-run"]))


class AuditRunTests(unittest.TestCase):
    def test_a_stress_test_case_gets_next_steps_and_a_sorted_report(self):
        script = load_script()
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "runs" / "stress-20261019T032219Z"

            def level(severity, failures, phase):
                return {"severity": severity, "outcomes": ["policy_failure"] * failures + ["success"] * (5 - failures),
                        "failures": failures, "reproducible": failures >= 4, "complete": True, "phase": phase}

            summary = {"mode": "m6-threshold", "config": {"sweep": [0.2, 0.6], "required_failures": 4, "attempts": 5,
                                                          "bisection_steps": 1, "families": ["blur"],
                                                          "suite": "libero_10", "task_id": 0, "init_state_index": 3},
                       "nominal_controls": {"outcomes": {"success": 5}, "planned": 5},
                       "families": {"blur": {"threshold_severity": 0.4, "lower_bound": 0.2, "stop_reason":
                                             "threshold_found", "attempts": 5, "levels": [
                                                 level(0.2, 0, "sweep"), level(0.6, 5, "sweep"),
                                                 level(0.4, 5, "bisect")]}}}
            write(run / "jobs" / "g1" / "evidence" / "m6_summary.json", summary)
            write(run / "steps.json", {"steps": {"audit-1": {"summary": "jobs/g1/evidence/m6_summary.json"}}})
            write(run / "cases" / "audit" / "merged-summary.json", summary)
            case = {"schema_version": 1, "kind": "audit", "case_id": "ab" * 32, "suite": "libero_10", "task_id": 0,
                    "start_index": 3, "families": {"blur": {"threshold_severity": 0.4,
                                                            "stop_reason": "threshold_found"}},
                    "groups": [{"step": "audit-1", "job_name": "g1", "families": ["blur"]}],
                    "summary": "cases/audit/merged-summary.json", "stop_reason": None, "complete": True}
            write(run / "cases" / "audit" / "case.json", case)
            write(run / "cases" / "audit" / "report.md", "# old\n")
            write(run / "cases" / "audit" / "research.json", dict(OLD_RESEARCH, case_id=case["case_id"]))
            fakes = Fakes()
            lines = []
            status = script.regenerate(run, deps=fakes.deps(script), diagnoses_root=Path(directory) / "diagnoses",
                                       out=lines.append)
            self.assertEqual(0, status, "\n".join(lines))
            self.assertEqual(([], 1), (fakes.explain_calls, len(fakes.steps_calls)))
            facts = fakes.steps_calls[0]["facts"]
            self.assertEqual({"severity": 0.4, "failures": 5, "attempts": 5, "evidence_id": "blur@0.4"},
                             facts["families"][0]["at_threshold"])
            report = (run / "cases" / "audit" / "report.md").read_text(encoding="utf-8")
            self.assertIn("| 0.4 | 5/5 | fails ← threshold | 3rd (narrowing) |", report)
            self.assertTrue(report.startswith("# Stress test: LIBERO-10 task 0, start 3"))
            self.assertEqual("ab" * 32, json.loads((run / "cases" / "audit" / "case.json").read_text(
                encoding="utf-8"))["case_id"])


if __name__ == "__main__":
    unittest.main()
