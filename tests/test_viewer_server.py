import json
import os
import subprocess
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
        for token in (
            "perturbationPosition",
            "perturbationPosition(episode)",
            "perturbationPosition(perturbed)",
            "isPerturbed",
            "matchesPrimary",
            "candidates.find(isPerturbed)",
            "visible = displayEpisodes",
            'typeof fault.x === "number"',
            'typeof fault.y === "number"',
            "x=",
            "y=",
        ):
            self.assertIn(token, app)
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

    def test_case_workbench_assets_expose_read_only_journey(self):
        _, _, page_body = self.get("/")
        _, _, app_body = self.get("/app.js")
        page = page_body.decode("utf-8")
        app = app_body.decode("utf-8")
        self.assertLess(page.index('id="case-workbench"'), page.index('id="comparison-conclusion"'))
        for identifier in ("case-select", "case-status", "case-inspection", "case-recipe-status",
                           "case-replay", "case-history", "case-prerequisites", "case-measurements",
                           "case-recipe", "case-export"):
            self.assertIn(f'id="{identifier}"', page)
        for caption in ("Current saved source", "Required inputs", "Fresh execution", "Recorded outcome"):
            self.assertIn(caption, page)
        self.assertIn('value="all"', page)
        self.assertIn('aria-live="polite"', page)
        for token in ("/api/cases", "refreshCases", "caseEpisodeMatches", "case_id", "manage_cases.py export",
                      "textContent", "source_reported_elapsed_seconds", "physical_episode_count",
                      "valid_episode_count"):
            self.assertIn(token, app)
        self.assertNotIn("innerHTML", app)
        self.assertIn("selected.evidence.lineage", app)
        self.assertIn("savedRoleFor", app)
        self.assertIn("Validated recipe unavailable", app)
        self.assertIn("caseSignature", app)
        self.assertIn("saved.episode_id === episode.episode_id", app)
        self.assertNotIn("saved.stage === episode.run_name", app)
        self.assertIn("<case-workspace-outside-source-root>", app)

    def test_case_javascript_rejects_ambiguous_links_and_handles_unavailable_entry(self):
        script = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
let source = fs.readFileSync(process.argv[1], 'utf8');
source = source.replace(/^refreshCatalog\(\)\.catch\(showFatalError\);$/m, '');
const element = { addEventListener() {}, dataset: {} };
const context = { document: { getElementById() { return element; } }, window: { setInterval() {} } };
vm.runInNewContext(source + '\nglobalThis.exposed = { caseEpisodeMatches, caseSignature };', context);
const { caseEpisodeMatches, caseSignature } = context.exposed;
assert.strictEqual(caseEpisodeMatches({ episode_id: 'saved', stage: 'parent', task_id: 1, reset_index: 0 },
  { episode_id: 'other', run_name: 'parent', task_id: 1, episode_index: 0 }), false);
assert.strictEqual(caseEpisodeMatches({ episode_id: 'saved' }, { episode_id: 'saved' }), true);
assert.strictEqual(caseSignature({ case_id: 'a'.repeat(64), status: 'unavailable' }), 'a'.repeat(64) + ':unavailable');
"""
        asset = self.web_root / "app.js"
        result = subprocess.run([r"C:\Program Files\nodejs\node.exe", "-e", script, str(asset)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_case_select_container_can_shrink_on_narrow_screens(self):
        _, _, body = self.get("/styles.css")
        css = body.decode("utf-8")
        self.assertIn(".case-heading > div { min-width: 0; max-width: 100%; }", css)

    def test_javascript_asset_uses_stable_content_type(self):
        with patch.object(
            viewer_server.mimetypes,
            "guess_type",
            return_value=("application/javascript", None),
        ):
            status, headers, _ = self.get("/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/javascript; charset=utf-8")

    def test_reduction_lineage_fixture_contract_is_present_in_viewer_assets(self):
        reduction = self.root / "failure-reduction"
        reduction.mkdir()
        (reduction / "session_summary.json").write_text(
            json.dumps({
                "geometry": {
                    "parent": {"area": 0.25},
                    "final": {"area": 0.1875},
                },
                "lineage": [{"rectangle": {"x": 0.5, "y": 0.0, "width": 0.375, "height": 0.5}}],
                "stop_reason": "reduced_failure_with_nominal_controls",
            }), encoding="utf-8"
        )
        (reduction / "replay_case.json").write_text(
            json.dumps({"acceptance_rule": {"failures": 4, "attempts": 5}}),
            encoding="utf-8",
        )

        status, _, body = self.get("/app.js")

        self.assertEqual(status, 200)
        app = body.decode("utf-8")
        for token in (
            "replay_case.json",
            "session_summary.json",
            "accepted lineage",
            "reduction-lineage",
            "Parent area",
            "Certification",
        ):
            self.assertIn(token, app)

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
