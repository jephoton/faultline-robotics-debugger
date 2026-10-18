"""The paraphrase diagnosis: spec, orchestrator pipeline (fake backend and fake Nemotron), report, CLI."""

from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

from robot_debug import cli
from robot_debug import ledger as lg
from robot_debug import orchestrator as orch
from robot_debug import paraphrase as pp
from robot_debug import spec as sp
from tests.test_orchestrator import (
    RATE, FakeBackend, FakeTools, MOMENT, cost, finished, make_world)

ROOT = Path(__file__).parents[1]
ORIGINAL = "pick up the alphabet soup and place it in the basket"
PARAPHRASES = [
    "grab the alphabet soup, then put it in the basket.",
    "take the alphabet soup and put it in the basket",
    "move the soup into the basket",
    "pick up the alphabet soup and put it in the basket",
]
BACKEND = {"kind": "nebius", "image": "cr.example.invalid/REGISTRY_ID/faultline@sha256:IMAGE_DIGEST",
           "hf_token_secret": "faultline-hf-token", "hourly_usd": RATE}
SUMMARY = "language_summary.json"


def paraphrase_spec(cap=10.0, hours=5.0, **paraphrase) -> sp.Spec:
    return sp.parse_spec({
        "faultline": 1, "name": "para-task0", "mode": "paraphrase", "policy": {"suite": "libero_object"},
        "paraphrase": dict({"task": 0, "start": 0, "count": 4}, **paraphrase),
        "budget": {"max_spend_usd": cap, "max_hours": hours}, "nemotron": {"explain": True},
        "backend": dict(BACKEND)})


# --- summaries ---------------------------------------------------------------------------------------


def lang_screen(paraphrases=PARAPHRASES, failing=("p01",), control=True, outcomes=None) -> Dict[str, Any]:
    rows = [{"label": "orig", "kind": "original", "text": ORIGINAL,
             "outcomes": ["success", "success"] if control else ["success", "policy_failure"],
             "failures": 0 if control else 1, "decision": None, "skipped_attempts": 0, "edit_count": None,
             "attempts": []}]
    for number, text in enumerate(paraphrases, 1):
        label = "p{:02d}".format(number)
        fails = label in failing
        row = (outcomes or {}).get(label) or (["policy_failure"] * 5 if fails else ["success"])
        rows.append({"label": label, "kind": "paraphrase", "text": text, "outcomes": row,
                     "failures": row.count("policy_failure"), "decision": "reproduces" if fails else None,
                     "skipped_attempts": 0, "edit_count": len(pp.word_edits(ORIGINAL, text)), "attempts": []})
    return {"schema_version": 1, "mode": "paraphrase-screen", "suite": "libero_object", "task_id": 0,
            "init_state_index": 0, "original": ORIGINAL, "instructions": rows,
            "control": {"outcomes": rows[0]["outcomes"], "passed": control},
            "reproducing": [label for label in failing], "stop_reason": None, "complete": True,
            "total_seconds": 600, "checkpoint": None, "confirm": {"skipped_attempts": 2}}


def lang_reduce(workload: Dict[str, Any], *, reduced=True, verified=True, stop="reduced") -> Dict[str, Any]:
    edits = workload["edits"]
    keep = edits[:1]
    text = pp.apply_edits(workload["original"], keep)

    def candidate(index, role, selection, text_, decision, outcomes):
        return {"index": index, "phase": "gate" if role != "hybrid" else "ddmin", "role": role, "reference": None,
                "selection": selection, "key": "key{}".format(index), "kind": "pass" if role == "reference" else "failure",
                "decision": decision, "gate_met": decision in ("reproduces", "passes"), "outcomes": outcomes,
                "late_outcomes": [], "skipped": 1, "stop_withdrawn": 0, "complete": True, "text": text_}

    candidates = [
        candidate(0, "failing", None, workload["paraphrase"], "reproduces", ["policy_failure"] * 4),
        candidate(1, "reference", None, workload["original"], "passes", ["success"] * 5),
        candidate(2, "hybrid", [keep[0]["id"]], text, "reproduces", ["policy_failure"] * 4),
    ]
    minimal = None
    if verified:
        minimal = {"edit_ids": [keep[0]["id"]], "edits": keep, "text": text,
                   "labels": [pp.edit_label(keep[0])], "verified": True, "edit_minimal": reduced}
    videos = {"original": {"case_id": "full", "outcome": "policy_failure", "video": "runs/full/a.mp4",
                           "key": "key0", "text": workload["paraphrase"]},
              "reference": {"case_id": "orig", "outcome": "success", "video": "runs/orig/a.mp4",
                            "key": "key1", "text": workload["original"]},
              "minimal": {"case_id": "cand", "outcome": "policy_failure", "video": "runs/cand/a.mp4",
                          "key": "key2", "text": text}} if verified else {}
    return {"schema_version": 1, "mode": "paraphrase-reduce", "suite": workload["suite"],
            "task_id": workload["task_id"], "init_state_index": workload["init_state_index"],
            "original": workload["original"], "paraphrase": workload["paraphrase"], "edits": edits,
            "minimal": minimal, "videos": videos,
            "reduction": {"stop_reason": stop, "reduced": reduced, "attempts": 5, "required_failures": 4,
                          "gates": {"paraphrase": "reproduces", "original": "passes"},
                          "final_edits": [keep[0]["id"]] if verified else None,
                          "final_candidate": 2 if verified else None, "candidates": candidates,
                          "candidates_tested": 1, "attempts_run": 11, "attempts_skipped": 3},
            "checkpoint": None, "total_seconds": 500, "stop_reason": None if reduced else stop,
            "complete": reduced}


