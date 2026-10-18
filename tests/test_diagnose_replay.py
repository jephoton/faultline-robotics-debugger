"""Replay of stress-test and wording cases (ADR 0035): the verdicts, the workloads, the exit codes."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

from robot_debug import cli
from robot_debug import orchestrator as orch
from tests.test_diagnose_pipeline import LANG, M6, ORIGINAL, lang_step, m6_step, m6_summary
from tests.test_orchestrator import FakeBackend, finished, make_world, spec_for
from tests.test_paraphrase_pipeline import ParaphraseTools

CHECKPOINT = {"id": "example/checkpoint-libero_10", "revision": "0123456789abcdef0123456789abcdef01234567",
              "pinned": True}


def audit_case(groups=None, **extra) -> Dict[str, Any]:
    groups = groups or [{"step": "probe-image-1", "families": [{"family": "blur", "severity": 0.4},
                                                                {"family": "noise", "severity": 0.6}]}]
    case = {"schema_version": 1, "kind": "audit", "case_id": "ab" * 32, "suite": "libero_10", "task_id": 3,
            "start_index": 0, "families": {}, "complete": True,
            "replay": {"kind": "audit", "attempts": 5, "required_failures": 4, "groups": groups}}
    case.update(extra)
    return case


def wording_case(**extra) -> Dict[str, Any]:
    case = {"schema_version": 1, "kind": "paraphrase_reduction", "case_id": "cd" * 32, "suite": "libero_10",
            "task_id": 3, "start_index": 0, "instruction": ORIGINAL,
            "replay": {"config": {"suite": "libero_10", "task_id": 3, "init_state_index": 0,
                                  "instruction": "grab the alphabet soup and put it in the basket"},
                       "reference_instruction": ORIGINAL, "gate": {"attempts": 5, "required_failures": 4}}}
    case.update(extra)
    return case


class Base(unittest.TestCase):
    def case_dir(self, case) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        (Path(directory.name) / "case.json").write_text(json.dumps(case), encoding="utf-8")
        return Path(directory.name)

    def replay(self, case, script, **options):
        temp, runner, backend, tools, ledger, lines = make_world(
            spec_for(mode="replay"), script, tools=ParaphraseTools(), **options)
        self.addCleanup(temp.cleanup)
        result = runner.replay(self.case_dir(case))
        saved = None
        path = runner.run_dir / "replay-result.json"
        if path.is_file():
            saved = json.loads(path.read_text(encoding="utf-8"))
        return result, saved, runner, backend, lines


class AuditReplay(Base):
    def test_each_failing_family_is_rerun_at_its_threshold_and_a_family_that_holds_is_reported(self):
        script = [m6_step(["blur", "noise"], thresholds={"blur": 0.4})]
        result, saved, runner, backend, lines = self.replay(audit_case(), script)
        workload = backend.workloads[backend.submitted[0]]
        self.assertEqual((workload["mode"], workload["families"], workload["sweep"], workload["bisection_steps"],
                          workload["attempts"], workload["required_failures"]),
                         ("m6-threshold", ["noise", "blur"], [0.4, 0.6], 0, 5, 4))
        self.assertEqual((workload["suite"], workload["task_id"], workload["init_state_index"]), ("libero_10", 3, 0))
        self.assertEqual((result.status, result.verdict, result.reproduces), ("completed", "still_reproduces", True))
        self.assertEqual(saved["verdict_text"], "still fails at s = 0.40 (blur); no longer fails at s = 0.60 (noise)")
        self.assertEqual(saved["kind"], "audit")
        self.assertIn("still fails at s = 0.40 (blur)", " ".join(lines))

    def test_a_family_that_no_longer_fails_is_a_fixed_verdict(self):
        result, saved, *_ = self.replay(audit_case(), [m6_step(["blur", "noise"])])
        self.assertEqual((result.verdict, result.reproduces, saved["verdict_text"]),
                         ("no_longer_reproduces", False, "no longer fails at s = 0.40 (blur), s = 0.60 (noise)"))

    def test_a_threshold_that_moved_up_is_not_still_failing(self):
        case = audit_case([{"step": "probe-image-1", "families": [{"family": "blur", "severity": 0.4}]}])
        result, saved, *_ = self.replay(case, [m6_step(["blur"], thresholds={"blur": 0.8})])
        self.assertEqual((result.verdict, result.reproduces), ("no_longer_reproduces", False))
        self.assertEqual(saved["verdict_text"], "no longer fails at s = 0.40 (blur; fails only at higher s = 0.80)")

    def test_a_threshold_that_moved_down_still_fails_at_the_new_level(self):
        case = audit_case([{"step": "probe-image-1", "families": [{"family": "blur", "severity": 0.6}]}])
        result, saved, *_ = self.replay(case, [m6_step(["blur"], thresholds={"blur": 0.4})])
        self.assertEqual((result.verdict, saved["verdict_text"]), ("still_reproduces", "still fails at s = 0.40 (blur)"))

    def test_a_family_the_replay_never_tested_is_not_listed_as_no_longer_failing(self):
        # The Job's summary holds no result for noise (it stopped first): noise is untested.
        result, saved, *_ = self.replay(audit_case(), [m6_step(["blur"], thresholds={"blur": 0.4})])
        self.assertEqual(result.verdict, "still_reproduces")
        self.assertEqual(saved["verdict_text"], "still fails at s = 0.40 (blur); not tested: noise")
        gone, saved2, *_ = self.replay(audit_case(), [m6_step(["blur"])])
        self.assertEqual((gone.status, gone.verdict), ("stopped", "incomplete"))
        self.assertNotIn("no longer fails", saved2["verdict_text"])

    def test_a_failing_control_is_inconclusive_not_fixed(self):
        result, saved, *_ = self.replay(audit_case(), [m6_step(["blur", "noise"], control_ok=False)])
        self.assertEqual((result.status, result.reason, result.verdict, result.reproduces),
                         ("stopped", "replay_inconclusive", "reference_fails", None))
        self.assertIn("unperturbed control", saved["verdict_text"])

    def test_a_replay_that_did_not_finish_cannot_say_fixed(self):
        script = [finished(lambda w: m6_summary(["blur", "noise"], complete=False), name=M6, state="FAILED",
                           reason="ContainerFailed")]
        result, saved, *_ = self.replay(audit_case(), script)
        self.assertEqual((result.status, result.verdict), ("stopped", "incomplete"))

    def test_a_case_with_failing_families_in_two_groups_replays_one_job_per_group(self):
        groups = [{"step": "probe-image-1", "families": [{"family": "blur", "severity": 0.4}]},
                  {"step": "probe-scene-1", "families": [{"family": "lighting", "severity": 0.8}]}]
        script = [m6_step(["blur"], thresholds={"blur": 0.4}), m6_step(["lighting"], thresholds={"lighting": 0.2})]
        result, saved, runner, backend, lines = self.replay(audit_case(groups), script)
        self.assertEqual([n.rsplit("-", 1)[1] for n in backend.submitted], ["replay", "2"])
        self.assertEqual(backend.workloads[backend.submitted[1]]["families"], ["lighting"])
        self.assertEqual(saved["verdict_text"], "still fails at s = 0.40 (blur); still fails at s = 0.20 (lighting)")
        self.assertEqual(len(saved["jobs"]), 2)

    def two_groups(self):
        return audit_case([{"step": "probe-image-1", "families": [{"family": "blur", "severity": 0.4}]},
                           {"step": "probe-scene-1", "families": [{"family": "lighting", "severity": 0.8}]}])

    def test_a_stop_between_groups_keeps_the_verdicts_of_the_groups_that_ran(self):
        temp, runner, backend, tools, ledger, lines = make_world(
            spec_for(mode="replay"), [m6_step(["blur"], thresholds={"blur": 0.4})], tools=ParaphraseTools())
        self.addCleanup(temp.cleanup)
        backend.fail_submit_at = 1                        # the second group's Job cannot be submitted
        result = runner.replay(self.case_dir(self.two_groups()))
        self.assertEqual((result.status, result.reason, result.verdict, result.reproduces),
                         ("stopped", "backend_error", "incomplete", None))
        saved = json.loads((runner.run_dir / "replay-result.json").read_text(encoding="utf-8"))
        self.assertEqual((saved["verdict"], saved["reproduces"], saved["partial"], len(saved["jobs"])),
                         ("incomplete", None, True, 1))
        self.assertIn("still fails at s = 0.40 (blur)", saved["verdict_text"])
        self.assertIn("not finished", saved["verdict_text"])
        self.assertEqual(saved["groups"], {"ran": 1, "planned": 2})

    def test_a_stop_before_any_group_ran_writes_no_partial_result(self):
        temp, runner, backend, tools, ledger, lines = make_world(
            spec_for(mode="replay"), [], tools=ParaphraseTools())
        self.addCleanup(temp.cleanup)
        backend.fail_submit_at = 0
        result = runner.replay(self.case_dir(self.two_groups()))
        self.assertEqual((result.status, result.reason, result.verdict), ("stopped", "backend_error", None))
        self.assertFalse((runner.run_dir / "replay-result.json").exists())

    def test_the_cases_own_checkpoint_is_replayed_against(self):
        script = [m6_step(["blur", "noise"], thresholds={"blur": 0.4})]
        result, saved, runner, backend, lines = self.replay(audit_case(checkpoint=CHECKPOINT), script)
        workload = backend.workloads[backend.submitted[0]]
        self.assertEqual((workload["checkpoint_id"], workload["checkpoint_revision"]),
                         (CHECKPOINT["id"], CHECKPOINT["revision"]))
        self.assertEqual(saved["checkpoint"]["id"], CHECKPOINT["id"])

    def test_a_case_without_a_failing_family_has_nothing_to_replay(self):
        case = audit_case()
        case["replay"]["groups"] = []
        result, saved, runner, backend, lines = self.replay(case, [])
        self.assertEqual((result.status, result.reason, backend.submitted), ("stopped", "replay_inputs_missing", []))

    def test_the_cap_rule_applies_to_the_replay_job(self):
        temp, runner, backend, tools, ledger, lines = make_world(
            spec_for(mode="replay", cap=0.5), [m6_step(["blur"])], tools=ParaphraseTools())
        self.addCleanup(temp.cleanup)
        result = runner.replay(self.case_dir(audit_case()))
        self.assertEqual((result.reason, backend.submitted), ("spend_cap", []))


class WordingReplay(Base):
    def test_the_failing_wording_is_rerun_against_the_original_control(self):
        result, saved, runner, backend, lines = self.replay(wording_case(), [lang_step(failing=("p01",))])
        workload = backend.workloads[backend.submitted[0]]
        self.assertEqual((workload["mode"], workload["original"], workload["paraphrases"], workload["confirm_attempts"]),
                         ("paraphrase-screen", ORIGINAL, ["grab the alphabet soup and put it in the basket"], 4))
        self.assertEqual((result.verdict, result.reproduces, saved["verdict_text"]),
                         ("still_reproduces", True, "the wording still fails"))
        self.assertEqual(saved["kind"], "paraphrase")

    def test_a_wording_that_passes_now_is_fixed(self):
        result, saved, *_ = self.replay(wording_case(), [lang_step(failing=())])
        self.assertEqual((result.verdict, saved["verdict_text"]), ("no_longer_reproduces", "no longer fails"))

    def test_a_failing_original_control_is_inconclusive(self):
        result, saved, *_ = self.replay(wording_case(), [lang_step(failing=("p01",), control=False)])
        self.assertEqual((result.status, result.verdict), ("stopped", "reference_fails"))
        self.assertIn("original wording", saved["verdict_text"])

    def test_a_case_with_no_failing_wording_has_nothing_to_replay(self):
        result, *_ = self.replay(wording_case(replay=None), [])
        self.assertEqual(result.reason, "replay_inputs_missing")

    def test_a_scenario_suite_mismatch_is_still_refused_for_every_kind(self):
        for case in (audit_case(), wording_case()):
            temp, runner, backend, tools, ledger, lines = make_world(
                spec_for(mode="replay", policy={"suite": "libero_object"}), [], tools=ParaphraseTools())
            self.addCleanup(temp.cleanup)
            self.assertEqual(runner.replay(self.case_dir(case)).reason, "suite_mismatch")


class ExpectGate(Base):
    def test_expect_works_for_the_new_kinds(self):
        out: List[str] = []
        still, *_ = self.replay(wording_case(), [lang_step(failing=("p01",))])
        self.assertEqual(cli._expectation_code(still, "reproduces", out.append), 0)
        self.assertEqual(cli._expectation_code(still, "fixed", out.append), cli.EXIT_UNEXPECTED_VERDICT)
        gone, *_ = self.replay(audit_case(), [m6_step(["blur", "noise"])])
        self.assertEqual(cli._expectation_code(gone, "fixed", out.append), 0)
        inconclusive, *_ = self.replay(audit_case(), [m6_step(["blur", "noise"], control_ok=False)])
        self.assertEqual(cli._expectation_code(inconclusive, "reproduces", out.append), cli.EXIT_UNEXPECTED_VERDICT)

    def test_the_not_met_message_speaks_of_the_kind_of_case_not_of_a_scene(self):
        out: List[str] = []
        gone, *_ = self.replay(audit_case(), [m6_step(["blur", "noise"])])
        self.assertEqual(cli._expectation_code(gone, "reproduces", out.append), cli.EXIT_UNEXPECTED_VERDICT)
        self.assertIn("no longer fails at s = 0.40 (blur)", out[-1])
        self.assertNotIn("The failure", out[-1])
        still, *_ = self.replay(wording_case(), [lang_step(failing=("p01",))])
        self.assertEqual(cli._expectation_code(still, "fixed", out.append), cli.EXIT_UNEXPECTED_VERDICT)
        self.assertIn("the wording still fails", out[-1])
        self.assertNotIn("The failure", out[-1])
        failing_control, *_ = self.replay(wording_case(), [lang_step(failing=("p01",), control=False)])
        cli._expectation_code(failing_control, "fixed", out.append)
        self.assertIn("original wording", out[-1])

    def test_expect_on_a_replay_that_stopped_part_way_says_inconclusive(self):
        temp, runner, backend, tools, ledger, lines = make_world(
            spec_for(mode="replay"), [m6_step(["blur"], thresholds={"blur": 0.4})], tools=ParaphraseTools())
        self.addCleanup(temp.cleanup)
        backend.fail_submit_at = 1
        groups = [{"step": "probe-image-1", "families": [{"family": "blur", "severity": 0.4}]},
                  {"step": "probe-scene-1", "families": [{"family": "lighting", "severity": 0.8}]}]
        result = runner.replay(self.case_dir(audit_case(groups)))
        out: List[str] = []
        self.assertEqual(cli._expectation_code(result, "reproduces", out.append), cli.EXIT_UNEXPECTED_VERDICT)
        self.assertEqual(len(out), 1)
        self.assertIn("inconclusive", out[0].lower())
        self.assertIn("backend_error", out[0])

    def test_expect_on_a_refusal_before_any_job_keeps_the_run_exit_code(self):
        temp, runner, backend, tools, ledger, lines = make_world(
            spec_for(mode="replay", policy={"suite": "libero_object"}), [], tools=ParaphraseTools())
        self.addCleanup(temp.cleanup)
        result = runner.replay(self.case_dir(audit_case()))
        self.assertEqual(result.reason, "suite_mismatch")
        self.assertEqual(cli._expectation_code(result, "fixed", [].append), result.exit_code)


if __name__ == "__main__":
    unittest.main()
