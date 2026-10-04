"""Allowlisted offline evidence packet contract."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from robot_debug.case_io import import_m4
from tests.test_case_io import fixture
from robot_debug.evidence_packet import (
    EvidencePacketError, make_evidence_packet, packet_identity,
    validate_evidence_packet,
)


class EvidencePacketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        fixture(Path(self.tmp.name))
        self.case = import_m4(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_injected_instruction_is_excluded_without_mutating_source(self):
        self.case["evidence"]["episodes"][0]["instruction"] = "--token SECRET"
        original = copy.deepcopy(self.case)
        with patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            packet = make_evidence_packet(self.case)
        self.assertEqual(self.case, original)
        self.assertEqual(set(packet), {"schema_version", "task", "reduced_mask", "episodes"})
        self.assertNotIn("SECRET", json.dumps(packet))
        self.assertNotIn("instruction", json.dumps(packet))
        self.assertEqual(len(packet["episodes"]), 14)

    def test_projection_is_sorted_private_and_detached(self):
        self.case["policy"]["provenance"]["private"] = "SECRET"
        self.case["evidence"]["episodes"][0]["video"] = {"path": "private/SECRET"}
        self.case["measurements"]["cost"] = "SECRET"
        packet = make_evidence_packet(self.case)
        self.assertEqual(list(packet["task"]), ["suite", "task_id", "reset_index"])
        self.assertEqual(set(packet["reduced_mask"]), {"family", "rectangle", "fill_value"})
        self.assertEqual(packet["reduced_mask"]["fill_value"], [0, 0, 0])
        self.assertEqual([e["evidence_id"] for e in packet["episodes"]], sorted(e["evidence_id"] for e in packet["episodes"]))
        self.assertTrue(all(set(e) == {"evidence_id", "role", "raw_outcome", "gate_outcome"} for e in packet["episodes"]))
        self.assertNotIn("SECRET", json.dumps(packet))
        self.assertNotIn("aggregate", json.dumps(packet))
        packet["episodes"][0]["role"] = "other"
        self.assertNotEqual(self.case["evidence"]["episodes"][0]["role"], "other")

    def test_order_independent_identity_and_validator_detachment(self):
        packet = make_evidence_packet(self.case)
        reversed_packet = copy.deepcopy(packet)
        reversed_packet["episodes"].reverse()
        self.assertEqual(packet_identity(packet), packet_identity(reversed_packet))
        validated = validate_evidence_packet(reversed_packet)
        self.assertEqual(validated, packet)
        validated["episodes"][0]["role"] = "other"
        self.assertNotEqual(reversed_packet["episodes"][-1]["role"], "other")
        self.assertEqual(len(packet_identity(packet)), 64)

    def test_rejects_packet_schema_enums_ids_and_pairs(self):
        base = make_evidence_packet(self.case)
        mutations = []
        def change(fn):
            value = copy.deepcopy(base); fn(value); mutations.append(value)
        change(lambda p: p.update(schema_version=True))
        change(lambda p: p.update(extra="SECRET"))
        change(lambda p: p["task"].update(extra=1))
        change(lambda p: p["reduced_mask"]["rectangle"].update(extra=1))
        change(lambda p: p["episodes"][0].update(extra=1))
        change(lambda p: p["episodes"][0].update(evidence_id=p["episodes"][1]["evidence_id"]))
        change(lambda p: p["episodes"][0].update(evidence_id="ABCDEF0123456789"))
        change(lambda p: p["episodes"][0].update(role="invented"))
        change(lambda p: p["episodes"][0].update(raw_outcome="invented"))
        change(lambda p: p["episodes"][0].update(gate_outcome="invented"))
        change(lambda p: p["episodes"][0].update(raw_outcome="success", gate_outcome="policy_failure"))
        change(lambda p: p.update(episodes=[]))
        change(lambda p: p.update(episodes=p["episodes"] * 5))
        for value in mutations:
            with self.subTest(value=value), self.assertRaisesRegex(EvidencePacketError, "^invalid evidence packet$"):
                validate_evidence_packet(value)

    def test_rejects_numeric_geometry_fill_and_byte_limits(self):
        base = make_evidence_packet(self.case)
        mutations = []
        def change(fn):
            value = copy.deepcopy(base); fn(value); mutations.append(value)
        for index in (True, -1, 1000001, 10 ** 1000):
            change(lambda p, v=index: p["task"].update(task_id=v))
        for width in (True, 0, -0.1, 2, float("nan"), float("inf"), 10 ** 1000):
            change(lambda p, v=width: p["reduced_mask"]["rectangle"].update(width=v))
        for fill in (True, -1, 256, [0, 0], [0, True, 0], [0, 256, 0]):
            change(lambda p, v=fill: p["reduced_mask"].update(fill_value=v))
        change(lambda p: p["task"].update(suite="other"))
        change(lambda p: p["reduced_mask"].update(family="other"))
        change(lambda p: p["reduced_mask"]["rectangle"].update(x=0.9))
        for value in mutations:
            with self.subTest(value=value), self.assertRaises(EvidencePacketError):
                validate_evidence_packet(value)

    def test_source_errors_are_sanitized_and_not_truncated(self):
        self.case["task"]["task_id"] = 1000001
        with self.assertRaisesRegex(EvidencePacketError, "^invalid evidence packet$"):
            make_evidence_packet(self.case)
        self.case["task"]["task_id"] = 0
        self.case["evidence"]["episodes"] *= 5
        with self.assertRaisesRegex(EvidencePacketError, "^invalid evidence packet$"):
            make_evidence_packet(self.case)
        self.case["evidence"]["episodes"] = self.case["evidence"]["episodes"][:14]
        self.case["evidence"]["private"] = "x" * 20000
        self.assertEqual(len(make_evidence_packet(self.case)["episodes"]), 14)

    def test_malformed_source_errors_hide_private_payloads(self):
        variants = []
        bad = copy.deepcopy(self.case); bad["evidence"]["episodes"][0]["episode_id"] = {"SECRET": 1}; variants.append(bad)
        bad = copy.deepcopy(self.case); bad["evidence"]["episodes"][0]["role"] = ["SECRET"]; variants.append(bad)
        bad = copy.deepcopy(self.case); bad["policy"]["provenance"]["recursive"] = bad; variants.append(bad)
        bad = copy.deepcopy(self.case); bad["perturbation"]["rectangle"]["width"] = 10 ** 1000; variants.append(bad)
        bad = copy.deepcopy(self.case); bad["task"]["suite"] = "SECRET"; variants.append(bad)
        for value in variants:
            with self.assertRaisesRegex(EvidencePacketError, "^invalid evidence packet$") as caught:
                make_evidence_packet(value)
            self.assertNotIn("SECRET", str(caught.exception))

    def test_all_consistent_outcome_pairs_are_retained(self):
        packet = make_evidence_packet(self.case)
        for raw, gate in (("success", "success"), ("task_failure", "policy_failure"),
                          ("episode_timeout", "policy_failure"),
                          ("infrastructure_error", "infrastructure_error")):
            packet["episodes"][0].update(raw_outcome=raw, gate_outcome=gate)
            self.assertEqual(validate_evidence_packet(packet)["episodes"][0]["raw_outcome"], raw)


if __name__ == "__main__": unittest.main()