class ParaphraseTools(FakeTools):
    """Real workload builders, report and case; fake Token Factory, time and registration."""

    def __init__(self, paraphrases=PARAPHRASES, result=None):
        super().__init__()
        self.generated = []
        self.result = result
        self.paraphrases = paraphrases

    def generate_paraphrases(self, original, count, model, env_file):
        self.generated.append((original, count, model, env_file))
        if self.result is not None:
            return self.result
        return {"original": original, "paraphrases": list(self.paraphrases), "rejected": [], "model": model,
                "fallback_reason": None, "provenance": {"model": model}, "raw_content": "raw reply"}


def screen_step(**kwargs):
    return finished(lambda workload: lang_screen(**kwargs), name=SUMMARY)


def reduce_step(**kwargs):
    return finished(lambda workload: lang_reduce(workload, **kwargs), name=SUMMARY)


class Base(unittest.TestCase):
    def world(self, behaviours, spec=None, tools=None, **options):
        temp, runner, backend, tools, ledger, lines = make_world(
            spec or paraphrase_spec(), behaviours, tools=tools or ParaphraseTools(), **options)
        self.addCleanup(temp.cleanup)
        return runner, backend, tools, ledger, lines


# --- spec ----------------------------------------------------------------------------------------------


class SpecTests(unittest.TestCase):
    def test_defaults(self):
        spec = paraphrase_spec()
        self.assertEqual(("paraphrase", "paraphrase", "libero_object"), (spec.mode, spec.mode_label, spec.suite))
        pc = spec.paraphrase
        self.assertEqual((0, 0, 4, pp.PARAPHRASE_MODEL), (pc.task, pc.start, pc.count, pc.model))
        self.assertEqual(ORIGINAL, pc.instruction)
        self.assertEqual(10, sp.parse_spec(dict(spec.raw, paraphrase={"task": 0, "start": 3})).paraphrase.count)
        self.assertEqual("nvidia/nemotron-3-super-120b-a12b", pp.PARAPHRASE_MODEL)

    def test_model_count_and_instruction_may_be_given(self):
        pc = paraphrase_spec(count=12, model="nvidia/Nemotron-3-Ultra-550b-a55b",
                             instruction="  put the bowl on  the plate ").paraphrase
        self.assertEqual((12, "nvidia/Nemotron-3-Ultra-550b-a55b", "put the bowl on the plate"),
                         (pc.count, pc.model, pc.instruction))

    def test_other_tasks_need_their_instruction(self):
        with self.assertRaises(sp.SpecError) as caught:
            paraphrase_spec(task=1)
        self.assertIn("paraphrase.instruction", str(caught.exception))
        self.assertEqual("open the drawer", paraphrase_spec(task=1, instruction="open the drawer").paraphrase.instruction)
        data = dict(paraphrase_spec().raw, policy={"suite": "libero_10"})
        with self.assertRaises(sp.SpecError):
            sp.parse_spec(data)

    def test_bad_values_are_refused_with_their_path(self):
        bad = ({"count": 0}, {"count": 13}, {"count": True}, {"count": "4"}, {"start": 50}, {"start": -1},
               {"task": 10}, {"model": ""}, {"model": "bad model"}, {"model": 3}, {"model": "x" * 200},
               {"instruction": ""}, {"instruction": "café"}, {"instruction": "x" * 201},
               {"instruction": "..."}, {"instruction": 3}, {"surprise": 1})
        for changes in bad:
            with self.subTest(changes=changes):
                with self.assertRaises(sp.SpecError) as caught:
                    paraphrase_spec(**changes)
                self.assertIn("paraphrase", str(caught.exception))

    def test_required_keys_and_sections(self):
        for key in ("start", "task"):
            data = copy.deepcopy(dict(paraphrase_spec().raw))
            del data["paraphrase"][key]
            with self.subTest(missing=key), self.assertRaises(sp.SpecError):
                sp.parse_spec(data)
        for key in ("paraphrase", "policy", "budget", "backend"):
            data = copy.deepcopy(dict(paraphrase_spec().raw))
            del data[key]
            with self.subTest(missing=key), self.assertRaises(sp.SpecError):
                sp.parse_spec(data)
        data = copy.deepcopy(dict(paraphrase_spec().raw))
        data["scenario"] = {"task": 0, "start": 1}
        with self.assertRaises(sp.SpecError):
            sp.parse_spec(data)

    def test_the_example_spec_loads(self):
        spec = sp.load_spec(ROOT / "configs" / "specs" / "paraphrase.yaml")
        self.assertEqual(("paraphrase", 10), (spec.mode, spec.paraphrase.count))
        self.assertEqual(ORIGINAL, spec.paraphrase.instruction)

    def test_every_suite_is_a_paraphrase_suite(self):
        for suite in sp.SUITES:
            data = dict(paraphrase_spec(instruction="open the drawer", task=2).raw, policy={"suite": suite})
            self.assertEqual(suite, sp.parse_spec(data).suite)


