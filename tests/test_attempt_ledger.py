"""Unit tests for durable M3 replay attempt ownership."""

from __future__ import annotations

import json
import unittest

from robot_debug.attempt_ledger import AttemptLedger


def result(case_id: str, *, status: str = "valid", **extra: object) -> dict[str, object]:
    return {
        "case_id": case_id,
        "kind": case_id.split("-", 1)[0],
        "status": status,
        "outcome": "success",
        **extra,
    }


class AttemptLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = AttemptLedger(["nominal-01", "mask-01"])

    def test_transitions_from_prepared_to_terminal(self) -> None:
        self.ledger.begin_submit("nominal-01")
        self.ledger.register_active("nominal-01")
        self.ledger.capture_result("nominal-01", result("nominal-01"), interrupted=False)

        pending = self.ledger.snapshot()
        self.assertEqual("completing_pending", pending["attempt_states"]["nominal-01"])
        self.assertEqual([], pending["results"])
        self.assertEqual(["nominal-01"], pending["in_flight_ids"])

        self.ledger.finish("nominal-01")
        snapshot = self.ledger.snapshot()
        self.assertEqual(
            {"nominal-01": "terminal", "mask-01": "prepared"}, snapshot["attempt_states"]
        )
        self.assertEqual([result("nominal-01")], snapshot["results"])
        self.assertEqual(1, snapshot["valid_count"])
        self.assertEqual([], snapshot["in_flight_ids"])

    def test_backward_transitions_and_duplicate_terminal_capture_are_rejected(self) -> None:
        self.ledger.begin_submit("nominal-01")
        self.ledger.register_active("nominal-01")
        with self.assertRaises(ValueError):
            self.ledger.begin_submit("nominal-01")
        with self.assertRaises(ValueError):
            self.ledger.finish("nominal-01")

        self.ledger.capture_result("nominal-01", result("nominal-01"), interrupted=False)
        self.ledger.finish("nominal-01")
        self.ledger.capture_result("nominal-01", result("nominal-01"), interrupted=False)
        with self.assertRaises(ValueError):
            self.ledger.capture_result(
                "nominal-01", result("nominal-01", outcome="policy_failure"), interrupted=False
            )

    def test_finishing_an_exact_same_terminal_is_idempotent(self) -> None:
        self.ledger.begin_submit("nominal-01")
        self.ledger.register_active("nominal-01")
        self.ledger.capture_result("nominal-01", result("nominal-01"), interrupted=False)
        self.ledger.finish("nominal-01")

        self.ledger.finish("nominal-01")
        self.assertEqual([result("nominal-01")], self.ledger.snapshot()["results"])

    def test_capture_copies_json_compatible_result_before_terminalization(self) -> None:
        self.ledger.begin_submit("nominal-01")
        self.ledger.register_active("nominal-01")
        captured = result("nominal-01", evidence={"metric": 0.75})
        self.ledger.capture_result("nominal-01", captured, interrupted=False)
        captured["evidence"]["metric"] = 0.0  # type: ignore[index]

        self.ledger.finish("nominal-01")
        self.assertEqual(0.75, self.ledger.snapshot()["results"][0]["evidence"]["metric"])

    def test_snapshot_is_ordered_and_attempted_cases_are_terminal_or_in_flight(self) -> None:
        self.ledger.begin_submit("nominal-01")
        self.ledger.register_active("nominal-01")
        self.ledger.capture_result("nominal-01", result("nominal-01"), interrupted=False)
        self.ledger.finish("nominal-01")
        self.ledger.begin_submit("mask-01")

        snapshot = self.ledger.snapshot()
        self.assertEqual(["nominal-01"], [record["case_id"] for record in snapshot["results"]])
        self.assertEqual(["mask-01"], snapshot["in_flight_ids"])
        attempted = {
            case_id for case_id, attempt in self.ledger.attempts.items() if attempt["state"] != "prepared"
        }
        terminal = {record["case_id"] for record in snapshot["results"]}
        in_flight = set(snapshot["in_flight_ids"])
        self.assertEqual(attempted, terminal | in_flight)
        self.assertFalse(terminal & in_flight)

    def test_late_valid_result_after_interruption_becomes_infrastructure_evidence(self) -> None:
        self.ledger.begin_submit("nominal-01")
        self.ledger.register_active("nominal-01")
        observed = result("nominal-01", evidence={"artifact": "runs/nominal-01/results.json"})
        self.ledger.capture_result("nominal-01", observed, interrupted=True)
        self.ledger.finish("nominal-01")

        terminal = self.ledger.snapshot()["results"][0]
        self.assertEqual("infrastructure_error", terminal["status"])
        self.assertEqual("success", terminal["outcome"])
        self.assertEqual({"artifact": "runs/nominal-01/results.json"}, terminal["evidence"])
        self.assertIn("interrupted", terminal["infrastructure_error"])
        self.assertEqual(0, self.ledger.snapshot()["valid_count"])

    def test_cancel_unstarted_returns_known_unstarted_work_to_prepared(self) -> None:
        self.ledger.begin_submit("mask-01")
        self.ledger.register_active("mask-01")
        self.ledger.cancel_unstarted("mask-01")

        snapshot = self.ledger.snapshot()
        self.assertEqual("prepared", snapshot["attempt_states"]["mask-01"])
        self.assertEqual([], snapshot["in_flight_ids"])

    def test_snapshot_makes_pending_completion_record_durable_json(self) -> None:
        self.ledger.begin_submit("nominal-01")
        self.ledger.register_active("nominal-01")
        captured = result("nominal-01", evidence={"artifact": "runs/nominal-01/results.json"})
        self.ledger.capture_result("nominal-01", captured, interrupted=False)

        serialized = json.dumps(self.ledger.snapshot())
        durable = json.loads(serialized)
        self.assertEqual(
            {"state": "completing_pending", "result": captured},
            durable["attempt_records"]["nominal-01"],
        )
        self.assertEqual({"state": "prepared"}, durable["attempt_records"]["mask-01"])

    def test_json_round_trip_restores_pending_result_for_reconciliation(self) -> None:
        self.ledger.begin_submit("nominal-01")
        self.ledger.register_active("nominal-01")
        captured = result("nominal-01", evidence={"artifact": "runs/nominal-01/results.json"})
        self.ledger.capture_result("nominal-01", captured, interrupted=False)

        restored = AttemptLedger.from_snapshot(
            ["nominal-01", "mask-01"], json.loads(json.dumps(self.ledger.snapshot()))
        )
        round_tripped = json.loads(json.dumps(self.ledger.snapshot()))
        restored_isolated = AttemptLedger.from_snapshot(["nominal-01", "mask-01"], round_tripped)
        round_tripped["attempt_records"]["nominal-01"]["result"]["evidence"]["artifact"] = "tampered"
        self.assertEqual(
            "runs/nominal-01/results.json",
            restored_isolated.snapshot()["attempt_records"]["nominal-01"]["result"]["evidence"]["artifact"],
        )
        self.assertEqual("completing_pending", restored.snapshot()["attempt_states"]["nominal-01"])
        restored.finish("nominal-01")
        self.assertEqual([captured], restored.snapshot()["results"])

    def test_restore_rejects_corrupt_attempt_records(self) -> None:
        snapshot = self.ledger.snapshot()
        with self.assertRaises(ValueError):
            AttemptLedger.from_snapshot(["nominal-01", "mask-01"], {"attempt_records": {}})
        with self.assertRaises(ValueError):
            AttemptLedger.from_snapshot(
                ["nominal-01", "mask-01"],
                {"attempt_records": {"nominal-01": {"state": "prepared"}, "other": {"state": "prepared"}}},
            )
        snapshot["attempt_records"]["nominal-01"] = {"state": "invented_success"}
        with self.assertRaises(ValueError):
            AttemptLedger.from_snapshot(["nominal-01", "mask-01"], snapshot)
        for state in ([], {}):
            snapshot = self.ledger.snapshot()
            snapshot["attempt_records"]["nominal-01"] = {"state": state}
            with self.assertRaises(ValueError):
                AttemptLedger.from_snapshot(["nominal-01", "mask-01"], snapshot)
        snapshot = self.ledger.snapshot()
        snapshot["attempt_records"]["nominal-01"] = {
            "state": "terminal", "result": {"case_id": "nominal-01", "status": "valid", "bad": object()},
        }
        with self.assertRaises(ValueError):
            AttemptLedger.from_snapshot(["nominal-01", "mask-01"], snapshot)


if __name__ == "__main__":
    unittest.main()
