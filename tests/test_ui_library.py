"""The library read model: items, fault codes, verdicts, details and the public projection."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from robot_debug.viewer import library as lib
from tests import ui_fixtures as fx


class LibraryCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.paths = fx.build(Path(directory.name))
        self.library = self.make()

    def make(self, **overrides):
        options = dict(runs_root=self.paths["runs"],
                       inspect_case=lambda workspace, case_id: fx.occlusion_case())
        options.update(overrides)
        return lib.Library(self.paths["artifacts"], **options)

    def items(self, library=None):
        return {item["id"]: item for item in (library or self.library).list()["items"]}


class FaultCodeTests(unittest.TestCase):
    def test_codes_use_the_kind_letter_and_the_first_hex_digits(self):
        self.assertEqual(lib.fault_code("scenario", "afb56ff6"), "FL-S-AFB5")
        self.assertEqual(lib.fault_code("audit", "08d3d629"), "FL-A-08D3")
        self.assertEqual(lib.fault_code("paraphrase", "c0de"), "FL-L-C0DE")
        self.assertEqual(lib.fault_code("occlusion", "52d8"), "FL-M-52D8")
        self.assertEqual(lib.fault_code("scenario", "afb56ff6b142", 6), "FL-S-AFB56F")

    def test_a_key_that_is_not_hex_is_hashed_so_the_code_is_stable(self):
        first = lib.fault_code("scenario", "paraphrase-quiet-20261016T020108Z")
        self.assertRegex(first, r"^FL-S-[0-9A-F]{4}$")
        self.assertEqual(first, lib.fault_code("scenario", "paraphrase-quiet-20261016T020108Z"))
        self.assertNotEqual(first, lib.fault_code("scenario", "paraphrase-quiet-20261016T020109Z"))

    def test_colliding_codes_are_lengthened_to_six_digits(self):
        items = [{"id": "a", "kind": "scenario"}, {"id": "b", "kind": "scenario"}, {"id": "c", "kind": "audit"}]
        lib.assign_fault_codes(items, {"a": "afb5aa11", "b": "afb5bb22", "c": "afb5cc33"})
        self.assertEqual([i["fault_code"] for i in items], ["FL-S-AFB5AA", "FL-S-AFB5BB", "FL-A-AFB5"])


class MagnitudeTests(unittest.TestCase):
    def test_rounds_half_up_like_the_report(self) -> None:
        # 3.65 is stored just below 3.65, so "{:.1f}" gives 3.6 while the report says 3.7.
        self.assertEqual(lib._magnitude({"position_cm": 3.65}, "position", 1.0), "3.7 cm")
        self.assertEqual(lib._magnitude({"position_cm": 2.89}, "position", 0.5), "1.4 cm")

    def test_joints_name_the_largest_offset(self) -> None:
        row = {"joints": [{"name": "j1", "offset": -1.469, "unit": "deg"}, {"name": "j2", "offset": 2.65, "unit": "deg"}]}
        self.assertEqual(lib._magnitude(row, "joints", 1.0), "2 joints, up to 2.7°")


class AuditSentenceTests(unittest.TestCase):
    def test_a_family_the_run_never_searched_is_not_tested_not_robust(self):
        case = {"families": {"viewpoint": {"stop_reason": "nominal_failed", "threshold_severity": None},
                             "jpeg": {"stop_reason": "no_reproducible_failure", "threshold_severity": None}},
                "stop_reason": "nominal_controls_failed", "complete": False}
        sentence = lib._audit_sentence(case)
        self.assertIn("Camera viewpoint: not tested", sentence)
        self.assertIn("JPEG compression: no failure found", sentence)


class ListTests(LibraryCase):
    def test_every_source_is_listed_once(self):
        items = self.items()
        self.assertEqual(sorted(items), sorted([
            "d-" + fx.SCENARIO_ID, "d-" + fx.SCENARIO_ID_TWIN, "d-" + fx.AUDIT_ID, "d-" + fx.PARAPHRASE_ID,
            "r-" + fx.QUIET_RUN, "m-" + fx.OCCLUSION_ID]))
        self.assertEqual(self.library.list()["warnings"], [])

    def test_the_contract_fields_are_present_and_nothing_else(self):
        expected = ["attention", "case_id", "created", "fault_code", "id", "instruction", "kind", "name", "run",
                    "suite", "task_id", "verdict", "verdict_text"]
        for item in self.items().values():
            self.assertEqual(sorted(item), expected)
            self.assertIn(item["verdict"], lib.VERDICTS)
            self.assertTrue(item["verdict_text"])

    def test_scenario_item(self):
        item = self.items()["d-" + fx.SCENARIO_ID]
        self.assertEqual((item["kind"], item["name"], item["verdict"]), ("scenario", "scenario-demo", "reproduces"))
        self.assertEqual((item["suite"], item["task_id"], item["instruction"]), ("libero_10", 0, fx.INSTRUCTION))
        self.assertEqual((item["created"], item["case_id"], item["run"]), ("2026-10-16T06:45:28Z", fx.SCENARIO_ID, fx.SCENARIO_RUN))
        self.assertEqual(item["verdict_text"], "Entity-minimal: 3 of 4 differences from the passing start are enough; "
                                               "their sizes were not shrunk.")
        self.assertTrue(item["attention"], "stopped at the candidate budget")

    def test_a_fully_reduced_scenario_needs_no_attention(self):
        case = dict(fx.scenario_case(), reduced=True, stop_reason="reduced")
        fx.write_json(self.paths["diagnoses"] / fx.SCENARIO_ID / "case.json", case)
        item = self.items()["d-" + fx.SCENARIO_ID]
        self.assertFalse(item["attention"])
        self.assertTrue(item["verdict_text"].startswith("Fully reduced: 3 of 4"))

    def test_audit_item_reproduces_when_any_family_has_a_threshold(self):
        item = self.items()["d-" + fx.AUDIT_ID]
        self.assertEqual((item["kind"], item["verdict"], item["suite"], item["attention"]), ("audit", "reproduces", "libero_goal", False))
        self.assertIn("1 of 2 disturbance families", item["verdict_text"])
        self.assertIn("darkening at severity 0.35", item["verdict_text"])

    def test_audit_without_a_threshold_is_no_failure_or_stopped(self):
        case = fx.audit_case()
        case["families"] = {name: {"stop_reason": "no_reproducible_failure", "threshold_severity": None}
                            for name in case["families"]}
        fx.write_json(self.paths["diagnoses"] / fx.AUDIT_ID / "case.json", case)
        item = self.items()["d-" + fx.AUDIT_ID]
        self.assertEqual((item["verdict"], item["attention"]), ("no_failure", False))
        case.update(complete=False, stop_reason="nominal_controls_failed")
        fx.write_json(self.paths["diagnoses"] / fx.AUDIT_ID / "case.json", case)
        item = self.items()["d-" + fx.AUDIT_ID]
        self.assertEqual((item["verdict"], item["attention"]), ("stopped", True))
        self.assertEqual(item["verdict_text"], lib.stop_text("nominal_controls_failed"))
        case.update(stop_reason="deadline_exhausted")
        fx.write_json(self.paths["diagnoses"] / fx.AUDIT_ID / "case.json", case)
        self.assertEqual(self.items()["d-" + fx.AUDIT_ID]["verdict"], "incomplete")

    def test_paraphrase_item(self):
        item = self.items()["d-" + fx.PARAPHRASE_ID]
        self.assertEqual((item["kind"], item["verdict"], item["attention"]), ("paraphrase", "reproduces", False))
        self.assertEqual(item["verdict_text"], "A reworded instruction makes the policy fail; 1 word edit is enough.")

    def test_a_run_that_found_nothing_is_listed_as_its_own_item(self):
        item = self.items()["r-" + fx.QUIET_RUN]
        self.assertEqual((item["kind"], item["verdict"], item["attention"]), ("paraphrase", "no_failure", False))
        self.assertEqual(item["verdict_text"], "No failure repeated 4 of 5 times.")
        self.assertEqual((item["case_id"], item["created"], item["run"]), (None, "2026-10-16T02:01:08Z", fx.QUIET_RUN))
        self.assertEqual((item["suite"], item["task_id"], item["instruction"]), ("libero_10", 0, fx.INSTRUCTION))

    def test_runs_with_a_case_replays_and_live_runs_are_not_extra_items(self):
        ids = set(self.items())
        for name in (fx.SCENARIO_RUN, fx.REPLAY_RUN, fx.LIVE_RUN, fx.AUDIT_RUN):
            self.assertNotIn("r-" + name, ids)

    def test_a_stopped_run_without_a_case_needs_attention(self):
        fx.write_json(self.paths["runs"] / fx.QUIET_RUN / "steps.json", fx.steps_document(
            "paraphrase-quiet", "paraphrase", {}, {"status": "stopped", "reason": "nominal_controls_failed"}))
        item = self.items()["r-" + fx.QUIET_RUN]
        self.assertEqual((item["verdict"], item["attention"]), ("stopped", True))
        fx.write_json(self.paths["runs"] / fx.QUIET_RUN / "steps.json", fx.steps_document(
            "paraphrase-quiet", "paraphrase", {}, {"status": "failed"}))
        item = self.items()["r-" + fx.QUIET_RUN]
        self.assertEqual((item["verdict"], item["attention"]), ("failed", True))

    def test_the_occlusion_case_is_listed_last_with_its_own_letter(self):
        listing = self.library.list()["items"]
        self.assertEqual(listing[-1]["id"], "m-" + fx.OCCLUSION_ID)
        item = listing[-1]
        self.assertEqual((item["kind"], item["verdict"], item["suite"], item["created"]), ("occlusion", "reproduces", "libero-object", None))
        self.assertIn("14%", item["verdict_text"])
        self.assertTrue(item["fault_code"].startswith("FL-M-52D8"))

    def test_newest_first(self):
        created = [i["created"] for i in self.library.list()["items"] if i["created"]]
        self.assertEqual(created, sorted(created, reverse=True))

    def test_codes_are_four_digits_unless_two_items_collide(self):
        items = self.items()
        self.assertEqual(items["d-" + fx.AUDIT_ID]["fault_code"], "FL-A-08D3")
        self.assertEqual(items["d-" + fx.PARAPHRASE_ID]["fault_code"], "FL-L-C0DE")
        first, twin = items["d-" + fx.SCENARIO_ID]["fault_code"], items["d-" + fx.SCENARIO_ID_TWIN]["fault_code"]
        self.assertEqual((first, twin), ("FL-S-AFB501", "FL-S-AFB5FE"))

    def test_local_fields_are_hidden_in_the_gallery_and_without_a_runs_root(self):
        for library in (self.make(local=False), self.make(runs_root=None)):
            for item in self.items(library).values():
                self.assertIsNone(item["run"])
        self.assertNotIn("r-" + fx.QUIET_RUN, self.items(self.make(runs_root=None)))

    def test_a_run_folder_that_was_cleaned_up_gives_no_run_name(self):
        import shutil

        shutil.rmtree(str(self.paths["runs"] / fx.SCENARIO_RUN))
        self.assertIsNone(self.items()["d-" + fx.SCENARIO_ID]["run"])

    def test_an_empty_artifacts_folder_is_an_empty_library(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(lib.Library(Path(root)).list(), {"items": [], "warnings": []})


class ScenarioDetailTests(LibraryCase):
    def detail(self, item_id="d-" + fx.SCENARIO_ID):
        return self.library.detail(item_id)

    def test_header_result_and_checkpoint(self):
        detail = self.detail()
        self.assertEqual(detail["stop_reason"], "budget_exhausted")
        self.assertEqual(detail["stop_text"], "Stopped at the candidate budget; this is the smallest cause found so far.")
        self.assertEqual(detail["sentence"], "Moving soup_1 by 2.9 cm, cheese_1 by 0.5 cm and 6 robot joints is enough.")
        self.assertEqual(detail["checkpoint"], {"id": fx.CHECKPOINT["id"], "revision": fx.CHECKPOINT["revision"], "pinned": True})
        self.assertTrue(detail["replayable"])
        self.assertEqual(detail["fault_code"], "FL-S-AFB501")

    def test_minimal_cause_magnitudes_are_in_units_a_person_can_picture(self):
        rows = {(r["entity"], r["part"]): r for r in self.detail()["scenario"]["minimal_cause"]}
        self.assertEqual(rows[("soup_1", "position")]["magnitude"], "2.9 cm")
        self.assertEqual(rows[("cheese_1", "position")]["magnitude"], "0.5 cm")
        self.assertEqual(rows[("cheese_1", "rotation")]["magnitude"], "6.0\u00b0")
        self.assertEqual(rows[("robot", "joints")]["magnitude"], "6 joints, up to 2.6\u00b0")
        self.assertEqual(rows[("cheese_1", "rotation")]["fraction"], 0.5)
        self.assertEqual(sorted(rows[("soup_1", "position")]), ["entity", "fraction", "magnitude", "part"])

    def test_the_scenario_block(self):
        block = self.detail()["scenario"]
        self.assertEqual((block["failing_start"], block["reference_start"], block["differences_count"]), (None, 28, 4))
        self.assertEqual(block["imported"], {"file_sha256": "ab" * 32, "state_sha256": "cd" * 32})
        self.assertEqual((block["entity_minimal"], block["reduced"]), (True, False))
        hypothesis = block["hypothesis"]
        self.assertEqual(hypothesis["ranked"], ["robot", "soup_1", "sauce_1"])
        self.assertEqual(hypothesis["measured_verdict"], "necessary_not_sufficient")
        self.assertEqual(hypothesis["verdict_text"], "The model's top suspect was needed but not enough on its own.")
        self.assertEqual(hypothesis["entities"][0], {"entity": "robot", "label": "necessary_not_sufficient",
                                                     "necessary": True, "sufficient": False})
        self.assertEqual(block["reruns"][2], {
            "index": 2, "phase": "probe", "role": "hybrid", "selection": {"robot": {"joints": 1.0}},
            "outcomes": ["success"] * 3, "decision": "does_not_reproduce"})
        self.assertIsNone(block["reruns"][0]["selection"])

    def test_a_case_without_a_hypothesis(self):
        case = fx.scenario_case()
        case["hypothesis"] = {"ranking": [], "source": "fixed_order"}
        fx.write_json(self.paths["diagnoses"] / fx.SCENARIO_ID / "case.json", case)
        self.assertIsNone(self.detail()["scenario"]["hypothesis"])

    def test_videos_link_to_the_media_route(self):
        videos = self.detail()["videos"]
        self.assertEqual([v["role"] for v in videos], ["original", "minimal", "reference"])
        self.assertEqual(videos[0]["label"], "Original failing start")
        self.assertEqual(videos[0]["url"], "/media/diagnoses/{}/videos/original.mp4".format(fx.SCENARIO_ID))
        self.assertEqual([v["outcome"] for v in videos], ["policy_failure", "policy_failure", "success"])

    def test_videos_that_were_not_kept_have_no_url(self):
        detail = self.detail("d-" + fx.SCENARIO_ID_TWIN)
        self.assertEqual(detail["videos"], [])

    def test_the_explanation_is_flattened_and_labelled(self):
        explanation = self.detail()["explanation"]
        self.assertEqual(explanation["status"], "validated-structure")
        self.assertEqual(explanation["model"], "example/nemotron")
        self.assertIn("human review is required", explanation["disclaimer"])
        self.assertEqual(explanation["hypotheses"], [{"text": "The joint offsets may matter.", "evidence_ids": ["c1", "c2"]}])
        self.assertEqual(explanation["observations"][0]["evidence_ids"], ["c2"])
        self.assertEqual(explanation["limitations"], ["Local minimum from limited reruns."])
        self.assertIsNone(self.detail("d-" + fx.SCENARIO_ID_TWIN)["explanation"])

    def test_the_report_files_and_history(self):
        detail = self.detail()
        self.assertTrue(detail["report_markdown"].startswith("# Scenario reduction"))
        self.assertEqual([f["name"] for f in detail["files"]],
                         ["report.md", "case.json", "explanation.json", "minimal-candidate.json", "replay-inputs.json"])
        self.assertEqual(detail["files"][0]["url"], "/api/library/d-{}/files/report.md".format(fx.SCENARIO_ID))
        history = detail["history"]
        self.assertEqual([s["key"] for s in history["steps"]], ["screen", "reduce", "report", "case", "register"])
        self.assertEqual(history["steps"][1], {"key": "reduce", "label": "Reduce the cause", "status": "done",
                                               "state": "FAILED", "partial": True, "cost_usd": 1.1})
        self.assertEqual((history["jobs"], history["spent_usd"], history["cap_usd"], history["hourly_usd"]), (1, 1.5, 10.0, 1.8))
        self.assertEqual((history["elapsed_seconds"], history["max_hours"]), (1234.5, 5.0))

    def test_replays_of_the_case(self):
        replays = self.detail()["replays"]
        self.assertEqual(replays, [{"run": fx.REPLAY_RUN, "verdict": "still_reproduces",
                                    "verdict_text": "The failure still reproduces.",
                                    "created": "2026-10-16T12:00:00Z", "cost_usd": 0.4}])
        self.assertEqual(self.detail("d-" + fx.SCENARIO_ID_TWIN)["replays"], [])

    def test_without_the_run_folder_history_and_replays_are_empty(self):
        detail = self.make(runs_root=None).detail("d-" + fx.SCENARIO_ID)
        self.assertIsNone(detail["history"])
        self.assertEqual(detail["replays"], [])
        self.assertTrue(detail["scenario"]["minimal_cause"], "the case itself still tells its story")

    def test_an_unknown_id_is_a_key_error(self):
        for bad in ("d-" + "0" * 64, "x-1", "", "r-nothing", "m-" + "0" * 64):
            with self.subTest(bad=bad), self.assertRaises(KeyError):
                self.library.detail(bad)

    def test_the_replayable_flag_needs_the_replay_inputs(self):
        self.assertFalse(self.detail("d-" + fx.SCENARIO_ID_TWIN)["replayable"])
        self.assertFalse(self.detail("d-" + fx.AUDIT_ID)["replayable"])


class OtherKindsDetailTests(LibraryCase):
    def test_audit_levels_come_from_the_run_summary(self):
        audit = self.library.detail("d-" + fx.AUDIT_ID)["audit"]
        self.assertEqual(audit["start_index"], 0)
        self.assertEqual(audit["nominal"], {"failures": 0, "attempts": 5})
        self.assertEqual([f["family"] for f in audit["families"]], ["darken", "blur"], "the configured order")
        darken = audit["families"][0]
        self.assertEqual((darken["label"], darken["threshold_severity"], darken["stop_reason"]),
                         ("Darkening", 0.35, "threshold_found"))
        self.assertEqual(darken["levels"][0], {"severity": 0.2, "failures": 0, "attempts": 5})
        self.assertEqual(darken["levels"][1], {"severity": 0.4, "failures": 5, "attempts": 5})
        self.assertIsNone(audit["families"][1]["threshold_severity"])

    def test_audit_without_the_run_folder_has_families_only(self):
        audit = self.make(runs_root=None).detail("d-" + fx.AUDIT_ID)["audit"]
        self.assertIsNone(audit["nominal"])
        self.assertEqual([f["family"] for f in audit["families"]], ["blur", "darken"])
        self.assertEqual([f["levels"] for f in audit["families"]], [[], []])
        self.assertEqual(audit["families"][1]["threshold_severity"], 0.35)

    def test_audit_sentence_names_each_family(self):
        sentence = self.library.detail("d-" + fx.AUDIT_ID)["sentence"]
        self.assertIn("Darkening from severity 0.35", sentence)
        self.assertIn("Gaussian blur: no failure found", sentence)

    def test_a_summary_path_that_leaves_the_run_folder_is_ignored(self):
        case = dict(fx.audit_case(), summary="../../../secret.json")
        fx.write_json(self.paths["diagnoses"] / fx.AUDIT_ID / "case.json", case)
        self.assertIsNone(self.library.detail("d-" + fx.AUDIT_ID)["audit"]["nominal"])

    def test_summary_paths_in_any_spelling_cannot_leave_the_run_folder(self):
        outside = self.paths["runs"] / "outside.json"
        fx.write_json(outside, fx.audit_summary())
        spellings = [r"..\outside.json", r"..\..\outside.json", "../outside.json", str(outside),
                     str(outside.resolve()), outside.as_posix(), "jobs/../../outside.json",
                     r"jobs\..\..\outside.json"]
        for spelling in spellings:
            with self.subTest(summary=spelling):
                fx.write_json(self.paths["diagnoses"] / fx.AUDIT_ID / "case.json", dict(fx.audit_case(), summary=spelling))
                self.assertIsNone(self.make().detail("d-" + fx.AUDIT_ID)["audit"]["nominal"])

    def test_a_summary_inside_the_run_folder_is_still_read(self):
        audit = self.make().detail("d-" + fx.AUDIT_ID)["audit"]
        self.assertEqual(audit["nominal"], {"failures": 0, "attempts": 5})

    def test_paraphrase_rows_with_the_meaning_check_and_the_minimal_edit(self):
        block = self.library.detail("d-" + fx.PARAPHRASE_ID)["paraphrase"]
        self.assertEqual(block["original"], fx.INSTRUCTION)
        self.assertEqual(block["control"], ["success", "success"])
        self.assertEqual([p["failures"] for p in block["paraphrases"]], [5, 0])
        self.assertEqual([p["meaning"] for p in block["paraphrases"]], ["kept", "object_or_target_dropped"])
        self.assertEqual(block["minimal_edit"], {"text": "put the alphabet soup and the tomato sauce in the basket",
                                                 "edits": ["drop \"both\""]})
        self.assertEqual(self.library.detail("d-" + fx.PARAPHRASE_ID)["sentence"],
                         "Dropping the word \"both\" is enough to make the policy fail.")

    def test_a_paraphrase_run_with_no_failure_reads_its_rows_from_the_run(self):
        detail = self.library.detail("r-" + fx.QUIET_RUN)
        block = detail["paraphrase"]
        self.assertEqual(block["original"], fx.INSTRUCTION)
        self.assertEqual(block["control"], ["success", "success"])
        self.assertEqual([(p["text"][:5], p["meaning"]) for p in block["paraphrases"]],
                         [("Place", "kept"), ("Drop ", "object_or_target_dropped")])
        self.assertIsNone(block["minimal_edit"])
        self.assertEqual((detail["stop_reason"], detail["stop_text"]), ("no_reproducible_failure", "No failure repeated 4 of 5 times."))
        self.assertEqual(detail["report_markdown"], "# Quiet\n")
        self.assertEqual(detail["history"]["steps"][0]["key"], "paraphrase")
        self.assertNotIn("raw detail", json.dumps(detail))

    def test_the_occlusion_case(self):
        detail = self.library.detail("m-" + fx.OCCLUSION_ID)
        block = detail["occlusion"]
        self.assertEqual(block["perturbation"]["family"], "agentview-opaque-rectangle")
        self.assertEqual(block["lineage"][-1], {"rectangle": {"x": 0.625, "y": 0.0, "width": 0.375, "height": 0.375},
                                                "edge": "bottom", "delta": 0.125})
        self.assertEqual([e["episode_id"] for e in block["episodes"]], ["1a8513e316cce7aa", "d02392d812d90d32"])
        self.assertEqual(block["episodes"][0]["outcome"], "policy_failure")
        self.assertEqual(block["episodes"][0]["url"], "/media/m4-source/runs/parent/episode.mp4")
        self.assertEqual(block["episodes"][0]["role"], "parent")
        self.assertIsNone(detail["explanation"])
        self.assertIsNone(detail["research"])
        self.assertEqual(detail["kind"], "occlusion")

    def test_the_occlusion_case_reads_its_stored_explanation_and_research(self):
        report = {"report_id": "r" * 64, "provenance": {"created_at": "2026-10-10T14:21:14Z", "model": "example/model"},
                  "report": {"interpretation_status": "validated-structure", "disclaimer": "Facts only.",
                             "interpretation": {"hypotheses": [{"text": "A hypothesis.", "evidence_ids": ["1a8513e316cce7aa"]}],
                                                "observations": [], "limitations": ["One task."]}}}
        research = {"queries": [{"results": [
            {"source_id": "S1", "title": "A paper", "url": "https://example.invalid/paper"},
            {"source_id": "S2", "title": "Insecure", "url": "http://example.invalid/plain"}]}],
            "summary": {"status": "interpreted", "related_work": [{"text": "Related finding.", "source_ids": ["S1"]}]}}
        with mock.patch("robot_debug.explanation_store.read_case_reports", return_value={"reports": [report], "warnings": []}), \
                mock.patch("robot_debug.research_store.read_case_research", return_value={"records": [research], "warnings": []}):
            detail = self.library.detail("m-" + fx.OCCLUSION_ID)
        self.assertEqual(detail["explanation"]["status"], "validated-structure")
        self.assertEqual(detail["explanation"]["hypotheses"][0]["text"], "A hypothesis.")
        self.assertEqual(detail["research"], {"related": "Related finding. [S1]",
                                              "sources": [{"title": "A paper", "url": "https://example.invalid/paper"}]})


class PublicProjectionTests(LibraryCase):
    FORBIDDEN = (fx.FAKE_JOB_ID, fx.FAKE_PROJECT, fx.FAKE_BUCKET, "backend-state", "job_id", "someone",
                 "C:\\\\Users", "/home/")

    def every_document(self, library=None):
        library = library or self.library
        listing = library.list()
        yield listing
        for item in listing["items"]:
            yield library.detail(item["id"])

    def test_no_job_ids_project_bucket_names_or_paths_anywhere(self):
        for document in self.every_document():
            text = json.dumps(document)
            for forbidden in self.FORBIDDEN:
                self.assertNotIn(forbidden, text)
            self.assertNotIn(str(self.paths["artifacts"]), text)
            self.assertNotIn(str(self.paths["artifacts"].resolve()).replace("\\", "\\\\"), text)

    def test_the_report_text_has_ids_and_paths_removed(self):
        text = self.library.detail("d-" + fx.SCENARIO_ID)["report_markdown"]
        self.assertIn("[local path omitted]", text)
        self.assertNotIn("someone", text)

    def test_the_gallery_projection_has_no_run_folder_names(self):
        gallery = self.make(local=False)
        for document in self.every_document(gallery):
            text = json.dumps(document)
            for name in (fx.SCENARIO_RUN, fx.AUDIT_RUN, fx.PARAPHRASE_RUN, fx.REPLAY_RUN, fx.TWIN_RUN):
                self.assertNotIn(name, text)
        replays = gallery.detail("d-" + fx.SCENARIO_ID)["replays"]
        self.assertIsNone(replays[0]["run"])

    def test_file_paths_are_limited_to_the_published_files(self):
        path = self.library.file_path("d-" + fx.SCENARIO_ID, "report.md")
        self.assertTrue(path.is_file())
        self.assertEqual(self.library.file_path("r-" + fx.QUIET_RUN, "report.md").name, "report.md")
        for item_id, name in (("d-" + fx.SCENARIO_ID, "../../runs/x/steps.json"), ("d-" + fx.SCENARIO_ID, "diagnosis.json"),
                              ("d-" + fx.SCENARIO_ID, "backend-state.json"), ("d-" + fx.SCENARIO_ID_TWIN, "explanation.json"),
                              ("r-" + fx.QUIET_RUN, "case.json"), ("m-" + fx.OCCLUSION_ID, "report.md"),
                              ("d-../x", "report.md")):
            with self.subTest(item=item_id, name=name), self.assertRaises((KeyError, ValueError)):
                self.library.file_path(item_id, name)


class HelperTests(unittest.TestCase):
    def test_stamp_to_iso(self):
        self.assertEqual(lib.stamp_to_iso("import-l10-start14-20261016T064528Z"), "2026-10-16T06:45:28Z")
        for bad in (None, "no-stamp", "x-20261316T064528Z", 5):
            self.assertIsNone(lib.stamp_to_iso(bad))

    def test_magnitude_edge_cases(self):
        self.assertEqual(lib._magnitude({}, "position", 1.0), "changed")
        self.assertEqual(lib._magnitude({"joints": []}, "joints", 1.0), "joints")
        row = {"joints": [{"name": "slide", "offset": 0.123456, "unit": "m"}]}
        self.assertEqual(lib._magnitude(row, "joints", 0.5), "1 joint, up to 0.0617 m")

    def test_the_explanation_block_tolerates_junk(self):
        block = lib._explanation(None, None, None, {"hypotheses": [{"text": 5}, "x", {"text": "ok", "evidence_ids": [1, "a"]}]})
        self.assertEqual(block["status"], "absent")
        self.assertEqual(block["hypotheses"], [{"text": "ok", "evidence_ids": ["a"]}])
        self.assertEqual(lib._explanation("rejected", None, None, None)["observations"], [])


if __name__ == "__main__":
    unittest.main()