# --- pure helpers ----------------------------------------------------------------------------------------


class HelperTests(unittest.TestCase):
    def test_choose_prefers_most_failures_then_fewest_edits_then_label(self):
        summary = lang_screen(failing=("p01", "p02", "p04"), outcomes={
            "p01": ["policy_failure"] * 4 + ["success"], "p02": ["policy_failure"] * 5,
            "p04": ["policy_failure"] * 5})
        edits = {row["label"]: row["edit_count"] for row in summary["instructions"][1:]}
        chosen = orch.choose_paraphrase(summary)
        expected = sorted(("p02", "p04"), key=lambda label: (edits[label], label))[0]
        self.assertEqual(expected, chosen["label"])
        summary["instructions"][2]["outcomes"] = ["policy_failure"] * 4 + ["success"]
        summary["instructions"][4]["outcomes"] = ["policy_failure"] * 4 + ["success"]
        summary["instructions"][2]["outcomes"] = ["policy_failure"] * 5
        self.assertEqual("p02", orch.choose_paraphrase(summary)["label"])

    def test_ties_on_failures_go_to_the_smaller_edit_set(self):
        summary = lang_screen(failing=("p01", "p04"))
        summary["instructions"][1]["edit_count"] = 5
        summary["instructions"][4]["edit_count"] = 2
        self.assertEqual("p04", orch.choose_paraphrase(summary)["label"])

    def test_only_reproducing_paraphrases_with_four_failures_qualify(self):
        self.assertIsNone(orch.choose_paraphrase(lang_screen(failing=())))
        summary = lang_screen(failing=("p01",), outcomes={"p01": ["policy_failure"] * 3 + ["success"] * 2})
        self.assertIsNone(orch.choose_paraphrase(summary))
        summary = lang_screen(failing=("p01",), outcomes={"p01": ["policy_failure"] * 4})
        self.assertEqual("p01", orch.choose_paraphrase(summary)["label"], "four recorded failures meet the gate")
        summary = lang_screen(failing=("p01",), outcomes={"p01": ["policy_failure"] * 3})
        self.assertIsNone(orch.choose_paraphrase(summary))
        summary = lang_screen(failing=("p01",))
        summary["instructions"][1]["decision"] = "does_not_reproduce"
        self.assertIsNone(orch.choose_paraphrase(summary))
        summary = lang_screen(failing=("p01",))
        summary["instructions"][0]["kind"] = "original"
        summary["instructions"][0]["decision"] = "reproduces"
        summary["instructions"][0]["outcomes"] = ["policy_failure"] * 5
        self.assertEqual("p01", orch.choose_paraphrase(summary)["label"], "the control is never chosen")
        self.assertIsNone(orch.choose_paraphrase({}))

    def test_a_paraphrase_that_dropped_the_object_or_target_is_never_chosen(self):
        # p03 ("move the soup into the basket") lost "alphabet"; it fails more often and with fewer edits.
        summary = lang_screen(failing=("p01", "p03"), outcomes={
            "p01": ["policy_failure"] * 4 + ["success"], "p03": ["policy_failure"] * 5})
        summary["instructions"][1]["edit_count"] = 9
        summary["instructions"][3]["edit_count"] = 1
        self.assertEqual("p01", orch.choose_paraphrase(summary)["label"])
        self.assertEqual("p03", orch.choose_paraphrase(summary, include_dropped=True)["label"])
        self.assertEqual("object_or_target_dropped", orch.paraphrase_meaning(summary, summary["instructions"][3]))
        self.assertEqual("kept", orch.paraphrase_meaning(summary, summary["instructions"][1]))
        self.assertIsNone(orch.paraphrase_meaning({}, summary["instructions"][1]))

    def test_the_october_15_nano_example_is_not_chosen(self):
        summary = lang_screen(paraphrases=["pick up the alphabet soup and place it in the container"],
                              failing=("p01",))
        self.assertIsNone(orch.choose_paraphrase(summary))
        self.assertIsNotNone(orch.choose_paraphrase(summary, include_dropped=True))

    def test_the_table_marks_the_flagged_paraphrases(self):
        lines = orch.paraphrase_table(lang_screen(failing=("p01", "p03")))
        self.assertNotIn("dropped", lines[0])
        self.assertIn("[dropped object/target]", lines[1])

    def test_the_table_lists_only_instructions_that_failed(self):
        lines = orch.paraphrase_table(lang_screen(failing=("p02",)))
        self.assertEqual(1, len(lines))
        self.assertTrue(lines[0].startswith("p02: F F F F F (reproduces) - "))
        self.assertEqual(["every instruction passed"], orch.paraphrase_table(lang_screen(failing=())))

    def test_candidate_budget_defaults_to_24_unless_the_spec_sets_one(self):
        self.assertEqual(24, orch.paraphrase_candidates(paraphrase_spec()))
        data = dict(paraphrase_spec().raw, budget={"max_spend_usd": 5.0, "max_hours": 2, "max_candidates": 10})
        self.assertEqual(10, orch.paraphrase_candidates(sp.parse_spec(data)))


