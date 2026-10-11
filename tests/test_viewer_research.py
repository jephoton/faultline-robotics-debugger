"""Read-only viewer integration for stored public-research records."""

import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from robot_debug.viewer.catalog import ArtifactCatalog
from robot_debug.viewer.server import default_research_reader, make_handler

WEB_ROOT = Path(__file__).resolve().parents[1] / "src" / "robot_debug" / "viewer" / "web"
CASE_ID = "a" * 64


def envelope():
    provenance = {
        "source": "live", "provider": "nebius-token-factory", "model": "m",
        "endpoint": "https://example.invalid/v1/", "created_at": "2026-10-11T10:00:00Z",
        "request_status": "completed", "error_code": None, "latency_seconds": 1.0,
        "prompt_tokens": 10, "completion_tokens": 5, "estimated_cost_usd": 0.0001,
        "billed_cost_usd": None, "reservation_usd": 0.01,
    }
    return {
        "records": [{
            "schema_version": 1, "record_id": "b" * 64, "case_id": CASE_ID, "packet_id": "c" * 64,
            "queries": [{
                "query": "VLA occlusion", "retrieved_at": "2026-10-11T09:00:00Z",
                "request_id": None, "credits": 1, "from_cache": False,
                "results": [{"source_id": "S1", "title": "A paper", "url": "https://example.org/a",
                             "snippet": "text", "score": 0.5}],
            }],
            "summary": {
                "status": "interpreted",
                "related_work": [{"text": "Related.", "source_ids": ["S1"]}],
                "limitations": ["Context only."], "provenance": provenance,
            },
        }],
        "warnings": [],
    }


class ViewerResearchServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.calls = []
        self.reader = self.default_reader
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        handler = make_handler(
            ArtifactCatalog(self.base), WEB_ROOT, self.workspace,
            research_reader=lambda workspace, case_id: self.reader(workspace, case_id))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:{}".format(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def default_reader(self, workspace, case_id):
        self.calls.append((workspace, case_id))
        return envelope()

    def request(self, path, method="GET"):
        request = Request(self.url + path, method=method, data=b"{}" if method == "POST" else None)
        try:
            with urlopen(request) as response:
                return response.status, dict(response.headers.items()), response.read()
        except HTTPError as error:
            return error.code, dict(error.headers.items()), error.read()

    def endpoint(self, case_id=CASE_ID):
        return "/api/cases/{}/research".format(case_id)

    def test_route_returns_injected_reader_envelope_without_network(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("external network used")):
            status, headers, body = self.request(self.endpoint())
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(json.loads(body), envelope())
        self.assertEqual(self.calls, [(self.workspace, CASE_ID)])

    def test_bad_case_ids_are_rejected_before_the_reader_runs(self):
        for case_id in ("short", "A" * 64, "g" * 64, "a" * 63, "a" * 65):
            status, _, _ = self.request(self.endpoint(case_id))
            self.assertEqual(status, 400, case_id)
        self.assertEqual(self.calls, [])

    def test_reader_errors_map_to_503_and_404(self):
        def broken(workspace, case_id):
            raise OSError("disk unavailable")
        self.reader = broken
        status, _, body = self.request(self.endpoint())
        self.assertEqual(status, 503)
        self.assertNotIn("disk unavailable", body.decode("utf-8"))

        def missing(workspace, case_id):
            raise FileNotFoundError(case_id)
        self.reader = missing
        status, _, _ = self.request(self.endpoint())
        self.assertEqual(status, 404)

    def test_route_has_no_write_methods(self):
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            status, _, _ = self.request(self.endpoint(), method)
            self.assertEqual(status, 501, method)
        self.assertEqual(self.calls, [])

    def test_default_reader_failure_to_import_is_unavailable_not_a_crash(self):
        with patch.dict("sys.modules", {"robot_debug.research_store": None}):
            with self.assertRaises(OSError):
                default_research_reader(self.workspace, CASE_ID)


class ViewerResearchStaticAssetTests(unittest.TestCase):
    def setUp(self):
        self.html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        self.script = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    def research_source(self):
        start = self.script.index("function beginResearchRequest")
        end = self.script.index("async function refreshReduction")
        return self.script[start:end]

    def test_index_contains_research_panel_after_explanations_with_fixed_banner(self):
        self.assertIn('<details id="case-research">', self.html)
        self.assertLess(self.html.index('id="case-explanations"'), self.html.index('id="case-research"'))
        self.assertIn("Related public research (context, not evidence)", self.html)
        self.assertIn(
            "Retrieved by Tavily from the public web. These sources do not prove why this case failed.",
            self.html)

    def test_research_rendering_never_writes_html_strings(self):
        source = self.research_source()
        self.assertIn("function renderResearch", source)
        for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "createContextualFragment"):
            self.assertNotIn(forbidden, source)

    def test_research_links_require_https_and_safe_rel(self):
        source = self.research_source()
        self.assertIn('protocol === "https:"', source)
        self.assertIn('"noopener noreferrer"', source)
        self.assertIn('target = "_blank"', source)
        self.assertIn("/research", source)

    def test_viewer_never_posts_to_a_provider(self):
        self.assertNotIn('method: "POST"', self.research_source())
        self.assertNotIn("tavily.com", self.script)


if __name__ == "__main__":
    unittest.main()
