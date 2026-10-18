"""The library's view of a pipeline run: findings, route, clips, replayable kinds, the run without a case."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from robot_debug import case_register as cr
from robot_debug import pipeline_cases as pc
from robot_debug.viewer.library import Library
from tests.test_case_register_cases import AUDIT_ID, JOB, WORDING_ID, make_pipeline_run
from tests.test_diagnose_pipeline import m6_summary
from tests.ui_fixtures import ledger_document, steps_document, write_json, write_text


class PipelineLibrary(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.run = make_pipeline_run(self.root)
        case = json.loads((self.run / "cases" / "audit" / "case.json").read_text())
        case["replay"] = {"kind": "audit", "attempts": 5, "required_failures": 4,
                          "groups": [{"step": "probe-image-1", "families": [{"family": "blur", "severity": 0.4}]}]}
        write_json(self.run / "cases" / "audit" / "case.json", case)
        write_json(self.run / "jobs" / JOB / "evidence" / "m6" / "m6_summary.json",
                   m6_summary(["blur", "noise"], thresholds={"blur": 0.4}))
        write_json(self.run / "cases" / "audit" / "merged-summary.json",
                   m6_summary(["blur", "noise"], thresholds={"blur": 0.4}))
        case["summary"] = "cases/audit/merged-summary.json"
        write_json(self.run / "cases" / "audit" / "case.json", case)
        write_json(self.run / "ledger.json", ledger_document(2.0))
        cr.register_cases(self.run)
        self.library = Library(self.root, runs_root=self.root / "runs")

    def test_both_cases_are_listed_with_their_own_verdicts(self):
        items = {i["id"]: i for i in self.library.list()["items"]}
        audit, wording = items["d-" + AUDIT_ID], items["d-" + WORDING_ID]
        self.assertEqual((audit["kind"], audit["verdict"]), ("audit", "reproduces"))
        self.assertEqual((wording["kind"], wording["verdict"]), ("paraphrase", "no_failure"))
        self.assertIn("None of the 0 rewordings", wording["verdict_text"])

    def test_findings_list_every_case_of_the_run_in_route_order_from_either_case(self):
        for identifier in ("d-" + AUDIT_ID, "d-" + WORDING_ID):
            detail = self.library.detail(identifier)
            self.assertEqual([f["id"] for f in detail["findings"]], ["d-" + AUDIT_ID, "d-" + WORDING_ID])
            self.assertEqual(sorted(detail["findings"][0]), ["fault_code", "id", "kind", "verdict", "verdict_text"])
            self.assertTrue(detail["findings"][0]["fault_code"].startswith("FL-A-"))
            self.assertTrue(detail["findings"][1]["fault_code"].startswith("FL-L-"))
            self.assertEqual(detail["route"], "probes")

    def test_clips_come_with_roles_labels_and_urls_control_first(self):
        detail = self.library.detail("d-" + AUDIT_ID)
        self.assertEqual([v["role"] for v in detail["videos"]], ["control", "blur@0.40", "noise@1.00"])
        by = {v["role"]: v for v in detail["videos"]}
        self.assertEqual(by["blur@0.40"]["label"], "Gaussian blur at s = 0.40 (failed)")
        self.assertEqual(by["blur@0.40"]["outcome"], "policy_failure")
        self.assertEqual(by["blur@0.40"]["url"], "/media/diagnoses/{}/videos/blur-0.40.mp4".format(AUDIT_ID))
        wording = self.library.detail("d-" + WORDING_ID)
        self.assertEqual([v["label"] for v in wording["videos"]], ["Original wording (passed)", 'Reworded "x" (passed)'])

    def test_audit_cases_with_a_failing_family_are_replayable_and_empty_wording_cases_are_not(self):
        self.assertTrue(self.library.detail("d-" + AUDIT_ID)["replayable"])
        self.assertFalse(self.library.detail("d-" + WORDING_ID)["replayable"])

    def test_a_wording_case_with_a_failing_wording_is_replayable(self):
        case = json.loads((self.run / "cases" / "wording" / "case.json").read_text())
        case.update(minimal={"text": "take the soup", "labels": ["x"], "sentence": "Changing x is enough."},
                    replay={"config": {"suite": "libero_object", "task_id": 0, "init_state_index": 0,
                                       "instruction": "take the soup"}, "reference_instruction": "pick up the soup",
                            "gate": {"attempts": 5, "required_failures": 4}}, reduced=True, stop_reason="reduced")
        case["videos"] = {}
        write_json(self.run / "cases" / "wording" / "case.json", case)
        cr.register_cases(self.run)
        detail = self.library.detail("d-" + WORDING_ID)
        self.assertTrue(detail["replayable"])
        self.assertEqual(detail["verdict"], "reproduces")

    def test_the_audit_levels_are_read_from_the_merged_summary(self):
        detail = self.library.detail("d-" + AUDIT_ID)
        blur = next(f for f in detail["audit"]["families"] if f["family"] == "blur")
        self.assertEqual(blur["threshold_severity"], 0.4)
        self.assertGreater(len(blur["levels"]), 0)

    def test_replay_results_use_their_own_kind_specific_sentence(self):
        replay = self.root / "runs" / "replay-20261019T010000Z"
        write_text(replay / "spec.yaml", "faultline: 1\nname: replay\nmode: replay\n")
        write_json(replay / "steps.json", steps_document("replay", "replay", {}, {"status": "completed"}))
        write_json(replay / "replay-result.json", {
            "case_id": AUDIT_ID, "reproduces": True, "verdict": "still_reproduces",
            "verdict_text": "still fails at s = 0.40 (blur)"})
        replays = self.library.detail("d-" + AUDIT_ID)["replays"]
        self.assertEqual((replays[0]["verdict"], replays[0]["verdict_text"]),
                         ("still_reproduces", "still fails at s = 0.40 (blur)"))

    def test_a_start_that_passes_untouched_is_a_run_item_with_the_passes_route(self):
        folder = self.root / "runs" / "quiet-20261019T020000Z"
        write_text(folder / "spec.yaml", "faultline: 1\nname: quiet\nmode: diagnose\npolicy: {suite: libero_object}\n"
                   "diagnose: {task: 0, start: 0}\nbudget: {max_spend_usd: 7, max_hours: 4}\n")
        write_json(folder / "steps.json", steps_document(
            "quiet", "diagnose", {"screen": {"status": "done"}, "report": {"status": "done"}},
            {"status": "completed", "reason": None, "route": "passes"}))
        write_json(folder / "ledger.json", ledger_document(0.5))
        write_text(folder / "report.md", "# screen only\n")
        items = {i["id"]: i for i in self.library.list()["items"]}
        item = items["r-quiet-20261019T020000Z"]
        self.assertEqual((item["verdict"], item["kind"]), ("no_failure", "scenario"))
        detail = self.library.detail(item["id"])
        self.assertEqual(detail["route"], "passes")
        self.assertEqual([f["id"] for f in detail["findings"]], [item["id"]])
        self.assertIn("no probes were chosen", detail["verdict_text"])
        self.assertFalse(detail["replayable"])

    def test_the_gallery_projection_keeps_findings_without_run_names(self):
        gallery = Library(self.root, local=False)
        detail = gallery.detail("d-" + WORDING_ID)
        self.assertEqual(len(detail["findings"]), 2)
        self.assertIsNone(detail["run"])

    def test_cases_of_other_modes_list_only_themselves(self):
        from tests.ui_fixtures import build

        paths = build(Path(tempfile.mkdtemp()))
        library = Library(paths["artifacts"], runs_root=paths["runs"])
        for item in (i for i in library.list()["items"] if not i["id"].startswith("m-")):
            detail = library.detail(item["id"])
            self.assertEqual([f["id"] for f in detail["findings"]], [item["id"]], item["id"])
            self.assertIsNone(detail["route"])


if __name__ == "__main__":
    unittest.main()
