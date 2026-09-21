"""Deterministic kernel for bounded robot-policy failure reduction.

The reducer shrinks a proven occlusion failure by removing one strip from one
edge of the current rectangle at a time and certifying each move with an
adaptive repeatability gate. This module is deliberately pure: it validates
normalized geometry, generates strict nested candidates, and decides the gate
from recorded policy outcomes. It never launches subprocesses, reads
artifacts, or touches the network, filesystem, or third-party packages.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Literal, Sequence, Tuple


@dataclass(frozen=True)
class Rect:
    """An axis-aligned rectangle in normalized, top-left-origin image space."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        """Reject non-finite, empty, or out-of-bounds geometry."""

        values = (self.x, self.y, self.width, self.height)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("rectangle values must be finite")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("rectangle dimensions must be positive")
        if self.x < 0 or self.y < 0 or self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("rectangle must remain within normalized image bounds")

    @property
    def area(self) -> float:
        """Return the normalized area of the rectangle."""

        return self.width * self.height


@dataclass(frozen=True)
class Candidate:
    """One strict nested rectangle produced by removing a single edge strip."""

    edge: Literal["left", "bottom", "right", "top"]
    rect: Rect


def candidates(parent: Rect, *, delta: float) -> Tuple[Candidate, ...]:
    """Return strict nested candidates made by removing one ``delta`` strip.

    Candidates use the deterministic edge order ``left, bottom, right, top``.
    Every candidate stays inside ``parent`` and has strictly smaller area. An
    edge is omitted when removing its strip would leave a non-positive
    dimension, so an empty result means no reduction of this size is possible.
    """

    if not math.isfinite(delta) or delta <= 0:
        raise ValueError("delta must be finite and positive")
    proposed = (
        ("left", Rect(parent.x + delta, parent.y, parent.width - delta, parent.height))
        if parent.width > delta else None,
        ("bottom", Rect(parent.x, parent.y, parent.width, parent.height - delta))
        if parent.height > delta else None,
        ("right", Rect(parent.x, parent.y, parent.width - delta, parent.height))
        if parent.width > delta else None,
        ("top", Rect(parent.x, parent.y + delta, parent.width, parent.height - delta))
        if parent.height > delta else None,
    )
    return tuple(Candidate(item[0], item[1]) for item in proposed if item is not None)


class GateDecision(str, Enum):
    """Result of the adaptive repeatability gate for one candidate rectangle."""

    PENDING = "pending"
    PASS = "pass"
    REJECT = "reject"


def classify_attempts(outcomes: Sequence[str]) -> GateDecision:
    """Return the gate decision for the ordered valid policy outcomes recorded.

    The gate passes as soon as four ``policy_failure`` outcomes are observed and
    rejects as soon as two valid non-failure outcomes are observed; anything
    else remains pending so the caller can spend the remaining attempts. More
    than five attempts, or any outcome that is not a completed policy result,
    raises ``ValueError`` so infrastructure and invalid evidence can never be
    mistaken for a rejection.
    """

    if len(outcomes) > 5:
        raise ValueError("a repeatability gate permits at most five attempts")
    if any(item not in {"policy_failure", "success"} for item in outcomes):
        raise ValueError("only valid policy outcomes may enter the gate")
    failures = outcomes.count("policy_failure")
    non_failures = len(outcomes) - failures
    if failures >= 4:
        return GateDecision.PASS
    if non_failures >= 2:
        return GateDecision.REJECT
    return GateDecision.PENDING
