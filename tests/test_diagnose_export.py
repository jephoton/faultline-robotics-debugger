"""The static export of a pipeline run: findings resolve, clips of every role are copied, the guard stays green."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from robot_debug import case_register as cr
from robot_debug.viewer import export as ex
from robot_debug.viewer.library import Library
from tests.test_case_register_cases import AUDIT_ID, WORDING_ID, make_pipeline_run
from tests.ui_fixtures import ledger_document, steps_document, write_json, write_text


class DiagnoseExport(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        self.run = make_pipeline_run(self.base)
        write_json(self.run / "ledger.json", ledger_document(2.0))
        cr.register_cases(self.run)
        self.app = self.base / "bundle"
        (self.app).mkdir()
        (self.app / "index.html").write_text("<!doctype html><title>Faultline</title>", encoding="utf-8")
        self.out = self.base / "gallery"

    def export(self, **options):
        return ex.export_gallery(self.out, self.base, runs_root=self.base / "runs", app_root=self.app,
                                 library=Library(self.base, runs_root=self.base / "runs", local=False), **options)

    def read(self, relative):
        return json.loads((self.out / relative).read_text(encoding="utf-8"))

    def test_both_cases_are_exported_with_their_clips_and_findings(self):
        summary = self.export()
        self.assertEqual(summary["cases"], 2)
        audit = self.read("data/library/d-{}.json".format(AUDIT_ID))
        self.assertEqual([f["id"] for f in audit["findings"]], ["d-" + AUDIT_ID, "d-" + WORDING_ID])
        self.assertEqual([v["role"] for v in audit["videos"]], ["control", "blur@0.40", "noise@1.00"])
        clip = audit["videos"][1]
        self.assertEqual(clip["url"], "/media/d-{}/videos/blur-0.40.mp4".format(AUDIT_ID))
        self.assertEqual((self.out / "media" / ("d-" + AUDIT_ID) / "videos" / "blur-0.40.mp4").read_text(),
                         "mp4 blur-s400000-a01")
        self.assertIsNone(audit["run"])
        self.assertEqual(audit["route"], "probes")

    def test_exporting_one_case_brings_the_rest_of_its_run_so_the_links_resolve(self):
        self.export(cases=[AUDIT_ID])
        listing = self.read("data/library.json")
        self.assertEqual(sorted(i["id"] for i in listing["items"]), sorted(["d-" + AUDIT_ID, "d-" + WORDING_ID]))
        detail = self.read("data/library/d-{}.json".format(AUDIT_ID))
        for finding in detail["findings"]:
            self.assertTrue((self.out / "data" / "library" / (finding["id"] + ".json")).is_file(), finding["id"])

    def test_a_start_that_passes_is_exported_with_a_public_id_when_asked_for(self):
        folder = self.base / "runs" / "quiet-20261019T020000Z"
        write_text(folder / "spec.yaml", "faultline: 1\nname: quiet\nmode: diagnose\npolicy: {suite: libero_object}\n"
                   "diagnose: {task: 0, start: 0}\nbudget: {max_spend_usd: 7, max_hours: 4}\n")
        write_json(folder / "steps.json", steps_document(
            "quiet", "diagnose", {"screen": {"status": "done"}}, {"status": "completed", "reason": None, "route": "passes"}))
        write_json(folder / "ledger.json", ledger_document(0.5))
        write_text(folder / "report.md", "# screen only\n")
        self.export(cases=["r-quiet-20261019T020000Z"])
        listing = self.read("data/library.json")
        public = listing["items"][0]["id"]
        self.assertRegex(public, r"^r-[0-9a-f]{12}$")
        detail = self.read("data/library/{}.json".format(public))
        self.assertEqual([f["id"] for f in detail["findings"]], [public])
        self.assertEqual(detail["route"], "passes")
        self.assertNotIn("20261019T020000Z", json.dumps(detail))

    def test_the_privacy_guard_still_refuses_a_leak_in_a_clip_label(self):
        case = json.loads((self.run / "cases" / "audit" / "case.json").read_text())
        case["videos"]["control"]["label"] = "Control at C:\\Users\\someone\\x"
        write_json(self.run / "cases" / "audit" / "case.json", case)
        cr.register_cases(self.run)
        with self.assertRaises(ex.ExportError):
            self.export()


if __name__ == "__main__":
    unittest.main()
