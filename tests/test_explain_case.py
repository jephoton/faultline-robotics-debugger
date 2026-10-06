"""Guarded CLI orchestration for evidence-bound explanation reports."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from robot_debug.case_io import import_m4
from robot_debug.case_store import inspect_case, register_case
from robot_debug.cases import case_identity
from robot_debug.evidence_packet import make_evidence_packet, packet_identity
from robot_debug.explanation_store import read_case_reports
from robot_debug.token_factory import MODEL, TokenFactoryError, reserve_pilot
from tests.test_case_io import fixture


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "explain_case.py"


def load_script():
    spec = importlib.util.spec_from_file_location("explain_case_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def live_provenance(status="completed", error_code=None):
    return {
        "source": "live", "provider": "nebius-token-factory", "model": MODEL,
        "endpoint": "https://api.tokenfactory.nebius.com/v1/",
        "created_at": "2026-10-05T12:34:56Z", "request_status": status,
        "error_code": error_code, "latency_seconds": 0.25,
        "prompt_tokens": 100 if status == "completed" else None,
        "completion_tokens": 20 if status == "completed" else None,
        "estimated_cost_usd": 0.0000108 if status == "completed" else None,
        "billed_cost_usd": None, "reservation_usd": 0.02,
    }


class ExplainCaseCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        fixture(self.source)
        self.workspace = self.base / "workspace"
        self.case = import_m4(self.source)
        register_case(self.case, self.source, self.workspace)
        self.case_id = self.case["case_id"]

    def tearDown(self):
        self.tmp.cleanup()

    def invoke(self, *args, env=None):
        clean_env = {key: value for key, value in os.environ.items()
                     if key != "NEBIUS_API_KEY"}
        clean_env["PYTHONPATH"] = str(ROOT / "src")
        if env:
            clean_env.update(env)
        return subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, args)], cwd=self.base,
            capture_output=True, text=True, env=clean_env,
        )

    def test_prepare_subprocess_succeeds_without_api_key(self):
        result = self.invoke("prepare", "--workspace", self.workspace,
                             "--case-id", self.case_id)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(set(output), {"case_id", "report_id", "interpretation_status",
                                      "request_status", "estimated_cost_usd"})
        self.assertEqual(output["case_id"], self.case_id)
        self.assertEqual(output["interpretation_status"], "absent")
        self.assertEqual(output["request_status"], "offline")
        self.assertIsNone(output["estimated_cost_usd"])
        self.assertEqual(len(read_case_reports(self.workspace, self.case_id)["reports"]), 1)

    def test_live_orders_fresh_checks_catalog_reservation_post_and_store(self):
        module = load_script()
        packet = make_evidence_packet(inspect_case(self.workspace, self.case_id))
        response = json.dumps({
            "schema_version": 1,
            "observations": [{"text": "Observed outcome.",
                              "evidence_ids": [packet["episodes"][0]["evidence_id"]]}],
            "hypotheses": [], "limitations": ["Human review required."],
        })
        events = []

        def inspect(workspace, case_id):
            events.append("inspect")
            return inspect_case(workspace, case_id)

        deps = module.Dependencies(
            inspect_case=inspect,
            load_api_key=lambda env_file: events.append("key") or "secret",
            preflight=lambda key: events.append("catalog") or {},
            reserve_pilot=lambda root, case_id, packet_id:
                events.append(("reserve", root, case_id, packet_id)) or {},
            request_interpretation=lambda sent, key:
                events.append("post") or {"response_json": response,
                                          "provenance": live_provenance()},
            store_report=lambda workspace, record: events.append("store") or Path("report"),
        )
        output = module.run_live(self.workspace, self.case_id, None, deps=deps)
        self.assertEqual([event if isinstance(event, str) else event[0] for event in events],
                         ["inspect", "key", "catalog", "inspect", "reserve", "post",
                          "inspect", "store"])
        reservation = events[4]
        self.assertEqual(reservation[1], ROOT / "artifacts" / "m5-nemotron-pilot")
        self.assertEqual(reservation[2:], (self.case_id, packet_identity(packet)))
        self.assertEqual(output["interpretation_status"], "validated-structure")
        self.assertEqual(output["request_status"], "completed")

    def test_failed_catalog_never_reserves_or_posts(self):
        module = load_script()
        calls = []
        deps = module.Dependencies(
            inspect_case=inspect_case,
            load_api_key=lambda env_file: "secret",
            preflight=lambda key: (_ for _ in ()).throw(TokenFactoryError("catalog_missing")),
            reserve_pilot=lambda *args: calls.append("reserve"),
            request_interpretation=lambda *args: calls.append("post"),
            store_report=lambda *args: calls.append("store"),
        )
        with self.assertRaisesRegex(TokenFactoryError, "^catalog_missing$"):
            module.run_live(self.workspace, self.case_id, None, deps=deps)
        self.assertEqual(calls, [])

    def test_changed_case_before_reservation_never_reserves_or_posts(self):
        module = load_script()
        first = inspect_case(self.workspace, self.case_id)
        changed = json.loads(json.dumps(first))
        changed["perturbation"]["rectangle"]["width"] -= 0.01
        changed["case_id"] = case_identity(changed)
        cases = iter((first, changed))
        calls = []
        deps = module.Dependencies(
            inspect_case=lambda *_: next(cases), load_api_key=lambda _: "secret",
            preflight=lambda _: {}, reserve_pilot=lambda *args: calls.append("reserve"),
            request_interpretation=lambda *args: calls.append("post"),
            store_report=lambda *args: calls.append("store"),
        )
        with self.assertRaisesRegex(module.ExplainCaseError,
                                    "^case evidence changed during explanation$"):
            module.run_live(self.workspace, self.case_id, None, deps=deps)
        self.assertEqual(calls, [])

    def test_changed_case_after_response_retains_reservation_without_storing(self):
        module = load_script()
        first = inspect_case(self.workspace, self.case_id)
        changed = json.loads(json.dumps(first))
        changed["perturbation"]["rectangle"]["width"] -= 0.01
        changed["case_id"] = case_identity(changed)
        cases = iter((first, first, changed))
        calls = []
        deps = module.Dependencies(
            inspect_case=lambda *_: next(cases), load_api_key=lambda _: "secret",
            preflight=lambda _: {}, reserve_pilot=lambda *args: calls.append("reserve"),
            request_interpretation=lambda *args: calls.append("post") or {
                "response_json": None,
                "provenance": live_provenance("transport_error", "timeout")},
            store_report=lambda *args: calls.append("store"),
        )
        with self.assertRaisesRegex(module.ExplainCaseError,
                                    "^case evidence changed during explanation$"):
            module.run_live(self.workspace, self.case_id, None, deps=deps)
        self.assertEqual(calls, ["reserve", "post"])

    def test_existing_reservation_prevents_a_second_post(self):
        module = load_script()
        pilot = self.base / "pilot"
        posts = []

        def reserve(_fixed_root, case_id, packet_id):
            return reserve_pilot(pilot, case_id, packet_id)

        deps = module.Dependencies(
            inspect_case=inspect_case, load_api_key=lambda _: "secret",
            preflight=lambda _: {}, reserve_pilot=reserve,
            request_interpretation=lambda *args: posts.append("post") or {
                "response_json": None,
                "provenance": live_provenance("transport_error", "timeout")},
            store_report=lambda workspace, record: Path("report"),
        )
        module.run_live(self.workspace, self.case_id, None, deps=deps)
        with self.assertRaisesRegex(TokenFactoryError, "^reservation_exists$"):
            module.run_live(self.workspace, self.case_id, None, deps=deps)
        self.assertEqual(posts, ["post"])
        self.assertTrue((pilot / "reservation.json").is_file())

    def test_live_transport_failure_stores_factual_fallback(self):
        module = load_script()
        records = []
        deps = module.Dependencies(
            inspect_case=inspect_case, load_api_key=lambda _: "secret",
            preflight=lambda _: {}, reserve_pilot=lambda *args: {},
            request_interpretation=lambda *args: {
                "response_json": None,
                "provenance": live_provenance("transport_error", "timeout")},
            store_report=lambda workspace, record: records.append(record) or Path("report"),
        )
        output = module.run_live(self.workspace, self.case_id, None, deps=deps)
        self.assertEqual(output["interpretation_status"], "absent")
        self.assertEqual(output["request_status"], "transport_error")
        self.assertEqual(records[0]["report"]["interpretation_status"], "absent")

    def test_preflight_is_get_only_and_stdout_is_bounded(self):
        module = load_script()
        calls = []
        deps = module.Dependencies(
            inspect_case=inspect_case,
            load_api_key=lambda path: calls.append(("key", path)) or "secret",
            preflight=lambda key: calls.append(("get", key)) or {
                "model": MODEL, "endpoint": "private"},
            reserve_pilot=reserve_pilot,
            request_interpretation=lambda *args: calls.append(("post", args)),
            store_report=lambda *args: None,
        )
        output = module.run_preflight(Path("chosen.env"), deps=deps)
        self.assertEqual(output, {"request_status": "ready"})
        self.assertEqual(calls, [("key", Path("chosen.env")), ("get", "secret")])

    def test_bad_arguments_and_failures_are_safe_json(self):
        bad = self.invoke("live", "--workspace", self.workspace, "--case-id", self.case_id,
                          "--endpoint", "https://attacker.invalid")
        self.assertEqual(bad.returncode, 2)
        self.assertEqual(json.loads(bad.stdout), {"error": "invalid arguments"})
        self.assertNotIn("Traceback", bad.stderr)
        self.assertNotIn("attacker", bad.stdout)

        missing = self.invoke("prepare", "--workspace", self.base / "private-workspace",
                              "--case-id", "0" * 64)
        self.assertEqual(missing.returncode, 2)
        self.assertEqual(json.loads(missing.stdout), {"error": "explanation operation failed"})
        self.assertNotIn(str(self.base), missing.stdout + missing.stderr)
        self.assertNotIn("Traceback", missing.stderr)

    def test_cli_exposes_no_unsafe_override_flags(self):
        for flag in ("--endpoint", "--model", "--cap", "--pilot-root", "--mock-live"):
            result = self.invoke("live", "--workspace", self.workspace,
                                 "--case-id", self.case_id, flag, "value")
            self.assertEqual(json.loads(result.stdout), {"error": "invalid arguments"})


if __name__ == "__main__":
    unittest.main()
