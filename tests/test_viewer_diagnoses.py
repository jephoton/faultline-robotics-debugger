"""The viewer lists registered diagnoses with their report and videos."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from robot_debug.case_register import register_run
from robot_debug.viewer.catalog import ArtifactCatalog
from robot_debug.viewer.server import make_handler
from tests.test_case_register import CASE_ID, make_run

WEB = Path(__file__).resolve().parents[1] / "src" / "robot_debug" / "viewer" / "web"


class DiagnosisViewerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        register_run(make_run(self.root))
        handler = make_handler(ArtifactCatalog(self.root), WEB)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = "http://127.0.0.1:{}".format(self.server.server_port)

    def get(self, path, headers=None):
        try:
            with urlopen(Request(self.base + path, headers=headers or {})) as response:
                return response.status, dict(response.headers.items()), response.read()
        except HTTPError as error:
            return error.code, dict(error.headers.items()), error.read()

    def test_the_list_has_the_summary_and_a_media_url_per_video(self):
        status, headers, body = self.get("/api/diagnoses")
        payload = json.loads(body)
        self.assertEqual(200, status)
        self.assertEqual("application/json; charset=utf-8", headers["Content-Type"])
        (entry,) = payload["diagnoses"]
        self.assertEqual((CASE_ID, "soup-start14", "libero_10"), (entry["case_id"], entry["name"], entry["suite"]))
        self.assertEqual("/media/diagnoses/{}/videos/original.mp4".format(CASE_ID), entry["videos"]["original"]["url"])
        self.assertNotIn("files", entry)
        self.assertNotIn(str(self.root), body.decode("utf-8"))

    def test_the_detail_has_the_report_and_the_explanation(self):
        status, _, body = self.get("/api/diagnoses/" + CASE_ID)
        detail = json.loads(body)["diagnosis"]
        self.assertEqual(200, status)
        self.assertIn("# Scenario reduction", detail["report"])
        self.assertEqual("scenario_explanation", detail["explanation"]["kind"])

    def test_a_registered_video_is_served_with_byte_ranges(self):
        url = json.loads(self.get("/api/diagnoses")[2])["diagnoses"][0]["videos"]["minimal"]["url"]
        status, headers, body = self.get(url, {"Range": "bytes=0-4"})
        self.assertEqual((206, b"video"), (status, body))
        self.assertEqual(200, self.get(url)[0])

    def test_unknown_and_malformed_ids_are_not_found(self):
        for path in ("/api/diagnoses/" + "00" * 32, "/api/diagnoses/not-an-id", "/api/diagnoses/..%2f..%2fx"):
            with self.subTest(path=path):
                self.assertIn(self.get(path)[0], (400, 404))

    def test_the_diagnoses_page_and_script_are_served(self):
        status, headers, body = self.get("/diagnoses")
        self.assertEqual(200, status)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"diagnoses.js", body)
        status, headers, body = self.get("/diagnoses.js")
        self.assertEqual(200, status)
        self.assertIn("javascript", headers["Content-Type"])
        self.assertIn(b"/api/diagnoses", body)

    def test_the_main_page_links_to_the_diagnoses(self):
        self.assertIn(b'href="/diagnoses"', self.get("/")[2])

    def test_an_empty_viewer_lists_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            handler = make_handler(ArtifactCatalog(Path(temporary)), WEB)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urlopen("http://127.0.0.1:{}/api/diagnoses".format(server.server_port)) as response:
                    self.assertEqual({"diagnoses": [], "warnings": []}, json.loads(response.read()))
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
