"""Validated immutable authority records and durable local run ownership."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import stat
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


class RecordError(ValueError):
    """An input record or persisted run state violates the safety contract."""


_TOP_KEYS = {
    "schema_version", "run_label", "project_id", "temporary", "protected",
    "approval", "deadlines", "paths", "pins", "ssh", "preflight",
}
_KEYS = {
    "temporary": {"instance_id", "disk_id", "snapshot_id", "ssh_rule_id"},
    "protected": {"instance_id", "disk_id"},
    "approval": {"reference", "max_total_usd", "max_starts", "max_runtime_seconds", "temporary_cleanup"},
    "deadlines": {"start_not_after_utc", "stop_request_utc", "stop_confirm_by_utc", "storage_cleanup_utc"},
    "paths": {"run_dir", "source_bundle", "manifest", "known_hosts", "ssh_identity_file", "guest_session", "wsl_cli"},
    "pins": {"source_sha", "bundle_sha256", "manifest_sha256", "upstream_sha", "checkpoint_id", "checkpoint_revision", "simulator_digest"},
    "ssh": {"user", "host_key_sha256", "port"},
    "preflight": {"checked_at_utc", "balance_usd", "pending_usd", "estimated_total_usd", "hourly_rate_usd", "expiry_checked", "quota_checked", "capacity_checked", "billing_checked"},
}
_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z", re.ASCII)
_APPROVAL_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z", re.ASCII)
_CREDENTIAL_MARKER = re.compile(r"token|password|secret|credential|private[_-]?key", re.IGNORECASE | re.ASCII)
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z")
_SERVICE_PREFIXES = {
    "instance_id": "computeinstance-",
    "disk_id": "computedisk-",
    "snapshot_id": "computedisksnapshot-",
    "ssh_rule_id": "vpcsecurityrule-",
    "project_id": "project-",
}
_EVENT_FIELDS = {
    "owner_id", "phase", "status", "operation_id", "timestamp_utc", "instance_id",
    "disk_id", "snapshot_id", "ssh_rule_id", "exit_code", "exit_classification",
    "reason", "attempt", "elapsed_seconds", "cost_usd", "verified", "artifact_count",
}
_EVENT_STRING = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .,_:/@+-]{0,255}\Z", re.ASCII)
_POSIX_SEGMENT = re.compile(r"[A-Za-z0-9._-]+\Z", re.ASCII)


def _fail(message: str) -> None:
    raise RecordError(message)


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{label} must be an object")
    unknown = set(value) - expected
    missing = expected - set(value)
    if unknown or missing:
        _fail(f"{label} has invalid fields (unknown={sorted(unknown)}, missing={sorted(missing)})")
    return value


def _duplicate_rejector(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not _UTC.fullmatch(value):
        _fail(f"{label} must be RFC3339 UTC ending in Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise RecordError(f"{label} is not a real UTC timestamp") from exc


def _number(value: Any, label: str, *, positive: bool) -> float:
    if type(value) not in (int, float):
        _fail(f"{label} must be a finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        _fail(f"{label} must be a finite number")
    if (positive and value <= 0) or (not positive and value < 0):
        _fail(f"{label} is outside its allowed range")
    return float(value)


def _int(value: Any, label: str, *, positive: bool = False) -> int:
    if type(value) is not int or (positive and value <= 0):
        _fail(f"{label} must be an exact integer" + (" greater than zero" if positive else ""))
    return value


def _service_id(value: Any, prefix: str, label: str) -> None:
    if not isinstance(value, str) or not value.startswith(prefix) or not _SAFE.fullmatch(value[len(prefix):]):
        _fail(f"{label} has an invalid service identity")


def _reparse(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(path.lstat().st_file_attributes & 0x400)
    except (AttributeError, OSError):
        return path.is_symlink()


def _reject_reparse_chain(path: Path, stop: Path | None = None) -> None:
    current = path
    chain = []
    while current != current.parent:
        chain.append(current)
        if stop is not None and current == stop:
            break
        current = current.parent
    for component in reversed(chain):
        if _reparse(component):
            _fail(f"reparse point is not allowed in writable path: {component}")


def _contained(path: Path, root: Path, label: str, *, strict: bool = False, existing: bool = True) -> Path:
    try:
        resolved = path.resolve(strict=existing)
        common = os.path.commonpath((str(resolved), str(root)))
    except (OSError, ValueError, RuntimeError) as exc:
        raise RecordError(f"{label} cannot be resolved") from exc
    if common != str(root) or (strict and resolved == root):
        _fail(f"{label} is outside its required control directory")
    return resolved


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise RecordError(f"cannot read pinned input file: {path}") from exc
    return digest.hexdigest()


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class CloudRunRecord:
    """A validated record whose nested values cannot be changed after loading."""

    run_label: str
    project_id: str
    temporary: Mapping[str, Any]
    protected: Mapping[str, Any]
    approval: Mapping[str, Any]
    deadlines: Mapping[str, Any]
    paths: Mapping[str, Any]
    pins: Mapping[str, Any]
    ssh: Mapping[str, Any]
    preflight: Mapping[str, Any]
    raw: Mapping[str, Any]
    digest: str


def load_record(
    path: str | os.PathLike[str],
    *,
    control_root: str | os.PathLike[str],
    now_utc: datetime,
    require_future: bool = True,
) -> CloudRunRecord:
    """Load, validate and hash a strict version-1 launcher run record."""
    if not isinstance(now_utc, datetime) or now_utc.tzinfo is None or now_utc.utcoffset() != timezone.utc.utcoffset(now_utc):
        _fail("now_utc must be a timezone-aware UTC datetime")
    now_utc = now_utc.astimezone(timezone.utc)
    try:
        with Path(path).open("r", encoding="utf-8") as stream:
            data = json.load(stream, object_pairs_hook=_duplicate_rejector, parse_constant=lambda value: _fail(f"invalid JSON number: {value}"))
    except RecordError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RecordError("record cannot be read as JSON") from exc

    _exact_keys(data, _TOP_KEYS, "record")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        _fail("schema_version must be integer 1")
    if not isinstance(data["run_label"], str) or not _SAFE.fullmatch(data["run_label"]):
        _fail("run_label must be a safe ASCII filename component")
    _service_id(data["project_id"], "project-", "project_id")
    obj = {key: _exact_keys(data[key], expected, key) for key, expected in _KEYS.items()}

    for key, prefix in _SERVICE_PREFIXES.items():
        if key == "project_id":
            continue
        if key in obj["temporary"]:
            _service_id(obj["temporary"][key], prefix, f"temporary.{key}")
        if key in obj["protected"]:
            _service_id(obj["protected"][key], prefix, f"protected.{key}")
    if obj["temporary"]["instance_id"] == obj["protected"]["instance_id"] or obj["temporary"]["disk_id"] == obj["protected"]["disk_id"]:
        _fail("temporary resource identity collides with a protected resource")

    approval = obj["approval"]
    if (
        not isinstance(approval["reference"], str)
        or not _APPROVAL_REF.fullmatch(approval["reference"])
        or _CREDENTIAL_MARKER.search(approval["reference"])
    ):
        _fail("approval.reference must be a safe ASCII identifier of at most 128 characters")
    _number(approval["max_total_usd"], "approval.max_total_usd", positive=True)
    if _int(approval["max_starts"], "approval.max_starts") != 1:
        _fail("approval.max_starts must equal one")
    _int(approval["max_runtime_seconds"], "approval.max_runtime_seconds", positive=True)
    if type(approval["temporary_cleanup"]) is not bool or not approval["temporary_cleanup"]:
        _fail("approval.temporary_cleanup must be true")

    deadlines = obj["deadlines"]
    deadline_times = {key: _parse_utc(value, f"deadlines.{key}") for key, value in deadlines.items()}
    start, request, confirm, cleanup = (deadline_times[key] for key in ("start_not_after_utc", "stop_request_utc", "stop_confirm_by_utc", "storage_cleanup_utc"))
    if not start < request < confirm <= cleanup:
        _fail("deadlines must be ordered start < stop request < stop confirmation <= storage cleanup")
    if (confirm - start).total_seconds() > approval["max_runtime_seconds"]:
        _fail("stop confirmation deadline exceeds the approved maximum runtime from the latest start")
    if (confirm - request).total_seconds() < 180:
        _fail("stop confirmation deadline must reserve at least 180 seconds after stop request")
    if require_future and start <= now_utc:
        _fail("start deadline has expired")

    paths = obj["paths"]
    root_path = Path(control_root)
    if not root_path.is_absolute():
        _fail("control_root must be absolute")
    try:
        root = root_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RecordError("control_root must be an existing directory") from exc
    if not root.is_dir() or _reparse(root_path):
        _fail("control_root must be a directory")
    local_paths: dict[str, Path] = {}
    for key in ("run_dir", "source_bundle", "manifest", "known_hosts", "ssh_identity_file"):
        if not isinstance(paths[key], str) or not Path(paths[key]).is_absolute():
            _fail(f"paths.{key} must be an absolute local path")
        local_paths[key] = Path(paths[key])
    run_dir = local_paths["run_dir"]
    resolved_run = _contained(run_dir, root, "paths.run_dir", strict=True)
    if not resolved_run.is_dir():
        _fail("paths.run_dir must be an existing directory")
    _reject_reparse_chain(run_dir, root_path.resolve())
    for key in ("source_bundle", "manifest"):
        resolved = _contained(local_paths[key], root, f"paths.{key}", existing=require_future)
        if require_future and (not resolved.is_file() or _reparse(local_paths[key]) or _reparse(resolved)):
            _fail(f"paths.{key} must be an existing regular file, not a reparse point")
    for key in ("known_hosts", "ssh_identity_file"):
        local = local_paths[key]
        if not require_future:
            continue
        try:
            resolved = local.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise RecordError(f"paths.{key} must be an existing regular file") from exc
        if not resolved.is_file() or _reparse(local):
            _fail(f"paths.{key} must be an explicit regular file")

    if require_future:
        key_path = local_paths["ssh_identity_file"].resolve(strict=True)
        for key in ("source_bundle", "manifest"):
            candidate = local_paths[key].resolve(strict=True)
            try:
                aliases_key = candidate == key_path or os.path.samefile(candidate, key_path)
            except OSError as exc:
                raise RecordError(f"cannot safely compare paths.{key} with the SSH identity file") from exc
            if aliases_key:
                _fail(f"paths.{key} cannot alias the SSH identity file")

    guest = paths["guest_session"]
    if not isinstance(guest, str) or not guest.startswith("/home/robot/"):
        _fail("paths.guest_session must be a dedicated path under /home/robot")
    segments = guest.split("/")[3:]
    if not segments or any(not _SAFE.fullmatch(segment) for segment in segments):
        _fail("paths.guest_session contains an unsafe path segment")
    wsl_cli = paths["wsl_cli"]
    wsl_parts = wsl_cli.split("/")[1:] if isinstance(wsl_cli, str) else []
    if not isinstance(wsl_cli, str) or not wsl_cli.startswith("/") or "\\" in wsl_cli or not wsl_parts or any(part in ("", ".", "..") or not _POSIX_SEGMENT.fullmatch(part) for part in wsl_parts):
        _fail("paths.wsl_cli must be an absolute safe POSIX path")

    pins = obj["pins"]
    for key in ("source_sha", "upstream_sha", "checkpoint_revision"):
        if not isinstance(pins[key], str) or not _HEX40.fullmatch(pins[key]):
            _fail(f"pins.{key} must be a 40-character lowercase SHA")
    for key in ("bundle_sha256", "manifest_sha256"):
        if not isinstance(pins[key], str) or not _HEX64.fullmatch(pins[key]):
            _fail(f"pins.{key} must be a 64-character lowercase SHA256")
    if not isinstance(pins["simulator_digest"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", pins["simulator_digest"]):
        _fail("pins.simulator_digest must be sha256:<64 lowercase hex>")
    if not isinstance(pins["checkpoint_id"], str) or not re.fullmatch(r"nvidia/gr00t[0-9A-Za-z._-]+(?:/[A-Za-z0-9._-]+)*", pins["checkpoint_id"]):
        _fail("pins.checkpoint_id must identify a safe NVIDIA GR00T checkpoint")
    if require_future:
        for key, pin in (("source_bundle", "bundle_sha256"), ("manifest", "manifest_sha256")):
            if _hash_file(local_paths[key]) != pins[pin]:
                _fail(f"paths.{key} content does not match its pinned digest")

    ssh = obj["ssh"]
    if ssh["user"] != "robot":
        _fail("ssh.user must be robot")
    host_pin = ssh["host_key_sha256"]
    if not isinstance(host_pin, str) or not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}", host_pin):
        _fail("ssh.host_key_sha256 must be a SHA256 OpenSSH fingerprint")
    try:
        if len(base64.b64decode(host_pin[7:] + "=", validate=True)) != 32:
            _fail("ssh.host_key_sha256 must encode 32 bytes")
    except ValueError as exc:
        raise RecordError("ssh.host_key_sha256 must be a valid base64 digest") from exc
    if _int(ssh["port"], "ssh.port") != 22:
        _fail("ssh.port must equal 22")

    preflight = obj["preflight"]
    checked = _parse_utc(preflight["checked_at_utc"], "preflight.checked_at_utc")
    balance = _number(preflight["balance_usd"], "preflight.balance_usd", positive=True)
    pending = _number(preflight["pending_usd"], "preflight.pending_usd", positive=False)
    estimate = _number(preflight["estimated_total_usd"], "preflight.estimated_total_usd", positive=True)
    _number(preflight["hourly_rate_usd"], "preflight.hourly_rate_usd", positive=True)
    for key in ("expiry_checked", "quota_checked", "capacity_checked", "billing_checked"):
        if type(preflight[key]) is not bool or not preflight[key]:
            _fail(f"preflight.{key} must be true")
    if balance - pending < estimate:
        _fail("preflight available balance does not cover the estimate")
    if estimate > approval["max_total_usd"]:
        _fail("preflight estimate exceeds the approved cap")
    if require_future and (checked > now_utc or (now_utc - checked).total_seconds() > 600):
        _fail("preflight must be current, nonfuture, and no more than ten minutes old")

    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
    frozen = _freeze(data)
    return CloudRunRecord(
        run_label=data["run_label"], project_id=data["project_id"],
        temporary=_freeze(obj["temporary"]), protected=_freeze(obj["protected"]),
        approval=_freeze(approval), deadlines=_freeze(deadlines), paths=_freeze(paths),
        pins=_freeze(pins), ssh=_freeze(ssh), preflight=_freeze(preflight),
        raw=frozen, digest=hashlib.sha256(canonical).hexdigest(),
    )


def _safe_snapshot(value: Any, label: str = "snapshot") -> Any:
    if isinstance(value, dict):
        clean = {}
        for key, child in value.items():
            if not isinstance(key, str) or not _SAFE.fullmatch(key) or re.search(r"secret|token|password|credential|stderr|command|private.?key", key, re.I):
                _fail(f"{label} contains an unsafe field name")
            clean[key] = _safe_snapshot(child, f"{label}.{key}")
        return clean
    if isinstance(value, list):
        return [_safe_snapshot(item, label) for item in value]
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            _fail(f"{label} contains a nonfinite number")
        return value
    if isinstance(value, str):
        if len(value) > 512 or "\n" in value or "\r" in value or re.search(r"-----BEGIN .*PRIVATE KEY-----|\b(?:token|password|secret)=|\b(?:nebius|ssh|scp|powershell|bash)\s+[-A-Za-z]", value, re.I):
            _fail(f"{label} contains unsafe text")
        return value
    _fail(f"{label} contains an unsupported value")


class RunStore:
    """Exclusive local run identity, event journal, status and controller lease."""

    def __init__(self, run_dir: str | os.PathLike[str], *, record_path: str | os.PathLike[str]):
        self.run_dir = Path(run_dir)
        self.record_path = Path(record_path)
        self.identity_path = self.run_dir / "identity.json"
        self.events_path = self.run_dir / "events.jsonl"
        self.status_path = self.run_dir / "status.json"
        self.lease_path = self.run_dir / "lease.json"
        self._lease_fd: int | None = None
        self._lease_owner: str | None = None
        self._mutex = threading.RLock()
        self._validate_run_dir()
        self._validate_record_path()
        self._expected_digest: str | None = None
        fresh = self._fresh_record_digest()
        if self._assert_regular_target(self.identity_path, allow_missing=True) is not None:
            self._expected_digest = fresh
            self._checked_identity()

    @property
    def record_digest(self) -> str:
        return self._checked_identity()

    def _created(self) -> str:
        return self._checked_identity()

    def _validate_run_dir(self) -> None:
        if not self.run_dir.is_absolute() or not self.run_dir.is_dir():
            _fail("run directory must be an existing absolute directory")
        _reject_reparse_chain(self.run_dir)

    def _validate_record_path(self) -> None:
        if not self.record_path.is_absolute():
            _fail("record_path must be absolute")
        _reject_reparse_chain(self.record_path)
        info = self._assert_regular_target(self.record_path, allow_missing=False)
        if info is None:
            _fail("record_path must be an existing regular file")

    def _assert_regular_target(self, path: Path, *, allow_missing: bool) -> os.stat_result | None:
        self._validate_run_dir()
        try:
            info = path.lstat()
        except FileNotFoundError:
            if allow_missing:
                return None
            _fail(f"required local file is missing: {path.name}")
        except OSError as exc:
            raise RecordError(f"cannot inspect local file: {path.name}") from exc
        if _reparse(path) or not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
            _fail(f"local file is not an isolated regular file: {path.name}")
        return info

    def _open_checked(self, path: Path, flags: int, *, mode: int = 0o600, allow_missing: bool = False) -> int:
        before = self._assert_regular_target(path, allow_missing=allow_missing)
        if allow_missing and before is None and flags & os.O_CREAT:
            flags |= os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags, mode)
        except OSError as exc:
            raise RecordError(f"could not safely open local file: {path.name}") from exc
        try:
            opened = os.fstat(fd)
            after = path.lstat()
            if not stat.S_ISREG(opened.st_mode) or after.st_nlink > 1 or not os.path.samestat(opened, after):
                _fail(f"local file changed during open: {path.name}")
            if before is not None and not os.path.samestat(before, opened):
                _fail(f"local file changed during open: {path.name}")
            return fd
        except Exception:
            os.close(fd)
            raise

    @staticmethod
    def _read_fd(fd: int) -> bytes:
        with os.fdopen(fd, "rb") as stream:
            return stream.read()

    @staticmethod
    def _canonical_digest(raw: bytes, label: str) -> str:
        try:
            data = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_duplicate_rejector,
                parse_constant=lambda value: _fail(f"invalid JSON number: {value}"),
            )
            canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
        except (RecordError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RecordError(f"{label} is not valid canonicalizable JSON") from exc
        return hashlib.sha256(canonical).hexdigest()

    def _fresh_record_digest(self) -> str:
        self._validate_run_dir()
        self._validate_record_path()
        fd = self._open_checked(self.record_path, os.O_RDONLY)
        raw = self._read_fd(fd)
        self._assert_record_run_dir(raw)
        return self._canonical_digest(raw, "record file")

    def _assert_record_run_dir(self, raw: bytes) -> None:
        try:
            data = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_rejector)
        except (RecordError, UnicodeError, json.JSONDecodeError) as exc:
            raise RecordError("record file is not valid JSON") from exc
        if not isinstance(data, dict) or not isinstance(data.get("paths"), dict):
            _fail("record file does not contain paths.run_dir")
        recorded = data["paths"].get("run_dir")
        if not isinstance(recorded, str) or not Path(recorded).is_absolute():
            _fail("record paths.run_dir must be absolute")
        try:
            recorded_path = Path(recorded).resolve(strict=True)
            store_path = self.run_dir.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RecordError("record and store run directories must resolve") from exc
        canonical_recorded = os.path.normcase(os.path.normpath(str(recorded_path)))
        canonical_store = os.path.normcase(os.path.normpath(str(store_path)))
        if canonical_recorded != canonical_store:
            _fail("RunStore directory does not match immutable record paths.run_dir")

    def _checked_identity(self) -> str:
        self._validate_run_dir()
        fresh = self._fresh_record_digest()
        if self._expected_digest is None:
            _fail("run store has no trusted record identity")
        if fresh != self._expected_digest:
            _fail("immutable record file changed after RunStore was opened")
        fd = self._open_checked(self.identity_path, os.O_RDONLY)
        try:
            identity = json.loads(self._read_fd(fd).decode("utf-8"), object_pairs_hook=_duplicate_rejector)
        except (RecordError, UnicodeError, json.JSONDecodeError) as exc:
            raise RecordError("run identity is missing or corrupt") from exc
        if not isinstance(identity, dict) or set(identity) != {"record_digest"} or identity["record_digest"] != self._expected_digest:
            _fail("run identity does not match the immutable original record")
        return self._expected_digest

    def _reject_existing_state(self) -> None:
        self._validate_run_dir()
        for path in (self.identity_path, self.events_path, self.status_path, self.lease_path):
            if self._assert_regular_target(path, allow_missing=True) is not None:
                _fail(f"run store already contains owned state: {path.name}")
        try:
            leftovers = [path for path in self.run_dir.iterdir() if path.name.startswith(".status-")]
        except OSError as exc:
            raise RecordError("cannot inspect run directory for interrupted status snapshots") from exc
        if leftovers:
            _fail("run store contains an interrupted status snapshot; refusing adoption")

    def create(self, record_digest: str) -> None:
        self._validate_run_dir()
        fresh = self._fresh_record_digest()
        if not isinstance(record_digest, str) or not _HEX64.fullmatch(record_digest) or record_digest != fresh or (self._expected_digest is not None and fresh != self._expected_digest):
            _fail("create digest must match the freshly read immutable record")
        self._reject_existing_state()
        payload = json.dumps({"record_digest": record_digest}, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        try:
            fd = self._open_checked(self.identity_path, os.O_WRONLY | os.O_CREAT, allow_missing=True)
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            self._fsync_directory()
            self._expected_digest = record_digest
        except OSError as exc:
            raise RecordError("could not durably create run identity") from exc

    def append(self, event: str, **safe_fields: Any) -> None:
        self._created()
        if not isinstance(event, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", event):
            _fail("event must be a safe lowercase identifier")
        unknown = set(safe_fields) - _EVENT_FIELDS
        if unknown:
            _fail(f"event has unsafe or unknown fields: {sorted(unknown)}")
        row = {"event": event}
        for key, value in safe_fields.items():
            row[key] = self._safe_event_value(value, key)
        encoded = json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
        with self._mutex:
            try:
                existing = self._assert_regular_target(self.events_path, allow_missing=True)
                if existing is not None:
                    journal_fd = self._open_checked(self.events_path, os.O_RDONLY)
                    journal = self._read_fd(journal_fd)
                    self._parse_events(journal)
                    if journal and not journal.endswith(b"\n"):
                        _fail("cannot append while the event journal has a truncated final line")
                flags = os.O_WRONLY | os.O_APPEND
                if existing is None:
                    flags |= os.O_CREAT
                fd = self._open_checked(self.events_path, flags, allow_missing=existing is None)
                with os.fdopen(fd, "ab") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                self._fsync_directory()
            except (OSError, RecordError) as exc:
                raise RecordError("could not durably append run event") from exc

    @staticmethod
    def _safe_event_value(value: Any, label: str) -> Any:
        if value is None or type(value) in (bool, int):
            return value
        if type(value) is float and math.isfinite(value):
            return value
        if isinstance(value, str) and len(value) <= 256 and _EVENT_STRING.fullmatch(value) and not re.search(r"secret|token|password|credential|stderr|command|private.?key|\b(?:nebius|ssh|scp|powershell|bash)\s+[-A-Za-z]", value, re.I):
            return value
        _fail(f"event field {label} contains an unsafe value")

    def read_events(self) -> list[dict[str, Any]]:
        self._created()
        if self._assert_regular_target(self.events_path, allow_missing=True) is None:
            return []
        fd = self._open_checked(self.events_path, os.O_RDONLY)
        return self._parse_events(self._read_fd(fd))

    def _parse_events(self, raw: bytes) -> list[dict[str, Any]]:
        lines = raw.splitlines(keepends=True)
        events = []
        for index, line in enumerate(lines):
            complete = line.endswith((b"\n", b"\r"))
            try:
                row = json.loads(line)
            except (UnicodeError, json.JSONDecodeError) as exc:
                if index == len(lines) - 1 and not complete:
                    break
                raise RecordError(f"run event journal is corrupt at line {index + 1}") from exc
            if not isinstance(row, dict) or not isinstance(row.get("event"), str):
                _fail(f"run event journal has an invalid event at line {index + 1}")
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", row["event"]):
                _fail(f"run event journal has an unsafe event at line {index + 1}")
            if set(row) - (_EVENT_FIELDS | {"event"}):
                _fail(f"run event journal has unknown fields at line {index + 1}")
            for key, value in row.items():
                if key != "event":
                    self._safe_event_value(value, key)
            events.append(row)
        return events

    def snapshot(self, payload: Mapping[str, Any]) -> None:
        digest = self._created()
        if not isinstance(payload, Mapping):
            _fail("status snapshot must be an object")
        safe = _safe_snapshot(dict(payload))
        if "record_digest" in safe and safe["record_digest"] != digest:
            _fail("status snapshot record digest does not match immutable run identity")
        safe.setdefault("record_digest", digest)
        encoded = json.dumps(safe, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
        self._assert_regular_target(self.status_path, allow_missing=True)
        self._validate_run_dir()
        fd, temp_name = tempfile.mkstemp(prefix=".status-", suffix=".tmp", dir=self.run_dir)
        try:
            temp_path = Path(temp_name)
            if _reparse(temp_path) or not stat.S_ISREG(temp_path.lstat().st_mode):
                _fail("temporary status file is not a regular file")
            with os.fdopen(fd, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            self._assert_regular_target(self.status_path, allow_missing=True)
            os.replace(temp_name, self.status_path)
            self._fsync_directory()
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    def read_status(self) -> dict[str, Any]:
        digest = self._created()
        if self._assert_regular_target(self.status_path, allow_missing=True) is None:
            _fail("run status snapshot does not exist")
        fd = self._open_checked(self.status_path, os.O_RDONLY)
        try:
            status = json.loads(self._read_fd(fd).decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RecordError("run status snapshot is corrupt") from exc
        if not isinstance(status, dict) or status.get("record_digest") != digest:
            _fail("run status snapshot does not match immutable run identity")
        _safe_snapshot(status)
        return status

    def acquire_lease(self, owner_id: str) -> None:
        self._created()
        if not isinstance(owner_id, str) or not _SAFE.fullmatch(owner_id) or owner_id.isdecimal():
            _fail("owner_id must be a safe non-PID identifier")
        descriptor = json.dumps({"owner_id": owner_id}, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        if self._assert_regular_target(self.lease_path, allow_missing=True) is not None:
            _fail("run lease already exists; refusing automatic recovery or steal")
        try:
            fd = self._open_checked(self.lease_path, os.O_RDWR | os.O_CREAT, allow_missing=True)
            view = memoryview(descriptor)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
            self._lock_fd(fd)
            self._lease_fd = fd
            self._lease_owner = owner_id
            self._fsync_directory()
        except Exception:
            if "fd" in locals():
                os.close(fd)
            raise

    def release_lease(self, owner_id: str) -> None:
        self._created()
        if self._lease_fd is None or self._lease_owner != owner_id:
            _fail("only the current lease owner may release a held lease")
        try:
            info = self._assert_regular_target(self.lease_path, allow_missing=False)
            if not os.path.samestat(info, os.fstat(self._lease_fd)):
                _fail("run lease file changed while held")
            os.lseek(self._lease_fd, 0, os.SEEK_SET)
            raw_descriptor = os.read(self._lease_fd, 4096)
            descriptor = json.loads(raw_descriptor.decode("utf-8"), object_pairs_hook=_duplicate_rejector)
            if descriptor != {"owner_id": owner_id}:
                _fail("run lease owner descriptor changed")
            self._unlock_fd(self._lease_fd)
            os.close(self._lease_fd)
            self._lease_fd = None
            self._lease_owner = None
            self.lease_path.unlink()
            self._fsync_directory()
        except OSError as exc:
            raise RecordError("could not safely release run lease") from exc

    @staticmethod
    def _lock_fd(fd: int) -> None:
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock_fd(fd: int) -> None:
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)

    def _fsync_directory(self) -> None:
        if os.name == "nt":
            return
        try:
            fd = os.open(self.run_dir, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass

    def close(self) -> None:
        """Flush is performed per write; held leases intentionally outlive this call."""
        return None
