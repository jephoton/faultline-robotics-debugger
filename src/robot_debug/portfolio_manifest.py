"""Immutable identity for a bounded multi-job LIBERO Object portfolio."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Sequence


DEFAULT_CHECKPOINT_ID = "nvidia/gr00t17-lerobot-libero_object-640"
DEFAULT_CHECKPOINT_REVISION = "1499db357f6ca3762b56c2e8c00b530eb9a09444"
_EXPECTED_KEYS = frozenset({
    "suite", "task_ids", "seed", "family", "checkpoint_id", "checkpoint_revision",
})


def _nonnegative_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def _nonempty_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a nonempty string")
    return value


@dataclass(frozen=True)
class PortfolioJob:
    """One task-level diagnostic identity; evidence is never shared by jobs."""

    job_id: str
    task_id: int
    seed: int


@dataclass(frozen=True)
class PortfolioManifest:
    """The frozen contract shared by sequential and adaptive portfolio modes."""

    suite: str
    task_ids: tuple[int, ...]
    seed: int
    family: str
    checkpoint_id: str = DEFAULT_CHECKPOINT_ID
    checkpoint_revision: str = DEFAULT_CHECKPOINT_REVISION

    def __post_init__(self) -> None:
        if self.suite != "libero_object":
            raise ValueError("suite must be libero_object for the first portfolio")
        _nonempty_text("family", self.family)
        _nonempty_text("checkpoint_id", self.checkpoint_id)
        _nonempty_text("checkpoint_revision", self.checkpoint_revision)
        _nonnegative_integer("seed", self.seed)
        if (isinstance(self.task_ids, str) or not isinstance(self.task_ids, Sequence)
                or len(self.task_ids) != 3):
            raise ValueError("task_ids must contain exactly three task IDs")
        normalized = tuple(_nonnegative_integer("task_id", task_id) for task_id in self.task_ids)
        if len(set(normalized)) != len(normalized):
            raise ValueError("task_ids must be distinct")
        if normalized != self.task_ids:
            object.__setattr__(self, "task_ids", normalized)

    @property
    def jobs(self) -> tuple[PortfolioJob, ...]:
        return tuple(
            PortfolioJob(job_id=f"task-{task_id:02d}", task_id=task_id, seed=self.seed)
            for task_id in self.task_ids
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "task_ids": list(self.task_ids),
            "seed": self.seed,
            "family": self.family,
            "checkpoint_id": self.checkpoint_id,
            "checkpoint_revision": self.checkpoint_revision,
        }

    @property
    def config_hash(self) -> str:
        encoded = json.dumps(
            self.to_mapping(), sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PortfolioManifest":
        if not isinstance(value, Mapping) or set(value) != _EXPECTED_KEYS:
            raise ValueError("manifest mapping must contain exactly the frozen fields")
        return cls(
            suite=value["suite"], task_ids=tuple(value["task_ids"]), seed=value["seed"],
            family=value["family"], checkpoint_id=value["checkpoint_id"],
            checkpoint_revision=value["checkpoint_revision"],
        )
