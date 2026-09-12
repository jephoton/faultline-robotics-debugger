"""Serializable records for robot-policy evaluation attempts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


class AttemptOutcome(StrEnum):
    SUCCESS = "success"
    TASK_FAILURE = "task_failure"
    EPISODE_TIMEOUT = "episode_timeout"
    INFRASTRUCTURE_ERROR = "infrastructure_error"
    INVALID_SCENARIO = "invalid_scenario"


@dataclass(frozen=True)
class AttemptRecord:
    attempt_id: str
    experiment_id: str
    scenario_id: str
    task_id: str
    instruction: str
    episode_index: int
    seed: int
    env_seed: int
    outcome: AttemptOutcome
    configuration: Mapping[str, Any]
    perturbation: Mapping[str, Any]
    revisions: Mapping[str, str]
    timing_seconds: Mapping[str, float]
    artifacts: Mapping[str, str]
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        if any(value < 0 for value in self.timing_seconds.values()):
            raise ValueError("timing_seconds values must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "experiment_id": self.experiment_id,
            "scenario_id": self.scenario_id,
            "task_id": self.task_id,
            "instruction": self.instruction,
            "episode_index": self.episode_index,
            "seed": self.seed,
            "env_seed": self.env_seed,
            "outcome": self.outcome.value,
            "configuration": dict(self.configuration),
            "perturbation": dict(self.perturbation),
            "revisions": dict(self.revisions),
            "timing_seconds": dict(self.timing_seconds),
            "artifacts": dict(self.artifacts),
            "failure_detail": self.failure_detail,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AttemptRecord":
        return cls(
            attempt_id=value["attempt_id"],
            experiment_id=value["experiment_id"],
            scenario_id=value["scenario_id"],
            task_id=value["task_id"],
            instruction=value["instruction"],
            episode_index=value["episode_index"],
            seed=value["seed"],
            env_seed=value["env_seed"],
            outcome=AttemptOutcome(value["outcome"]),
            configuration=value["configuration"],
            perturbation=value["perturbation"],
            revisions=value["revisions"],
            timing_seconds=value["timing_seconds"],
            artifacts=value["artifacts"],
            failure_detail=value.get("failure_detail"),
        )


class DuplicateAttemptError(ValueError):
    """Raised when a record would overwrite an existing attempt."""


class AttemptLedger:
    """In-memory uniqueness guard for attempt records."""

    def __init__(self) -> None:
        self._records: dict[str, AttemptRecord] = {}

    def add(self, record: AttemptRecord) -> None:
        if record.attempt_id in self._records:
            raise DuplicateAttemptError(f"attempt already recorded: {record.attempt_id}")
        self._records[record.attempt_id] = record
