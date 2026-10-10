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

    def test_forged_string_enum_values_are_rejected_without_echo(self):
        class ForgedString(str):
            def __new__(cls, target):
                instance = str.__new__(cls, "SECRET")
                instance.target = target
                return instance

            def __hash__(self):
                return hash(self.target)

            def __eq__(self, other):
                return other == self.target

        packet = make_evidence_packet(self.case)
        for field, allowed in (("role", "nominal"), ("raw_outcome", "success"),
                               ("gate_outcome", "success")):
            with self.subTest(field=field):
                forged = copy.deepcopy(packet)
                forged["episodes"][0].update(role="nominal", raw_outcome="success", gate_outcome="success")
                forged["episodes"][0][field] = ForgedString(allowed)
                with self.assertRaisesRegex(EvidencePacketError, "^invalid evidence packet$") as caught:
                    validate_evidence_packet(forged)
                self.assertNotIn("SECRET", str(caught.exception))

                source = copy.deepcopy(self.case)
                source["evidence"]["episodes"][0][field] = ForgedString(allowed)
                with self.assertRaisesRegex(EvidencePacketError, "^invalid evidence packet$") as caught:
                    make_evidence_packet(source)
                self.assertNotIn("SECRET", str(caught.exception))


if __name__ == "__main__": unittest.main()


class EvidencePacketV2Tests(unittest.TestCase):
    """Geometry-aware packet used by the v2 interpretation prompt."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        fixture(Path(self.tmp.name))
        self.case = import_m4(Path(self.tmp.name))
        for episode in self.case["evidence"]["episodes"]:
            if episode["role"] == "parent":
                episode["stage"] = episode["stage"].replace(
                    "parent-", "parent-x0500-y0000-w0500-h0500-")

    def tearDown(self):
        self.tmp.cleanup()

    def test_v1_remains_the_default_projection(self):
        packet = make_evidence_packet(self.case)
        self.assertEqual(packet["schema_version"], 1)
        self.assertTrue(all("mask" not in e for e in packet["episodes"]))

    def test_v2_adds_parsed_and_fallback_masks(self):
        packet = make_evidence_packet(self.case, schema_version=2)
        self.assertEqual(packet["schema_version"], 2)
        by_role = {}
        for episode in packet["episodes"]:
            by_role.setdefault(episode["role"], set()).add(json.dumps(episode["mask"], sort_keys=True))
        self.assertEqual(by_role["nominal"], {"null"})
        self.assertEqual(by_role["parent"], {json.dumps(
            {"height": 0.5, "width": 0.5, "x": 0.5, "y": 0.0}, sort_keys=True)})
        self.assertEqual(by_role["reduced"], {json.dumps(
            packet["reduced_mask"]["rectangle"], sort_keys=True)})
        self.assertEqual(validate_evidence_packet(packet), packet)

    def test_unparseable_other_stage_has_no_mask(self):
        self.case["evidence"]["episodes"][0]["role"] = "other"
        self.case["evidence"]["episodes"][0]["stage"] = "other-free-text"
        packet = make_evidence_packet(self.case, schema_version=2)
        target = self.case["evidence"]["episodes"][0]["episode_id"]
        (episode,) = [e for e in packet["episodes"] if e["evidence_id"] == target]
        self.assertIsNone(episode["mask"])

    def test_versions_have_distinct_identities(self):
        self.assertNotEqual(packet_identity(make_evidence_packet(self.case)),
                            packet_identity(make_evidence_packet(self.case, schema_version=2)))

    def test_v2_rejects_invalid_masks_and_v1_rejects_mask_fields(self):
        packet = make_evidence_packet(self.case, schema_version=2)
        for mask in ({"x": 0.9, "y": 0.0, "width": 0.5, "height": 0.5},
                     {"x": 0.1, "y": 0.0, "width": 0.5},
                     {"x": 0.1, "y": 0.0, "width": 0.0, "height": 0.5},
                     "x0500"):
            broken = copy.deepcopy(packet)
            broken["episodes"][0]["mask"] = mask
            with self.subTest(mask=mask), self.assertRaises(EvidencePacketError):
                validate_evidence_packet(broken)
        missing = copy.deepcopy(packet)
        del missing["episodes"][0]["mask"]
        with self.assertRaises(EvidencePacketError):
            validate_evidence_packet(missing)
        v1_with_mask = make_evidence_packet(self.case)
        v1_with_mask["episodes"][0]["mask"] = None
        with self.assertRaises(EvidencePacketError):
            validate_evidence_packet(v1_with_mask)
        with self.assertRaises(EvidencePacketError):
            make_evidence_packet(self.case, schema_version=3)
