"""Closed-run configuration validation and conservative evidence export."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple


_CONFIG_FIELDS = {"schema_version", "mode", "run_id", "deadline_seconds"}
BATCH_MODES = {"m3-batch-smoke", "m3-batch"}
# ADR 0026: the M6 smoke Job has fixed conditions; the threshold Job is bounded by these fields.
M6_MODES = {"m6-smoke", "m6-threshold"}
# ADR 0028: LIBERO-10 scenario screening and reduction. Their fields live in scenario_experiment.
SCENARIO_MODES = {"scenario-smoke", "scenario-screen", "scenario-reduce"}
_MODES = {"pilot", "search", "grid", "reduce", "m5b", "m5b-grid"} | BATCH_MODES | M6_MODES | SCENARIO_MODES
_BATCH_FIELDS = {"phases", "repeats_per_kind"}
_BATCH_WORKERS = (4, 8, 12)
# Equal-work manifest sizes fixed by ADR 0025: repeats per kind (nominal, reduced mask).
_BATCH_REPEATS = {"m3-batch-smoke": 2, "m3-batch": 12}
_MAX_BATCH_PHASES = 6
M6_FAMILIES = ("darken", "noise", "blur", "contrast")
_M6_THRESHOLD_FIELDS = {"families", "sweep", "attempts", "required_failures", "bisection_steps"}
# Optional audit target (M7a): which suite, task and benchmark start the threshold searches run on.
# Absent means the recorded default (LIBERO-Object, task 0, the upstream start behaviour).
_M6_AUDIT_TARGET_FIELDS = {"suite", "task_id", "init_state_index"}
M6_SUITES = ("libero_object", "libero_10")
_M6_TASKS_PER_SUITE = 10
_M6_MAX_START_INDEX = 49
_M6_MAX_SWEEP_LEVELS = 8
_M6_MAX_ATTEMPTS = 12
_M6_MAX_BISECTION_STEPS = 6
_M6_MAX_TOTAL_ATTEMPTS = 400
_M6_NOMINAL_CONTROLS = 5
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

    if type(config) is not dict:
        _fail("workload configuration must contain exactly the required fields")
    mode_name = config.get("mode") if type(config.get("mode")) is str else None
    batch_mode = mode_name in BATCH_MODES
    expected_fields = _CONFIG_FIELDS
    if batch_mode:
        expected_fields = _CONFIG_FIELDS | _BATCH_FIELDS
    elif mode_name == "m6-threshold":
        required_fields = _CONFIG_FIELDS | _M6_THRESHOLD_FIELDS
        if not required_fields <= set(config) <= required_fields | _M6_AUDIT_TARGET_FIELDS:
            _fail("workload configuration must contain exactly the required fields")
        expected_fields = set(config)
    elif mode_name in SCENARIO_MODES:
        from robot_debug import scenario_experiment as scenario

        required = _CONFIG_FIELDS | scenario.MODE_REQUIRED[mode_name]
        allowed = required | scenario.COMMON_OPTIONAL | scenario.MODE_OPTIONAL[mode_name]
        if not required <= set(config) <= allowed:
            _fail("workload configuration must contain exactly the required fields")
        expected_fields = set(config)
    if set(config) != expected_fields:
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
    if type(deadline) not in (int, float) or not (0 < deadline <= 3000) or not math.isfinite(deadline):
        _fail("workload deadline is invalid")
    validated = {
        "schema_version": schema_version,
        "mode": mode,
        "run_id": run_id,
        "deadline_seconds": deadline,
    }
    if batch_mode:
        validated["repeats_per_kind"], validated["phases"] = _validate_batch_fields(config, mode)
    if mode == "m6-threshold":
        validated.update(_validate_m6_threshold_fields(config))
    if mode in SCENARIO_MODES:
        from robot_debug import scenario_experiment as scenario

        try:
            validated.update(scenario.validate_mode_fields(mode, config))
        except scenario.ScenarioConfigError as error:
            raise JobRuntimeError(str(error)) from error
    return validated


def _validate_m6_threshold_fields(config: Dict[str, Any]) -> Dict[str, Any]:
    """Bounded M6 threshold-search fields: families, coarse sweep, gate and bisection depth."""

    families = config["families"]
    if (
        type(families) is not list or not 1 <= len(families) <= len(M6_FAMILIES)
        or any(type(name) is not str or name not in M6_FAMILIES for name in families)
        or len(set(families)) != len(families)
    ):
        _fail("m6 families must be a non-empty list of distinct known families")
    sweep = config["sweep"]
    if type(sweep) is not list or not 1 <= len(sweep) <= _M6_MAX_SWEEP_LEVELS:
        _fail("m6 sweep must be a short non-empty list of severities")
    levels = []
    previous = 0.0
    for value in sweep:
        if type(value) not in (int, float) or not math.isfinite(value) or not previous < value <= 1.0:
            _fail("m6 sweep severities must increase strictly within (0, 1]")
        if abs(round(value, 6) - value) > 1e-12:
            _fail("m6 sweep severities support at most six decimals")
        previous = float(value)
        levels.append(float(value))
    attempts = config["attempts"]
    if type(attempts) is not int or not 1 <= attempts <= _M6_MAX_ATTEMPTS:
        _fail("m6 attempts must be an integer from 1 to {}".format(_M6_MAX_ATTEMPTS))
    required = config["required_failures"]
    if type(required) is not int or not 1 <= required <= attempts:
        _fail("m6 required_failures must be an integer from 1 to attempts")
    steps = config["bisection_steps"]
    if type(steps) is not int or not 0 <= steps <= _M6_MAX_BISECTION_STEPS:
        _fail("m6 bisection_steps must be an integer from 0 to {}".format(_M6_MAX_BISECTION_STEPS))
    worst_case = _M6_NOMINAL_CONTROLS + len(families) * (len(levels) + steps) * attempts
    if worst_case > _M6_MAX_TOTAL_ATTEMPTS:
        _fail("m6 threshold workload exceeds the episode bound")
    fields = {
        "families": list(families), "sweep": levels, "attempts": attempts,
        "required_failures": required, "bisection_steps": steps,
    }  # type: Dict[str, Any]
    if "suite" in config and (type(config["suite"]) is not str or config["suite"] not in M6_SUITES):
        _fail("m6 suite must be one of {}".format(", ".join(M6_SUITES)))
    if "task_id" in config and (
        type(config["task_id"]) is not int or not 0 <= config["task_id"] < _M6_TASKS_PER_SUITE
    ):
        _fail("m6 task_id must be an integer from 0 to {}".format(_M6_TASKS_PER_SUITE - 1))
    if "init_state_index" in config and (
        type(config["init_state_index"]) is not int or not 0 <= config["init_state_index"] <= _M6_MAX_START_INDEX
    ):
        _fail("m6 init_state_index must be an integer from 0 to {}".format(_M6_MAX_START_INDEX))
    for key in ("suite", "task_id", "init_state_index"):
        if key in config:
            fields[key] = config[key]
    return fields


def _validate_batch_fields(config: Dict[str, Any], mode: str) -> Tuple[int, List[List[int]]]:
    """Phases are ``[workers, max_batch_size]`` pairs over a fixed equal-work manifest."""

    repeats = config["repeats_per_kind"]
    if type(repeats) is not int or repeats != _BATCH_REPEATS[mode]:
        _fail("batch workload repeats_per_kind must match the frozen manifest for the mode")
    phases = config["phases"]
    if type(phases) is not list or not 1 <= len(phases) <= _MAX_BATCH_PHASES:
        _fail("batch workload phases must be a short non-empty list")
    items = 2 * repeats
    normalized = []
    for phase in phases:
        if type(phase) is not list or len(phase) != 2:
            _fail("each batch phase must be [workers, max_batch_size]")
        workers, batch_size = phase
        if type(workers) is not int or workers not in _BATCH_WORKERS or workers > items:
            _fail("batch phase workers must be 4, 8 or 12 and no more than the manifest size")
        if type(batch_size) is not int or batch_size not in (1, workers):
            _fail("batch phase max_batch_size must be 1 or equal to the worker count")
        if [workers, batch_size] in normalized:
            _fail("batch phases must be unique")
        normalized.append([workers, batch_size])
    return repeats, normalized


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


def _hash_destination(path: Path) -> Tuple[int, str]:
    """Hash an exported copy by content.

    Object-storage mounts do not keep stable inode identity across opens or
    support atomic rename, so destination copies are verified by their bytes;
    the strict identity checks apply to the local source tree only.
    """

    try:
        info = path.lstat()
    except OSError as exc:
        raise JobRuntimeError("could not inspect an exported evidence copy") from exc
    if _is_link_or_reparse(path) or not stat.S_ISREG(info.st_mode):
        _fail("exported evidence copies must be ordinary files")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    digest = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(os.open(path, flags), "rb") as stream:
            while True:
                chunk = stream.read(_COPY_CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise JobRuntimeError("could not read an exported evidence copy") from exc
    return size, digest.hexdigest()


def _copy_file(source: Path, destination: Path, secrets: Sequence[bytes]) -> Tuple[int, str]:
    """Copy one source straight to its exclusive final path; retained for fault injection.

    There is no staging rename: object-storage mounts implement rename as a
    non-atomic copy. A failed copy leaves a partial file, and the manifest,
    published last, remains the only completion marker.
    """

    source_fd, opened = _open_source(source)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        destination_fd = os.open(destination, flags, 0o600)
    except BaseException:
        os.close(source_fd)
        raise
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
    except Exception:
        # Partial destination data is deliberately retained for recovery.
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


def _verify_final_evidence(
    collected: Sequence[Tuple[str, Path, int, str, os.stat_result]],
    destination: Path,
    secrets: Sequence[bytes],
) -> None:
    """Recheck every source and copy immediately before manifest publication."""

    for portable, source_path, expected_size, expected_digest, expected_info in collected:
        destination_path = destination.joinpath(*portable.split("/"))
        _reject_link_chain(source_path)
        _reject_link_chain(destination_path)
        source_size, source_digest, _ = _hash_source(source_path, secrets, expected_info)
        destination_size, destination_digest = _hash_destination(destination_path)
        if (
            source_size != expected_size
            or destination_size != expected_size
            or source_digest != expected_digest
            or destination_digest != expected_digest
        ):
            _fail("evidence changed before manifest publication")


def _publish_manifest(manifest_path: Path, payload: bytes) -> None:
    """Publish one exclusive marker and remove only that marker on failure."""

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(manifest_path, flags, 0o600)
    try:
        stream = os.fdopen(descriptor, "wb")
        descriptor = None
        with stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException as publication_error:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            current = manifest_path.lstat()
            # The marker was created exclusively above; inode identity is not
            # stable on object-storage mounts, so only its kind is rechecked.
            if _is_link_or_reparse(manifest_path) or not stat.S_ISREG(current.st_mode):
                raise JobRuntimeError("manifest marker changed during failed publication")
            manifest_path.unlink()
            if manifest_path.exists() or manifest_path.is_symlink():
                raise JobRuntimeError("manifest marker removal could not be confirmed")
        except BaseException:
            raise JobRuntimeError("manifest publication failed and marker cleanup could not be confirmed") from publication_error
        raise


def export_closed_evidence(
    source_root: object,
    destination_root: object,
    *,
    status: object,
    cleanup_confirmed: object,
    secret_values: object = (),
) -> Dict[str, Any]:
    """Export allowlisted evidence after the caller confirms external cleanup.

    This guards a closed, non-hostile workspace against accidental mutation. The
    repeated checks are not an arbitrary-race security boundary for hostile local
    processes with concurrent filesystem access.
    """

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
        destination_size, destination_digest = _hash_destination(destination_path)
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

    _verify_final_evidence(collected, destination, secrets)
    manifest = {"schema_version": 1, "status": status, "files": files}
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    manifest_path = destination / "manifest.json"
    _publish_manifest(manifest_path, payload)
    return manifest


__all__ = [
    "BATCH_MODES",
    "JobRuntimeError",
    "M6_FAMILIES",
    "M6_MODES",
    "M6_SUITES",
    "SCENARIO_MODES",
    "export_closed_evidence",
    "validate_workload_config",
]
