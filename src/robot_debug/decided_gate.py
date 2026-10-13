"""Early-decided repeatability gates (ADR 0029, M3 latency).

A candidate start is judged by a gate over ``attempts`` (five) episodes:

* the **failure gate** reproduces when at least ``required_failures`` (four) are
  policy failures. It is fixed at the fourth failure ("reproduces") or at the
  second non-failure ("does_not_reproduce"), whichever comes first;
* the **pass gate** (a reference must succeed every time) is fixed at the first
  non-success ("fails") or at the fifth success ("passes").

Once the outcome is fixed the remaining attempts cannot change it, so attempts
that have not started are skipped (withdrawn from the pool, or never
submitted). Attempts that already started finish and are recorded, but the
decision is not revisited: it equals the decision all five attempts would give
(``tests/test_decided_gate.py`` enumerates all 32 outcome sequences).
Scenes are deterministic, so an ``invalid_scene`` outcome is decided at once as
``invalid_scene`` (never a policy failure) and the rest are skipped.

``decide`` and ``decide_pass`` are pure. ``run_gates`` schedules a batch of
independent candidates on an executor so that workers freed by an early
decision take attempts of other candidates.

Executor protocol (adapt the real ``EvaluatorPool`` to it; tests use fakes)::

    executor.submit(item: dict) -> Ticket
    executor.wait_any(tickets, timeout: float) -> None   # returns when at
        # least one ticket is done, or after ``timeout`` seconds
    ticket.done() -> bool
    ticket.record -> dict | None        # None until done
    ticket.withdraw(reason="decided_skipped") -> bool   # True iff it had not started;
        # its record then becomes {"status": reason, ...}; ``stop_withdrawn`` is used for
        # attempts withdrawn because the whole batch stopped, never for early decisions

A record has ``status`` in {"valid", "infrastructure_error", "cancelled",
"deadline_skipped", "decided_skipped", ...} and, when valid, ``outcome`` in
{"success", "policy_failure", "invalid_scene"}. ``run_gates`` submits
``{**candidate["item"], "attempt": i}`` for attempt ``i``; the candidate's own
item is never modified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

OUTCOMES = ("success", "policy_failure", "invalid_scene")
FAILURE_DECISIONS = ("reproduces", "does_not_reproduce", "invalid_scene")
PASS_DECISIONS = ("passes", "fails", "invalid_scene")
KINDS = ("failure", "pass")
DEFAULT_WAIT_SECONDS = 5.0


class Ticket(Protocol):
    """One submitted attempt."""

    @property
    def record(self) -> Optional[Dict[str, Any]]: ...

    def done(self) -> bool: ...

    def withdraw(self, reason: str = "decided_skipped") -> bool: ...


class Executor(Protocol):
    """The minimal pool surface the gate scheduler needs."""

    def submit(self, item: Dict[str, Any]) -> Ticket: ...

    def wait_any(self, tickets: Sequence[Ticket], timeout: float) -> None: ...


# --- pure decisions ---------------------------------------------------------------


def _check(outcomes: Sequence[str], attempts: int, required_failures: Optional[int]) -> None:
    if type(attempts) is not int or attempts < 1:
        raise ValueError("attempts must be a positive integer")
    if required_failures is not None and (
            type(required_failures) is not int or not 1 <= required_failures <= attempts):
        raise ValueError("required_failures must be an integer between 1 and attempts")
    if isinstance(outcomes, (str, bytes)) or len(outcomes) > attempts:
        raise ValueError("a gate permits at most the stated number of attempts")
    if any(item not in OUTCOMES for item in outcomes):
        raise ValueError("only valid policy outcomes may enter a gate")


def decide(outcomes: Sequence[str], required_failures: int = 4, attempts: int = 5) -> Optional[str]:
    """Failure-gate decision from the outcomes observed so far (any order).

    Returns ``"reproduces"`` once ``required_failures`` policy failures are
    seen, ``"does_not_reproduce"`` once too few attempts remain to reach that
    count, ``"invalid_scene"`` if any attempt reports it, else ``None``.
    """

    _check(outcomes, attempts, required_failures)
    if "invalid_scene" in outcomes:
        return "invalid_scene"
    failures = list(outcomes).count("policy_failure")
    non_failures = len(outcomes) - failures
    if failures >= required_failures:
        return "reproduces"
    if non_failures > attempts - required_failures:
        return "does_not_reproduce"
    return None


def decide_pass(outcomes: Sequence[str], attempts: int = 5) -> Optional[str]:
    """Pass-gate decision: ``"fails"`` at the first non-success, ``"passes"`` at
    ``attempts`` successes, ``"invalid_scene"`` if any attempt reports it."""

    _check(outcomes, attempts, None)
    if "invalid_scene" in outcomes:
        return "invalid_scene"
    if any(item != "success" for item in outcomes):
        return "fails"
    if len(outcomes) == attempts:
        return "passes"
    return None


# --- scheduling --------------------------------------------------------------------


@dataclass
class GateRun:
    """Result of one ``run_gates`` batch (keys are the candidates' keys)."""

    decisions: Dict[str, Optional[str]] = field(default_factory=dict)
    outcomes: Dict[str, List[str]] = field(default_factory=dict)
    records: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    skipped: Dict[str, int] = field(default_factory=dict)            # early-decision savings only
    stop_withdrawn: Dict[str, int] = field(default_factory=dict)     # withdrawn because the batch stopped
    stop: Optional[str] = None           # None, "infrastructure_error" or "deadline_exhausted"
    detail: Optional[str] = None         # the record status or problem that caused the stop
    late: List[Tuple[str, Ticket]] = field(default_factory=list)

    @property
    def skipped_total(self) -> int:
        return sum(self.skipped.values())

    @property
    def stop_withdrawn_total(self) -> int:
        return sum(self.stop_withdrawn.values())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decisions": dict(self.decisions), "outcomes": {k: list(v) for k, v in self.outcomes.items()},
            "records": {k: list(v) for k, v in self.records.items()}, "skipped": dict(self.skipped),
            "skipped_total": self.skipped_total, "stop_withdrawn": dict(self.stop_withdrawn),
            "stop_withdrawn_total": self.stop_withdrawn_total, "stop": self.stop, "detail": self.detail,
            "late": len(self.late),
        }


