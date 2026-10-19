"""The shipped offline diagnosis must stay readable and publication-safe."""
import json
from pathlib import Path
import unittest

from robot_debug.viewer.export import scan_public
from robot_debug.viewer.library import Library


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo" / "root"
CASE_ID = "8e0dbd229d2ecda2599be4effa4a19ecfe14d71745b0be30b770fef6a16190b7"


class PackagedDemoTests(unittest.TestCase):
    def test_offline_case_has_evidence_videos_and_accepted_next_steps(self):
        detail = Library(DEMO, local=False).detail("d-" + CASE_ID)
        self.assertEqual(detail["fault_code"], "FL-S-8E0D")
        self.assertEqual(detail["verdict"], "reproduces")
        self.assertEqual(len(detail["videos"]), 3)
        self.assertTrue(all(video["url"] for video in detail["videos"]))
        self.assertEqual(detail["next_steps"]["status"], "interpreted")
        self.assertGreaterEqual(len(detail["next_steps"]["items"]), 2)

    def test_source_titles_links_and_ids_ship_without_retrieved_snippets(self):
        folder = DEMO / "diagnoses" / CASE_ID
        research = json.loads((folder / "research.json").read_text(encoding="utf-8"))
        metadata = json.loads((folder / "diagnosis.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["files"]["research"], "research.json")
        self.assertNotIn("run", metadata)
        for query in research["queries"]:
            self.assertEqual(set(query), {"results"})
            for source in query["results"]:
                self.assertEqual(set(source), {"source_id", "title", "url"})

    def test_all_shipped_text_passes_the_gallery_privacy_guard(self):
        for path in sorted(DEMO.rglob("*")):
            if path.suffix in (".json", ".md"):
                with self.subTest(file=path.name):
                    self.assertIsNone(scan_public(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
