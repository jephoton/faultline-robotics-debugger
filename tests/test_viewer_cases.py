"""HTTP contract for read-only, source-free saved cases."""
import json
import hashlib
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from robot_debug.case_io import import_m4
from robot_debug.case_store import register_case
from robot_debug.viewer.catalog import ArtifactCatalog
from robot_debug.viewer.server import make_handler, build_parser
from robot_debug.viewer.server import public_recipe
from test_case_io import fixture


class ViewerCaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        fixture(self.source)
        self.workspace = self.base / "cases"
        self.case = import_m4(self.source)
        self.web = Path(__file__).resolve().parents[1] / "src/robot_debug/viewer/web"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(ArtifactCatalog(self.source), self.web, self.workspace))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def get(self, path):
        try:
            with urlopen(self.url + path) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_empty_workspace_and_cli_override(self):
        self.assertEqual(self.get("/api/cases"), (200, {"cases": [], "warnings": []}))
        self.assertEqual(build_parser().parse_args(["--cases", "saved"]).cases, "saved")

    def test_registered_case_projects_safe_evidence_and_incomplete_recipe(self):
        register_case(self.case, self.source, self.workspace)
        case_id = self.case["case_id"]
        status, listed = self.get("/api/cases")
        self.assertEqual(status, 200)
        self.assertEqual(len(listed["cases"]), 1)
        self.assertEqual(listed["cases"][0]["case_id"], case_id)
        self.assertEqual(listed["cases"][0]["capabilities"]["exercised_replay"]["status"], "unverified")
        self.assertEqual(listed["cases"][0]["evidence"]["episodes"][0]["episode_id"], self.case["evidence"]["episodes"][0]["episode_id"])
        self.assertNotIn(str(self.source), json.dumps(listed))
        self.assertNotIn("source", listed["cases"][0])
        self.assertNotIn("aggregate", listed["cases"][0]["evidence"]["episodes"][0])
        detail_status, detail = self.get(f"/api/cases/{case_id}")
        self.assertEqual(detail_status, 200)
        self.assertEqual(detail["case"], listed["cases"][0])
        recipe_status, recipe = self.get(f"/api/cases/{case_id}/recipe")
        self.assertEqual(recipe_status, 200)
        self.assertIsNone(recipe["recipe"])
        self.assertIn("policy.checkpoint_revision", recipe["missing"])

    def test_missing_binding_and_changed_source_downgrade_claims(self):
        target = register_case(self.case, self.source, self.workspace)
        (target / "local-source.json").unlink()
        _, listed = self.get("/api/cases")
        self.assertEqual(listed["cases"][0]["capabilities"]["inspection"]["status"], "unavailable")
        self.assertEqual(listed["cases"][0]["capabilities"]["historical_failure"]["status"], "not-established")
        self.assertNotIn(str(self.source), json.dumps(listed))

    def test_changed_core_source_downgrades_without_writing(self):
        register_case(self.case, self.source, self.workspace)
        source_file = self.source / "failure-reduction/replay_case.json"
        data = json.loads(source_file.read_text())
        data["seed"] = 8
        source_file.write_text(json.dumps(data))
        before = source_file.read_bytes()
        _, detail = self.get(f"/api/cases/{self.case['case_id']}")
        self.assertEqual(detail["case"]["capabilities"]["inspection"]["status"], "unavailable")
        self.assertEqual(detail["case"]["capabilities"]["historical_failure"]["status"], "not-established")
        self.assertEqual(source_file.read_bytes(), before)

    def test_complete_recipe_contains_only_safe_structured_fields(self):
        proof = self.source / "failure-reduction/proof.txt"
        proof.write_text("proof")
        ref = {"path": "failure-reduction/proof.txt", "sha256": hashlib.sha256(proof.read_bytes()).hexdigest()}
        fields = ("policy.model_id", "policy.checkpoint_revision", "runtime.project_revision", "runtime.upstream_harness_revision", "runtime.simulator_image_digest")
        profile = {"schema_version": 1,
                   "policy": {"model_id": "opaque-model", "checkpoint_revision": "checkpoint"},
                   "runtime": {"project_revision": "revision", "upstream_harness_revision": "upstream", "simulator_image_digest": "sha256:" + "a" * 64},
                   "provenance": {key: ref for key in fields}}
        (self.source / "failure-reduction/profile.json").write_text(json.dumps(profile))
        case = import_m4(self.source, profile="failure-reduction/profile.json")
        register_case(case, self.source, self.workspace)
        status, payload = self.get(f"/api/cases/{case['case_id']}/recipe")
        self.assertEqual(status, 200)
        self.assertEqual(payload["missing"], [])
        self.assertEqual(set(payload["recipe"]), {"schema_version", "case_id", "task", "policy", "runtime", "perturbation", "protocol"})
        self.assertNotIn("provenance", json.dumps(payload))
        self.assertNotIn(str(self.source), json.dumps(payload))

    def test_unbound_case_does_not_expose_untrusted_freeform_metadata(self):
        target = register_case(self.case, self.source, self.workspace)
        path = target / "case.json"
        saved = json.loads(path.read_text())
        saved["measurements"]["cost"] = {"private_config": str(self.source)}
        saved["limitations"] = [str(self.source)]
        saved["evidence"]["lineage"] = [{"rectangle": {"x": 0, "y": 0, "width": 1, "height": 1}, "edge": {"private_config": str(self.source)}, "delta": 1}]
        path.write_text(json.dumps(saved))
        (target / "local-source.json").unlink()
        _, payload = self.get(f"/api/cases/{self.case['case_id']}")
        self.assertNotIn(str(self.source), payload["case"].get("limitations", []))
        self.assertNotEqual(payload["case"]["measurements"].get("cost"), {"private_config": str(self.source)})
        self.assertEqual(payload["case"]["evidence"].get("lineage"), [])

    def test_redacted_required_pin_makes_public_recipe_incomplete(self):
        case = dict(self.case)
        case["policy"] = dict(case["policy"], model_id=str(self.source))
        case["capabilities"] = dict(case["capabilities"], replay_recipe={"status": "complete", "missing": []})
        recipe = public_recipe(case)
        self.assertIsNone(recipe["recipe"])
        self.assertIn("policy.model_id", recipe["missing"])

    def test_malformed_unbound_evidence_is_an_unavailable_entry(self):
        target = register_case(self.case, self.source, self.workspace)
        path = target / "case.json"
        saved = json.loads(path.read_text())
        saved["evidence"]["episodes"] = [None]
        saved["evidence"]["media_counts"] = []
        path.write_text(json.dumps(saved))
        (target / "local-source.json").unlink()
        status, payload = self.get("/api/cases")
        self.assertEqual(status, 200)
        self.assertEqual(payload["cases"][0]["status"], "unavailable")
        self.assertEqual(self.get(f"/api/cases/{self.case['case_id']}/recipe")[1]["recipe"], None)

    def test_nested_unbound_episode_metadata_is_never_projected(self):
        target = register_case(self.case, self.source, self.workspace)
        path = target / "case.json"
        saved = json.loads(path.read_text())
        saved["evidence"]["episodes"] = [{"instruction": {"private_config": str(self.source)}}]
        path.write_text(json.dumps(saved))
        (target / "local-source.json").unlink()
        status, payload = self.get("/api/cases")
        self.assertEqual(status, 200)
        self.assertEqual(payload["cases"][0]["status"], "unavailable")

    def test_corrupt_entry_is_contained_and_ids_are_strict(self):
        register_case(self.case, self.source, self.workspace)
        (self.workspace / "bad-name").mkdir()
        (self.workspace / ("a" * 64)).mkdir()
        _, listed = self.get("/api/cases")
        self.assertEqual(len(listed["cases"]), 3)
        self.assertTrue(any(case.get("status") == "unavailable" for case in listed["cases"]))
        self.assertEqual(self.get("/api/cases/not-an-id")[0], 400)
        self.assertEqual(self.get("/api/cases/" + "A" * 64)[0], 400)
        self.assertEqual(self.get("/api/cases/" + "f" * 64)[0], 404)


if __name__ == "__main__":
    unittest.main()
