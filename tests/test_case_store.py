"""Local case persistence and portable export tests."""
import json
import tempfile
import unittest
from pathlib import Path

from robot_debug.case_io import SanitizedCaseValidationError, import_m4
from robot_debug.case_store import register_case, inspect_case, list_cases, export_case, reimport_case
from test_case_io import fixture


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.base = Path(self.tmp.name)
        self.source = self.base / "source"; self.source.mkdir(); fixture(self.source)
        self.workspace = self.base / "workspace"
        self.case = import_m4(self.source)

    def tearDown(self): self.tmp.cleanup()

    def test_register_inspect_list_are_idempotent_and_do_not_copy_sources(self):
        target = register_case(self.case, self.source, self.workspace)
        self.assertEqual(target, register_case(self.case, self.source, self.workspace))
        self.assertEqual(inspect_case(self.workspace, self.case["case_id"])["case_id"], self.case["case_id"])
        self.assertEqual([item["case_id"] for item in list_cases(self.workspace)], [self.case["case_id"]])
        self.assertEqual(sorted(p.name for p in target.iterdir()), ["case.json", "local-source.json"])
        self.assertNotIn(str(self.source), (target / "case.json").read_text())

    def test_export_reimport_preserves_identity_and_excludes_private_binding(self):
        register_case(self.case, self.source, self.workspace)
        output = self.base / "export"
        export_case(self.workspace, self.case["case_id"], output)
        self.assertEqual(sorted(p.name for p in output.iterdir()), ["README.md", "case.json"])
        self.assertNotIn(str(self.source), (output / "case.json").read_text())
        second = self.base / "second"
        reimport_case(output / "case.json", self.source, second)
        self.assertEqual(inspect_case(second, self.case["case_id"])["case_id"], self.case["case_id"])

    def test_tampered_badge_is_recomputed(self):
        target = register_case(self.case, self.source, self.workspace)
        p = target / "case.json"; data = json.loads(p.read_text()); data["capabilities"]["exercised_replay"]["status"] = "verified"; p.write_text(json.dumps(data))
        actual = inspect_case(self.workspace, self.case["case_id"])
        self.assertEqual(actual["capabilities"]["exercised_replay"]["status"], "unverified")

    def test_changed_source_refuses_export(self):
        register_case(self.case, self.source, self.workspace)
        p = self.source / "failure-reduction" / "replay_case.json"; data = json.loads(p.read_text()); data["seed"] = 8; p.write_text(json.dumps(data))
        inspected = inspect_case(self.workspace, self.case["case_id"])
        self.assertEqual(inspected["capabilities"]["historical_failure"]["status"], "not-established")
        with self.assertRaises(SanitizedCaseValidationError): export_case(self.workspace, self.case["case_id"], self.base / "bad-export")
        self.assertFalse((self.base / "bad-export").exists())

    def test_changed_aggregate_downgrades_history_and_refuses_export(self):
        register_case(self.case, self.source, self.workspace)
        p = next((self.source / "failure-reduction" / "runs").glob("parent*/*_aggregate.json"))
        data = json.loads(p.read_text()); data["tasks"][0]["episodes"][0]["metrics"]["success"] = True; p.write_text(json.dumps(data))
        inspected = inspect_case(self.workspace, self.case["case_id"])
        self.assertEqual(inspected["capabilities"]["historical_failure"]["status"], "not-established")
        with self.assertRaises(SanitizedCaseValidationError): export_case(self.workspace, self.case["case_id"], self.base / "changed")

    def test_optional_media_loss_preserves_historical_claim_and_reimport(self):
        run = next((self.source / "failure-reduction" / "runs").glob("parent*"))
        media = run / "task0000_ep0000_clip.mp4"; media.write_bytes(b"video")
        original = import_m4(self.source)
        register_case(original, self.source, self.workspace)
        media.unlink()
        inspected = inspect_case(self.workspace, original["case_id"])
        self.assertEqual(inspected["capabilities"]["historical_failure"]["status"], "confirmed")
        self.assertEqual(inspected["capabilities"]["inspection"]["status"], "unavailable")
        output = self.base / "portable"; export_case(self.workspace, original["case_id"], output)
        reimport_case(output / "case.json", self.source, self.base / "other")

    def test_reimport_rejects_tampered_core(self):
        register_case(self.case, self.source, self.workspace)
        output = self.base / "export"; export_case(self.workspace, self.case["case_id"], output)
        p = output / "case.json"; data = json.loads(p.read_text()); data["evidence"]["episodes"].pop(); p.write_text(json.dumps(data))
        with self.assertRaises(SanitizedCaseValidationError): reimport_case(p, self.source, self.base / "other")

    def test_explicit_null_profile_reimports_as_absent_profile(self):
        register_case(self.case, self.source, self.workspace)
        output = self.base / "export"; export_case(self.workspace, self.case["case_id"], output)
        p = output / "case.json"; data = json.loads(p.read_text()); data["source"]["profile"] = None; p.write_text(json.dumps(data))
        rebound = reimport_case(p, self.source, self.base / "other")
        self.assertEqual(rebound.name, self.case["case_id"])

    def test_bad_id_rejected_before_path_join(self):
        with self.assertRaises(SanitizedCaseValidationError): inspect_case(self.workspace, "../escape")

    def test_workspace_inside_source_is_rejected(self):
        with self.assertRaises(SanitizedCaseValidationError): register_case(self.case, self.source, self.source / "cases")

    def test_export_does_not_write_inside_source_root(self):
        register_case(self.case, self.source, self.workspace)
        with self.assertRaises(SanitizedCaseValidationError): export_case(self.workspace, self.case["case_id"], self.source / "portable")
        self.assertFalse((self.source / "portable").exists())

    def test_malformed_registry_entry_is_visible_as_unavailable(self):
        self.workspace.mkdir(); (self.workspace / "bad-name").mkdir()
        entries = list_cases(self.workspace)
        self.assertEqual(entries[0]["status"], "unavailable")

    def test_same_id_different_stored_core_refuses_registration(self):
        target = register_case(self.case, self.source, self.workspace)
        p = target / "case.json"; data = json.loads(p.read_text()); data["evidence"]["episodes"].pop(); p.write_text(json.dumps(data))
        with self.assertRaises(SanitizedCaseValidationError): register_case(self.case, self.source, self.workspace)

    def test_unknown_stored_schema_is_unavailable(self):
        target = register_case(self.case, self.source, self.workspace)
        p = target / "case.json"; data = json.loads(p.read_text()); data["schema_version"] = 2; p.write_text(json.dumps(data))
        self.assertEqual(list_cases(self.workspace)[0]["status"], "unavailable")


if __name__ == "__main__": unittest.main()
