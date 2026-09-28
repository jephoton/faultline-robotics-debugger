"""Durable, JSON-only ownership state for fixed replay attempts."""

from __future__ import annotations

import json
from typing import Any


_PREPARED = "prepared"
_SUBMITTING_UNKNOWN = "submitting_unknown"
_ACTIVE = "active"
_COMPLETING_PENDING = "completing_pending"
_TERMINAL = "terminal"


class AttemptLedger:
    """Own one immutable manifest's attempt states and terminal records.

    The scheduler persists :meth:`snapshot` between transitions.  Runtime
    Future objects deliberately stay outside this object.
    """

    def __init__(self, case_ids: list[str]) -> None:
        if not isinstance(case_ids, list) or not case_ids:
            raise ValueError("case_ids must be a non-empty list")
        if any(not isinstance(case_id, str) or not case_id for case_id in case_ids):
            raise ValueError("case_ids must be non-empty strings")
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case_ids must be unique")
        self._attempts: dict[str, dict[str, Any]] = {
            case_id: {"state": _PREPARED} for case_id in case_ids
        }

    @classmethod
    def from_snapshot(cls, case_ids: list[str], snapshot: dict[str, Any]) -> "AttemptLedger":
        """Restore a validated ledger from its authoritative durable records."""
        ledger = cls(case_ids)
        if not isinstance(snapshot, dict):
            raise ValueError("snapshot must be a dictionary")
        records = snapshot.get("attempt_records")
        if not isinstance(records, dict) or set(records) != set(ledger._attempts):
            raise ValueError("attempt_records must contain exactly the manifest case_ids")
        for case_id in ledger._attempts:
            record = records[case_id]
            if not isinstance(record, dict):
                raise ValueError("attempt record must be a dictionary")
            state = record.get("state")
            if state in {_PREPARED, _SUBMITTING_UNKNOWN, _ACTIVE}:
                if set(record) != {"state"}:
                    raise ValueError("nonterminal attempt record has unexpected fields")
                ledger._attempts[case_id] = {"state": state}
            elif state in {_COMPLETING_PENDING, _TERMINAL}:
                if set(record) != {"state", "result"}:
                    raise ValueError("completed attempt record requires exactly one result")
                ledger._attempts[case_id] = {
                    "state": state,
                    "result": _result_copy(case_id, record["result"]),
                }
            else:
                raise ValueError("attempt record has an invalid state")
        return ledger

    @property
    def attempts(self) -> dict[str, dict[str, Any]]:
        """Return a copy for inspection without exposing ledger ownership."""
        return _json_copy(self._attempts)

    def begin_submit(self, case_id: str) -> None:
        state = self._state(case_id)
        if state == _PREPARED:
            self._attempts[case_id] = {"state": _SUBMITTING_UNKNOWN}
        elif state != _SUBMITTING_UNKNOWN:
            self._illegal(case_id, "begin_submit")

    def register_active(self, case_id: str) -> None:
        state = self._state(case_id)
        if state == _SUBMITTING_UNKNOWN:
            self._attempts[case_id]["state"] = _ACTIVE
        elif state != _ACTIVE:
            self._illegal(case_id, "register_active")

    def capture_result(self, case_id: str, result: dict[str, Any], *, interrupted: bool) -> None:
        if not isinstance(interrupted, bool):
            raise ValueError("interrupted must be a boolean")
        state = self._state(case_id)
        copied = _result_copy(case_id, result)
        if interrupted and copied.get("status") == "valid":
            copied["status"] = "infrastructure_error"
            previous = copied.get("infrastructure_error")
            message = "interrupted before completion could be classified"
            copied["infrastructure_error"] = (
                message if previous is None else f"{previous}; {message}"
            )
        if state == _ACTIVE:
            self._attempts[case_id] = {"state": _COMPLETING_PENDING, "result": copied}
        elif state == _COMPLETING_PENDING:
            if self._attempts[case_id]["result"] != copied:
                self._illegal(case_id, "capture_result with a different result")
        elif state == _TERMINAL:
            if self._attempts[case_id]["result"] != copied:
                self._illegal(case_id, "capture_result with a different terminal result")
        else:
            self._illegal(case_id, "capture_result")

    def finish(self, case_id: str) -> None:
        state = self._state(case_id)
        if state == _COMPLETING_PENDING:
            self._attempts[case_id]["state"] = _TERMINAL
        elif state != _TERMINAL:
            self._illegal(case_id, "finish")

    def cancel_unstarted(self, case_id: str) -> None:
        """Return caller-proven never-started work to the launchable state."""
        if self._state(case_id) not in {_SUBMITTING_UNKNOWN, _ACTIVE}:
            self._illegal(case_id, "cancel_unstarted")
        self._attempts[case_id] = {"state": _PREPARED}

    def snapshot(self) -> dict[str, Any]:
        """Return legacy summary fields derived from the one authoritative map."""
        states = {case_id: attempt["state"] for case_id, attempt in self._attempts.items()}
        results = [
            _json_copy(attempt["result"])
            for attempt in self._attempts.values()
            if attempt["state"] == _TERMINAL
        ]
        return {
            "attempt_states": states,
            "attempt_records": _json_copy(self._attempts),
            "results": results,
            "valid_count": sum(result.get("status") == "valid" for result in results),
            "in_flight_ids": [
                case_id for case_id, state in states.items() if state not in {_PREPARED, _TERMINAL}
            ],
        }

    def _state(self, case_id: str) -> str:
        try:
            return self._attempts[case_id]["state"]
        except KeyError as error:
            raise ValueError(f"unknown case_id: {case_id}") from error

    @staticmethod
    def _illegal(case_id: str, transition: str) -> None:
        raise ValueError(f"illegal transition for {case_id}: {transition}")


def _result_copy(case_id: str, result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise ValueError("result must be a dictionary")
    copied = _json_copy(result)
    if copied.get("case_id") != case_id:
        raise ValueError("result case_id must match the attempt")
    return copied


def _json_copy(value: Any) -> Any:
    """Copy while rejecting non-JSON-compatible values and non-finite numbers."""
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise ValueError("ledger values must be JSON-compatible") from error