# --- the pipeline ------------------------------------------------------------------------------------------


class EndToEnd(Base):
    def test_generate_screen_choose_reduce_report_case_register(self):
        runner, backend, tools, ledger, lines = self.world([screen_step(), reduce_step()])
        result = runner.diagnose()
        run_dir = runner.run_dir
        self.assertEqual((result.status, result.reason, result.exit_code), ("completed", None, 0))
        tag = runner.tag
        self.assertEqual(["para-task0-{}-screen".format(tag), "para-task0-{}-reduce".format(tag)], backend.submitted)
        self.assertAlmostEqual(2 * cost(), ledger.spent)

        self.assertEqual([(ORIGINAL, 4, pp.PARAPHRASE_MODEL, None)], tools.generated)
        screen, reduce_ = (backend.workloads[name] for name in backend.submitted)
        self.assertEqual("paraphrase-screen", screen["mode"])
        self.assertEqual((ORIGINAL, PARAPHRASES, "libero_object", 0, 0),
                         (screen["original"], screen["paraphrases"], screen["suite"], screen["task_id"],
                          screen["init_state_index"]))
        self.assertEqual("paraphrase-reduce", reduce_["mode"])
        self.assertEqual(PARAPHRASES[0], reduce_["paraphrase"])               # the only one that failed
        self.assertEqual(pp.word_edits(ORIGINAL, PARAPHRASES[0]), reduce_["edits"])
        self.assertEqual(24, reduce_["max_candidates"])
        for workload in (screen, reduce_):
            self.assertNotIn("api_key", json.dumps(workload).lower())

        for name in ("report.md", "case.json", "spec.yaml", "ledger.json", "steps.json", "paraphrases.json"):
            self.assertTrue((run_dir / name).is_file(), name)
        stored = json.loads((run_dir / "paraphrases.json").read_text())
        self.assertEqual(PARAPHRASES, stored["paraphrases"])
        self.assertEqual("raw reply", stored["raw_content"])
        case = json.loads((run_dir / "case.json").read_text())
        self.assertEqual("paraphrase_reduction", case["kind"])
        self.assertEqual(result.case_id, case["case_id"])
        self.assertEqual(case["minimal"]["text"], case["replay"]["config"]["instruction"])
        report = (run_dir / "report.md").read_text()
        self.assertIn(ORIGINAL, report)
        self.assertIn(case["minimal"]["text"], report)
        self.assertEqual([run_dir], tools.registered)
        self.assertEqual([], tools.explained, "paraphrase cases have no explanation yet")
        steps = json.loads((run_dir / "steps.json").read_text())["steps"]
        for step in ("paraphrase", "screen", "reduce", "report", "case", "register"):
            self.assertEqual("done", steps[step]["status"], step)
        self.assertEqual(1, backend.finished)
        self.assertTrue(any("choose" in line and "p01" in line for line in lines))
        self.assertTrue(all("spent US$" in line for line in lines))

    def test_a_flagged_paraphrase_is_screened_but_the_reduction_takes_the_next_one(self):
        paraphrases = [PARAPHRASES[2], PARAPHRASES[0], PARAPHRASES[1], PARAPHRASES[3]]      # p01 dropped "alphabet"
        tools = ParaphraseTools(paraphrases=paraphrases)
        runner, backend, tools, ledger, lines = self.world(
            [screen_step(paraphrases=paraphrases, failing=("p01", "p02"), outcomes={
                "p01": ["policy_failure"] * 5, "p02": ["policy_failure"] * 4 + ["success"]}), reduce_step()],
            tools=tools)
        result = runner.diagnose()
        self.assertEqual("completed", result.status)
        screen, reduce_ = (backend.workloads[name] for name in backend.submitted)
        self.assertEqual(paraphrases, screen["paraphrases"], "the flagged one is still screened")
        self.assertEqual(paraphrases[1], reduce_["paraphrase"], "but not reduced")
        stored = json.loads((runner.run_dir / "paraphrases.json").read_text())
        self.assertEqual(["object_or_target_dropped", "kept", "kept", "kept"],
                         [item["meaning_check"] for item in stored["meaning_checks"]])
        self.assertTrue(any("1 of 4 paraphrases dropped an object or target word" in line for line in lines))
        report = (runner.run_dir / "report.md").read_text()
        self.assertIn("Flagged in this screen: p01.", report)
        self.assertIn("Failed 4 of 5 but flagged, so not reduced: p01.", report)
        case = json.loads((runner.run_dir / "case.json").read_text())
        self.assertEqual("kept", case["paraphrase_meaning_check"])

    def test_when_every_failure_dropped_something_the_run_stops_before_the_reduction(self):
        paraphrases = ["pick up the alphabet soup and place it in the container", PARAPHRASES[0]]
        tools = ParaphraseTools(paraphrases=paraphrases)
        runner, backend, tools, ledger, lines = self.world(
            [screen_step(paraphrases=paraphrases, failing=("p01",))], tools=tools)
        result = runner.diagnose()
        self.assertEqual(("stopped", "no_faithful_failure"), (result.status, result.reason))
        self.assertEqual(1, len(backend.submitted), "no reduce Job")
        report = (runner.run_dir / "report.md").read_text()
        self.assertIn("each of them dropped an object or target word", report)
        self.assertTrue(any("[dropped object/target]" in line for line in lines))

    def test_the_spec_candidate_budget_and_model_reach_the_jobs_and_the_request(self):
        spec = sp.parse_spec(dict(paraphrase_spec(model="nvidia/other-model").raw, budget={
            "max_spend_usd": 10.0, "max_hours": 5, "max_candidates": 12}))
        runner, backend, tools, ledger, lines = self.world([screen_step(), reduce_step()], spec=spec)
        runner.diagnose()
        self.assertEqual("nvidia/other-model", tools.generated[0][2])
        self.assertEqual(12, backend.workloads[backend.submitted[1]]["max_candidates"])

    def test_no_reproducing_paraphrase_stops_with_the_screen_table_and_no_reduce_job(self):
        runner, backend, tools, ledger, lines = self.world([screen_step(failing=())])
        result = runner.diagnose()
        self.assertEqual(("stopped", "no_reproducible_failure"), (result.status, result.reason))
        self.assertEqual(1, len(backend.submitted))
        self.assertTrue((runner.run_dir / "report.md").is_file())
        self.assertIn("robust", (runner.run_dir / "report.md").read_text())
        self.assertFalse((runner.run_dir / "case.json").exists())
        self.assertEqual([], tools.registered)
        self.assertAlmostEqual(cost(), ledger.spent)

    def test_a_failing_control_stops_before_the_reduction(self):
        runner, backend, tools, ledger, lines = self.world([screen_step(control=False)])
        result = runner.diagnose()
        self.assertEqual("control_not_passing", result.reason)
        self.assertEqual(1, len(backend.submitted))
        self.assertIn("did NOT pass", (runner.run_dir / "report.md").read_text())

    def test_nemotron_is_required_so_no_llm_stops_before_any_job(self):
        runner, backend, tools, ledger, lines = self.world([], no_llm=True)
        result = runner.diagnose()
        self.assertEqual("llm_required", result.reason)
        self.assertEqual([], backend.submitted)
        self.assertEqual([], tools.generated)

    def test_no_usable_paraphrases_stop_before_any_job(self):
        tools = ParaphraseTools(result={"original": ORIGINAL, "paraphrases": [], "rejected": [], "model": "m",
                                        "fallback_reason": "model_unavailable", "provenance": None,
                                        "raw_content": None})
        runner, backend, _tools, ledger, lines = self.world([], tools=tools)
        result = runner.diagnose()
        self.assertEqual("paraphrase_failed", result.reason)
        self.assertEqual([], backend.submitted)
        self.assertEqual(0.0, ledger.spent)
        self.assertTrue(any("model_unavailable" in line for line in lines))

    def test_a_missing_key_is_a_clear_stop(self):
        from robot_debug import token_factory as tf

        class NoKey(orch.DefaultTools):
            def __init__(self):
                super().__init__(load_key=self._raise)
                self.clock = MOMENT

            @staticmethod
            def _raise(env_file):
                raise tf.TokenFactoryError("missing_api_key")

            def now(self):
                return self.clock

        runner, backend, _t, ledger, lines = self.world([], tools=NoKey())
        result = runner.diagnose()
        self.assertEqual("paraphrase_failed", result.reason)
        self.assertTrue(any("missing_api_key" in line for line in lines))
        self.assertEqual([], backend.submitted)

    def test_the_default_tools_hand_the_key_to_the_request_and_never_to_a_workload(self):
        calls = []

        def transport(method, path, payload, api_key):
            calls.append((method, path, api_key))
            if method == "GET":
                return {"data": [{"id": pp.PARAPHRASE_MODEL}]}
            return {"model": payload["model"], "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                                                         "total_tokens": 2},
                    "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(
                        {"paraphrases": PARAPHRASES[:3]})}}]}

        tools = orch.DefaultTools(load_key=lambda env: "KEY-123", paraphrase_transport=transport)
        result = tools.generate_paraphrases(ORIGINAL, 3, pp.PARAPHRASE_MODEL, Path("x.env"))
        self.assertEqual(PARAPHRASES[:3], result["paraphrases"])
        self.assertEqual({"KEY-123"}, {call[2] for call in calls})
        workload = tools.paraphrase_screen_workload("r1", paraphrase_spec(), ORIGINAL, result["paraphrases"])
        self.assertNotIn("KEY-123", json.dumps(workload))
        self.assertNotIn("KEY-123", json.dumps(result))

    def test_a_partial_reduction_still_reports_and_registers_the_best_verified_wording(self):
        script = [screen_step(), reduce_step(reduced=False, stop="budget_exhausted")]
        runner, backend, tools, ledger, lines = self.world(script)
        result = runner.diagnose()
        self.assertEqual(("stopped", "budget_exhausted"), (result.status, result.reason))
        self.assertIsNotNone(result.case_id)
        case = json.loads((runner.run_dir / "case.json").read_text())
        self.assertFalse(case["reduced"])
        self.assertIn("stopped early", case["minimal"]["sentence"])
        self.assertEqual([runner.run_dir], tools.registered)

    def test_a_reduction_that_verified_nothing_has_a_report_but_no_case(self):
        script = [screen_step(), reduce_step(reduced=False, verified=False, stop="failing_not_reproducible")]
        runner, backend, tools, ledger, lines = self.world(script)
        result = runner.diagnose()
        self.assertEqual(("stopped", "failing_not_reproducible"), (result.status, result.reason))
        self.assertIsNone(result.case_id)
        self.assertTrue((runner.run_dir / "report.md").is_file())
        self.assertFalse((runner.run_dir / "case.json").exists())
        self.assertEqual([], tools.registered)

    def test_a_job_that_fails_without_a_summary_is_a_stop(self):
        script = [{"state": "FAILED", "reason": "ContainerFailed", "container_seconds": 100, "summary": None,
                   "summary_name": SUMMARY}]
        runner, backend, tools, ledger, lines = self.world(script)
        self.assertEqual("job_failed", runner.diagnose().reason)

    def test_the_cap_refuses_the_second_job_before_it_is_submitted(self):
        screen_deadline, _reduce_deadline = ParaphraseTools().paraphrase_deadlines(paraphrase_spec())
        spec = paraphrase_spec(cap=lg.worst_case_seconds(screen_deadline) / 3600.0 * RATE + 0.01)
        runner, backend, tools, ledger, lines = self.world([screen_step(), reduce_step()], spec=spec)
        result = runner.diagnose()
        self.assertEqual("spend_cap", result.reason)
        self.assertEqual(1, len(backend.submitted))

    def test_resume_never_asks_for_paraphrases_or_submits_again(self):
        spec = paraphrase_spec()
        runner, backend, tools, ledger, lines = self.world([screen_step(), reduce_step()], spec=spec)
        runner.diagnose()
        second_tools = ParaphraseTools()
        backend2 = FakeBackend([])
        temp, runner2, backend2, _t, ledger2, lines2 = make_world(
            spec, [], tools=second_tools, backend=backend2, run_dir=runner.run_dir)
        self.addCleanup(temp.cleanup)
        result = runner2.diagnose()
        self.assertEqual("completed", result.status)
        self.assertEqual([], backend2.submitted)
        self.assertEqual([], second_tools.generated)

    def test_resume_after_the_screen_reuses_the_stored_paraphrases(self):
        spec = paraphrase_spec()
        backend1 = FakeBackend([screen_step()])
        backend1.fail_submit_at = 1
        temp, runner1, backend1, tools1, ledger1, lines1 = make_world(
            spec, [], tools=ParaphraseTools(), backend=backend1)
        self.addCleanup(temp.cleanup)
        self.assertEqual("backend_error", runner1.diagnose().reason)
        tools2 = ParaphraseTools(paraphrases=["something else entirely"])
        backend2 = FakeBackend([reduce_step()])
        temp2, runner2, backend2, _t, ledger2, lines2 = make_world(
            spec, [], tools=tools2, backend=backend2, run_dir=runner1.run_dir)
        self.addCleanup(temp2.cleanup)
        result = runner2.diagnose()
        self.assertEqual("completed", result.status)
        self.assertEqual([], tools2.generated)
        self.assertEqual(1, len(backend2.submitted))


