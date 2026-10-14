"""Tests for registering finished diagnosis runs as viewer-visible diagnoses."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from robot_debug import case_register as cr
from robot_debug.case_register import RegisterError, list_diagnoses, read_diagnosis, register_run

CASE_ID = "ab" * 32
VIDEO = {"original": "runs/fail-1-a01/episodes/pilot/o.mp4",
         "minimal": "runs/hyb-1-a01/episodes/pilot/m.mp4",
         "reference": "runs/ref-1-a01/episodes/pilot/r.mp4"}


def case_record(**changes):
    case = {
        "schema_version": 1, "kind": "scenario_reduction", "case_id": CASE_ID, "suite": "libero_10",
        "task_id": 0, "instruction": "put the soup in the basket", "failing_start": 14,
        "reference_start": 12, "reduced": True, "stop_reason": "reduced",
        "minimal": {"sentence": "Moving the soup by 3 cm is enough.", "entity_minimal": True, "selection": {}},
        "hypothesis": {"measured_verdict": "confirmed"},
        "videos": {role: {"case_id": "c-" + role, "outcome": "policy_failure" if role != "reference" else "success",
                          "video": path, "key": "k"} for role, path in VIDEO.items()},
    }
    case.update(changes)
    return case


def make_run(root, name="soup-start14-20261014T010000Z", *, case=None, jobs=("soup-reduce-1",),
             with_videos=True, spec="faultline: 1\nname: soup-start14\nmode: scenario\n"):
    run = Path(root) / "runs" / name
    run.mkdir(parents=True)
    (run / "spec.yaml").write_text(spec, encoding="utf-8")
    (run / "report.md").write_text("# Scenario reduction\n\nbody\n", encoding="utf-8")
    (run / "case.json").write_text(json.dumps(case or case_record()), encoding="utf-8")
    (run / "minimal-candidate.json").write_text('{"state": [1.0]}', encoding="utf-8")
    (run / "explanation.json").write_text(json.dumps({
        "kind": "scenario_explanation", "interpretation_status": "validated-structure"}), encoding="utf-8")
    (run / "ledger.json").write_text("{}", encoding="utf-8")
    (run / "steps.json").write_text("[]", encoding="utf-8")
    if with_videos:
        for job in jobs:
            scenario = run / "jobs" / job / "evidence" / "faultline-runs" / job / "scenario"
            for path in VIDEO.values():
                target = scenario / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(("video from " + job).encode("utf-8"))
    return run


class RegisterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.artifacts = Path(temporary.name)

    def register(self, run, **kwargs):
        return register_run(run, **kwargs)

    def test_a_run_is_registered_with_report_case_explanation_and_videos(self):
        run = make_run(self.artifacts)
        case_id = self.register(run)
        self.assertEqual(CASE_ID, case_id)
        entry = self.artifacts / "diagnoses" / CASE_ID
        for name in ("diagnosis.json", "report.md", "case.json", "explanation.json", "minimal-candidate.json",
                     "videos/original.mp4", "videos/minimal.mp4", "videos/reference.mp4"):
            self.assertTrue((entry / name).is_file(), name)
        index = json.loads((entry / "diagnosis.json").read_text(encoding="utf-8"))
        self.assertEqual(("diagnosis", CASE_ID, "soup-start14", "scenario"), (
            index["kind"], index["case_id"], index["name"], index["mode"]))
        self.assertEqual(("libero_10", 0, 14, 12, True), (
            index["suite"], index["task_id"], index["failing_start"], index["reference_start"], index["reduced"]))
        self.assertEqual("Moving the soup by 3 cm is enough.", index["sentence"])
        self.assertEqual("confirmed", index["hypothesis_verdict"])
        self.assertEqual("validated-structure", index["explanation_status"])
        self.assertEqual({"file": "videos/original.mp4", "outcome": "policy_failure", "case_id": "c-original"},
                         index["videos"]["original"])

    def test_the_default_root_is_diagnoses_beside_runs(self):
        run = make_run(self.artifacts)
        self.assertEqual((self.artifacts / "diagnoses").resolve(), cr.default_root(run))

    def test_an_explicit_root_is_used(self):
        run = make_run(self.artifacts)
        other = self.artifacts / "elsewhere"
        self.register(run, root=other)
        self.assertTrue((other / CASE_ID / "diagnosis.json").is_file())
        self.assertFalse((self.artifacts / "diagnoses").exists())

    def test_videos_are_found_in_the_job_that_has_them_newest_first(self):
        run = make_run(self.artifacts, jobs=("soup-reduce-1", "soup-reduce-2"))
        self.register(run)
        video = (self.artifacts / "diagnoses" / CASE_ID / "videos" / "original.mp4").read_bytes()
        self.assertEqual(b"video from soup-reduce-2", video)

    def test_a_missing_video_is_recorded_as_missing_not_an_error(self):
        run = make_run(self.artifacts, with_videos=False)
        self.register(run)
        index = json.loads((self.artifacts / "diagnoses" / CASE_ID / "diagnosis.json").read_text(encoding="utf-8"))
        self.assertEqual({"original": None, "minimal": None, "reference": None}, index["videos"])
        self.assertFalse((self.artifacts / "diagnoses" / CASE_ID / "videos").exists())

    def test_unsafe_video_paths_are_not_followed(self):
        outside = self.artifacts / "secret.mp4"
        outside.write_bytes(b"secret")
        bad = case_record()
        for role, path in (("original", "../../../../../../../secret.mp4"), ("minimal", "/abs.mp4"),
                           ("reference", "runs\\x.mp4")):
            bad["videos"][role]["video"] = path
        run = make_run(self.artifacts, case=bad)
        self.register(run)
        index = json.loads((self.artifacts / "diagnoses" / CASE_ID / "diagnosis.json").read_text(encoding="utf-8"))
        self.assertEqual({"original": None, "minimal": None, "reference": None}, index["videos"])

    def test_non_video_files_are_not_copied_as_videos(self):
        bad = case_record()
        bad["videos"]["original"]["video"] = "runs/fail-1-a01/episodes/pilot/o.jsonl"
        run = make_run(self.artifacts, case=bad)
        scenario = next((run / "jobs").glob("*/evidence/faultline-runs/*/scenario"))
        (scenario / "runs/fail-1-a01/episodes/pilot/o.jsonl").write_text("{}", encoding="utf-8")
        self.register(run)
        self.assertFalse((self.artifacts / "diagnoses" / CASE_ID / "videos" / "original.mp4").exists())

    def test_registering_twice_replaces_the_entry(self):
        run = make_run(self.artifacts)
        self.register(run)
        (run / "report.md").write_text("# Updated\n", encoding="utf-8")
        self.assertEqual(CASE_ID, self.register(run))
        self.assertEqual("# Updated\n", (self.artifacts / "diagnoses" / CASE_ID / "report.md").read_text(
            encoding="utf-8"))
        self.assertEqual([CASE_ID], [p.name for p in (self.artifacts / "diagnoses").iterdir()],
                         "no staging folders are left behind")

    def test_an_audit_run_without_a_case_gets_a_name_based_id(self):
        run = self.artifacts / "runs" / "audit-1-20261014T020000Z"
        run.mkdir(parents=True)
        (run / "spec.yaml").write_text("faultline: 1\nname: audit-1\nmode: audit\n", encoding="utf-8")
        (run / "report.md").write_text("# Audit\n", encoding="utf-8")
        case_id = self.register(run)
        self.assertRegex(case_id, r"^[0-9a-f]{64}$")
        self.assertEqual(case_id, self.register(run), "stable across registrations")
        entry = read_diagnosis(self.artifacts / "diagnoses", case_id)
        self.assertEqual(("audit", "audit-1", None), (entry["mode"], entry["name"], entry["case_kind"]))
        self.assertEqual("# Audit\n", entry["report"])
        self.assertIsNone(entry["explanation"])

    def test_a_run_with_nothing_to_show_is_refused(self):
        run = self.artifacts / "runs" / "empty"
        run.mkdir(parents=True)
        with self.assertRaises(RegisterError):
            self.register(run)
        with self.assertRaises(RegisterError):
            self.register(self.artifacts / "runs" / "missing")

    def test_a_broken_case_record_is_refused(self):
        run = make_run(self.artifacts)
        (run / "case.json").write_text("[1, 2", encoding="utf-8")
        with self.assertRaises(RegisterError):
            self.register(run)
        self.assertFalse((self.artifacts / "diagnoses").exists() and any(
            (self.artifacts / "diagnoses").iterdir()))

    def test_no_local_path_ends_up_in_the_index(self):
        run = make_run(self.artifacts)
        self.register(run)
        text = (self.artifacts / "diagnoses" / CASE_ID / "diagnosis.json").read_text(encoding="utf-8")
        self.assertNotIn(str(self.artifacts), text)
        self.assertNotIn(str(self.artifacts).replace("\\", "/"), text)


class ListAndReadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.artifacts = Path(temporary.name)
        self.root = self.artifacts / "diagnoses"

    def test_listing_is_sorted_and_skips_invalid_entries(self):
        register_run(make_run(self.artifacts))
        other = make_run(self.artifacts, "a-run", case=case_record(case_id="cd" * 32),
                         spec="faultline: 1\nname: aaa\nmode: scenario\n")
        register_run(other)
        (self.root / "not-an-id").mkdir()
        broken = self.root / ("ef" * 32)
        broken.mkdir()
        (broken / "diagnosis.json").write_text("{", encoding="utf-8")
        mismatch = self.root / ("12" * 32)
        mismatch.mkdir()
        (mismatch / "diagnosis.json").write_text(json.dumps({
            "schema_version": 1, "kind": "diagnosis", "case_id": "34" * 32}), encoding="utf-8")
        self.assertEqual(["aaa", "soup-start14"], [e["name"] for e in list_diagnoses(self.root)])

    def test_listing_an_absent_folder_is_empty(self):
        self.assertEqual([], list_diagnoses(self.artifacts / "nothing"))

    def test_read_returns_report_and_explanation(self):
        register_run(make_run(self.artifacts))
        entry = read_diagnosis(self.root, CASE_ID)
        self.assertIn("# Scenario reduction", entry["report"])
        self.assertEqual("scenario_explanation", entry["explanation"]["kind"])

    def test_read_refuses_bad_ids(self):
        register_run(make_run(self.artifacts))
        for bad in ("../x", "short", CASE_ID.upper(), "00" * 32, None):
            with self.subTest(bad=bad), self.assertRaises(KeyError):
                read_diagnosis(self.root, bad)


if __name__ == "__main__":
    unittest.main()
