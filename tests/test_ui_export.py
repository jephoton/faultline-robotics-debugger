"""The static export: shapes, media, the public projection and the refusals (ADR 0033)."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import robot_debug
from robot_debug.viewer import export as ex
from robot_debug.viewer.library import Library
from tests import ui_fixtures as fx


class ExportCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        self.paths = fx.build(self.base)
        self.app = self.base / "bundle"
        (self.app / "assets").mkdir(parents=True)
        (self.app / "index.html").write_text("<!doctype html><title>Faultline</title>", encoding="utf-8")
        (self.app / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
        self.out = self.base / "gallery"

    def library(self):
        return Library(self.paths["artifacts"], runs_root=self.paths["runs"], local=False,
                       inspect_case=lambda workspace, case_id: fx.occlusion_case())

    def export(self, **options):
        options.setdefault("library", self.library())
        options.setdefault("app_root", self.app)
        options.setdefault("runs_root", self.paths["runs"])
        return ex.export_gallery(self.out, self.paths["artifacts"], **options)

    def read(self, relative):
        return json.loads((self.out / relative).read_text(encoding="utf-8"))

    def every_text_file(self):
        return [p for p in self.out.rglob("*") if p.is_file() and p.suffix in (".json", ".md", ".html", ".js")]


class ShapeTests(ExportCase):
    def test_the_gallery_has_the_bundle_the_data_and_the_rewrite(self):
        summary = self.export()
        self.assertEqual(summary["cases"], 5)
        self.assertTrue((self.out / "index.html").is_file())
        self.assertTrue((self.out / "assets" / "index-abc123.js").is_file())
        self.assertEqual(self.read("vercel.json"), {"rewrites": [
            {"source": "/((?!assets/|data/|media/).*)", "destination": "/index.html"}]})
        session = self.read("data/session.json")
        self.assertEqual((session["api_version"], session["mode"], session["controls"], session["token"]),
                         (1, "static", False, None))
        self.assertIsInstance(session["version"], str)

    def test_the_library_lists_diagnoses_and_the_old_case_but_not_runs_without_a_case(self):
        self.export()
        listing = self.read("data/library.json")
        ids = sorted(item["id"] for item in listing["items"])
        self.assertEqual(ids, sorted(["d-" + fx.SCENARIO_ID, "d-" + fx.SCENARIO_ID_TWIN, "d-" + fx.AUDIT_ID,
                                      "d-" + fx.PARAPHRASE_ID, "m-" + fx.OCCLUSION_ID]))
        self.assertEqual(listing["warnings"], [])
        for item in listing["items"]:
            self.assertIsNone(item["run"])
            self.assertTrue((self.out / "data" / "library" / (item["id"] + ".json")).is_file())

    def test_details_match_the_local_shape_with_run_null(self):
        self.export()
        detail = self.read("data/library/d-{}.json".format(fx.SCENARIO_ID))
        local = Library(self.paths["artifacts"], runs_root=self.paths["runs"]).detail("d-" + fx.SCENARIO_ID)
        self.assertEqual(sorted(detail), sorted(local))
        self.assertIsNone(detail["run"])
        self.assertEqual(detail["scenario"], local["scenario"])
        self.assertEqual(detail["history"]["jobs"], 1, "the step history is part of the story and is kept")
        self.assertEqual([r["run"] for r in detail["replays"]], [None])
        self.assertEqual([(r["checkpoint"], r["original"]) for r in detail["replays"]], [(None, None)],
                         "the replay rows keep the checkpoint fields (an older replay recorded none)")

    def test_videos_and_files_are_copied_and_their_urls_rewritten(self):
        self.export()
        identifier = "d-" + fx.SCENARIO_ID
        detail = self.read("data/library/{}.json".format(identifier))
        for video in detail["videos"]:
            self.assertEqual(video["url"], "/media/{}/videos/{}.mp4".format(identifier, video["role"]))
            self.assertTrue((self.out / video["url"].lstrip("/")).is_file())
        self.assertEqual([f["name"] for f in detail["files"]],
                         ["report.md", "case.json", "explanation.json", "minimal-candidate.json", "replay-inputs.json"])
        for entry in detail["files"]:
            self.assertEqual(entry["url"], "/media/{}/files/{}".format(identifier, entry["name"]))
            self.assertTrue((self.out / entry["url"].lstrip("/")).is_file())
        report = (self.out / "media" / identifier / "files" / "report.md").read_text(encoding="utf-8")
        self.assertNotIn("someone", report)
        self.assertIn("[local path omitted]", report)

    def test_the_old_case_episodes_are_copied_too(self):
        self.export()
        identifier = "m-" + fx.OCCLUSION_ID
        block = self.read("data/library/{}.json".format(identifier))["occlusion"]
        self.assertEqual(block["episodes"][0]["url"], "/media/{}/episodes/1a8513e316cce7aa.mp4".format(identifier))
        for episode in block["episodes"]:
            self.assertTrue((self.out / episode["url"].lstrip("/")).is_file())

    def test_a_video_that_is_missing_has_no_url(self):
        for path in (self.paths["diagnoses"] / fx.SCENARIO_ID / "videos").glob("*.mp4"):
            path.unlink()
        self.export()
        detail = self.read("data/library/d-{}.json".format(fx.SCENARIO_ID))
        self.assertTrue(all(v["url"] is None for v in detail["videos"]))


class PublicProjectionTests(ExportCase):
    def test_nothing_private_is_in_any_exported_file(self):
        self.export()
        files = self.every_text_file()
        self.assertGreater(len(files), 10)
        run_names = [p.name for p in self.paths["runs"].iterdir()]
        for path in files:
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(ex.scan_public(text), path.name)
            for private in run_names + [fx.FAKE_JOB_ID, fx.FAKE_PROJECT, fx.FAKE_BUCKET, "someone", "backend-state",
                                        str(self.base), str(self.base.resolve()).replace("\\", "\\\\"), "job_id"]:
                self.assertNotIn(private, text, "{} in {}".format(private, path.name))

    def test_no_path_in_the_export_names_a_run_folder(self):
        self.export()
        run_names = {p.name for p in self.paths["runs"].iterdir()}
        for path in self.out.rglob("*"):
            self.assertFalse(run_names & set(path.relative_to(self.out).parts), str(path))

    def test_a_private_detail_in_a_copied_file_aborts_the_export_and_removes_it(self):
        case = fx.scenario_case()
        case["note"] = "from " + fx.FAKE_JOB_ID
        fx.write_json(self.paths["diagnoses"] / fx.SCENARIO_ID / "case.json", case)
        with self.assertRaises(ex.ExportError) as caught:
            self.export()
        self.assertIn("a Job id", str(caught.exception))
        self.assertNotIn(fx.FAKE_JOB_ID, str(caught.exception))
        self.assertFalse(self.out.exists(), "a refused export leaves nothing behind")

    def test_the_scanner_knows_private_details_and_ignores_urls(self):
        for text in ("C:\\Users\\x", "C:/Users/x", "see /home/me/x", "aijob-abcdef12", "project-abcdef12",
                     "registry-abcdef12", "cr.eu-north1.nebius.cloud/x", "demo-20261016T064528Z", "backend-state.json",
                     '"bucket_name": "x"', "\\\\server\\share"):
            self.assertIsNotNone(ex.scan_public(text), text)
        for text in ("https://example.com/home/page", "http://x.y/a/b", "plain text", "2026-10-16T06:45:28Z",
                     "afb5" + "0123456789abcdef" * 3, "e00a" + "1" * 60, "S: success",
                     # A paper title in LaTeX, as JSON writes it: not a network path.
                     '"title": "Evaluating \\\\( \\\\pi_0 \\\\) in the Wild"'):
            self.assertIsNone(ex.scan_public(text), text)


class GuardGapTests(ExportCase):
    """More private details the last-line scan must refuse (review L4)."""

    def test_more_paths_buckets_secret_names_and_emails_are_refused(self):
        for text, label in (
                ("saved in /private/var/folders/x", "path"), ("data at /srv/faultline/runs", "path"),
                ("cwd /workspace/repo/artifacts", "path"), ("see ~/work/runs/demo", "path"),
                ("bucket faultline-demo-3fa9c1 holds it", "bucket"), ('"bucket": "faultline-soup-start-0a1b2c"', "bucket"),
                ("secret faultline-hf-token is set", "secret"), ("uses team-hf-token for access", "secret"),
                ("mail jane.doe@example.com for access", "email"), ("owner someone+tag@mail.example.org", "email")):
            with self.subTest(text=text):
                self.assertIsNotNone(ex.scan_public(text), label)

    def test_public_text_that_looks_close_is_still_fine(self):
        for text in ("https://github.com/jephoton/faultline-robotics-debugger", "faultline-robotics-debugger",
                     "Faultline finds failures", "faultline-serverless:local", "image@sha256:abcdef0123456789",
                     "approximately ~5 cm", "a ratio of 3~4", "version pkg@1.2.3", "HF_TOKEN is read from the environment",
                     "the /api/library endpoint", "https://example.com/private/page", "a/b/c.json"):
            with self.subTest(text=text):
                self.assertIsNone(ex.scan_public(text))

    def test_a_secret_name_taken_from_the_runs_own_spec_is_refused(self):
        spec = self.paths["runs"] / fx.SCENARIO_RUN / "spec.yaml"
        spec.write_text("backend:\n  kind: nebius\n  hf_token_secret: quiet-vault-entry\n", encoding="utf-8")
        case = fx.scenario_case()
        case["note"] = "token from quiet-vault-entry"
        fx.write_json(self.paths["diagnoses"] / fx.SCENARIO_ID / "case.json", case)
        with self.assertRaises(ex.ExportError) as caught:
            self.export()
        self.assertIn("secret", str(caught.exception))
        self.assertNotIn("quiet-vault-entry", str(caught.exception))
        self.assertFalse(self.out.exists())

    def test_a_copied_file_with_an_email_aborts_the_export(self):
        case = fx.scenario_case()
        case["note"] = "contact jane.doe@example.com"
        fx.write_json(self.paths["diagnoses"] / fx.SCENARIO_ID / "case.json", case)
        with self.assertRaises(ex.ExportError) as caught:
            self.export()
        self.assertIn("an email address", str(caught.exception))
        self.assertNotIn("jane.doe", str(caught.exception))


class SelectionTests(ExportCase):
    def ids(self):
        return sorted(item["id"] for item in self.read("data/library.json")["items"])

    def test_cases_can_be_chosen_by_library_id_case_id_or_a_long_prefix(self):
        self.export(cases=["d-" + fx.AUDIT_ID, fx.PARAPHRASE_ID, fx.SCENARIO_ID[:10]])
        self.assertEqual(self.ids(), sorted(["d-" + fx.AUDIT_ID, "d-" + fx.PARAPHRASE_ID, "d-" + fx.SCENARIO_ID]))

    def test_an_unknown_or_ambiguous_choice_is_refused(self):
        for ask, words in (("d-" + "0" * 64, "No single case"), ("zzzz", "No single case"), (fx.SCENARIO_ID[:4], "No single case")):
            with self.subTest(ask=ask), self.assertRaises(ex.ExportError) as caught:
                self.export(cases=[ask])
            self.assertIn(words, str(caught.exception))
        self.assertFalse(self.out.exists())

    def test_a_run_without_a_case_can_be_chosen_and_gets_a_digest_id(self):
        self.export(cases=["r-" + fx.QUIET_RUN])
        [item] = self.read("data/library.json")["items"]
        self.assertRegex(item["id"], r"^r-[0-9a-f]{12}$")
        self.assertNotIn(fx.QUIET_RUN, json.dumps(item))
        detail = self.read("data/library/{}.json".format(item["id"]))
        self.assertEqual(detail["id"], item["id"])
        self.assertEqual(detail["paraphrase"]["original"], fx.INSTRUCTION)
        for path in self.every_text_file():
            self.assertNotIn(fx.QUIET_RUN, path.read_text(encoding="utf-8"))
        self.assertEqual([f["name"] for f in detail["files"]], ["report.md"])


class OutputRefusalTests(ExportCase):
    def test_an_output_folder_inside_the_source_tree_is_refused(self):
        source = Path(robot_debug.__file__).resolve().parents[1]
        self.out = source / "export-test-should-not-exist"
        try:
            with self.assertRaises(ex.ExportError) as caught:
                self.export()
            self.assertIn("src folder", str(caught.exception))
            self.assertFalse(self.out.exists())
        finally:
            shutil.rmtree(str(self.out), ignore_errors=True)

    def test_a_folder_that_is_not_empty_needs_force(self):
        self.out.mkdir()
        (self.out / "keep.txt").write_text("mine", encoding="utf-8")
        with self.assertRaises(ex.ExportError) as caught:
            self.export()
        self.assertIn("--force", str(caught.exception))
        self.assertEqual((self.out / "keep.txt").read_text(encoding="utf-8"), "mine")

    def test_an_empty_existing_folder_is_fine(self):
        self.out.mkdir()
        self.assertEqual(self.export()["cases"], 5)

    def test_force_replaces_a_previous_export_and_keeps_unrelated_files(self):
        self.export()
        stale = self.out / "media" / "d-old" / "videos" / "original.mp4"
        stale.parent.mkdir(parents=True)
        stale.write_text("old", encoding="utf-8")
        (self.out / "data" / "library" / "d-old.json").write_text("{}", encoding="utf-8")
        (self.out / "notes.txt").write_text("keep me", encoding="utf-8")
        self.export(force=True)
        self.assertFalse(stale.exists())
        self.assertFalse((self.out / "data" / "library" / "d-old.json").exists())
        self.assertEqual((self.out / "notes.txt").read_text(encoding="utf-8"), "keep me")
        self.assertEqual(len(self.read("data/library.json")["items"]), 5)

    def make_foreign_folder(self, session=None):
        self.out.mkdir()
        mine = {"data/notes.csv": "my data", "media/holiday.txt": "my photos", "assets/logo.svg": "<svg/>",
                "readme.txt": "mine"}
        for name, text in mine.items():
            (self.out / name).parent.mkdir(parents=True, exist_ok=True)
            (self.out / name).write_text(text, encoding="utf-8")
        if session is not None:
            (self.out / "data" / "session.json").write_text(session, encoding="utf-8")
        return mine

    def assert_untouched(self, mine):
        for name, text in mine.items():
            self.assertEqual((self.out / name).read_text(encoding="utf-8"), text, name)

    def test_force_refuses_a_folder_that_is_not_a_previous_export(self):
        mine = self.make_foreign_folder()
        with self.assertRaises(ex.ExportError) as caught:
            self.export(force=True)
        self.assertIn("not a previous Faultline export", str(caught.exception))
        self.assert_untouched(mine)

    def test_force_refuses_a_session_file_that_is_not_a_static_export(self):
        for session in ('{"mode": "local"}', "not json", "[]", '{"mode": "static"'):
            with self.subTest(session=session):
                shutil.rmtree(str(self.out), ignore_errors=True)
                mine = self.make_foreign_folder(session)
                with self.assertRaises(ex.ExportError):
                    self.export(force=True)
                self.assert_untouched(mine)

    def test_force_accepts_an_empty_folder_and_an_earlier_export(self):
        self.out.mkdir()
        self.export(force=True)
        self.assertEqual(self.read("data/session.json")["mode"], "static")
        self.export(force=True)

    def test_a_file_in_place_of_the_folder_is_refused(self):
        self.out.write_text("x", encoding="utf-8")
        with self.assertRaises(ex.ExportError):
            self.export(force=True)

    def test_a_missing_bundle_is_a_plain_error(self):
        shutil.rmtree(str(self.app))
        with self.assertRaises(ex.ExportError) as caught:
            self.export()
        self.assertIn("npm run build", str(caught.exception))
        self.assertFalse(self.out.exists())


class IdTests(unittest.TestCase):
    def test_public_ids(self):
        self.assertEqual(ex.public_id("d-" + "a" * 64), "d-" + "a" * 64)
        self.assertEqual(ex.public_id("m-" + "b" * 64), "m-" + "b" * 64)
        self.assertRegex(ex.public_id("r-some-run-20261016T020108Z"), r"^r-[0-9a-f]{12}$")
        self.assertEqual(ex.public_id("r-x"), ex.public_id("r-x"))


if __name__ == "__main__":
    unittest.main()