class _Candidate:
    def __init__(self, key: str, item: Mapping[str, Any], kind: str) -> None:
        self.key, self.item, self.kind = key, item, kind
        self.tickets: List[Ticket] = []
        self.outcomes: List[str] = []
        self.records: List[Dict[str, Any]] = []
        self.skipped = 0
        self.stop_withdrawn = 0
        self.decision: Optional[str] = None


def _validate_candidates(candidates: Sequence[Mapping[str, Any]]) -> List[_Candidate]:
    result: List[_Candidate] = []
    seen = set()
    for entry in candidates:
        if not isinstance(entry, Mapping) or set(entry) != {"key", "item", "kind"}:
            raise ValueError("a candidate needs exactly key, item and kind")
        key, item, kind = entry["key"], entry["item"], entry["kind"]
        if type(key) is not str or not key or key in seen:
            raise ValueError("candidate keys must be unique non-empty strings")
        if not isinstance(item, Mapping):
            raise ValueError("candidate item must be an object")
        if kind not in KINDS:
            raise ValueError("candidate kind must be 'failure' or 'pass'")
        seen.add(key)
        result.append(_Candidate(key, item, kind))
    return result


def run_gates(
    executor: Executor,
    candidates: Sequence[Mapping[str, Any]],
    *,
    attempts: int = 5,
    required_failures: int = 4,
    max_in_flight: Optional[int] = None,
    remaining: Optional[Callable[[], Optional[float]]] = None,
    wait_timeout: float = DEFAULT_WAIT_SECONDS,
    drain: bool = False,
) -> GateRun:
    """Run independent gate candidates, deciding each as early as possible.

    ``candidates`` are ``{"key", "item", "kind"}`` with ``kind`` ``"failure"``
    (decided by ``decide``) or ``"pass"`` (``decide_pass``); the order is the
    submission priority. With ``max_in_flight=None`` every attempt is submitted
    up front and the not-yet-started ones are withdrawn when their candidate is
    decided. With an integer, at most that many unfinished tickets exist at a
    time (set it to the worker count): attempts are then submitted attempt-major
    round robin across the undecided candidates, so a decided candidate's later
    attempts are simply never submitted. Both count as skipped.

    A failure-gate candidate holds its last attempt back: it has at most
    ``required_failures`` tickets in flight until those are all back, and gets the
    remaining ones only if the gate is still undecided (with 4 of 5 that means exactly
    three failures among the first four). Pass gates submit all attempts.

    ``remaining()`` is the seconds left (``None`` = unlimited); at zero the
    batch stops with ``deadline_exhausted``. Any record that is neither valid nor
    ``decided_skipped`` stops the batch (``deadline_skipped`` as
    ``deadline_exhausted``, everything else as ``infrastructure_error``) and
    withdraws queued attempts; episodes already running are never killed.
    With ``drain`` the call waits for started attempts of decided candidates
    and records them; without it they are returned in ``late`` for
    ``collect_late`` so the caller can start its next round at once.
    """

    pool = _validate_candidates(candidates)
    if type(attempts) is not int or attempts < 1:
        raise ValueError("attempts must be a positive integer")
    if type(required_failures) is not int or not 1 <= required_failures <= attempts:
        raise ValueError("required_failures must be between 1 and attempts")
    if max_in_flight is not None and (type(max_in_flight) is not int or max_in_flight < 1):
        raise ValueError("max_in_flight must be a positive integer")

    run = GateRun()
    if not pool:
        return run

    pending: Dict[int, Tuple[_Candidate, Ticket]] = {}
    state: Dict[str, Optional[str]] = {"stop": None, "detail": None}

    def stop(reason: str, detail: str) -> None:
        if state["stop"] is None:
            state["stop"], state["detail"] = reason, detail

    def out_of_time() -> bool:
        if remaining is None:
            return False
        left = remaining()
        return left is not None and left <= 0

    def decide_for(candidate: _Candidate) -> Optional[str]:
        if candidate.kind == "pass":
            return decide_pass(candidate.outcomes, attempts)
        return decide(candidate.outcomes, required_failures, attempts)

    def limit(candidate: _Candidate) -> int:
        """How many attempts of ``candidate`` may be submitted now.

        A failure gate is fixed by its ``required_failures``-th failure or its second
        non-failure, and with ``required_failures`` attempts back the only open case is
        exactly one non-failure. So it gets at most ``required_failures`` tickets until
        those are all back, and the last attempt only if the gate is still undecided
        ("hold the fifth attempt"). A pass gate needs all of its attempts anyway.
        """

        if candidate.kind != "failure" or required_failures >= attempts:
            return attempts
        if len(candidate.tickets) >= required_failures and not any(
                owner is candidate for owner, _ in pending.values()):
            return attempts
        return required_failures

    def submit_more() -> None:
        while state["stop"] is None:
            if max_in_flight is not None and len(pending) >= max_in_flight:
                return
            choices = [c for c in pool if c.decision is None and len(c.tickets) < limit(c)]
            if not choices:
                return
            candidate = min(choices, key=lambda c: len(c.tickets))   # stable: first in order wins ties
            try:
                ticket = executor.submit({**candidate.item, "attempt": len(candidate.tickets)})
            except Exception as error:  # noqa: BLE001 - recorded by type only
                stop("infrastructure_error", "submit_" + type(error).__name__)
                return
            candidate.tickets.append(ticket)
            pending[id(ticket)] = (candidate, ticket)

    def process_finished() -> None:
        for ident, (candidate, ticket) in list(pending.items()):
            if not ticket.done():
                continue
            del pending[ident]
            record = ticket.record
            if not isinstance(record, dict):
                stop("infrastructure_error", "invalid_record")
                continue
            candidate.records.append(record)
            status = record.get("status")
            if status == "valid":
                outcome = record.get("outcome")
                if outcome not in OUTCOMES:
                    stop("infrastructure_error", "invalid_outcome")
                    continue
                candidate.outcomes.append(outcome)
                if candidate.decision is None:
                    candidate.decision = decide_for(candidate)
            elif status == "decided_skipped":
                continue
            elif status == "deadline_skipped":
                stop("deadline_exhausted", "deadline_skipped")
            else:
                stop("infrastructure_error", str(status))

    def withdraw_queued(only_decided: bool) -> None:
        for ident, (candidate, ticket) in list(pending.items()):
            if only_decided and candidate.decision is None:
                continue
            # An attempt of a decided candidate is an early-decision saving; one withdrawn only
            # because the batch stopped is not.
            decided = candidate.decision is not None
            if not ticket.done() and ticket.withdraw("decided_skipped" if decided else "stop_withdrawn"):
                if decided:
                    candidate.skipped += 1
                else:
                    candidate.stop_withdrawn += 1
                del pending[ident]
                if isinstance(ticket.record, dict):
                    candidate.records.append(ticket.record)

    def wait() -> None:
        timeout = wait_timeout
        if remaining is not None:
            left = remaining()
            if left is not None:
                timeout = max(0.0, min(timeout, left))
        executor.wait_any([ticket for _, ticket in pending.values()], timeout)

    if out_of_time():
        stop("deadline_exhausted", "deadline")
    while state["stop"] is None:
        submit_more()
        process_finished()
        withdraw_queued(only_decided=True)
        if state["stop"] is not None:
            break
        undecided = [c for c in pool if c.decision is None]
        if not undecided:
            break
        if not pending and not any(len(c.tickets) < limit(c) for c in undecided):
            stop("infrastructure_error", "undecided")
            break
        if out_of_time():
            stop("deadline_exhausted", "deadline")
            break
        if pending:
            wait()

    if state["stop"] is not None:
        withdraw_queued(only_decided=False)
    elif drain:
        while pending and state["stop"] is None:
            wait()
            process_finished()
            if out_of_time() and pending:
                stop("deadline_exhausted", "deadline")
        if state["stop"] is not None:
            withdraw_queued(only_decided=False)

    for candidate in pool:
        if candidate.decision is not None:
            candidate.skipped += attempts - len(candidate.tickets)     # never submitted
        run.decisions[candidate.key] = candidate.decision
        run.outcomes[candidate.key] = list(candidate.outcomes)
        run.records[candidate.key] = candidate.records
        run.skipped[candidate.key] = candidate.skipped
        run.stop_withdrawn[candidate.key] = candidate.stop_withdrawn
    run.stop, run.detail = state["stop"], state["detail"]
    run.late = [(candidate.key, ticket) for candidate, ticket in pending.values()]
    return run


