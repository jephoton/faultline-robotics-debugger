"""Generic coarse-sweep-then-bisect threshold search over one severity number.

A *level* is a severity ``s`` in (0, 1]. It is a **reproducible failure** when at
least ``required_failures`` of its ``attempts`` are policy failures (the project's
4-of-5 gate). The search sweeps the coarse levels in increasing order, stops at
the first reproducible level, then bisects between the last non-reproducible
level (0.0 when the first level already fails) and that level. The reported
threshold is the **smallest tested level that reproduces**, not a proof that no
smaller severity fails: the bisection assumes failure is roughly monotone in the
severity and its resolution is ``first_gap / 2**bisection_steps``.

The module is pure and family-agnostic. ``evaluate_level(severity, attempts)``
runs the attempts (in parallel inside the runner) and returns one outcome per
attempt: ``"success"`` or ``"policy_failure"``. Anything else, a wrong count or an
exception is an infrastructure problem; it is never counted as a policy failure
and it ends the search with ``infrastructure_error``.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

DEFAULT_SWEEP = (0.2, 0.4, 0.6, 0.8, 1.0)
VALID_OUTCOMES = ("success", "policy_failure")
STOP_REASONS = (
    "threshold_found",
    "no_reproducible_failure",
    "budget_exhausted",
    "deadline_exhausted",
    "infrastructure_error",
)
_STOP_CAUSES = ("deadline_exhausted", "budget_exhausted", "infrastructure_error")
_DECIMALS = 6


class ThresholdStop(Exception):
    """Raised by ``evaluate_level`` to end the search with a specific stop reason.

    ``outcomes`` optionally carries the attempts that did finish, so a partially
    evaluated level stays in the record (marked incomplete).
    """

    def __init__(self, reason: str, outcomes: Optional[Sequence[Any]] = None) -> None:
        if reason not in _STOP_CAUSES:
            raise ValueError("unsupported stop reason")
        super().__init__(reason)
        self.reason = reason
        self.outcomes = [] if outcomes is None else list(outcomes)


def _validate(
    sweep: Sequence[float], attempts: int, required_failures: int, bisection_steps: int
) -> List[float]:
    for name, value in (
        ("attempts", attempts), ("required_failures", required_failures),
        ("bisection_steps", bisection_steps),
    ):
        if type(value) is not int:
            raise ValueError("{} must be an integer".format(name))
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    if not 1 <= required_failures <= attempts:
        raise ValueError("required_failures must be between 1 and attempts")
    if bisection_steps < 0:
        raise ValueError("bisection_steps must not be negative")
    if isinstance(sweep, (str, bytes)) or not isinstance(sweep, Sequence) or not sweep:
        raise ValueError("sweep must be a non-empty sequence of severities")
    levels = []
    previous = 0.0
    for value in sweep:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("sweep severities must be finite numbers")
        if not previous < value <= 1.0:
            raise ValueError("sweep severities must increase strictly within (0, 1]")
        previous = float(value)
        levels.append(round(float(value), _DECIMALS))
    return levels


def run_threshold_search(
    evaluate_level: Callable[[float, int], Sequence[str]],
    *,
    sweep: Sequence[float] = DEFAULT_SWEEP,
    attempts: int = 5,
    required_failures: int = 4,
    bisection_steps: int = 4,
    can_start: Optional[Callable[[], bool]] = None,
    max_attempts: Optional[int] = None,
    physical: Optional[Callable[[float], Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Find the smallest reproducibly failing severity; returns a JSON-clean record.

    ``can_start()`` is asked before every level; ``False`` ends the search with
    ``deadline_exhausted``. ``max_attempts`` bounds the total attempts (before a
    level that would exceed it the search ends with ``budget_exhausted``).
    ``physical(severity)`` adds the physical parameter to each level record.
    """

    sweep_levels = _validate(sweep, attempts, required_failures, bisection_steps)
    if max_attempts is not None and (type(max_attempts) is not int or max_attempts < 0):
        raise ValueError("max_attempts must be a nonnegative integer")

    levels: List[Dict[str, Any]] = []
    state: Dict[str, Any] = {"lower": 0.0, "upper": None, "used": 0, "stop": None, "error": None}

    def describe(severity: float) -> Dict[str, Any]:
        record: Dict[str, Any] = {"severity": severity}
        if physical is not None:
            record["physical"] = dict(physical(severity))
        return record

    def evaluate(severity: float, phase: str) -> Optional[bool]:
        """Run one level; ``None`` means the search must stop (reason is in state)."""

        if can_start is not None and not can_start():
            state["stop"] = "deadline_exhausted"
            return None
        if max_attempts is not None and state["used"] + attempts > max_attempts:
            state["stop"] = "budget_exhausted"
            return None
        record = describe(severity)
        record.update(phase=phase, outcomes=[], failures=None, reproducible=None, complete=False)
        levels.append(record)
        try:
            outcomes = evaluate_level(severity, attempts)
        except ThresholdStop as stop:
            record["outcomes"] = [str(item) for item in stop.outcomes]
            state["used"] += len(stop.outcomes)
            state["stop"] = stop.reason
            return None
        except Exception as error:  # noqa: BLE001 - recorded by type, never by message
            state["stop"], state["error"] = "infrastructure_error", type(error).__name__
            return None
        if isinstance(outcomes, (str, bytes)) or not isinstance(outcomes, Sequence):
            state["stop"], state["error"] = "infrastructure_error", "invalid_level_result"
            return None
        record["outcomes"] = [item if isinstance(item, str) else str(item) for item in outcomes]
        state["used"] += len(outcomes)
        if len(outcomes) != attempts or any(item not in VALID_OUTCOMES for item in record["outcomes"]):
            state["stop"] = "infrastructure_error"
            return None
        record["failures"] = record["outcomes"].count("policy_failure")
        record["reproducible"] = record["failures"] >= required_failures
        record["complete"] = True
        return record["reproducible"]

    for severity in sweep_levels:
        verdict = evaluate(severity, "sweep")
        if verdict is None:
            break
        if verdict:
            state["upper"] = severity
            break
        state["lower"] = severity
    else:
        state["stop"] = "no_reproducible_failure"

    steps_done = 0
    if state["stop"] is None:
        for _ in range(bisection_steps):
            middle = round((state["lower"] + state["upper"]) / 2.0, _DECIMALS)
            if not state["lower"] < middle < state["upper"]:
                break
            verdict = evaluate(middle, "bisect")
            if verdict is None:
                break
            steps_done += 1
            if verdict:
                state["upper"] = middle
            else:
                state["lower"] = middle
        if state["stop"] is None:
            state["stop"] = "threshold_found"

    upper = state["upper"]
    result: Dict[str, Any] = {
        "threshold_severity": upper,
        "lower_bound": state["lower"],
        "resolution": None if upper is None else round(upper - state["lower"], _DECIMALS),
        "stop_reason": state["stop"],
        "sweep": sweep_levels,
        "attempts": attempts,
        "required_failures": required_failures,
        "bisection_steps": bisection_steps,
        "bisection_steps_done": steps_done,
        "levels_tried": [level["severity"] for level in levels],
        "attempts_used": state["used"],
        "levels": levels,
    }
    if physical is not None:
        result["threshold_physical"] = None if upper is None else dict(physical(upper))
    if state["error"] is not None:
        result["error"] = state["error"]
    return result


__all__ = [
    "DEFAULT_SWEEP",
    "STOP_REASONS",
    "ThresholdStop",
    "VALID_OUTCOMES",
    "run_threshold_search",
]
