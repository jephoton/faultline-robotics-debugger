"""Pure, fair admission of independent diagnostic jobs into one GPU wave."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Sequence


@dataclass(frozen=True)
class PortfolioBounds:
    """Shared remaining admission limits, never per-worker resource limits."""

    episode_slots: int
    seconds_left: float
    dollars_left: float

    def __post_init__(self) -> None:
        if isinstance(self.episode_slots, bool) or not isinstance(self.episode_slots, int) or self.episode_slots < 0:
            raise ValueError("episode_slots must be a nonnegative integer")
        for name, value in (("seconds_left", self.seconds_left), ("dollars_left", self.dollars_left)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite nonnegative number")

    @property
    def admits_work(self) -> bool:
        return self.episode_slots > 0 and self.seconds_left > 0 and self.dollars_left > 0


@dataclass(frozen=True)
class PortfolioChoice:
    job_id: str
    case_id: str
    reason: str


@dataclass(frozen=True)
class PortfolioWave:
    requests: tuple[PortfolioChoice, ...]
    next_cursor: int
    reason: str


def choose_wave(
    ready_by_job: Mapping[str, Sequence[str] | None], *, cursor: int, slots: int,
    bounds: PortfolioBounds,
) -> PortfolioWave:
    """Choose at most one earliest-ready case from each rotated eligible job.

    Job IDs are sorted to make rotation independent of mapping insertion order.
    ``next_cursor`` advances exactly one position after the wave's first job,
    so a continuously eligible job becomes first in turn even if earlier jobs
    are also continuously ready.
    """
    if not isinstance(ready_by_job, Mapping):
        raise ValueError("ready_by_job must be a mapping")
    if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
        raise ValueError("cursor must be a nonnegative integer")
    if isinstance(slots, bool) or not isinstance(slots, int) or not 1 <= slots <= 4:
        raise ValueError("slots must be an integer from 1 through 4")
    if not isinstance(bounds, PortfolioBounds):
        raise ValueError("bounds must be PortfolioBounds")
    eligible: list[tuple[str, str]] = []
    for job_id, cases in ready_by_job.items():
        if not isinstance(job_id, str) or not job_id:
            raise ValueError("job IDs must be nonempty strings")
        if cases is None:
            continue
        if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)):
            raise ValueError("ready cases must be sequences or None")
        if any(not isinstance(case_id, str) or not case_id for case_id in cases):
            raise ValueError("case IDs must be nonempty strings")
        if len(set(cases)) != len(cases):
            raise ValueError("a job cannot offer the same ready case twice")
        if cases:
            eligible.append((job_id, cases[0]))
    job_count = len(eligible)
    if not bounds.admits_work or not eligible:
        return PortfolioWave((), cursor if not eligible else cursor % job_count,
                             "shared admission limit prevents work" if not bounds.admits_work else "no eligible jobs")
    eligible.sort(key=lambda item: item[0])
    first = cursor % job_count
    rotated = eligible[first:] + eligible[:first]
    count = min(slots, bounds.episode_slots, job_count)
    requests = tuple(PortfolioChoice(job_id, case_id, "round_robin_ready")
                     for job_id, case_id in rotated[:count])
    return PortfolioWave(requests, (first + 1) % job_count, "work_conserving_round_robin")