def collect_late(
    executor: Executor,
    late: Sequence[Tuple[str, Ticket]],
    *,
    wait_timeout: float = DEFAULT_WAIT_SECONDS,
    remaining: Optional[Callable[[], Optional[float]]] = None,
) -> List[Tuple[str, Dict[str, Any]]]:
    """Wait for started attempts left over by ``run_gates(drain=False)``.

    Returns ``(key, record)`` for every one that finished, in completion order;
    ones still running when ``remaining()`` reaches zero are left out.
    """

    waiting = list(late)
    collected: List[Tuple[str, Dict[str, Any]]] = []
    while waiting:
        finished = [(key, ticket) for key, ticket in waiting if ticket.done()]
        for key, ticket in finished:
            collected.append((key, ticket.record if isinstance(ticket.record, dict) else {}))
        waiting = [(key, ticket) for key, ticket in waiting if not ticket.done()]
        if not waiting:
            break
        timeout = wait_timeout
        if remaining is not None:
            left = remaining()
            if left is not None:
                if left <= 0:
                    break
                timeout = min(timeout, left)
        executor.wait_any([ticket for _, ticket in waiting], timeout)
    return collected


__all__ = [
    "Executor", "FAILURE_DECISIONS", "GateRun", "OUTCOMES", "PASS_DECISIONS", "Ticket",
    "collect_late", "decide", "decide_pass", "run_gates",
]
