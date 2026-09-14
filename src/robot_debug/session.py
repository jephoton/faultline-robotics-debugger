"""Pure parsing and decision helpers for a bounded evaluation session."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Optional, Sequence


@dataclass(frozen=True)
class EpisodeResult:
    """The evidence needed to make a session-level decision about one episode."""

    success: bool
    steps: int
    elapsed_seconds: float
    episode_index: int
    failure_reason: Optional[str]
    failure_detail: Optional[str]
    outcome: str


def classify_aggregate(aggregate: Mapping[str, Any]) -> EpisodeResult:
    """Classify the single episode contained in an evaluator aggregate."""

    if not isinstance(aggregate, Mapping):
        raise ValueError("aggregate must be a mapping")
    tasks = aggregate.get("tasks")
    if not _is_sequence(tasks) or len(tasks) != 1 or not isinstance(tasks[0], Mapping):
        raise ValueError("aggregate must contain exactly one task")
    episodes = tasks[0].get("episodes")
    if not _is_sequence(episodes) or len(episodes) != 1 or not isinstance(episodes[0], Mapping):
        raise ValueError("aggregate must contain exactly one episode")

    raw = episodes[0]
    metrics = raw.get("metrics")
    if not isinstance(metrics, Mapping) or "success" not in metrics:
        raise ValueError("episode metrics.success is required")
    success = metrics["success"]
    if type(success) is not bool:
        raise ValueError("episode metrics.success must be a bool")

    try:
        raw_steps = raw["steps"]
        elapsed_seconds = float(raw["elapsed_sec"])
        raw_episode_index = raw.get("episode_idx", raw.get("episode_id"))
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise ValueError("episode is missing required timing or index fields") from error
    steps = _finite_nonnegative_integer(raw_steps, "episode steps")
    episode_index = _finite_nonnegative_integer(
        raw_episode_index, "episode index"
    )
    if not math.isfinite(elapsed_seconds) or elapsed_seconds < 0:
        raise ValueError("episode elapsed_sec must be finite and non-negative")

    failure_reason = raw.get("failure_reason")
    failure_detail = raw.get("failure_detail")
    if failure_reason is not None and not isinstance(failure_reason, str):
        raise ValueError("failure_reason must be a string")
    if failure_detail is not None and not isinstance(failure_detail, str):
        raise ValueError("failure_detail must be a string")

    if _has_infrastructure_indication(raw, failure_reason):
        outcome = "infrastructure_error"
    elif success:
        outcome = "success"
    else:
        outcome = "policy_failure"

    return EpisodeResult(
        success=success,
        steps=steps,
        elapsed_seconds=elapsed_seconds,
        episode_index=episode_index,
        failure_reason=failure_reason,
        failure_detail=failure_detail,
        outcome=outcome,
    )


def should_launch_next(elapsed_seconds: float, launch_cutoff_seconds: float) -> bool:
    """Return whether a new evaluator process may start before the cutoff."""

    elapsed = _finite_nonnegative(elapsed_seconds, "elapsed_seconds")
    cutoff = _finite_nonnegative(launch_cutoff_seconds, "launch_cutoff_seconds")
    return elapsed < cutoff


def is_reproducible(outcomes: Sequence[str], required: int = 4) -> bool:
    """Apply the four-of-five gate to five valid completed replay outcomes."""

    valid_outcomes = {"policy_failure", "success"}
    if len(outcomes) != 5:
        raise ValueError("reproducibility requires exactly five replay outcomes")
    unknown_outcomes = set(outcomes) - valid_outcomes
    if unknown_outcomes:
        raise ValueError("replay outcomes must be completed policy results")
    return outcomes.count("policy_failure") >= required


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def _has_infrastructure_indication(
    raw: Mapping[str, Any], failure_reason: Optional[str]
) -> bool:
    if raw.get("exception") or raw.get("infrastructure_error"):
        return True
    return failure_reason is not None and failure_reason.lower() in {
        "exception",
        "infrastructure",
        "infrastructure_error",
    }


def _finite_nonnegative(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("{} must be a finite non-negative number".format(name))
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError("{} must be a finite non-negative number".format(name))
    return parsed


def _finite_nonnegative_integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError("{} must be a non-negative finite integer".format(name))
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("{} must be a non-negative finite integer".format(name)) from error
    if not math.isfinite(parsed) or parsed < 0 or not parsed.is_integer():
        raise ValueError("{} must be a non-negative finite integer".format(name))
    return int(parsed)
