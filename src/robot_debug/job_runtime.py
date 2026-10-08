"""Closed-run configuration validation and conservative evidence export."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple


_CONFIG_FIELDS = {"schema_version", "mode", "run_id", "deadline_seconds"}
_MODES = {"pilot", "search", "grid", "reduce"}
_RUN_ID = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", re.ASCII)
_ALLOWED_SUFFIXES = {".json", ".jsonl", ".mp4", ".sqlite", ".yaml", ".yml", ".txt", ".log"}
_CREDENTIAL_NAME = re.compile(
    r"(?:^|[._-])(?:key|token|credential|credentials|creds|secret|private[-_]?key|id[-_]?rsa|id[-_]?ed25519)(?:[._-]|$)",
    re.IGNORECASE,
)
_MAX_TOTAL_BYTES = 1 << 30
_COPY_CHUNK_SIZE = 1024 * 1024


class JobRuntimeError(ValueError):
    """Raised when a workload or evidence export violates its closed contract."""


def _fail(message: str) -> None:
    raise JobRuntimeError(message)


def validate_workload_config(config: object) -> Dict[str, Any]:
    """Validate and return a fresh, JSON-compatible workload configuration."""

    if type(config) is not dict or set(config) != _CONFIG_FIELDS:
        _fail("workload configuration must contain exactly the required fields")
    schema_version = config["schema_version"]
    mode = config["mode"]
    run_id = config["run_id"]
    deadline = config["deadline_seconds"]
    if type(schema_version) is not int or schema_version != 1:
        _fail("workload configuration schema version is unsupported")
    if type(mode) is not str or mode not in _MODES:
        _fail("workload mode is unsupported")
    if type(run_id) is not str or not (1 <= len(run_id) <= 63) or _RUN_ID.fullmatch(run_id) is None:
        _fail("workload run identifier is invalid")
    if type(deadline) not in (int, float) or not math.isfinite(deadline) or not (0 < deadline <= 3000):
        _fail("workload deadline is invalid")
    return {
        "schema_version": schema_version,
        "mode": mode,
        "run_id": run_id,
        "deadline_seconds": deadline,
    }


def _path(value: object, label: str) -> Path:
    if isinstance(value, bytes):
        _fail(f"{label} must be a filesystem path")
    try:
        path = Path(os.fspath(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        _fail(f"{label} must be a filesystem path")
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _is_link_or_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError as exc:
        raise JobRuntimeError("could not inspect an evidence path") from exc
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)


def _existing_chain(path: Path) -> Iterable[Path]:
    current = path
    items = []
    while True:
        if current.exists() or current.is_symlink():
            items.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent
    return reversed(items)


def _reject_link_chain(path: Path) -> None:
    for component in _existing_chain(path):
        if _is_link_or_reparse(component):
            _fail("evidence paths may not contain symbolic links or reparse points")


def _portable_relative(path: Path, source: Path) -> str:
    relative = path.relative_to(source)
    parts = relative.parts
    if not parts:
        _fail("evidence path is empty")
    for part in parts:
        if part in (".", "..") or "\\" in part or any(ord(char) < 32 or ord(char) == 127 for char in part):
            _fail("evidence contains an unsafe path")
    portable = "/".join(parts)
    if portable.startswith("/") or portable == "manifest.json":
        _fail("evidence contains a reserved path")
    return portable


def _validate_evidence_name(path: Path, portable: str) -> None:
    name = path.name
    lower = name.lower()
    if lower == "manifest.json":
        _fail("source completion manifests cannot be exported as evidence")
    if lower.startswith(".env") or path.suffix.lower() in {".key", ".pem"}:
        _fail("credential-shaped files cannot be exported")
    if _CREDENTIAL_NAME.search(lower):
        _fail("credential-shaped files cannot be exported")
    if lower.endswith((".sqlite-wal", ".sqlite-shm")):
        _fail("SQLite companion files cannot be exported")
    if path.suffix.lower() not in _ALLOWED_SUFFIXES:
        _fail("unsupported evidence file type")


def _secret_patterns(secret_values: object) -> Tuple[bytes, ...]:
    if type(secret_values) is not tuple:
        _fail("secret values must be an explicit tuple")
    patterns = []
    for value in secret_values:
        if type(value) is not str or not value:
            _fail("secret values must be nonempty plain strings")
        patterns.append(value.encode("utf-8"))
    return tuple(patterns)


def _prefix_table(pattern: bytes) -> List[int]:
    table = [0] * len(pattern)
    matched = 0
    for index in range(1, len(pattern)):
        while matched and pattern[index] != pattern[matched]:
            matched = table[matched - 1]
        if pattern[index] == pattern[matched]:
            matched += 1
            table[index] = matched
    return table


class _SecretScanner:
    def __init__(self, patterns: Sequence[bytes]):
        self._patterns = patterns
        self._tables = tuple(_prefix_table(pattern) for pattern in patterns)
        self._matched = [0] * len(patterns)

    def scan(self, chunk: bytes) -> None:
        for pattern_index, pattern in enumerate(self._patterns):
            matched = self._matched[pattern_index]
            table = self._tables[pattern_index]
            for byte in chunk:
                while matched and byte != pattern[matched]:
                    matched = table[matched - 1]
                if byte == pattern[matched]:
                    matched += 1
                    if matched == len(pattern):
                        _fail("evidence contains an explicitly supplied secret")
            self._matched[pattern_index] = matched


def _file_identity(info: os.stat_result) -> Tuple[int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000)),
        getattr(info, "st_ctime_ns", int(info.st_ctime * 1_000_000_000)),
    )


def _open_source(path: Path, expected: os.stat_result | None = None) -> Tuple[int, os.stat_result]:
    try:
        before = path.lstat()
    except OSError as exc:
        raise JobRuntimeError("could not inspect an evidence file") from exc
    if _is_link_or_reparse(path) or not stat.S_ISREG(before.st_mode):
        _fail("evidence children must be ordinary files or directories")
    if expected is not None and _file_identity(before) != _file_identity(expected):
        _fail("source evidence changed during export")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        after = path.lstat()
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(before, opened) or not os.path.samestat(opened, after):
            _fail("source evidence changed during open")
        return descriptor, opened
    except Exception:
        if "descriptor" in locals():
            os.close(descriptor)
        raise


def _hash_source(path: Path, secrets: Sequence[bytes], expected: os.stat_result | None = None) -> Tuple[int, str, os.stat_result]:
    descriptor, opened = _open_source(path, expected)
    digest = hashlib.sha256()
    scanner = _SecretScanner(secrets)
    size = 0
    try:
        with os.fdopen(descriptor, "rb") as stream:
            while True:
                chunk = stream.read(_COPY_CHUNK_SIZE)
                if not chunk:
                    break
                scanner.scan(chunk)
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise JobRuntimeError("could not read evidence file") from exc
    try:
        after = path.lstat()
    except OSError as exc:
        raise JobRuntimeError("could not re-inspect evidence file") from exc
    if _file_identity(after) != _file_identity(opened) or size != opened.st_size:
        _fail("source evidence changed while it was read")
    return size, digest.hexdigest(), opened


def _copy_file(source: Path, destination: Path, secrets: Sequence[bytes]) -> Tuple[int, str]:
    """Copy one source through an exclusive staging path; retained for fault injection."""

    source_fd, opened = _open_source(source)
    staging = destination.with_name("." + destination.name + "." + uuid.uuid4().hex + ".part")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    destination_fd = os.open(staging, flags, 0o600)
    digest = hashlib.sha256()
    scanner = _SecretScanner(secrets)
    size = 0
    try:
        with os.fdopen(source_fd, "rb") as reader, os.fdopen(destination_fd, "wb") as writer:
            while True:
                chunk = reader.read(_COPY_CHUNK_SIZE)
                if not chunk:
                    break
                scanner.scan(chunk)
                writer.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        after = source.lstat()
        if _file_identity(after) != _file_identity(opened) or size != opened.st_size:
            _fail("source evidence changed while it was copied")
        reserve_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        reserve_fd = os.open(destination, reserve_flags, 0o600)
        os.close(reserve_fd)
        os.replace(staging, destination)
    except Exception:
        # Partial staging data is deliberately retained for recovery.
        raise
    return size, digest.hexdigest()


def _collect_source(source: Path, secrets: Sequence[bytes]) -> List[Tuple[str, Path, int, str, os.stat_result]]:
    collected = []
    total = 0
    pending = [source]
    while pending:
        directory = pending.pop()
        if _is_link_or_reparse(directory) or not stat.S_ISDIR(directory.lstat().st_mode):
            _fail("evidence children must be ordinary files or directories")
        try:
            children = list(directory.iterdir())
        except OSError as exc:
            raise JobRuntimeError("could not enumerate evidence source") from exc
        for child in children:
            portable = _portable_relative(child, source)
            try:
                info = child.lstat()
            except OSError as exc:
                raise JobRuntimeError("could not inspect evidence source") from exc
            if _is_link_or_reparse(child):
                _fail("evidence children may not be symbolic links or reparse points")
            if stat.S_ISDIR(info.st_mode):
                pending.append(child)
            elif stat.S_ISREG(info.st_mode):
                _validate_evidence_name(child, portable)
                total += info.st_size
                if total > _MAX_TOTAL_BYTES:
                    _fail("evidence exceeds the export size limit")
                size, digest, stable = _hash_source(child, secrets, info)
                collected.append((portable, child, size, digest, stable))
            else:
                _fail("special files cannot be exported as evidence")
    collected.sort(key=lambda item: item[0])
    return collected


def _resolved_destination(source: Path, destination: Path) -> Tuple[Path, Path]:
    _reject_link_chain(source)
    _reject_link_chain(destination.parent)
    if not source.is_dir():
        _fail("evidence source must be an existing directory")
    if not destination.parent.is_dir():
        _fail("evidence destination parent must be an existing directory")
    if destination.exists() or destination.is_symlink():
        _fail("evidence destination must not already exist")
    try:
        canonical_source = source.resolve(strict=True)
        canonical_parent = destination.parent.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise JobRuntimeError("evidence roots could not be resolved") from exc
    canonical_destination = canonical_parent / destination.name
    if (
        canonical_source == canonical_destination
        or canonical_source in canonical_destination.parents
        or canonical_destination in canonical_source.parents
    ):
        _fail("evidence source and destination may not overlap")
    return canonical_source, canonical_destination


def _make_destination_directories(destination: Path, paths: Sequence[str]) -> None:
    destination.mkdir(mode=0o700)
    created = {destination}
    for portable in paths:
        current = destination
        for part in Path(portable).parts[:-1]:
            current = current / part
            if current not in created:
                current.mkdir(mode=0o700)
                created.add(current)


def export_closed_evidence(
    source_root: object,
    destination_root: object,
    *,
    status: object,
    cleanup_confirmed: object,
    secret_values: object = (),
) -> Dict[str, Any]:
    """Export allowlisted evidence after the caller confirms external cleanup."""

    if type(status) is not str or status not in {"complete", "partial"}:
        _fail("evidence status must be complete or partial")
    if cleanup_confirmed is not True:
        _fail("external cleanup must be explicitly confirmed before export")
    secrets = _secret_patterns(secret_values)
    source = _path(source_root, "source root")
    destination = _path(destination_root, "destination root")
    source, destination = _resolved_destination(source, destination)
    collected = _collect_source(source, secrets)

    _resolved_destination(source, destination)
    _make_destination_directories(destination, [item[0] for item in collected])
    files = []
    for portable, source_path, expected_size, expected_digest, expected_info in collected:
        destination_path = destination.joinpath(*portable.split("/"))
        current = source_path.lstat()
        if _file_identity(current) != _file_identity(expected_info):
            _fail("source evidence changed before copy")
        copied_size, copied_digest = _copy_file(source_path, destination_path, secrets)
        source_size, source_digest, _ = _hash_source(source_path, secrets, expected_info)
        destination_size, destination_digest, _ = _hash_source(destination_path, (), None)
        if (
            copied_size != expected_size
            or source_size != expected_size
            or destination_size != expected_size
            or copied_digest != expected_digest
            or source_digest != expected_digest
            or destination_digest != expected_digest
        ):
            _fail("copied evidence did not match the stable source")
        files.append({"path": portable, "size_bytes": expected_size, "sha256": expected_digest})

    manifest = {"schema_version": 1, "status": status, "files": files}
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    manifest_path = destination / "manifest.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(manifest_path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return manifest


__all__ = ["JobRuntimeError", "export_closed_evidence", "validate_workload_config"]
