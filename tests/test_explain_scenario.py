"""The scenario commands of scripts/explain_case.py, with fakes only (no network, no credentials)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from robot_debug import scenario_packet as sp
from tests.test_scenario_packet import FakeTransport, KEY, partial_case, response

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "explain_case.py"


def load_script():
    spec = importlib.util.spec_from_file_location("explain_case_scenario_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ScenarioExplainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cli = load_script()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.case = partial_case()
        self.case_path = self.base / "case.json"
        self.case_path.write_text(json.dumps(self.case), encoding="utf-8")
        self.reservations = []
        self.transport = FakeTransport()

    def deps(self, transport=None):
        from robot_debug import token_factory as tf

        transport = transport or self.transport

        def reserve(root, case_id, packet_id):
            self.reservations.append((Path(root), case_id, packet_id))
            return {}

        return self.cli.ScenarioDependencies(
            load_api_key=lambda env_file: KEY,
            preflight=lambda api_key: {},
            reserve_pilot=reserve,
            request_scenario_interpretation=lambda packet, api_key: tf.request_scenario_interpretation(
                packet, api_key, transport))

    def test_prepare_is_offline_and_reports_the_packet(self):
        out = self.base / "packet.json"
        result = self.cli.run_scenario_prepare(self.case_path, out)
        self.assertEqual(self.case["case_id"], result["case_id"])
        self.assertRegex(result["packet_id"], r"^[0-9a-f]{64}$")
        self.assertIn("c7", result["evidence_ids"])
        self.assertEqual("necessary_not_sufficient", result["measured_verdict"])
        packet = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(sp.scenario_packet_identity(packet), result["packet_id"])
        with self.assertRaises(self.cli.ExplainCaseError):
            self.cli.run_scenario_prepare(self.case_path, out)

    def test_prepare_through_the_command_line_needs_no_key(self):
        env = {key: value for key, value in os.environ.items() if key != "NEBIUS_API_KEY"}
        env["PYTHONPATH"] = str(ROOT / "src")
        done = subprocess.run([sys.executable, str(SCRIPT), "scenario-prepare", "--case", str(self.case_path)],
                              cwd=self.base, capture_output=True, text=True, env=env)
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual(self.case["case_id"], json.loads(done.stdout)["case_id"])

    def test_a_bad_case_file_is_refused_with_a_fixed_message(self):
        for text in ("{}", "[1]", "not json", json.dumps(dict(self.case, kind="occlusion"))):
            path = self.base / "bad.json"
            path.write_text(text, encoding="utf-8")
            with self.subTest(text=text[:20]), self.assertRaises(self.cli.ExplainCaseError) as caught:
                self.cli.run_scenario_prepare(path)
            self.assertEqual("invalid scenario case", str(caught.exception))
        with self.assertRaises(self.cli.ExplainCaseError):
            self.cli.run_scenario_prepare(self.base / "absent.json")

    def test_live_makes_one_reserved_attempt_and_stores_the_validated_interpretation(self):
        out = self.base / "explanation.json"
        summary = self.cli.run_scenario_live(self.case_path, out, None, "s-01", deps=self.deps())
        self.assertEqual("validated-structure", summary["interpretation_status"])
        self.assertEqual(1, len(self.transport.calls))
        self.assertEqual([(self.cli.SCENARIO_ATTEMPTS_ROOT / "s-01", self.case["case_id"], summary["packet_id"])],
                         self.reservations)
        record = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual("scenario_explanation", record["kind"])
        self.assertEqual(["c7"], record["interpretation"]["observations"][0]["evidence_ids"])
        self.assertEqual("completed", record["provenance"]["request_status"])
        self.assertIn("human review", record["disclaimer"])
        self.assertNotIn(KEY, out.read_text(encoding="utf-8"))

    def test_a_rejected_or_failed_response_is_stored_without_an_interpretation(self):
        for transport, status in (
            (FakeTransport(content=response(observations=[{"text": "x", "evidence_ids": ["c99"]}])), "absent"),
            (FakeTransport(error=TimeoutError("late")), "absent"),
        ):
            out = self.base / "{}.json".format(len(list(self.base.iterdir())))
            with self.subTest(status=status):
                summary = self.cli.run_scenario_live(self.case_path, out, None, "s-02", deps=self.deps(transport))
                self.assertEqual(status, summary["interpretation_status"])
                self.assertIsNone(json.loads(out.read_text(encoding="utf-8"))["interpretation"])

    def test_labels_and_existing_outputs_are_checked_before_any_reservation(self):
        out = self.base / "explanation.json"
        for label in ("", "S-01", "../x", "a" * 33, "s 1"):
            with self.subTest(label=label), self.assertRaises(self.cli.ExplainCaseError):
                self.cli.run_scenario_live(self.case_path, out, None, label, deps=self.deps())
        out.write_text("{}", encoding="utf-8")
        with self.assertRaises(self.cli.ExplainCaseError):
            self.cli.run_scenario_live(self.case_path, out, None, "s-03", deps=self.deps())
        self.assertEqual([], self.reservations)
        self.assertEqual([], self.transport.calls)


if __name__ == "__main__":
    unittest.main()