class DryRun(unittest.TestCase):
    def test_dry_run_lists_the_generation_and_both_jobs(self):
        lines, required = orch.dry_run_lines(paraphrase_spec(cap=5.0), FakeTools())
        text = "\n".join(lines)
        self.assertIn(pp.PARAPHRASE_MODEL, text)
        self.assertIn("screen 4 paraphrases of task 0 start 0", text)
        self.assertIn("reduce the best failing paraphrase (24 candidates)", text)
        self.assertNotIn("optional", text)
        self.assertGreater(required, 0)
        self.assertIn("cap US$5.00", text)

    def test_dry_run_warns_when_the_jobs_exceed_the_cap(self):
        lines, _ = orch.dry_run_lines(paraphrase_spec(cap=0.5), FakeTools())
        self.assertIn("WARNING", "\n".join(lines))

    def test_too_many_candidates_for_one_job_is_a_clear_stop(self):
        data = dict(paraphrase_spec().raw, budget={"max_spend_usd": 10.0, "max_hours": 5, "max_candidates": 60})
        with self.assertRaises(orch.StopRun) as caught:
            orch.dry_run_lines(sp.parse_spec(data), FakeTools())
        self.assertEqual("candidates_too_large", caught.exception.reason)

    def test_the_cli_dry_run_prints_the_plan_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            spec_path = Path(temporary) / "spec.yaml"
            spec_path.write_text("""\
faultline: 1
name: para-task0
mode: paraphrase
policy: {suite: libero_object}
paraphrase: {task: 0, start: 0, count: 6}
budget: {max_spend_usd: 5.0, max_hours: 3}
backend:
  kind: nebius
  image: cr.example.invalid/REGISTRY_ID/faultline@sha256:IMAGE_DIGEST
  hf_token_secret: faultline-hf-token
  hourly_usd: 1.8
""", encoding="utf-8")
            lines: List[str] = []
            backends = []

            def make(spec):
                backends.append(FakeBackend([]))
                return backends[-1]

            code = cli.main(["diagnose", str(spec_path), "--dry-run", "--runs-root", str(Path(temporary) / "runs")],
                            make_backend=make, tools=FakeTools(), out=lines.append)
            text = "\n".join(lines)
            self.assertEqual(0, code, text)
            self.assertIn("screen 6 paraphrases", text)
            self.assertIn("nothing was created", text)
            self.assertFalse((Path(temporary) / "runs").exists())
            self.assertEqual((0, [], 0), (backends[0].prepared, backends[0].submitted, backends[0].finished))

    def test_cli_lists_a_finished_paraphrase_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            runs = Path(temporary) / "runs"
            runs.mkdir()
            spec = paraphrase_spec()
            tools = ParaphraseTools()
            run_dir = orch.create_run_dir(runs, spec, None, MOMENT)
            _t, runner, backend, tools, ledger, lines = make_world(
                spec, [screen_step(), reduce_step()], tools=tools, run_dir=run_dir)
            self.addCleanup(_t.cleanup)
            runner.diagnose()
            listing = cli.list_runs(runs)
            self.assertEqual(1, len(listing))
            self.assertIn("paraphrase", listing[0])
            self.assertIn("completed", listing[0])


