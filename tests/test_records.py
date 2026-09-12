import unittest
from dataclasses import replace

from robot_debug import records
from robot_debug.records import AttemptOutcome, AttemptRecord


class AttemptRecordTests(unittest.TestCase):
    def _record(self) -> AttemptRecord:
        return AttemptRecord(
            attempt_id="attempt-001",
            experiment_id="baseline-object-pilot",
            scenario_id="object-task-0-state-3",
            task_id="libero_object:0",
            instruction="pick up the object",
            episode_index=3,
            seed=7,
            env_seed=7,
            outcome=AttemptOutcome.TASK_FAILURE,
            configuration={"max_steps": 280, "action_chunk_size": 16},
            perturbation={"kind": "camera_occlusion", "fraction": 0.2},
            revisions={
                "harness": "35f1200eb15608aa898f727a3722f7eef889c6cd",
                "checkpoint": "1499db357f6ca3762b56c2e8c00b530eb9a09444",
            },
            timing_seconds={"wall_clock": 12.5, "inference": 7.25},
            artifacts={"video": "artifacts/attempt-001.mp4"},
            failure_detail="task horizon exhausted",
        )

    def test_round_trip_preserves_a_replayable_attempt(self) -> None:
        record = self._record()

        restored = AttemptRecord.from_dict(record.to_dict())

        self.assertEqual(restored, record)
        self.assertEqual(restored.outcome, AttemptOutcome.TASK_FAILURE)

    def test_ledger_refuses_to_overwrite_an_existing_attempt(self) -> None:
        ledger_type = getattr(records, "AttemptLedger", None)
        duplicate_error = getattr(records, "DuplicateAttemptError", None)
        self.assertIsNotNone(ledger_type)
        self.assertIsNotNone(duplicate_error)

        ledger = ledger_type()
        ledger.add(self._record())

        with self.assertRaises(duplicate_error):
            ledger.add(self._record())

    def test_rejects_negative_timing(self) -> None:
        with self.assertRaisesRegex(ValueError, "timing_seconds"):
            replace(self._record(), timing_seconds={"wall_clock": -0.1})
