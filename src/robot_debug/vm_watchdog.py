"""Fail-closed, exact-instance Nebius VM watchdog primitives.

This module deliberately has no discovery or start operation.  A caller must
provide one validated immutable instance ID in an ignored local run record.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import os
import time
from typing import Any


_EXPECTED_KEYS = {
    "schema_version", "instance_id", "project_id", "deadline_utc", "run_label",
    "wsl_cli_path", "log_path",
}
_INSTANCE_ID = re.compile(r"computeinstance-[A-Za-z0-9][A-Za-z0-9-]*\Z")
_PROJECT_ID = re.compile(r"project-[A-Za-z0-9][A-Za-z0-9-]*\Z")
_RUN_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


class RecordError(ValueError):
    """The untrusted local run record cannot safely control a VM."""


class TargetMismatch(RecordError):
    """The exact-instance read-back contradicts the immutable run record."""


@dataclass(frozen=True)
class GuardRecord:
    instance_id: str
    project_id: str
    deadline_utc: datetime
    run_label: str
    wsl_cli_path: str
    log_path: Path

    def get_command(self) -> list[str]:
        return [
            r"C:\Windows\System32\wsl.exe", "--exec", self.wsl_cli_path,
            "compute", "instance", "get", "--id", self.instance_id,
            "--format", "json", "--no-browser", "--timeout", "30s", "--no-check-update",
        ]

    def stop_command(self) -> list[str]:
        return [
            r"C:\Windows\System32\wsl.exe", "--exec", self.wsl_cli_path,
            "compute", "instance", "stop", "--id", self.instance_id,
            "--no-browser", "--timeout", "30s", "--no-check-update",
        ]


def load_record(path: Path, *, control_root: Path, now_utc: datetime) -> GuardRecord:
    """Validate a run record without accepting secrets or broad targets."""

    record_path = _contained_absolute_path(str(Path(path).resolve()), Path(control_root))
    try:
        raw = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecordError("record must be readable JSON") from error
    if not isinstance(raw, dict) or set(raw) != _EXPECTED_KEYS:
        raise RecordError("record must contain exactly the approved keys")
    if raw["schema_version"] != 1:
        raise RecordError("unsupported record schema_version")
    instance_id = _required_string(raw, "instance_id", _INSTANCE_ID)
    project_id = _required_string(raw, "project_id", _PROJECT_ID)
    run_label = _required_string(raw, "run_label", _RUN_LABEL)
    cli_path = _required_string(raw, "wsl_cli_path", None)
    if not cli_path.startswith("/") or "\x00" in cli_path:
        raise RecordError("wsl_cli_path must be an absolute POSIX path")
    deadline = _parse_utc(raw.get("deadline_utc"))
    current = _as_utc(now_utc)
    if deadline <= current:
        raise RecordError("deadline_utc must be in the future")
    log_path = _contained_absolute_path(raw.get("log_path"), Path(control_root))
    return GuardRecord(instance_id, project_id, deadline, run_label, cli_path, log_path)


def _required_string(raw: dict[str, Any], name: str, pattern: re.Pattern[str] | None) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value or (pattern is not None and not pattern.fullmatch(value)):
        raise RecordError("{} is invalid".format(name))
    return value


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise RecordError("deadline_utc must be RFC3339 UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise RecordError("deadline_utc must be RFC3339 UTC") from error
    if parsed.tzinfo != timezone.utc:
        raise RecordError("deadline_utc must be UTC")
    return parsed


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise RecordError("now_utc must be timezone-aware")
    return value.astimezone(timezone.utc)


def _contained_absolute_path(value: Any, control_root: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise RecordError("log_path is invalid")
    candidate = Path(value)
    if not candidate.is_absolute():
        raise RecordError("log_path must be absolute")
    root = control_root.resolve()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise RecordError("log_path must be inside control_root") from error
    return resolved


def watch(
    record: GuardRecord,
    *,
    invoke: Any,
    now: Any = lambda: datetime.now(timezone.utc),
    sleep: Any = time.sleep,
    monotonic: Any = time.monotonic,
    poll_seconds: float = 5.0,
    retries: int = 3,
) -> str:
    """Verify and stop exactly ``record.instance_id`` at its deadline.

    ``invoke`` is intentionally injected: production wiring owns the process
    boundary and tests never need credentials or a Nebius CLI.
    """

    audit = _AuditLog(record.log_path)
    try:
        initial = _get_verified(record, invoke)
        audit.write("verified", state=_state(initial))
        audit.write("armed", deadline_utc=_timestamp(record.deadline_utc))
        _wait_until(record.deadline_utc, now, sleep, monotonic)
        audit.write("deadline_reached")
        deadline_state = None
        for attempt in range(retries):
            try:
                deadline_state = _get_verified(record, invoke)
                break
            except TargetMismatch:
                audit.write("stop_unconfirmed", reason="target_readback_mismatch")
                return "stop_unconfirmed"
            except Exception as error:
                audit.write("deadline_get_failed", attempt=attempt + 1, error=type(error).__name__)
        if deadline_state is not None and _state(deadline_state) == "STOPPED":
            audit.write("already_stopped")
            return "already_stopped"
        # The initial lookup already verified the immutable target. If later
        # reads fail transiently, still issue the exact-ID stop rather than
        # abandoning an active billable VM.
        if not _retry_stop(record, invoke, retries, audit):
            audit.write("stop_unconfirmed", reason="stop_command_failed")
            return "stop_unconfirmed"
        audit.write("stop_requested")
        for _ in range(retries):
            try:
                current = _get_verified(record, invoke)
            except Exception as error:  # diagnostic, then bounded retry
                audit.write("poll_failed", error=type(error).__name__)
                continue
            state = _state(current)
            if state == "STOPPED":
                audit.write("stop_confirmed")
                return "stop_confirmed"
            audit.write("polling", state=state)
            sleep(poll_seconds)
        audit.write("stop_unconfirmed", reason="poll_retry_exhausted")
        return "stop_unconfirmed"
    except Exception as error:
        audit.write("exception", error=type(error).__name__)
        raise


def _wait_until(deadline: datetime, now: Any, sleep: Any, monotonic: Any) -> None:
    remaining = max(0.0, (deadline - _as_utc(now())).total_seconds())
    target = monotonic() + remaining
    while True:
        remaining = target - monotonic()
        if remaining <= 0:
            return
        sleep(min(remaining, 5.0))


def _retry_stop(record: GuardRecord, invoke: Any, retries: int, audit: "_AuditLog") -> bool:
    if not isinstance(retries, int) or retries < 1:
        raise ValueError("retries must be a positive integer")
    for attempt in range(retries):
        try:
            invoke(record.stop_command())
            return True
        except Exception as error:
            audit.write("stop_failed", attempt=attempt + 1, error=type(error).__name__)
    return False


def _get_verified(record: GuardRecord, invoke: Any) -> dict[str, Any]:
    result = _decode_result(invoke(record.get_command()))
    metadata = result.get("metadata")
    instance_id = metadata.get("id") if isinstance(metadata, dict) else None
    parent_id = metadata.get("parent_id") if isinstance(metadata, dict) else None
    if instance_id != record.instance_id:
        raise TargetMismatch("exact instance read-back ID does not match target")
    if parent_id != record.project_id:
        raise TargetMismatch("exact instance read-back parent does not match project")
    return result


def _decode_result(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise RecordError("CLI returned malformed JSON") from error
    if not isinstance(value, dict):
        raise RecordError("CLI result must be a JSON object")
    return value


def _state(result: dict[str, Any]) -> str:
    status = result.get("status")
    state = status.get("state") if isinstance(status, dict) else None
    if not isinstance(state, str) or not state:
        raise RecordError("exact instance read-back has no status.state")
    return state


def _timestamp(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


class _AuditLog:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, **fields: Any) -> None:
        payload = {"timestamp_utc": _timestamp(datetime.now(timezone.utc)), "event": event}
        payload.update(fields)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        with self._path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
