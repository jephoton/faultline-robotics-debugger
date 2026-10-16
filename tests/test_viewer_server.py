import json
import os
import shutil
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
        self.app_root = self.root.parent / (self.root.name + "-app")
        (self.app_root / "assets").mkdir(parents=True)
        (self.app_root / "index.html").write_text("<!doctype html><title>Faultline</title>", encoding="utf-8")
        (self.app_root / "assets" / "x.js").write_text("console.log(1)", encoding="utf-8")
        self.addCleanup(shutil.rmtree, str(self.app_root), True)
        handler = make_handler(self.catalog, app_root=self.app_root)
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

    def test_javascript_asset_uses_stable_content_type(self):
        with patch.object(
            viewer_server.mimetypes,
            "guess_type",
            return_value=("application/javascript", None),
        ):
            status, headers, _ = self.get("/assets/x.js")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/javascript; charset=utf-8")

    def test_the_app_page_is_faultline_and_carries_the_security_headers(self):
        status, headers, body = self.get("/")

        self.assertEqual(status, 200)
        self.assertIn(b"<title>Faultline</title>", body)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")

    def test_unknown_paths_and_the_retired_pages_are_404(self):
        for path in ("/api/nonsense", "/app.js", "/styles.css", "/diagnoses.js", "/assets/none.js"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path)[0], 404)

    def test_reduction_endpoint_returns_validated_session_metrics(self):
        self._write_reduction_fixture()

        status, _, body = self.get("/api/reduction")

        payload = json.loads(body)
        self.assertEqual(status, 200)
        reduction = payload["reduction"]
        self.assertEqual(reduction["session_name"], "failure-reduction")
        self.assertEqual(reduction["metrics"], {
            "parent_area_percent": 25.0,
            "reduced_area_percent": 18.75,
            "area_reduction_percent": 25.0,
        })
        self.assertEqual(reduction["certification"], "4/5 rule passed")
        self.assertEqual(reduction["terminal_outcome"], "reduced_failure_with_nominal_controls")

    def test_reduction_endpoint_isolated_from_unrelated_episode_and_media_json(self):
        self._write_reduction_fixture()

        status, _, body = self.get("/api/reduction")
        media_status, _, _ = self.get("/media/failure-reduction/session_summary.json")

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["reduction"]["session_name"], "failure-reduction")
        self.assertIn(media_status, (400, 404))

    def test_reduction_endpoint_suppresses_missing_malformed_and_mismatched_evidence(self):
        status, _, body = self.get("/api/reduction")
        self.assertEqual(status, 200)
        self.assertIsNone(json.loads(body)["reduction"])

        reduction = self.root / "failure-reduction"
        reduction.mkdir()
        (reduction / "session_summary.json").write_text("{bad", encoding="utf-8")
        (reduction / "replay_case.json").write_text("{}", encoding="utf-8")
        status, _, body = self.get("/api/reduction")
        self.assertIsNone(json.loads(body)["reduction"])

        for key in ("geometry", "completed"):
            self._write_reduction_fixture()
            summary_path = reduction / "session_summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary[key] = None
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            status, _, body = self.get("/api/reduction")
            self.assertEqual(status, 200)
            self.assertIsNone(json.loads(body)["reduction"])

        self._write_reduction_fixture()
        manifest = json.loads((reduction / "replay_case.json").read_text(encoding="utf-8"))
        manifest["rectangle"]["width"] = 0.25
        (reduction / "replay_case.json").write_text(json.dumps(manifest), encoding="utf-8")
        status, _, body = self.get("/api/reduction")
        self.assertIsNone(json.loads(body)["reduction"])

    def test_reduction_endpoint_with_failed_nominal_controls_has_no_certification(self):
        self._write_reduction_fixture(
            stop_reason="reduced_failure_nominal_controls_failed", control_outcomes=["success"] * 4 + ["task_failure"]
        )

        status, _, body = self.get("/api/reduction")

        reduction = json.loads(body)["reduction"]
        self.assertEqual(status, 200)
        self.assertIsNone(reduction["certification"])
        self.assertEqual(reduction["terminal_outcome"], "reduced_failure_nominal_controls_failed")

    def test_reduction_endpoint_rejects_zero_outside_parent_and_parent_decisions(self):
        self._write_reduction_fixture()
        reduction = self.root / "failure-reduction"
        summary_path = reduction / "session_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["completed"]["decisions"][0]["label"] = "parent"
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        self.assertIsNone(json.loads(self.get("/api/reduction")[2])["reduction"])

        self._write_reduction_fixture()
        summary = json.loads((reduction / "session_summary.json").read_text(encoding="utf-8"))
        summary["geometry"]["final"]["width"] = 10 ** 3000
        (reduction / "session_summary.json").write_text(json.dumps(summary), encoding="utf-8")
        self.assertIsNone(json.loads(self.get("/api/reduction")[2])["reduction"])

        self._write_reduction_fixture()
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["geometry"]["final"]["width"] = 0
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        self.assertIsNone(json.loads(self.get("/api/reduction")[2])["reduction"])

        self._write_reduction_fixture()
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["geometry"]["final"]["x"] = 0.8
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        self.assertIsNone(json.loads(self.get("/api/reduction")[2])["reduction"])

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_reduction_endpoint_rejects_file_symlink_escape(self):
        outside = self.root.parent / (self.root.name + "-outside")
        outside.mkdir()
        try:
            (outside / "session_summary.json").write_text("{}", encoding="utf-8")
            (outside / "replay_case.json").write_text("{}", encoding="utf-8")
            reduction = self.root / "failure-reduction"
            reduction.mkdir()
            try:
                os.symlink(outside / "session_summary.json", reduction / "session_summary.json")
                os.symlink(outside / "replay_case.json", reduction / "replay_case.json")
            except OSError as error:
                self.skipTest("symlink setup unavailable: {}".format(error))
            self.assertIsNone(json.loads(self.get("/api/reduction")[2])["reduction"])
        finally:
            for path in (outside / "session_summary.json", outside / "replay_case.json"):
                path.unlink(missing_ok=True)
            outside.rmdir()

    def _write_reduction_fixture(self, *, stop_reason="reduced_failure_with_nominal_controls", control_outcomes=None):
        reduction = self.root / "failure-reduction"
        reduction.mkdir(exist_ok=True)
        rectangle = {"x": 0.5, "y": 0.0, "width": 0.375, "height": 0.5}
        summary = {
            "geometry": {
                "parent": {"x": 0.5, "y": 0.0, "width": 0.5, "height": 0.5, "area": 0.25},
                "current": dict(rectangle, area=0.1875),
                "final": dict(rectangle, area=0.1875),
            },
            "lineage": [{"edge": "left", "rectangle": rectangle, "area": 0.1875}],
            "stop_reason": stop_reason,
            "completed": {
                "decisions": [{
                    "label": "candidate", "edge": "left", "decision": "pass",
                    "rectangle": rectangle, "outcomes": ["policy_failure"] * 4 + ["success"],
                }],
                    "control_outcomes": control_outcomes if control_outcomes is not None else ["success"] * 5,
            },
        }
        replay = {
            "rectangle": rectangle,
            "acceptance_rule": {"failures": 4, "attempts": 5},
            "expected_outcome": "policy_failure",
        }
        (reduction / "session_summary.json").write_text(json.dumps(summary), encoding="utf-8")
        (reduction / "replay_case.json").write_text(json.dumps(replay), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
