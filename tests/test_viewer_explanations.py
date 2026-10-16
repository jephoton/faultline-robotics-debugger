"""Read-only viewer integration for evidence-bound explanation sidecars."""

import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from robot_debug.case_io import import_m4
from robot_debug.case_store import register_case
from robot_debug.evidence_packet import make_evidence_packet
from robot_debug.explanation import build_offline_report
from robot_debug.explanation_store import make_stored_report, store_report
from robot_debug.viewer.catalog import ArtifactCatalog
from robot_debug.viewer.server import make_handler
from tests.test_case_io import fixture


class ViewerExplanationServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        fixture(self.source)
        self.workspace = self.base / "workspace"
        self.case = import_m4(self.source)
        register_case(self.case, self.source, self.workspace)
        self.packet = make_evidence_packet(self.case)
        handler = make_handler(ArtifactCatalog(self.source), self.workspace)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:{}".format(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def provenance(self, *, created_at="2026-10-05T12:34:56Z", live=False, **changes):
        value = {
            "source": "offline", "provider": None, "model": None, "endpoint": None,
            "created_at": created_at, "request_status": "offline", "error_code": None,
            "latency_seconds": None, "prompt_tokens": None, "completion_tokens": None,
            "estimated_cost_usd": None, "billed_cost_usd": None, "reservation_usd": 0,
        }
        if live:
            value.update({
                "source": "live", "provider": "nebius-token-factory",
                "model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
                "endpoint": "https://api.tokenfactory.nebius.com/v1/",
                "request_status": "completed", "latency_seconds": 1.25,
                "prompt_tokens": 100, "completion_tokens": 50,
                "estimated_cost_usd": 0.000018, "reservation_usd": 0.02,
            })
        value.update(changes)
        return value

    def save(self, report=None, provenance=None):
        record = make_stored_report(
            self.case["case_id"], self.packet,
            report or build_offline_report(self.packet),
            provenance or self.provenance(),
        )
        store_report(self.workspace, record)
        return record

    def request(self, path, method="GET"):
        request = Request(self.url + path, method=method)
        try:
            with urlopen(request) as response:
                return response.status, dict(response.headers.items()), response.read()
        except HTTPError as error:
            return error.code, dict(error.headers.items()), error.read()

    def endpoint(self):
        return "/api/cases/{}/explanations".format(self.case["case_id"])

    def test_get_returns_exact_history_for_offline_valid_and_rejected_reports(self):
        offline = self.save()
        evidence_id = self.packet["episodes"][0]["evidence_id"]
        response = json.dumps({
            "schema_version": 1,
            "observations": [{"text": "Reported outcome differs.", "evidence_ids": [evidence_id]}],
            "hypotheses": [], "limitations": ["Human review remains required."],
        })
        valid = self.save(build_offline_report(self.packet, response), self.provenance(
            created_at="2026-10-05T12:34:58Z", live=True))
        rejected = self.save(build_offline_report(self.packet, "malformed"), self.provenance(
            created_at="2026-10-05T12:34:57Z", live=True,
            request_status="invalid_response", error_code="invalid_response",
            prompt_tokens=None, completion_tokens=None, estimated_cost_usd=None))

        with patch("urllib.request.urlopen", side_effect=AssertionError("external network used")):
            status, headers, body = self.request(self.endpoint())

        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(json.loads(body), {"reports": [offline, rejected, valid], "warnings": []})

    def test_get_isolates_corrupt_report_and_stale_or_missing_case(self):
        record = self.save()
        reports = self.workspace / self.case["case_id"] / "reports"
        (reports / ("f" * 64 + ".json")).write_text("{bad", encoding="utf-8")

        status, _, body = self.request(self.endpoint())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {
            "reports": [record],
            "warnings": ["one or more report records are unavailable or invalid"],
        })

        (self.source / "failure-reduction" / "replay_case.json").unlink()
        status, _, body = self.request(self.endpoint())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {
            "reports": [], "warnings": ["case evidence is unavailable or changed"],
        })

        missing = "0" * 64
        status, _, body = self.request("/api/cases/{}/explanations".format(missing))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {
            "reports": [], "warnings": ["case evidence is unavailable or changed"],
        })

    def test_endpoint_rejects_bad_ids_and_has_no_http_write_method(self):
        record = self.save()
        report_path = self.workspace / self.case["case_id"] / "reports" / (record["report_id"] + ".json")
        before = report_path.read_bytes()

        bad_status, _, _ = self.request("/api/cases/ABC/explanations")
        post_status, _, _ = self.request(self.endpoint(), method="POST")

        self.assertEqual(bad_status, 400)
        self.assertIn(post_status, (405, 501))
        self.assertEqual(report_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
