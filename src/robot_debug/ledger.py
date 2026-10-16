"""The spend ledger of one ``faultline`` run (ADR 0031).

Every paid Job is *reserved* before it is submitted at its worst case (the provider
timeout the Job is created with, which is its deadline plus a fixed grace rounded up to
whole minutes, plus the image-pull and start allowance, at the backend's hourly rate) and
*settled* afterwards at the measured container time plus that start allowance. A
reservation is refused when spent + reserved + the new worst case would exceed the
cap, so a run can never be committed beyond ``budget.max_spend_usd``. A Job that
never started (no capacity) settles at zero.

The wall-clock cap (``budget.max_hours``) counts only time the run was active: a
resumed run does not pay for the hours the machine was off.

The file is rewritten atomically after every change, so a crash leaves a ledger
that is at worst pessimistic (a reservation never settled).
"""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

SCHEMA_VERSION = 1
DEFAULT_START_ALLOWANCE_SECONDS = 240
JOB_TIMEOUT_GRACE_SECONDS = 600        # provider timeout = Job deadline + this, rounded up to whole minutes
_EPSILON = 1e-9


class LedgerError(RuntimeError):
    """A bookkeeping error; the message is fixed text and never holds a secret."""


class BudgetExceeded(LedgerError):
    """A reservation would take the run past its spend cap."""


class TimeExhausted(LedgerError):
    """The run's wall-clock cap is used up."""


def provider_timeout_seconds(deadline_seconds: float) -> int:
    """The ``--timeout`` a Job with this deadline is created with: deadline + grace, whole minutes up.

    The provider stops the Job at this limit whatever the laptop is doing, so it bounds what one
    Job can bill. The watchdog (deadline + 300 s, then at most 300 s for the cancel) ends earlier.
    """

    return int(math.ceil((float(deadline_seconds) + JOB_TIMEOUT_GRACE_SECONDS) / 60.0)) * 60


def worst_case_seconds(deadline_seconds: float, start_allowance_seconds: float = DEFAULT_START_ALLOWANCE_SECONDS) -> int:
    """Billable seconds one Job can cost at most: provider timeout + start allowance."""

    return provider_timeout_seconds(deadline_seconds) + int(start_allowance_seconds)


def _money(value: float) -> float:
    return round(float(value), 6)


