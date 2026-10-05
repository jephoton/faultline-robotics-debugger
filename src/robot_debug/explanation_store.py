"""Immutable evidence-bound explanation report storage."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import stat
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .case_store import inspect_case
from .evidence_packet import make_evidence_packet, validate_evidence_packet
from .explanation import build_offline_report


class ExplanationStoreError(ValueError):
    """A report or its local evidence binding is invalid."""


_INVALID = "invalid stored report"
_CASE_CHANGED = "report case is unavailable or changed"
_STORAGE = "report storage is unavailable"
_COLLECTION_WARNING = "one or more report records are unavailable or invalid"
_CASE_WARNING = "case evidence is unavailable or changed"
_LIMIT_WARNING = "report collection exceeds the scan limit"
_ID = re.compile(r"[0-9a-f]{64}\Z")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
_MAX_RECORD = 65_536
_MAX_REPORTS = 100
_PROVENANCE_KEYS = {
    "source", "provider", "model", "endpoint", "created_at", "request_status",
    "error_code", "latency_seconds", "prompt_tokens", "completion_tokens",
    "estimated_cost_usd", "billed_cost_usd", "reservation_usd",
}
_MODEL = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
_ENDPOINT = "https://api.tokenfactory.nebius.com/v1/"
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _fail(message: str = _INVALID):
    raise ExplanationStoreError(message)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            _fail()
        result[key] = value
    return result


def _constant(_value):
    _fail()


def _canonical(value: object, *, bounded: bool = True) -> bytes:
    try:
        data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8", "strict")
    except (TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        _fail()
    if bounded and len(data) > _MAX_RECORD:
        _fail()
    return data


def _decode(data: bytes) -> dict:
    if len(data) > _MAX_RECORD:
        _fail()
    try:
        value = json.loads(data.decode("utf-8", "strict"), object_pairs_hook=_pairs,
                           parse_constant=_constant)
    except ExplanationStoreError:
        raise
    except (UnicodeError, ValueError, RecursionError, OverflowError, TypeError):
        _fail()
    if type(value) is not dict:
        _fail()
    return value


def _number(value: object, *, maximum: float | None = None) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(number) and number >= 0 and (maximum is None or number <= maximum)


def _integer(value: object, maximum: int) -> bool:
    return type(value) is int and 0 <= value <= maximum


def _timestamp(value: object) -> bool:
    if type(value) is not str or _UTC.fullmatch(value) is None:
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _provenance(value: object) -> dict:
    if type(value) is not dict or set(value) != _PROVENANCE_KEYS:
        _fail()
    source = value["source"]
    if source not in {"offline", "live"} or not _timestamp(value["created_at"]):
        _fail()
    if value["billed_cost_usd"] is not None:
        _fail()
    latency = value["latency_seconds"]
    prompt = value["prompt_tokens"]
    completion = value["completion_tokens"]
    estimate = value["estimated_cost_usd"]
    if latency is not None and not _number(latency):
        _fail()
    if (prompt is None) != (completion is None):
        _fail()
    if prompt is not None and (not _integer(prompt, 262_144)
                               or not _integer(completion, 600)):
        _fail()
    if source == "offline":
        if (value["provider"], value["model"], value["endpoint"]) != (None, None, None):
            _fail()
        if value["request_status"] != "offline" or value["error_code"] is not None:
            _fail()
        if any(item is not None for item in (latency, prompt, completion, estimate)):
            _fail()
        if type(value["reservation_usd"]) not in (int, float) or value["reservation_usd"] != 0:
            _fail()
    else:
        if (value["provider"], value["model"], value["endpoint"]) != (
                "nebius-token-factory", _MODEL, _ENDPOINT):
            _fail()
        status = value["request_status"]
        code = value["error_code"]
        valid = (status == "completed" and code is None) or (
            status == "transport_error" and code == "timeout") or (
            status == "http_error" and code in {
                "http_error", "authentication_failed", "catalog_missing"}) or (
            status == "invalid_response" and code == "invalid_response")
        if not valid:
            _fail()
        if type(value["reservation_usd"]) not in (int, float) or value["reservation_usd"] != .02:
            _fail()
        if prompt is None:
            if estimate is not None:
                _fail()
        else:
            expected = (Decimal(prompt) * Decimal("0.06")
                        + Decimal(completion) * Decimal("0.24")) / Decimal(1_000_000)
            try:
                supplied = Decimal(str(estimate))
            except (InvalidOperation, ValueError):
                _fail()
            if not _number(estimate, maximum=.02) or supplied != expected:
                _fail()
    # A canonical JSON round trip supplies the detached return without deepcopy hazards.
    return _decode(_canonical(value))


def _expected_report(packet: dict, supplied: object) -> dict:
    if type(supplied) is not dict:
        _fail()
    status = supplied.get("interpretation_status")
    if status == "absent":
        expected = build_offline_report(packet)
    elif status == "rejected":
        expected = build_offline_report(packet, "")
    elif status == "validated-structure":
        try:
            response = json.dumps(supplied.get("interpretation"), sort_keys=True,
                                  separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
            _fail()
        expected = build_offline_report(packet, response)
    else:
        _fail()
    if _canonical(supplied) != _canonical(expected):
        _fail()
    return _decode(_canonical(expected))


def validate_stored_report(value: dict) -> dict:
    """Validate an exact stored-report record and return a detached normalized copy."""
    try:
        if type(value) is not dict or set(value) != {
                "schema_version", "report_id", "case_id", "packet", "report", "provenance"}:
            _fail()
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            _fail()
        if type(value["case_id"]) is not str or _ID.fullmatch(value["case_id"]) is None:
            _fail()
        if type(value["report_id"]) is not str or _ID.fullmatch(value["report_id"]) is None:
            _fail()
        packet = validate_evidence_packet(value["packet"])
        report = _expected_report(packet, value["report"])
        provenance = _provenance(value["provenance"])
        body = {"schema_version": 1, "case_id": value["case_id"], "packet": packet,
                "report": report, "provenance": provenance}
        report_id = hashlib.sha256(_canonical(body)).hexdigest()
        if value["report_id"] != report_id:
            _fail()
        result = {"schema_version": 1, "report_id": report_id, "case_id": value["case_id"],
                  "packet": packet, "report": report, "provenance": provenance}
        _canonical(result)
        return _decode(_canonical(result))
    except ExplanationStoreError:
        raise
    except Exception:
        raise ExplanationStoreError(_INVALID) from None


def make_stored_report(case_id: str, packet: dict, report: dict, provenance: dict) -> dict:
    """Build a normalized record whose ID binds all supplied evidence and provenance."""
    try:
        normalized_packet = validate_evidence_packet(packet)
        normalized_report = _expected_report(normalized_packet, report)
        normalized_provenance = _provenance(provenance)
        body = {"schema_version": 1, "case_id": case_id, "packet": normalized_packet,
                "report": normalized_report, "provenance": normalized_provenance}
        if type(case_id) is not str or _ID.fullmatch(case_id) is None:
            _fail()
        result = {"schema_version": 1,
                  "report_id": hashlib.sha256(_canonical(body)).hexdigest(),
                  "case_id": case_id, "packet": normalized_packet,
                  "report": normalized_report, "provenance": normalized_provenance}
        return validate_stored_report(result)
    except ExplanationStoreError:
        raise
    except Exception:
        raise ExplanationStoreError(_INVALID) from None


def _is_reparse(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & _REPARSE)


def _safe_existing(path: Path, *, directory: bool | None = None) -> None:
    # Do not resolve first: resolution would hide a linked ancestor.
    absolute = path.absolute()
    for component in (*reversed(absolute.parents), absolute):
        if _is_reparse(component):
            _fail(_STORAGE)
    try:
        if directory is True and not path.is_dir():
            _fail(_STORAGE)
        if directory is False and not path.is_file():
            _fail(_STORAGE)
    except OSError:
        _fail(_STORAGE)


def _fresh_packet(workspace: Path, case_id: str) -> dict:
    try:
        _paths(workspace, case_id)
        case = inspect_case(workspace, case_id)
        if case["capabilities"]["inspection"]["status"] != "available":
            _fail(_CASE_CHANGED)
        return make_evidence_packet(case)
    except ExplanationStoreError:
        raise
    except Exception:
        _fail(_CASE_CHANGED)


def _paths(workspace: Path, case_id: str) -> tuple[Path, Path]:
    base = Path(workspace)
    if not base.is_absolute():
        base = base.absolute()
    case_dir = base / case_id
    reports = case_dir / "reports"
    _safe_existing(base, directory=True)
    _safe_existing(case_dir, directory=True)
    return case_dir, reports


def _read_record(path: Path) -> dict:
    _safe_existing(path, directory=False)
    try:
        with path.open("rb") as stream:
            data = stream.read(_MAX_RECORD + 1)
    except OSError:
        _fail()
    return validate_stored_report(_decode(data))


def store_report(workspace: Path, value: dict) -> Path:
    """Publish one immutable report atomically within its registered case."""
    record = validate_stored_report(value)
    fresh = _fresh_packet(Path(workspace), record["case_id"])
    if _canonical(fresh) != _canonical(record["packet"]):
        _fail(_CASE_CHANGED)
    _case_dir, reports = _paths(Path(workspace), record["case_id"])
    try:
        reports.mkdir()
    except FileExistsError:
        pass
    except OSError:
        _fail(_STORAGE)
    _safe_existing(reports, directory=True)
    target = reports / f"{record['report_id']}.json"
    if target.exists() or _is_reparse(target):
        try:
            existing = _read_record(target)
        except ExplanationStoreError:
            _fail(_STORAGE)
        if _canonical(existing) == _canonical(record):
            return target
        _fail(_STORAGE)
    data = _canonical(record)
    temporary = reports / f".{record['report_id']}.{secrets.token_hex(8)}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        final_packet = _fresh_packet(Path(workspace), record["case_id"])
        if _canonical(final_packet) != _canonical(record["packet"]):
            _fail(_CASE_CHANGED)
        try:
            os.link(temporary, target)
        except FileExistsError:
            existing = _read_record(target)
            if _canonical(existing) != _canonical(record):
                _fail(_STORAGE)
        return target
    except ExplanationStoreError:
        raise
    except OSError:
        _fail(_STORAGE)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def read_case_reports(workspace: Path, case_id: str) -> dict:
    """Read a bounded valid report set, isolating corrupt immutable sidecars."""
    try:
        initial = _fresh_packet(Path(workspace), case_id)
    except ExplanationStoreError:
        return {"reports": [], "warnings": [_CASE_WARNING]}
    try:
        _case_dir, reports_dir = _paths(Path(workspace), case_id)
        if not reports_dir.exists():
            final = _fresh_packet(Path(workspace), case_id)
            if _canonical(initial) != _canonical(final):
                return {"reports": [], "warnings": [_CASE_WARNING]}
            return {"reports": [], "warnings": []}
        _safe_existing(reports_dir, directory=True)
        entries = []
        with os.scandir(reports_dir) as iterator:
            for entry in iterator:
                entries.append(entry.name)
                if len(entries) > _MAX_REPORTS:
                    return {"reports": [], "warnings": [_LIMIT_WARNING]}
    except (OSError, ExplanationStoreError):
        return {"reports": [], "warnings": [_COLLECTION_WARNING]}
    records = []
    corrupt = False
    for name in entries:
        if re.fullmatch(r"[0-9a-f]{64}\.json", name) is None:
            corrupt = True
            continue
        path = reports_dir / name
        try:
            record = _read_record(path)
            if name != record["report_id"] + ".json" or record["case_id"] != case_id:
                _fail()
            if _canonical(record["packet"]) != _canonical(initial):
                _fail()
            records.append(record)
        except ExplanationStoreError:
            corrupt = True
    try:
        final = _fresh_packet(Path(workspace), case_id)
        if _canonical(initial) != _canonical(final):
            return {"reports": [], "warnings": [_CASE_WARNING]}
    except ExplanationStoreError:
        return {"reports": [], "warnings": [_CASE_WARNING]}
    records.sort(key=lambda record: (record["provenance"]["created_at"], record["report_id"]))
    return {"reports": records, "warnings": [_COLLECTION_WARNING] if corrupt else []}
