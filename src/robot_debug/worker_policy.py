"""Conservative worker choice on one already allocated GPU VM.

Measurements are warm *per-item* observations, not guarantees for a short
round. The deadline and cost checks are admission estimates; the live session
still needs its independent stop guard and approved allocation cap.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping


@dataclass(frozen=True)
class WorkerChoice:
    workers: int
    reason: str
    predicted_seconds: float
    predicted_cost_usd: float


def _number(name: str, value: object, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except OverflowError as error:
        raise ValueError(f"{name} must be a finite number") from error
    if not math.isfinite(result) or result < 0 or (positive and result == 0):
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")
    return result


def choose_workers(
    *,
    ready_count: int,
    seconds_left: float,
    dollars_left: float,
    hourly_rate: float,
    measured_seconds: Mapping[int, float],
    shutdown_reserve_seconds: float,
) -> WorkerChoice:
    """Choose the cheapest feasible measured 1/2/4-worker mode for one VM.

    No choice here provisions a GPU. For a partially filled wave, the estimate
    is floored by the observed one-worker item duration when available. If no
    trustworthy measurement exists, one worker may run only if the remaining
    full time window is affordable; its reported time is that whole window.
    """
    if (isinstance(ready_count, bool) or not isinstance(ready_count, int)
            or ready_count < 0 or ready_count > 2 ** 53):
        raise ValueError("ready_count must be a nonnegative integer")
    remaining = _number("seconds_left", seconds_left)
    budget = _number("dollars_left", dollars_left)
    rate = _number("hourly_rate", hourly_rate, positive=True)
    reserve = _number("shutdown_reserve_seconds", shutdown_reserve_seconds, positive=True)
    if not isinstance(measured_seconds, Mapping):
        raise ValueError("measured_seconds must be a mapping")
    if any(isinstance(key, bool) or key not in (1, 2, 4) for key in measured_seconds):
        raise ValueError("measured_seconds contains an unsupported worker count")
    if ready_count == 0:
        return WorkerChoice(0, "no ready episodes", 0.0, 0.0)
    if remaining <= reserve:
        return WorkerChoice(0, "deadline leaves no launch window", 0.0, 0.0)

    valid = {}
    for workers, raw in measured_seconds.items():
        try:
            valid[workers] = _number(f"measured_seconds[{workers}]", raw, positive=True)
        except ValueError:
            pass
    if 1 not in valid:
        cost = remaining * rate / 3600
        if cost <= budget:
            return WorkerChoice(1, "fallback: no trustworthy baseline; budget covers full remaining window", remaining, cost)
        return WorkerChoice(0, "no trustworthy baseline and full window exceeds budget", 0.0, 0.0)

    parallel_consistent = True
    previous = valid[1]
    for workers in (2, 4):
        if workers not in valid:
            continue
        observed = valid[workers]
        if observed > previous or observed < valid[1] / workers:
            parallel_consistent = False
        previous = observed
    if not parallel_consistent:
        valid = {1: valid[1]}

    choices = []
    for workers in (1, 2, 4):
        if workers > ready_count or workers not in valid:
            continue
        warm = max(
            ready_count * valid[workers],
            math.ceil(ready_count / workers) * valid[1],
        )
        total = warm + reserve
        cost = total * rate / 3600
        if math.isfinite(total) and math.isfinite(cost) and total <= remaining and cost <= budget:
            reason = "fallback: inconsistent parallel measurements" if not parallel_consistent else "measured one-GPU throughput estimate"
            choices.append(WorkerChoice(workers, reason, total, cost))
    if not choices:
        return WorkerChoice(0, "no measured mode fits deadline and dollar cap", 0.0, 0.0)
    return min(choices, key=lambda choice: (choice.predicted_cost_usd, choice.workers))
