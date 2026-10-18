"""Several cases per run folder, and the clips of audit and wording cases (ADR 0035)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from robot_debug import case_register as cr
from robot_debug import pipeline_cases as pc
from tests.test_diagnose_pipeline import m6_summary
from tests.ui_fixtures import write_json, write_text

AUDIT_ID = "a1" + "00" * 31
WORDING_ID = "b2" + "11" * 31
JOB = "demo-2610181000-probe-image-1"


def audit_case(summary):
    return {"schema_version": 1, "kind": "audit", "case_id": AUDIT_ID, "suite": "libero_object", "task_id": 0,
            "start_index": 0, "complete": True, "stop_reason": None,
            "families": {"blur": {"threshold_severity": 0.4, "stop_reason": "threshold_found"},
                         "noise": {"threshold_severity": None, "stop_reason": "no_reproducible_failure"}},
            "summary": "jobs/{}/evidence/m6/m6_summary.json".format(JOB),
            "videos": pc.audit_videos([(JOB, summary)])}


def wording_case():
    return {"schema_version": 1, "kind": "paraphrase_reduction", "case_id": WORDING_ID, "suite": "libero_object",
            "task_id": 0, "start_index": 0, "instruction": "pick up the soup", "paraphrase": None,
            "minimal": None, "failure": False, "reduced": False, "stop_reason": "no_reproducible_failure",
            "videos": {"control": {"case_id": "orig-a01", "outcome": "success", "video": "runs/orig-a01/a.mp4",
                                   "job": "demo-2610181000-rewording-screen", "label": "Original wording (passed)"},
                       "reworded": {"case_id": "p01-a01", "outcome": "success", "video": "runs/p01-a01/a.mp4",
                                    "job": "demo-2610181000-rewording-screen", "label": 'Reworded "x" (passed)'}},
            "screen": []}


def make_pipeline_run(root: Path) -> Path:
    run = root / "runs" / "demo-20261018T100000Z"
    summary = m6_summary(["blur", "noise"], thresholds={"blur": 0.4})
    write_text(run / "spec.yaml", "faultline: 1\nname: demo\nmode: diagnose\n")
    write_json(run / "steps.json", {"schema_version": 1, "name": "demo", "mode": "diagnose", "steps": {},
                                    "run": {"status": "completed", "route": "probes"}})
    for name, case, report in (("audit", audit_case(summary), "# audit\n"), ("wording", wording_case(), "# words\n")):
        write_json(run / "cases" / name / "case.json", case)
        write_text(run / "cases" / name / "report.md", report)
    write_json(run / "cases" / "audit" / "replay-inputs.json", {"kind": "audit"})
    evidence = run / "jobs" / JOB / "evidence" / "m6" / "runs"
    for case_id in ("nominal-control-01", "blur-s400000-a01", "noise-s1000000-a01"):
        write_text(evidence / case_id / "episodes" / "ep0" / "video.mp4", "mp4 " + case_id)
    write_text(evidence / "blur-s400000-a02" / "episodes" / "ep0" / "video.mp4", "another")
    language = run / "jobs" / "demo-2610181000-rewording-screen" / "evidence" / "language" / "runs"
    for case_id in ("orig-a01", "p01-a01"):
        write_text(language / case_id / "a.mp4", "mp4 " + case_id)
    return run


class MultipleCases(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.run = make_pipeline_run(self.root)
        self.diagnoses = self.root / "diagnoses"

    def test_each_case_folder_is_registered_in_route_order(self):
        ids = cr.register_cases(self.run)
        self.assertEqual(ids, [AUDIT_ID, WORDING_ID])
        entries = {e["case_id"]: e for e in cr.list_diagnoses(self.diagnoses)}
        audit, wording = entries[AUDIT_ID], entries[WORDING_ID]
        self.assertEqual((audit["order"], wording["order"]), (0, 1))
        self.assertEqual(audit["name"], "demo - stress test")
        self.assertEqual(wording["name"], "demo - rewordings")
        self.assertEqual((audit["route"], audit["mode"], audit["run"]), ("probes", "diagnose", self.run.name))
        self.assertEqual(audit["files"]["replay_inputs"], "replay-inputs.json")
        self.assertIsNone(wording["files"]["replay_inputs"])
        self.assertEqual(cr.read_diagnosis(self.diagnoses, AUDIT_ID)["report"], "# audit\n")
        self.assertEqual(cr.read_diagnosis(self.diagnoses, WORDING_ID)["report"], "# words\n")

    def test_a_single_case_run_registers_as_before(self):
        run = self.root / "runs" / "single-20261018T100100Z"
        write_text(run / "spec.yaml", "faultline: 1\nname: single\nmode: audit\n")
        write_text(run / "report.md", "# only a report\n")
        ids = cr.register_cases(run)
        self.assertEqual(len(ids), 1)
        self.assertIsNone(cr.read_diagnosis(self.diagnoses, ids[0]).get("route"))

    def test_the_clips_are_copied_with_their_labels_one_per_role(self):
        cr.register_cases(self.run)
        audit = cr.read_diagnosis(self.diagnoses, AUDIT_ID)
        self.assertEqual(sorted(k for k, v in audit["videos"].items() if v),
                         ["blur@0.40", "control", "noise@1.00"])
        clip = audit["videos"]["blur@0.40"]
        self.assertEqual((clip["file"], clip["outcome"], clip["label"]),
                         ("videos/blur-0.40.mp4", "policy_failure", "Gaussian blur at s = 0.40 (failed)"))
        self.assertEqual((self.diagnoses / AUDIT_ID / "videos" / "blur-0.40.mp4").read_text(),
                         "mp4 blur-s400000-a01")
        self.assertEqual(audit["videos"]["control"]["label"], "Unperturbed control (passed)")
        wording = cr.read_diagnosis(self.diagnoses, WORDING_ID)
        self.assertEqual((self.diagnoses / WORDING_ID / "videos" / "control.mp4").read_text(), "mp4 orig-a01")
        self.assertEqual(wording["videos"]["reworded"]["label"], 'Reworded "x" (passed)')

    def test_a_clip_the_job_did_not_keep_is_simply_missing(self):
        for path in (self.run / "jobs" / JOB / "evidence" / "m6" / "runs" / "noise-s1000000-a01").rglob("*.mp4"):
            path.unlink()
        cr.register_cases(self.run)
        audit = cr.read_diagnosis(self.diagnoses, AUDIT_ID)
        self.assertNotIn("noise@1.00", {k for k, v in audit["videos"].items() if v})

    def test_re_registering_replaces_the_entries(self):
        cr.register_cases(self.run)
        cr.register_cases(self.run)
        self.assertEqual(len(cr.list_diagnoses(self.diagnoses)), 2)

    def test_re_registering_an_old_audit_case_attaches_its_clips(self):
        run = self.root / "runs" / "old-20261015T155833Z"
        summary = m6_summary(["blur", "noise"], thresholds={"blur": 0.4})
        job = "old-2610151558-audit"
        old = {"schema_version": 1, "kind": "audit", "case_id": "c3" + "22" * 31, "suite": "libero_object",
               "task_id": 0, "start_index": 0, "complete": True, "stop_reason": None, "job_name": job,
               "summary": "jobs/{}/evidence/m6/m6_summary.json".format(job),
               "families": {"blur": {"threshold_severity": 0.4, "stop_reason": "threshold_found"}}}
        write_text(run / "spec.yaml", "faultline: 1\nname: old\nmode: audit\n")
        write_json(run / "case.json", old)
        write_text(run / "report.md", "# old\n")
        write_json(run / "jobs" / job / "evidence" / "m6" / "m6_summary.json", summary)
        write_text(run / "jobs" / job / "evidence" / "m6" / "runs" / "blur-s400000-a01" / "e" / "v.mp4", "old clip")
        before = cr.register_cases(run)
        self.assertNotIn("blur@0.40", cr.read_diagnosis(self.diagnoses, before[0])["videos"])
        ids = cr.reregister_run(run)
        self.assertEqual(ids, before)
        entry = cr.read_diagnosis(self.diagnoses, ids[0])
        self.assertEqual(entry["videos"]["blur@0.40"]["label"], "Gaussian blur at s = 0.40 (failed)")
        self.assertEqual(json.loads((run / "case.json").read_text())["videos"]["blur@0.40"]["job"], job)
        self.assertEqual(cr.reregister_run(run), ids, "running it again changes nothing")


class AuditVideos(unittest.TestCase):
    def test_the_threshold_clip_is_the_first_failing_attempt_and_a_robust_family_uses_its_top_level(self):
        videos = pc.audit_videos([("job-1", m6_summary(["blur", "noise"], thresholds={"blur": 0.4125}))])
        self.assertEqual(sorted(videos), ["blur@0.4125", "control", "noise@1.00"])
        self.assertEqual(videos["blur@0.4125"]["case_id"], "blur-s412500-a01")
        self.assertEqual(videos["noise@1.00"]["outcome"], "success")

    def test_a_failed_control_is_shown_as_failed_and_untested_families_have_no_clip(self):
        videos = pc.audit_videos([("job-1", m6_summary(["blur"], control_ok=False))])
        self.assertEqual(list(videos), ["control"])
        self.assertEqual(videos["control"]["label"], "Unperturbed control (failed)")

    def test_the_family_labels_match_the_viewers(self):
        from robot_debug.viewer.library import FAMILY_LABELS

        self.assertEqual(pc.FAMILY_LABELS, FAMILY_LABELS)

    def test_only_the_first_groups_control_is_kept(self):
        videos = pc.audit_videos([("job-1", m6_summary(["blur"])), ("job-2", m6_summary(["lighting"]))])
        self.assertEqual(videos["control"]["job"], "job-1")
        self.assertEqual(videos["lighting@1.00"]["job"], "job-2")


if __name__ == "__main__":
    unittest.main()