class Ledger:
    def __init__(self, path: Any, *, cap_usd: float, max_hours: float, hourly_usd: float,
                 clock: Callable[[], float] = time.time,
                 start_allowance_seconds: int = DEFAULT_START_ALLOWANCE_SECONDS,
                 _state: Optional[Dict[str, Any]] = None) -> None:
        self.path = Path(path)
        self.cap_usd = float(cap_usd)
        self.max_hours = float(max_hours)
        self.hourly_usd = float(hourly_usd)
        self.start_allowance_seconds = int(start_allowance_seconds)
        self._clock = clock
        self.jobs: Dict[str, Dict[str, Any]] = dict((_state or {}).get("jobs", {}))
        self._elapsed_base = float((_state or {}).get("elapsed_seconds", 0.0))
        self._segment_start = clock()
        self._save()

    # -- construction --------------------------------------------------------------

    @classmethod
    def load(cls, path: Any, *, cap_usd: float, max_hours: float, hourly_usd: float,
             clock: Callable[[], float] = time.time,
             start_allowance_seconds: int = DEFAULT_START_ALLOWANCE_SECONDS) -> "Ledger":
        """Open ``path`` (creating it when absent); a ledger from another spec is refused."""

        target = Path(path)
        if not target.exists():
            return cls(target, cap_usd=cap_usd, max_hours=max_hours, hourly_usd=hourly_usd, clock=clock,
                       start_allowance_seconds=start_allowance_seconds)
        try:
            state = json.loads(target.read_text(encoding="utf-8"))
            if state["schema_version"] != SCHEMA_VERSION or type(state["jobs"]) is not dict:
                raise ValueError
            for key, value in (("cap_usd", cap_usd), ("max_hours", max_hours), ("hourly_usd", hourly_usd)):
                if not math.isclose(float(state[key]), float(value), rel_tol=0, abs_tol=_EPSILON):
                    raise LedgerError("the ledger was written for a different {}; start a new run".format(key))
            float(state["elapsed_seconds"])
        except LedgerError:
            raise
        except (OSError, ValueError, KeyError, TypeError):
            raise LedgerError("the ledger file is unreadable") from None
        return cls(target, cap_usd=cap_usd, max_hours=max_hours, hourly_usd=hourly_usd, clock=clock,
                   start_allowance_seconds=start_allowance_seconds, _state=state)

    # -- money -----------------------------------------------------------------------

    @property
    def spent(self) -> float:
        return _money(sum(job["cost_usd"] for job in self.jobs.values() if job["state"] == "settled"))

    @property
    def reserved(self) -> float:
        return _money(sum(job["reserved_usd"] for job in self.jobs.values() if job["state"] == "reserved"))

    @property
    def remaining(self) -> float:
        return _money(self.cap_usd - self.spent - self.reserved)

    def worst_case_usd(self, deadline_seconds: float) -> float:
        """What a Job with this deadline can cost at most: its provider timeout plus the start allowance."""

        return worst_case_seconds(deadline_seconds, self.start_allowance_seconds) / 3600.0 * self.hourly_usd

    def reserve(self, job_name: str, worst_case_usd: float) -> None:
        if type(job_name) is not str or not job_name or job_name in self.jobs:
            raise LedgerError("a reservation needs a new job name")
        if type(worst_case_usd) not in (int, float) or not math.isfinite(worst_case_usd) or worst_case_usd < 0:
            raise LedgerError("a reservation must be a non-negative amount")
        amount = _money(worst_case_usd)
        if self.spent + self.reserved + amount > self.cap_usd + _EPSILON:
            raise BudgetExceeded(
                "spend cap US${:.2f}: spent {:.2f} + reserved {:.2f} + this Job's worst case {:.2f} would exceed it".format(
                    self.cap_usd, self.spent, self.reserved, amount))
        self.jobs[job_name] = {"state": "reserved", "reserved_usd": amount, "cost_usd": 0.0,
                               "container_seconds": None}
        self._save()

    def settle(self, job_name: str, container_seconds: Optional[float],
               start_allowance_seconds: Optional[int] = None) -> float:
        """Record what the Job cost; ``None`` means it never started and costs nothing."""

        job = self._job(job_name)
        if job["state"] == "settled" and not job.get("worst_case"):
            return job["cost_usd"]
        if container_seconds is None and job.get("worst_case"):
            return job["cost_usd"]          # an unconfirmed Job keeps its worst case until measured
        if container_seconds is None:
            cost = 0.0
        else:
            if type(container_seconds) not in (int, float) or not math.isfinite(container_seconds) \
                    or container_seconds < 0:
                raise LedgerError("container seconds must be a non-negative number")
            allowance = self.start_allowance_seconds if start_allowance_seconds is None else start_allowance_seconds
            cost = (float(container_seconds) + allowance) / 3600.0 * self.hourly_usd
        job.update(state="settled", cost_usd=_money(cost),
                   container_seconds=None if container_seconds is None else float(container_seconds))
        job.pop("worst_case", None)
        self._save()
        return job["cost_usd"]

    def settle_worst_case(self, job_name: str) -> float:
        """Charge the whole reservation: the Job's outcome is unknown, so assume the worst."""

        job = self._job(job_name)
        if job["state"] == "settled":
            return job["cost_usd"]
        # Flagged so a later measurement (a resumed run that reaches the Job) can replace it.
        job.update(state="settled", cost_usd=job["reserved_usd"], worst_case=True)
        self._save()
        return job["cost_usd"]

    def _job(self, job_name: str) -> Dict[str, Any]:
        try:
            return self.jobs[job_name]
        except KeyError:
            raise LedgerError("no such reservation") from None

    # -- time ------------------------------------------------------------------------

    def elapsed_seconds(self) -> float:
        return self._elapsed_base + max(0.0, self._clock() - self._segment_start)

    def remaining_seconds(self) -> float:
        return self.max_hours * 3600.0 - self.elapsed_seconds()

    def check_time(self, extra_seconds: float = 0.0) -> None:
        """Raise when ``extra_seconds`` more would pass the wall-clock cap (0: is it spent already)."""

        if self.remaining_seconds() - extra_seconds <= 0:
            raise TimeExhausted("the {:g} h wall-clock cap is used up".format(self.max_hours))

    # -- output ----------------------------------------------------------------------

    def status_text(self) -> str:
        return "spent US${:.2f} / {:.2f}".format(self.spent, self.cap_usd)

    def _save(self) -> None:
        state = {"schema_version": SCHEMA_VERSION, "cap_usd": self.cap_usd, "max_hours": self.max_hours,
                 "hourly_usd": self.hourly_usd, "elapsed_seconds": round(self.elapsed_seconds(), 3),
                 "spent_usd": self.spent, "reserved_usd": self.reserved, "jobs": self.jobs}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(state, indent=1, sort_keys=True, allow_nan=False) + "\n",
                             encoding="utf-8", newline="\n")
        os.replace(str(temporary), str(self.path))


__all__ = ["BudgetExceeded", "Ledger", "LedgerError", "TimeExhausted", "DEFAULT_START_ALLOWANCE_SECONDS",
           "JOB_TIMEOUT_GRACE_SECONDS", "provider_timeout_seconds", "worst_case_seconds"]
