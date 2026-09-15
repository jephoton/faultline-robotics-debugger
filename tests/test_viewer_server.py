import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

import robot_debug.viewer.server as viewer_server
from robot_debug.viewer.catalog import ArtifactCatalog
from robot_debug.viewer.server import make_handler
from tests.test_viewer_catalog import write_episode


class ViewerServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        write_episode(self.root, "valid", success=True)
        self.catalog = ArtifactCatalog(self.root)
        self.web_root = Path(__file__).resolve().parents[1] / "src" / "robot_debug" / "viewer" / "web"
        handler = make_handler(self.catalog, self.web_root)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = "http://127.0.0.1:{}".format(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temporary_directory.cleanup()

    def get(self, path, headers=None):
        request = Request(self.base_url + path, headers=headers or {})
        try:
            with urlopen(request) as response:
                return response.status, dict(response.headers.items()), response.read()
        except HTTPError as error:
            return error.code, dict(error.headers.items()), error.read()

    def test_runs_endpoint_returns_normalized_snapshot(self):
        status, headers, body = self.get("/api/runs")

        payload = json.loads(body)

        self.assertEqual(status, 200)
        self.assertEqual(payload["episodes"][0]["outcome"], "success")
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_trace_endpoint_returns_points(self):
        episode_id = self.catalog.list_episodes()[0].episode_id

        status, _, body = self.get("/api/episodes/{}/trace".format(episode_id))

        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)["points"]), 2)

    def test_media_endpoint_rejects_traversal(self):
        status, _, _ = self.get("/media/%2e%2e/secret.txt")

        self.assertIn(status, (400, 404))

    def test_media_endpoint_honors_byte_ranges(self):
        episode = self.catalog.list_episodes()[0]

        status, headers, body = self.get(
            "/media/" + episode.video_path, {"Range": "bytes=1-3"}
        )

        self.assertEqual(status, 206)
        self.assertEqual(body, b"ide")
        self.assertEqual(headers["Content-Range"], "bytes 1-3/5")

    def test_health_and_unknown_episode_endpoints(self):
        health_status, _, health_body = self.get("/api/health")
        unknown_status, _, _ = self.get("/api/episodes/missing/trace")

        self.assertEqual(health_status, 200)
        self.assertEqual(json.loads(health_body)["read_only"], True)
        self.assertEqual(unknown_status, 404)

    def test_static_workbench_assets_expose_semantic_landmarks(self):
        page_status, page_headers, page_body = self.get("/")
        css_status, css_headers, css_body = self.get("/styles.css")
        app_status, app_headers, app_body = self.get("/app.js")

        page = page_body.decode("utf-8")
        self.assertEqual(page_status, 200)
        self.assertEqual(page_headers["Content-Type"], "text/html; charset=utf-8")
        self.assertEqual(css_status, 200)
        self.assertEqual(css_headers["Content-Type"], "text/css; charset=utf-8")
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", css_body.decode("utf-8"))
        self.assertEqual(app_status, 200)
        self.assertEqual(app_headers["Content-Type"], "text/javascript; charset=utf-8")
        app = app_body.decode("utf-8")
        self.assertIn("refreshCatalog", app)
        self.assertIn("representativeNominal", app)
        self.assertIn("displayEpisodes", app)
        for identifier in (
            'id="demo-guide"',
            'id="comparison-conclusion"',
            'id="primary-role"',
            'id="comparison-role"',
            'id="link-state"',
        ):
            self.assertIn(identifier, page)
        for landmark in ("<header", "<nav", "<main", "<aside", 'id="connection-status"'):
            self.assertIn(landmark, page)

    def test_javascript_asset_uses_stable_content_type(self):
        with patch.object(
            viewer_server.mimetypes,
            "guess_type",
            return_value=("application/javascript", None),
        ):
            status, headers, _ = self.get("/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/javascript; charset=utf-8")


if __name__ == "__main__":
    unittest.main()