# --- the report ------------------------------------------------------------------------------------------------


def load_report_module():
    spec = importlib.util.spec_from_file_location("report_paraphrase_test", ROOT / "scripts" / "report_paraphrase.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.module = load_report_module()
        workload = {"suite": "libero_object", "task_id": 0, "init_state_index": 0, "original": ORIGINAL,
                    "paraphrase": PARAPHRASES[0], "edits": pp.word_edits(ORIGINAL, PARAPHRASES[0])}
        self.screen = lang_screen()
        self.reduction = lang_reduce(workload)

    def test_the_report_compares_the_wordings_and_lists_everything(self):
        text = self.module.build_report(self.screen, self.reduction, 1.7468)
        minimal = self.reduction["minimal"]["text"]
        for expected in (ORIGINAL, PARAPHRASES[0], minimal, "~~pick up~~ **grab**", "## Screen", "## Reduction",
                         "### Every candidate", "### Videos", "Original wording (passes)",
                         "Minimal wording (fails)", "not a causal proof", "about US$", "1-minimal"):
            self.assertIn(expected, text)
        for row in self.screen["instructions"]:
            self.assertIn(row["text"], text)
        for candidate in self.reduction["reduction"]["candidates"]:
            self.assertIn(candidate["text"], text)

    def summary_of(self, text):
        start = text.index("## Summary")
        return text[start:text.index("\n## ", start + 5)]

    def test_the_summary_follows_the_title_with_control_rewordings_failures_and_the_smallest_wording(self):
        text = self.module.build_report(self.screen, self.reduction, None)
        self.assertLess(text.index("# Faultline paraphrase report"), text.index("## Summary"))
        self.assertLess(text.index("## Summary"), text.index("## Setup"))
        block = self.summary_of(text)
        self.assertIn("- Control: the original wording passed (S S).", block)
        dropped = sum(1 for text in PARAPHRASES if pp.meaning_check(ORIGINAL, text) == pp.MEANING_DROPPED)
        self.assertIn("- Rewordings: {} screened; {} kept by the meaning check, {} dropped".format(
            len(PARAPHRASES), len(PARAPHRASES) - dropped, dropped), block)
        self.assertIn("- Failures: 1 rewording failed at least 4 of 5 attempts (p01).", block)
        self.assertIn("- Smallest failing wording: 1 word edit from the original; each remaining edit is needed.",
                      block)
        self.assertIn('- Minimal wording: "{}"'.format(self.reduction["minimal"]["text"]), block)

    def test_the_summary_counts_rewordings_the_meaning_check_dropped(self):
        screen = lang_screen(paraphrases=PARAPHRASES[:2] + ["pick up the alphabet soup and place it in the container"],
                             failing=("p03",))
        block = self.summary_of(self.module.build_report(screen, None, None))
        self.assertIn("- Rewordings: 3 screened; 2 kept by the meaning check, 1 dropped", block)
        self.assertIn("- Smallest failing wording: not reduced.", block)

    def test_the_summary_says_when_nothing_failed_and_when_the_control_did_not_pass(self):
        block = self.summary_of(self.module.build_report(lang_screen(failing=()), None, None))
        self.assertIn("- Failures: none. No rewording failed at least 4 of 5 attempts in this screen.", block)
        self.assertNotIn("Smallest failing wording", block)
        block = self.summary_of(self.module.build_report(lang_screen(failing=(), control=False), None, None))
        self.assertIn("- Control: the original wording did not pass both attempts", block)

    def test_the_summary_does_not_call_an_early_stop_fully_reduced(self):
        self.reduction["minimal"]["edit_minimal"] = False
        self.reduction["reduction"]["reduced"] = False
        block = self.summary_of(self.module.build_report(self.screen, self.reduction, None))
        self.assertIn("the reduction stopped early", block)
        self.assertIn("(not fully reduced)", block)

    def test_the_report_flags_a_paraphrase_that_dropped_the_object_or_target(self):
        screen = lang_screen(paraphrases=PARAPHRASES[:2] + ["pick up the alphabet soup and place it in the container"],
                             failing=("p01", "p03"))
        text = self.module.build_report(screen, None, None)
        self.assertIn("meaning check", text)
        self.assertIn("Flagged in this screen: p03.", text)
        self.assertIn("Failed 4 of 5 but flagged, so not reduced: p03.", text)
        self.assertIn("object_or_target_dropped", text)
        self.assertNotIn("each of them dropped", text, "p01 kept its meaning")

    def test_a_screen_whose_only_failures_dropped_something_is_not_called_robust(self):
        screen = lang_screen(paraphrases=["pick up the alphabet soup and place it in the container"],
                             failing=("p01",))
        text = self.module.build_report(screen, None, None)
        self.assertIn("each of them dropped an object or target word", text)
        self.assertNotIn("was robust", text)

    def test_the_case_records_the_meaning_check_of_every_wording(self):
        screen = lang_screen(paraphrases=PARAPHRASES[:2] + ["pick up the alphabet soup and place it in the container"],
                             failing=("p01",))
        case = self.module.build_case_record(screen, self.reduction)
        self.assertEqual("kept", case["paraphrase_meaning_check"])
        self.assertEqual("kept", case["minimal"]["meaning_check"])
        checks = {row["label"]: row["meaning_check"] for row in case["screen"]}
        self.assertEqual({"orig": None, "p01": "kept", "p02": "kept", "p03": "object_or_target_dropped"}, checks)

    def test_the_screen_only_report_says_the_policy_was_robust(self):
        text = self.module.build_report(lang_screen(failing=()), None, None)
        self.assertIn("robust", text)
        self.assertNotIn("## Reduction", text)

    def test_an_early_stop_is_not_called_minimal(self):
        self.reduction["minimal"]["edit_minimal"] = False
        self.reduction["reduction"]["reduced"] = False
        self.reduction["reduction"]["stop_reason"] = "budget_exhausted"
        text = self.module.build_report(self.screen, self.reduction, None)
        self.assertIn("stopped early", text)

    def test_wrong_inputs_are_refused(self):
        with self.assertRaises(self.module.ReportError):
            self.module.build_report(self.reduction, None)
        with self.assertRaises(self.module.ReportError):
            self.module.build_report(self.screen, self.screen)
        with self.assertRaises(self.module.ReportError):
            self.module.build_report({})

    def test_mark_edits_shows_replacements_insertions_and_deletions(self):
        edits = pp.word_edits("pick up the red bowl", "grab the bowl now")
        marked = self.module.mark_edits("pick up the red bowl", edits)
        self.assertEqual("~~pick up~~ **grab** the ~~red~~ bowl **now**", marked)

    def test_the_command_line_writes_a_report_and_a_case(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "screen.json").write_text(json.dumps(self.screen), encoding="utf-8")
            (root / "reduce.json").write_text(json.dumps(self.reduction), encoding="utf-8")
            code = self.module.main([str(root / "screen.json"), "--reduction", str(root / "reduce.json"),
                                     "--out", str(root / "report.md"), "--case-out", str(root / "case.json"),
                                     "--hourly-rate", "1.8"])
            self.assertEqual(0, code)
            self.assertIn("Faultline paraphrase report", (root / "report.md").read_text(encoding="utf-8"))
            self.assertEqual("paraphrase_reduction", json.loads((root / "case.json").read_text())["kind"])
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(2, self.module.main([str(root / "screen.json"), "--out", str(root / "report.md")]))


if __name__ == "__main__":
    unittest.main()


class OriginalWordingTests(unittest.TestCase):
    def test_same_wording_ignores_case_and_spacing_only(self):
        from robot_debug import language_experiment as le
        self.assertTrue(le.same_wording("Pick up  the soup", "pick up the soup"))
        self.assertFalse(le.same_wording("pick up the soup", "pick up a soup"))
        self.assertFalse(le.same_wording(None, "pick up the soup"))
