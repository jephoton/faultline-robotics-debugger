"""Offline interpretation validation and factual fallback contract."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from robot_debug.case_io import import_m4
from robot_debug.evidence_packet import EvidencePacketError, make_evidence_packet, packet_identity
from robot_debug.explanation import (
    ExplanationValidationError, build_offline_report, deterministic_summary,
    validate_explanation,
)
from tests.test_case_io import fixture


class ExplanationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        fixture(Path(self.tmp.name))
        self.packet = make_evidence_packet(import_m4(Path(self.tmp.name)))
        self.eid = self.packet["episodes"][0]["evidence_id"]

    def tearDown(self):
        self.tmp.cleanup()

    def response(self, **changes):
        value = {"schema_version": 1, "observations": [{"text": "Reported outcome.", "evidence_ids": [self.eid]}],
                 "hypotheses": [], "limitations": ["Human review required."]}
        value.update(changes)
        return json.dumps(value)

    def test_unknown_citation_rejects_interpretation_but_keeps_facts(self):
        original = copy.deepcopy(self.packet)
        with patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            absent = build_offline_report(self.packet)
            rejected = build_offline_report(self.packet, self.response(observations=[{
                "text": "Unsupported citation.", "evidence_ids": ["ffffffffffffffff"]}]))
        self.assertEqual(rejected["interpretation_status"], "rejected")
        self.assertIsNone(rejected["interpretation"])
        self.assertEqual(rejected["error_code"], "invalid_explanation")
        self.assertEqual(rejected["facts"], absent["facts"])
        self.assertEqual(rejected["packet_id"], absent["packet_id"])
        self.assertEqual(self.packet, original)

    def test_counts_preserve_raw_timeout_and_gate_category(self):
        packet = copy.deepcopy(self.packet)
        packet["episodes"][0].update(raw_outcome="episode_timeout", gate_outcome="policy_failure")
        facts = deterministic_summary(packet)
        self.assertEqual(set(facts), {"total_episodes", "counts_by_role", "reduced_mask_area_fraction"})
        self.assertEqual(facts["total_episodes"], 14)
        self.assertEqual(facts["reduced_mask_area_fraction"], .1875)
        self.assertEqual(set(facts["counts_by_role"]), {"nominal", "parent", "reduced", "other"})
        for counts in facts["counts_by_role"].values():
            self.assertEqual(set(counts), {"raw_outcomes", "gate_outcomes"})
            self.assertEqual(set(counts["raw_outcomes"]), {"success", "task_failure", "episode_timeout", "infrastructure_error"})
            self.assertEqual(set(counts["gate_outcomes"]), {"success", "policy_failure", "infrastructure_error"})
        self.assertEqual(sum(row["raw_outcomes"]["episode_timeout"] for row in facts["counts_by_role"].values()), 1)
        self.assertEqual(sum(sum(row["raw_outcomes"].values()) for row in facts["counts_by_role"].values()), 14)
        self.assertEqual(sum(sum(row["gate_outcomes"].values()) for row in facts["counts_by_role"].values()), 14)

    def test_absent_valid_rejected_reports_share_facts_and_disclaimer(self):
        original = copy.deepcopy(self.packet)
        absent = build_offline_report(self.packet)
        valid = build_offline_report(self.packet, self.response())
        rejected = build_offline_report(self.packet, "SECRET invalid")
        self.assertEqual(set(absent), {"schema_version", "packet_id", "facts", "interpretation_status", "interpretation", "error_code", "disclaimer"})
        self.assertEqual([r["interpretation_status"] for r in (absent, valid, rejected)],
                         ["absent", "validated-structure", "rejected"])
        self.assertEqual([r["error_code"] for r in (absent, valid, rejected)], [None, None, "invalid_explanation"])
        self.assertIsNone(absent["interpretation"])
        self.assertEqual(valid["interpretation"]["observations"][0]["text"], "Reported outcome.")
        self.assertIsNone(rejected["interpretation"])
        self.assertEqual(absent["packet_id"], packet_identity(self.packet))
        self.assertTrue(all(r["facts"] == absent["facts"] for r in (valid, rejected)))
        self.assertTrue(all(r["disclaimer"] == absent["disclaimer"] for r in (valid, rejected)))
        self.assertNotIn("SECRET", json.dumps(rejected))
        self.assertEqual(self.packet, original)

    def test_valid_structure_does_not_certify_fabricated_prose(self):
        response = self.response(observations=[{"text": "This proves a cause.", "evidence_ids": [self.eid]}])
        report = build_offline_report(self.packet, response)
        self.assertEqual(report["interpretation_status"], "validated-structure")
        self.assertIn("human review", report["disclaimer"].lower())
        self.assertNotIn("confirmed", json.dumps(report))

    def test_empty_lists_valid_and_result_detached(self):
        valid = validate_explanation(self.response(observations=[], hypotheses=[], limitations=[]), self.packet)
        self.assertEqual(valid, {"schema_version": 1, "observations": [], "hypotheses": [], "limitations": []})
        report = build_offline_report(self.packet, self.response())
        report["facts"]["counts_by_role"]["nominal"]["raw_outcomes"]["success"] = 999
        report["interpretation"]["observations"][0]["evidence_ids"].append("ffffffffffffffff")
        fresh = build_offline_report(self.packet, self.response())
        self.assertNotEqual(fresh["facts"], report["facts"])
        self.assertEqual(fresh["interpretation"]["observations"][0]["evidence_ids"], [self.eid])

    def test_rejects_malformed_json_fields_text_and_citations(self):
        invalid = [
            "", "```json\n" + self.response() + "\n```", self.response() + " trailing",
            '{"schema_version":1,"schema_version":1,"observations":[],"hypotheses":[],"limitations":[]}',
            self.response(schema_version=True), self.response(extra="SECRET"),
            self.response(observations={}), self.response(observations=[{"text": "x"}]),
            self.response(observations=[{"text": "x", "evidence_ids": [self.eid], "extra": 1}]),
            self.response(observations=[{"text": "x", "evidence_ids": []}]),
            self.response(observations=[{"text": "x", "evidence_ids": [self.eid, self.eid]}]),
            self.response(observations=[{"text": "x", "evidence_ids": ["ffffffffffffffff"]}]),
            self.response(observations=[{"text": "   ", "evidence_ids": [self.eid]}]),
            self.response(observations=[{"text": "line\nbreak", "evidence_ids": [self.eid]}]),
            self.response(observations=[{"text": "x" * 601, "evidence_ids": [self.eid]}]),
            self.response(observations=[{"text": "x", "evidence_ids": [self.eid]}] * 5),
            self.response(hypotheses=[{"text": "x", "evidence_ids": [self.eid]}] * 4),
            self.response(limitations=["x"] * 7),
            self.response(limitations=[" "]), self.response(limitations=["two\nlines"]),
            self.response(limitations=["x" * 601]),
            self.response(limitations=["\ud800"]),
            self.response(limitations=["x" * 17000]),
            self.response(limitations=[{"nested": "x"}]),
            self.response().replace("[]", "[NaN]", 1),
            "[" * 300 + "0" + "]" * 300,
        ]
        for response in invalid:
            with self.subTest(response=response[:80]), self.assertRaisesRegex(ExplanationValidationError, "^invalid explanation$"):
                validate_explanation(response, self.packet)

    def test_all_python_line_separators_reject_every_text_field_and_preserve_facts(self):
        absent = build_offline_report(self.packet)
        separators = "\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029"
        for separator in separators:
            for field in ("observations", "hypotheses", "limitations"):
                with self.subTest(separator=hex(ord(separator)), field=field):
                    text = f"first{separator}second"
                    if field == "limitations":
                        response = self.response(limitations=[text])
                    else:
                        response = self.response(**{field: [{"text": text, "evidence_ids": [self.eid]}]})
                    with self.assertRaisesRegex(ExplanationValidationError, "^invalid explanation$"):
                        validate_explanation(response, self.packet)
                    report = build_offline_report(self.packet, response)
                    self.assertEqual(report["interpretation_status"], "rejected")
                    self.assertIsNone(report["interpretation"])
                    self.assertEqual(report["error_code"], "invalid_explanation")
                    self.assertEqual(report["facts"], absent["facts"])

    def test_bad_packet_raises_packet_error_before_response_fallback(self):
        packet = copy.deepcopy(self.packet); packet["episodes"] = []
        for response in (None, "SECRET invalid"):
            with self.assertRaises(EvidencePacketError):
                build_offline_report(packet, response)
        with self.assertRaises(EvidencePacketError):
            validate_explanation("invalid", packet)


if __name__ == "__main__": unittest.main()
