"""Immutable, evidence-bound public-research records for registered cases.

A record holds the Tavily sources retrieved for a case and an optional
source-cited Nemotron summary. It is published once under
``<workspace>/<case_id>/research/<record_id>.json`` and bound to the current
version 2 evidence packet. Retrieved text is untrusted: it is cleaned and
length-bounded here, and consumers must render it as plain text only.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

from .evidence_packet import packet_identity, validate_evidence_packet
from .explanation_store import ExplanationStoreError, _fresh_packets, _is_reparse, _safe_existing
from .tavily_search import _clean_text, _clean_url


class ResearchStoreError(ValueError):
    """A research record or its local evidence binding is invalid."""


_INVALID = "invalid research record"
_CASE_CHANGED = "research case is unavailable or changed"
_STORAGE = "research storage is unavailable"
_COLLECTION_WARNING = "one or more research records are unavailable or invalid"
_CASE_WARNING = "case evidence is unavailable or changed"
_LIMIT_WARNING = "research collection exceeds the scan limit"
_STALE_WARNING = "one or more research records do not match the current case evidence"
_ID = re.compile(r"[0-9a-f]{64}\Z")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
_SOURCE_ID = re.compile(r"S([1-9][0-9]?)\Z")
_CITATION = re.compile(r"\[S(\d+)\]")
_BARE_DOMAIN = re.compile(
    r"[A-Za-z0-9-]+\.(?:com|org|net|io|ai|edu|gov|dev|co|info|ac|uk|de)\b", re.IGNORECASE)
_MAX_RECORD = 131_072
_MAX_RECORDS = 50
_MAX_QUERIES = 3
_MAX_RESULTS = 5
_MAX_RELATED = 4
_MAX_LIMITATIONS = 3
_MAX_SOURCES_PER_ENTRY = 3
_MAX_TEXT = 400
_MAX_QUERY = 200
_MAX_COMPLETION_TOKENS = 1500
_RESERVATION_USD = Decimal("0.01")
_PROVENANCE_KEYS = {
    "source", "provider", "model", "endpoint", "created_at", "request_status",
    "error_code", "latency_seconds", "prompt_tokens", "completion_tokens",
    "estimated_cost_usd", "billed_cost_usd", "reservation_usd",
}
_MODEL = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
_ENDPOINT = "https://api.tokenfactory.nebius.com/v1/"
_STATUSES = ("not_requested", "interpreted", "rejected", "provider_error")


def _fail(message: str = _INVALID):
    raise ResearchStoreError(message)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            _fail()
        result[key] = value
    return result


def _constant(_value):
    _fail()


def _canonical(value: object) -> bytes:
    try:
        data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8", "strict")
    except (TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        _fail()
    if len(data) > _MAX_RECORD:
        _fail()
    return data


def _decode(data: bytes) -> dict:
    if len(data) > _MAX_RECORD:
        _fail()
    try:
        value = json.loads(data.decode("utf-8", "strict"), object_pairs_hook=_pairs,
                           parse_constant=_constant)
    except ResearchStoreError:
        raise
    except (UnicodeError, ValueError, RecursionError, OverflowError, TypeError):
        _fail()
    if type(value) is not dict:
        _fail()
    return value


def _detached(value: object) -> dict:
    return _decode(_canonical(value))


def _timestamp(value: object) -> bool:
    if type(value) is not str or _UTC.fullmatch(value) is None:
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


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


# --- sources ---------------------------------------------------------------

def _url_key(url: str) -> tuple:
    parts = urlsplit(url)
    return (parts.hostname.lower(), parts.port or 443, parts.path.rstrip("/"), parts.query)


def _validate_query_entry(entry: object, expected_next: int, seen: set) -> tuple[dict, int]:
    keys = {"query", "retrieved_at", "request_id", "credits", "from_cache", "results"}
    if type(entry) is not dict or set(entry) != keys:
        _fail()
    query = entry["query"]
    if (type(query) is not str or not query.strip() or len(query) > _MAX_QUERY
            or not query.isascii() or not query.isprintable()):
        _fail()
    if not _timestamp(entry["retrieved_at"]):
        _fail()
    request_id = entry["request_id"]
    if request_id is not None and (
            type(request_id) is not str or not 0 < len(request_id) <= 100
            or not request_id.isascii() or not request_id.isprintable()):
        _fail()
    if not _integer(entry["credits"], 100) or type(entry["from_cache"]) is not bool:
        _fail()
    results = entry["results"]
    if type(results) is not list or len(results) > _MAX_RESULTS:
        _fail()
    checked = []
    for item in results:
        if type(item) is not dict or set(item) != {
                "source_id", "title", "url", "snippet", "score"}:
            _fail()
        match = _SOURCE_ID.fullmatch(item["source_id"]) if type(item["source_id"]) is str else None
        if match is None or int(match.group(1)) != expected_next:
            _fail()
        title, snippet = item["title"], item["snippet"]
        if (type(title) is not str or not title or _clean_text(title, 200) != title
                or type(snippet) is not str or _clean_text(snippet, 600) != snippet):
            _fail()
        url = item["url"]
        if _clean_url(url) is None:
            _fail()
        key = _url_key(url)
        if key in seen:
            _fail()
        seen.add(key)
        score = item["score"]
        if type(score) not in (int, float) or not _number(score, maximum=1):
            _fail()
        checked.append({"source_id": item["source_id"], "title": title, "url": url,
                        "snippet": snippet, "score": float(score)})
        expected_next += 1
    return ({"query": query, "retrieved_at": entry["retrieved_at"], "request_id": request_id,
             "credits": entry["credits"], "from_cache": entry["from_cache"],
             "results": checked}, expected_next)


def _validate_queries(value: object) -> list:
    if type(value) is not list or not 1 <= len(value) <= _MAX_QUERIES:
        _fail()
    checked, seen, expected = [], set(), 1
    for entry in value:
        normalized, expected = _validate_query_entry(entry, expected, seen)
        checked.append(normalized)
    if len({entry["query"] for entry in checked}) != len(checked):
        _fail()
    return checked


def source_ids(queries: list) -> list:
    """Source IDs in order of appearance."""
    return [item["source_id"] for entry in queries for item in entry["results"]]


def assign_sources(searches: list) -> list:
    """Number results S1.. in query order, keeping each distinct URL once.

    ``searches`` are the dicts returned by ``tavily_search.search``. A URL that
    an earlier query already returned is dropped from later queries, so every
    source ID appears exactly once in the record.
    """
    try:
        queries, seen, number = [], set(), 1
        for search in searches:
            results = []
            for item in search["results"]:
                clean_url = _clean_url(item["url"])
                if clean_url is None:
                    continue
                key = _url_key(clean_url)
                if key in seen:
                    continue
                seen.add(key)
                results.append({"source_id": f"S{number}", "title": item["title"],
                                "url": clean_url, "snippet": item["snippet"],
                                "score": item["score"]})
                number += 1
            queries.append({"query": search["query"], "retrieved_at": search["retrieved_at"],
                            "request_id": search.get("request_id"),
                            "credits": search["credits"], "from_cache": search["from_cache"],
                            "results": results})
        return queries
    except ResearchStoreError:
        raise
    except Exception:
        raise ResearchStoreError(_INVALID) from None


# --- summary ---------------------------------------------------------------

def _summary_text(value: object) -> str:
    if (type(value) is not str or not 0 < len(value) <= _MAX_TEXT or value != value.strip()
            or not value.isprintable()):
        _fail()
    lowered = value.lower()
    if ("http" in lowered or "www." in lowered or "](" in value or "://" in value
            or _BARE_DOMAIN.search(value) is not None):
        _fail()
    return value


def validate_summary_content(related_work: object, limitations: object,
                             valid_source_ids: list) -> tuple[list, list]:
    """Check source-cited related work and limitations against retrieved sources."""
    if type(related_work) is not list or not 1 <= len(related_work) <= _MAX_RELATED:
        _fail()
    allowed = set(valid_source_ids)
    entries = []
    for entry in related_work:
        if type(entry) is not dict or set(entry) != {"text", "source_ids"}:
            _fail()
        text = _summary_text(entry["text"])
        cited = entry["source_ids"]
        if (type(cited) is not list or not 1 <= len(cited) <= _MAX_SOURCES_PER_ENTRY
                or len(set(cited)) != len(cited)
                or any(type(item) is not str or item not in allowed for item in cited)):
            _fail()
        if any(f"S{match}" not in cited for match in _CITATION.findall(text)):
            _fail()
        entries.append({"text": text, "source_ids": list(cited)})
    if type(limitations) is not list or not 1 <= len(limitations) <= _MAX_LIMITATIONS:
        _fail()
    return entries, [_summary_text(item) for item in limitations]


def _provenance(value: object, status: str) -> dict:
    if type(value) is not dict or set(value) != _PROVENANCE_KEYS:
        _fail()
    if not _timestamp(value["created_at"]) or value["billed_cost_usd"] is not None:
        _fail()
    latency, prompt = value["latency_seconds"], value["prompt_tokens"]
    completion, estimate = value["completion_tokens"], value["estimated_cost_usd"]
    if latency is not None and not _number(latency):
        _fail()
    if (prompt is None) != (completion is None):
        _fail()
    if prompt is not None and (not _integer(prompt, 262_144)
                               or not _integer(completion, _MAX_COMPLETION_TOKENS)):
        _fail()
    reservation = value["reservation_usd"]
    if status == "not_requested":
        if value["source"] != "offline":
            _fail()
        if (value["provider"], value["model"], value["endpoint"]) != (None, None, None):
            _fail()
        if value["request_status"] != "offline" or value["error_code"] is not None:
            _fail()
        if any(item is not None for item in (latency, prompt, completion, estimate)):
            _fail()
        if type(reservation) not in (int, float) or reservation != 0:
            _fail()
        return _detached(value)
    if value["source"] != "live":
        _fail()
    if (value["provider"], value["model"], value["endpoint"]) != (
            "nebius-token-factory", _MODEL, _ENDPOINT):
        _fail()
    request_status, code = value["request_status"], value["error_code"]
    if status == "interpreted":
        valid = request_status == "completed" and code is None
    elif status == "rejected":
        valid = request_status == "invalid_response" and code in {
            "invalid_response", "output_limit"}
    else:
        valid = (request_status == "transport_error" and code == "timeout") or (
            request_status == "http_error" and code in {
                "http_error", "authentication_failed", "catalog_missing"})
    if not valid:
        _fail()
    if type(reservation) not in (int, float) or Decimal(str(reservation)) != _RESERVATION_USD:
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
        if (type(estimate) not in (int, float) or not _number(estimate, maximum=0.01)
                or supplied != expected):
            _fail()
    return _detached(value)


def _validate_summary(value: object, queries: list) -> dict:
    if type(value) is not dict or set(value) != {
            "status", "related_work", "limitations", "provenance"}:
        _fail()
    status = value["status"]
    if type(status) is not str or status not in _STATUSES:
        _fail()
    provenance = _provenance(value["provenance"], status)
    if status == "interpreted":
        related, limitations = validate_summary_content(
            value["related_work"], value["limitations"], source_ids(queries))
    else:
        if value["related_work"] != [] or value["limitations"] != []:
            _fail()
        related, limitations = [], []
    return {"status": status, "related_work": related, "limitations": limitations,
            "provenance": provenance}


# --- record ----------------------------------------------------------------

def offline_provenance(created_at: str) -> dict:
    """Provenance for a record whose summary was not requested."""
    return {
        "source": "offline", "provider": None, "model": None, "endpoint": None,
        "created_at": created_at, "request_status": "offline", "error_code": None,
        "latency_seconds": None, "prompt_tokens": None, "completion_tokens": None,
        "estimated_cost_usd": None, "billed_cost_usd": None, "reservation_usd": 0,
    }


def not_requested_summary(created_at: str) -> dict:
    return {"status": "not_requested", "related_work": [], "limitations": [],
            "provenance": offline_provenance(created_at)}


def validate_research_record(value: dict) -> dict:
    """Validate an exact research record and return a detached normalized copy."""
    try:
        if type(value) is not dict or set(value) != {
                "schema_version", "record_id", "case_id", "packet_id", "queries", "summary"}:
            _fail()
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            _fail()
        for field in ("case_id", "packet_id", "record_id"):
            if type(value[field]) is not str or _ID.fullmatch(value[field]) is None:
                _fail()
        queries = _validate_queries(value["queries"])
        summary = _validate_summary(value["summary"], queries)
        body = {"schema_version": 1, "case_id": value["case_id"],
                "packet_id": value["packet_id"], "queries": queries, "summary": summary}
        record_id = hashlib.sha256(_canonical(body)).hexdigest()
        if value["record_id"] != record_id:
            _fail()
        return _detached({"schema_version": 1, "record_id": record_id,
                          "case_id": value["case_id"], "packet_id": value["packet_id"],
                          "queries": queries, "summary": summary})
    except ResearchStoreError:
        raise
    except Exception:
        raise ResearchStoreError(_INVALID) from None


def make_research_record(case_id: str, packet: dict, queries: list, summary: dict) -> dict:
    """Build a normalized record whose ID binds the packet identity, sources and summary.

    ``queries`` is the output of :func:`assign_sources`.
    """
    try:
        if type(case_id) is not str or _ID.fullmatch(case_id) is None:
            _fail()
        validated = validate_evidence_packet(packet)
        if validated["schema_version"] != 2:
            _fail()
        checked = _validate_queries(queries)
        normalized_summary = _validate_summary(summary, checked)
        body = {"schema_version": 1, "case_id": case_id,
                "packet_id": packet_identity(validated), "queries": checked,
                "summary": normalized_summary}
        record = dict(body, record_id=hashlib.sha256(_canonical(body)).hexdigest())
        return validate_research_record(record)
    except ResearchStoreError:
        raise
    except Exception:
        raise ResearchStoreError(_INVALID) from None


def with_summary(record: dict, summary: dict) -> dict:
    """A new record with the same case, packet and sources but a different summary."""
    checked = validate_research_record(record)
    body = {"schema_version": 1, "case_id": checked["case_id"],
            "packet_id": checked["packet_id"], "queries": checked["queries"],
            "summary": _validate_summary(summary, checked["queries"])}
    return validate_research_record(
        dict(body, record_id=hashlib.sha256(_canonical(body)).hexdigest()))


def record_sort_key(record: dict) -> tuple:
    """Oldest first: creation time of the summary, latest retrieval, then ID."""
    retrieved = max(entry["retrieved_at"] for entry in record["queries"])
    return (record["summary"]["provenance"]["created_at"], retrieved, record["record_id"])


# --- storage ---------------------------------------------------------------

def _paths(workspace: Path, case_id: str) -> tuple[Path, Path]:
    base = Path(workspace)
    if not base.is_absolute():
        base = base.absolute()
    case_dir = base / case_id
    _safe_existing(base, directory=True)
    _safe_existing(case_dir, directory=True)
    return case_dir, case_dir / "research"


def _current_packets(workspace: Path, case_id: str) -> dict:
    try:
        if type(case_id) is not str or _ID.fullmatch(case_id) is None:
            _fail(_CASE_CHANGED)
        return _fresh_packets(Path(workspace), case_id)
    except (ResearchStoreError, ExplanationStoreError):
        raise ResearchStoreError(_CASE_CHANGED) from None


def _current_identity(workspace: Path, case_id: str) -> str:
    return packet_identity(_current_packets(workspace, case_id)[2])


def _read_record(path: Path) -> dict:
    try:
        _safe_existing(path, directory=False)
    except ExplanationStoreError:
        _fail()
    try:
        with path.open("rb") as stream:
            data = stream.read(_MAX_RECORD + 1)
    except OSError:
        _fail()
    return validate_research_record(_decode(data))


def store_research_record(workspace: Path, value: dict) -> Path:
    """Publish one immutable record atomically within its registered case."""
    record = validate_research_record(value)
    case_id = record["case_id"]
    if _current_identity(workspace, case_id) != record["packet_id"]:
        _fail(_CASE_CHANGED)
    try:
        _case_dir, research = _paths(workspace, case_id)
    except ExplanationStoreError:
        raise ResearchStoreError(_STORAGE) from None
    try:
        research.mkdir()
    except FileExistsError:
        pass
    except OSError:
        _fail(_STORAGE)
    try:
        _safe_existing(research, directory=True)
    except ExplanationStoreError:
        raise ResearchStoreError(_STORAGE) from None
    target = research / f"{record['record_id']}.json"
    if target.exists() or _is_reparse(target):
        try:
            existing = _read_record(target)
        except ResearchStoreError:
            _fail(_STORAGE)
        if _canonical(existing) == _canonical(record):
            return target
        _fail(_STORAGE)
    data = _canonical(record)
    temporary = research / f".{record['record_id']}.{secrets.token_hex(8)}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if _current_identity(workspace, case_id) != record["packet_id"]:
            _fail(_CASE_CHANGED)
        try:
            os.link(temporary, target)
        except FileExistsError:
            existing = _read_record(target)
            if _canonical(existing) != _canonical(record):
                _fail(_STORAGE)
        return target
    except ResearchStoreError:
        raise
    except OSError:
        _fail(_STORAGE)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def read_case_research(workspace: Path, case_id: str) -> dict:
    """Read a bounded set of valid records, isolating corrupt immutable sidecars.

    Returns ``{"records": [...], "warnings": [...]}`` with records ordered oldest
    to newest. A record is returned only while its ``packet_id`` matches the
    case's current version 2 evidence packet.
    """
    try:
        initial = _current_packets(workspace, case_id)
    except ResearchStoreError:
        return {"records": [], "warnings": [_CASE_WARNING]}
    identity = packet_identity(initial[2])
    try:
        _case_dir, research = _paths(workspace, case_id)
        if not research.exists():
            final = _current_packets(workspace, case_id)
            if any(_canonical(initial[v]) != _canonical(final[v]) for v in initial):
                return {"records": [], "warnings": [_CASE_WARNING]}
            return {"records": [], "warnings": []}
        _safe_existing(research, directory=True)
        entries = []
        with os.scandir(research) as iterator:
            for entry in iterator:
                entries.append(entry.name)
                if len(entries) > _MAX_RECORDS:
                    return {"records": [], "warnings": [_LIMIT_WARNING]}
    except (OSError, ResearchStoreError, ExplanationStoreError):
        return {"records": [], "warnings": [_COLLECTION_WARNING]}
    records, corrupt, stale = [], False, False
    for name in entries:
        if re.fullmatch(r"[0-9a-f]{64}\.json", name) is None:
            corrupt = True
            continue
        try:
            record = _read_record(research / name)
            if name != record["record_id"] + ".json" or record["case_id"] != case_id:
                _fail()
        except ResearchStoreError:
            corrupt = True
            continue
        if record["packet_id"] != identity:
            stale = True
            continue
        records.append(record)
    try:
        final = _current_packets(workspace, case_id)
        if any(_canonical(initial[v]) != _canonical(final[v]) for v in initial):
            return {"records": [], "warnings": [_CASE_WARNING]}
    except ResearchStoreError:
        return {"records": [], "warnings": [_CASE_WARNING]}
    records.sort(key=record_sort_key)
    warnings = []
    if corrupt:
        warnings.append(_COLLECTION_WARNING)
    if stale:
        warnings.append(_STALE_WARNING)
    return {"records": records, "warnings": warnings}
