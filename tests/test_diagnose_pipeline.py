"""The one diagnosis pipeline (ADR 0035) end to end: fake backend, fake Nemotron, summaries of every branch."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

from robot_debug import case_register as cr
from robot_debug import orchestrator as orch
from robot_debug import spec as sp
from tests.test_orchestrator import (
    RATE, SOUP_ONLY, cost, finished, make_world, reduce_one, screen_summary)
from tests.test_paraphrase_pipeline import ORIGINAL, ParaphraseTools, lang_reduce, lang_screen

M6 = "m6_summary.json"
LANG = "language_summary.json"
BACKEND = {"kind": "nebius", "image": "cr.example.invalid/REGISTRY_ID/faultline@sha256:IMAGE_DIGEST",
           "hf_token_secret": "faultline-hf-token", "hourly_usd": RATE}
FAMILIES = ["blur", "noise", "lighting"]


def diag_spec(*, probes: Optional[Dict[str, Any]] = None, layout: bool = True, cap: float = 40.0,
              name: str = "soup-diag", **diagnose) -> sp.Spec:
    probes = {"families": FAMILIES, "rewordings": 4, "instruction": ORIGINAL} if probes is None else probes
    return sp.parse_spec({
        "faultline": 1, "name": name, "mode": "diagnose", "policy": {"suite": "libero_10"},
        "diagnose": dict({"task": 3, "start": 0, "probes": probes, "layout": layout}, **diagnose),
        "budget": {"max_spend_usd": cap, "max_hours": 10, "max_candidates": 36},
        "nemotron": {"hypothesis": True, "explain": True}, "backend": dict(BACKEND)})


def m6_summary(families, thresholds=None, control_ok=True, complete=True) -> Dict[str, Any]:
    """A group summary shaped like ``m6_summary.json``: episode records, levels and the control."""

    thresholds = thresholds or {}
    sweep = [0.2, 0.4, 0.6, 0.8, 1.0]
    items: List[Dict[str, Any]] = []
    for number in range(1, 6):
        outcome = "success" if control_ok or number > 2 else "policy_failure"
        items.append({"case_id": "nominal-control-{:02d}".format(number), "kind": "nominal", "status": "valid",
                      "outcome": outcome, "condition": "nominal", "repeat": number})
    result: Dict[str, Any] = {}

    def record(family, severity, failures):
        for number in range(1, 6):
            items.append({
                "case_id": "{}-s{:06d}-a{:02d}".format(family, int(round(severity * 1e6)), number),
                "kind": family, "status": "valid", "family": family, "severity": severity, "attempt": number,
                "phase": "sweep", "outcome": "policy_failure" if number <= failures else "success"})
        return {"severity": severity, "failures": failures, "complete": True,
                "outcomes": ["policy_failure"] * failures + ["success"] * (5 - failures)}

    for family in families:
        if not control_ok:
            result[family] = {"threshold_severity": None, "stop_reason": "nominal_failed", "levels": [],
                              "attempts_used": 0}
        elif family in thresholds:
            levels = [record(family, 0.2, 0), record(family, thresholds[family], 5)]
            result[family] = {"threshold_severity": thresholds[family], "lower_bound": 0.2,
                              "stop_reason": "threshold_found", "levels": levels, "attempts_used": 10}
        else:
            result[family] = {"threshold_severity": None, "stop_reason": "no_reproducible_failure",
                              "levels": [record(family, level, 0) for level in sweep], "attempts_used": 25}
    outcomes = {"success": sum(1 for i in items if i["kind"] == "nominal" and i["outcome"] == "success"),
                "policy_failure": sum(1 for i in items if i["kind"] == "nominal" and i["outcome"] != "success")}
    return {"schema_version": 1, "mode": "m6-threshold", "complete": complete and control_ok,
            "stop_reason": None if control_ok and complete else ("nominal_controls_failed" if not control_ok else "deadline_exhausted"),
            "config": {"families": list(families), "sweep": sweep, "attempts": 5, "required_failures": 4,
                       "bisection_steps": 4, "suite": "libero_10", "task_id": 3, "init_state_index": 0},
            "nominal_controls": {"outcomes": outcomes, "planned": 5}, "families": result, "items": items}


def m6_step(families, **kwargs):
    return finished(lambda workload: m6_summary(families, **kwargs), name=M6)


def lang_step(**kwargs):
    return finished(lambda workload: lang_screen(**kwargs), name=LANG)


def reduce_step(**kwargs):
    return finished(lambda workload: lang_reduce(workload, **kwargs), name=LANG)


def screen_step(failing=False):
    return finished(lambda workload: screen_summary(failing=failing))


class Base(unittest.TestCase):
    def world(self, behaviours, spec=None, tools=None, **options):
        temp, runner, backend, tools, ledger, lines = make_world(
            spec or diag_spec(), behaviours, tools=tools or ParaphraseTools(), **options)
        self.addCleanup(temp.cleanup)
        return runner, backend, tools, ledger, lines

    @staticmethod
    def diagnoses(runner):
        return cr.list_diagnoses(runner.run_dir.parent.parent / "diagnoses")

    @staticmethod
    def read(runner, *parts):
        return json.loads(runner.run_dir.joinpath(*parts).read_text(encoding="utf-8"))

    def header(self, runner):
        return self.read(runner, "steps.json")


class ProbesRoute(Base):
    def full_script(self):
        return [screen_step(), m6_step(["blur", "noise"], thresholds={"blur": 0.4}),
                m6_step(["lighting"]), lang_step(failing=("p01",)), reduce_step()]

    def test_a_passing_start_gets_the_stress_test_and_the_rewordings_and_two_cases(self):
        runner, backend, tools, ledger, lines = self.world(self.full_script())
        result = runner.diagnose()
        tag = runner.tag
        self.assertEqual((result.status, result.reason, result.route), ("completed", None, "probes"))
        self.assertEqual(backend.submitted, ["soup-diag-{}-{}".format(tag, step) for step in (
            "screen", "probe-image-1", "probe-scene-1", "rewording-screen", "rewording-reduce")])
        self.assertAlmostEqual(ledger.spent, 5 * cost())
        self.assertEqual(self.header(runner)["run"]["route"], "probes")
        # The probe Jobs are audit Jobs on the chosen start, split by kind.
        image, scene = backend.workloads[backend.submitted[1]], backend.workloads[backend.submitted[2]]
        self.assertEqual((image["mode"], image["families"], image["init_state_index"], image["task_id"]),
                         ("m6-threshold", ["noise", "blur"], 0, 3))
        self.assertEqual(scene["families"], ["lighting"])
        self.assertEqual(backend.workloads[backend.submitted[3]]["mode"], "paraphrase-screen")

        audit = self.read(runner, "cases", "audit", "case.json")
        self.assertEqual(audit["kind"], "audit")
        self.assertEqual(audit["families"]["blur"]["threshold_severity"], 0.4)
        self.assertIsNone(audit["families"]["lighting"]["threshold_severity"])
        self.assertTrue(audit["complete"])
        self.assertEqual(audit["replay"]["groups"],
                         [{"step": "probe-image-1", "families": [{"family": "blur", "severity": 0.4}]}])
        self.assertEqual(self.read(runner, "cases", "audit", "replay-inputs.json"), audit["replay"])
        self.assertEqual(set(audit["videos"]), {"control", "blur@0.40", "noise@1.00", "lighting@1.00"})
        self.assertEqual(audit["videos"]["blur@0.40"]["label"], "Gaussian blur at s = 0.40 (failed)")
        self.assertEqual(audit["videos"]["lighting@1.00"]["label"], "Scene lighting at s = 1.00 (passed)")
        self.assertTrue((runner.run_dir / "cases" / "audit" / "report.md").is_file())
        merged = self.read(runner, "cases", "audit", "merged-summary.json")
        self.assertEqual(set(merged["families"]), set(FAMILIES))
        self.assertEqual(audit["summary"], "cases/audit/merged-summary.json")

        wording = self.read(runner, "cases", "wording", "case.json")
        self.assertEqual((wording["kind"], wording["reduced"]), ("paraphrase_reduction", True))
        self.assertIn("instruction", wording["replay"]["config"])
        self.assertEqual(self.read(runner, "cases", "wording", "replay-inputs.json"), wording["replay"])
        self.assertTrue((runner.run_dir / "cases" / "wording" / "report.md").is_file())

        entries = self.diagnoses(runner)
        self.assertEqual(sorted(e["case_id"] for e in entries), sorted([audit["case_id"], wording["case_id"]]))
        self.assertEqual({e["route"] for e in entries}, {"probes"})
        self.assertEqual(result.case_ids, [audit["case_id"], wording["case_id"]])
        steps = self.header(runner)["steps"]
        for step in ("screen", "probe-image-1", "probe-scene-1", "rewording-screen", "rewording-reduce",
                     "case-audit", "case-wording", "register"):
            self.assertEqual(steps[step]["status"], "done", step)

    def test_no_failure_anywhere_still_records_both_cases(self):
        script = [screen_step(), m6_step(["blur", "noise"]), m6_step(["lighting"]), lang_step(failing=())]
        runner, backend, tools, ledger, lines = self.world(script)
        result = runner.diagnose()
        self.assertEqual((result.status, result.route, len(backend.submitted)), ("completed", "probes", 4))
        audit = self.read(runner, "cases", "audit", "case.json")
        self.assertNotIn("replay", audit)
        self.assertFalse((runner.run_dir / "cases" / "audit" / "replay-inputs.json").exists())
        wording = self.read(runner, "cases", "wording", "case.json")
        self.assertIsNone(wording["minimal"])
        self.assertFalse(wording["failure"])
        self.assertEqual(wording["stop_reason"], "no_reproducible_failure")
        self.assertEqual(wording["instruction"], ORIGINAL)
        self.assertFalse((runner.run_dir / "cases" / "wording" / "replay-inputs.json").exists())
        self.assertEqual(len(self.diagnoses(runner)), 2)

    def test_a_flaky_start_skips_the_other_groups_and_the_rewordings(self):
        script = [screen_step(), m6_step(["blur", "noise"], control_ok=False)]
        runner, backend, tools, ledger, lines = self.world(script)
        result = runner.diagnose()
        self.assertEqual((result.status, result.reason, result.route), ("completed", None, "flaky"))
        self.assertEqual(len(backend.submitted), 2)
        self.assertEqual(tools.generated, [], "no Nemotron call for a flaky start")
        audit = self.read(runner, "cases", "audit", "case.json")
        self.assertEqual(audit["stop_reason"], "nominal_controls_failed")
        self.assertFalse(audit["complete"])
        self.assertEqual(audit["families"]["lighting"]["stop_reason"], "not_run")
        self.assertEqual(audit["videos"]["control"]["label"], "Unperturbed control (failed)")
        self.assertFalse((runner.run_dir / "cases" / "wording").exists())
        self.assertEqual(self.header(runner)["run"]["route"], "flaky")
        self.assertEqual(len(self.diagnoses(runner)), 1)

    def test_a_failing_rewording_control_is_a_flaky_start_too(self):
        script = [screen_step(), m6_step(["blur", "noise"]), m6_step(["lighting"]),
                  lang_step(failing=("p01",), control=False)]
        runner, backend, tools, ledger, lines = self.world(script)
        result = runner.diagnose()
        self.assertEqual((result.route, len(backend.submitted)), ("flaky", 4))
        wording = self.read(runner, "cases", "wording", "case.json")
        self.assertEqual(wording["stop_reason"], "control_not_passing")
        self.assertIsNone(wording["minimal"])

    def test_the_wording_probe_uses_the_task_wording_the_check_recorded(self):
        spec = diag_spec(probes={"families": [], "rewordings": 4})
        script = [screen_step(), lang_step(failing=())]
        runner, backend, tools, ledger, lines = self.world(script, spec=spec)
        runner.diagnose()
        self.assertEqual(tools.generated[0][0], "put the soup in the basket")
        self.assertEqual(backend.workloads[backend.submitted[1]]["original"], "put the soup in the basket")

    def test_families_only_and_rewordings_only(self):
        runner, backend, *_ = self.world([screen_step(), m6_step(["blur"])],
                                         spec=diag_spec(probes={"families": ["blur"], "rewordings": 0}))
        result = runner.diagnose()
        self.assertEqual((result.status, len(backend.submitted), len(result.case_ids)), ("completed", 2, 1))
        self.assertFalse((runner.run_dir / "cases" / "wording").exists())

    def test_nemotron_failing_keeps_the_paid_stress_test_and_stops_for_a_resume(self):
        tools = ParaphraseTools(result={"original": ORIGINAL, "paraphrases": [], "fallback_reason": "down"})
        runner, backend, tools, ledger, lines = self.world(
            [screen_step(), m6_step(["blur", "noise"]), m6_step(["lighting"])], tools=tools)
        result = runner.diagnose()
        self.assertEqual((result.status, result.reason), ("stopped", "paraphrase_failed"))
        self.assertEqual(len(backend.submitted), 3)
        self.assertEqual(len(self.diagnoses(runner)), 1, "the audit case is registered before the stop")
        self.assertEqual(self.header(runner)["run"]["status"], "stopped")

    def test_probe_only_runs_the_probes_even_when_the_start_fails(self):
        script = [screen_step(failing=True), m6_step(["blur"]), ]
        spec = diag_spec(probes={"families": ["blur"], "rewordings": 0}, layout=False)
        runner, backend, tools, ledger, lines = self.world(script, spec=spec)
        result = runner.diagnose()
        self.assertEqual((result.route, len(backend.submitted)), ("probes", 2))

    def test_an_incomplete_group_makes_the_run_stopped_but_keeps_the_case(self):
        script = [screen_step(), finished(lambda w: m6_summary(["blur", "noise"], complete=False), name=M6,
                                          state="FAILED", reason="ContainerFailed"),
                  m6_step(["lighting"])]
        spec = diag_spec(probes={"families": FAMILIES, "rewordings": 0})
        runner, backend, tools, ledger, lines = self.world(script, spec=spec)
        result = runner.diagnose()
        self.assertEqual(result.status, "stopped")
        self.assertTrue(result.reason)
        self.assertEqual(len(self.diagnoses(runner)), 1)

    def test_stop_and_resume_keep_every_branch_step(self):
        script = self.full_script()[:3]
        runner, backend, tools, ledger, lines = self.world(script)
        backend.kills_at_wait = 3                               # the scene group's Job is cut off
        with self.assertRaises(BaseException):
            runner.diagnose()
        run_dir = runner.run_dir
        backend2_script = [m6_step(["lighting"]), lang_step(failing=("p01",)), reduce_step()]
        from tests.test_orchestrator import FakeBackend

        temp, runner2, backend2, tools2, ledger2, lines2 = make_world(
            diag_spec(), [], backend=FakeBackend(backend2_script), tools=ParaphraseTools(), run_dir=run_dir)
        self.addCleanup(temp.cleanup)
        result = runner2.diagnose()
        self.assertEqual((result.status, result.route), ("completed", "probes"))
        self.assertEqual((len(backend2.submitted), len(backend2.waited)), (2, 3), "the cut-off Job is re-attached, not resubmitted")
        self.assertTrue(any("already done" in line and "screen" in line for line in lines2))
        self.assertEqual(len(self.diagnoses(runner2)), 2)


class PassesAndLayout(Base):
    def test_a_passing_start_with_no_probes_is_a_finding(self):
        spec = diag_spec(probes={"enabled": False})
        runner, backend, tools, ledger, lines = self.world([screen_step()], spec=spec)
        result = runner.diagnose()
        self.assertEqual((result.status, result.reason, result.route, result.exit_code),
                         ("completed", None, "passes", 0))
        self.assertEqual(len(backend.submitted), 1)
        self.assertEqual(self.header(runner)["run"]["route"], "passes")
        self.assertEqual(self.header(runner)["run"]["status"], "completed")
        self.assertTrue((runner.run_dir / "report.md").is_file())
        self.assertFalse((runner.run_dir / "cases").exists())
        self.assertEqual(self.diagnoses(runner), [])

    def test_a_failing_start_continues_exactly_like_the_scenario_mode(self):
        script = [screen_step(failing=True),
                  finished(reduce_one(stop_reason="reduced", selection=SOUP_ONLY, entity_minimal=True, reduced=True))]
        runner, backend, tools, ledger, lines = self.world(script, tools=ParaphraseTools())
        result = runner.diagnose()
        self.assertEqual((result.status, result.route), ("completed", "layout"))
        self.assertEqual(len(backend.submitted), 2, "no probe runs for a failing start")
        self.assertEqual(backend.workloads[backend.submitted[1]]["mode"], "scenario-reduce")
        self.assertEqual(self.header(runner)["run"]["route"], "layout")
        self.assertTrue((runner.run_dir / "case.json").is_file())
        self.assertEqual(tools.registered, [runner.run_dir])

    def test_a_range_of_starts_is_layout_only_and_stops_when_nothing_fails(self):
        spec = sp.parse_spec(dict(diag_spec().raw, diagnose={"task": 3, "screen": {"starts": "0-3"}}))
        runner, backend, tools, ledger, lines = self.world([screen_step()], spec=spec)
        result = runner.diagnose()
        self.assertEqual((result.status, result.reason), ("stopped", "no_reproducible_failure"))
        self.assertEqual(len(backend.submitted), 1)

    def test_probe_free_failing_start_with_layout_off_is_refused_by_the_spec(self):
        with self.assertRaises(sp.SpecError):
            diag_spec(probes={"enabled": False}, layout=False)


class JobNames(Base):
    def test_a_long_spec_name_is_shortened_so_the_longest_step_still_fits(self):
        runner, *_ = self.world([], spec=diag_spec(name="a" * 40))
        for step in ("rewording-reduce", "probe-image-2", "reduce4"):
            name = runner.job_name(step, 5)
            self.assertLessEqual(len(name), 63)
            self.assertTrue(name.endswith("-" + step + "-e"))
            self.assertIn(runner.tag, name)

    def test_names_that_already_fit_are_unchanged(self):
        runner, *_ = self.world([], spec=diag_spec(name="soup-diag"))
        self.assertEqual(runner.job_name("screen", 0), "soup-diag-{}-screen".format(runner.tag))


if __name__ == "__main__":
    unittest.main()
