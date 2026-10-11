"""Bounded Tavily search client for M5D public-research context.

The request body, host, path and credit cap are fixed. Every request first
consumes one entry of an exclusive on-disk ledger, so the project-wide cap holds
across processes. Responses are reduced to an allowlisted, length-bounded shape;
retrieved text is untrusted data and is never executed or rendered as markup.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import http.client
import json
import math
import os
import re
import secrets
import socket
import ssl
import stat
import unicodedata
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from .token_factory import _fsync_directory, _is_reparse, _safe_path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RESEARCH_ROOT = REPOSITORY_ROOT / "artifacts" / "m5d-research"
LEDGER_ROOT = RESEARCH_ROOT / "tavily-ledger"
CACHE_ROOT = RESEARCH_ROOT / "cache"
DEFAULT_ENV_FILE = REPOSITORY_ROOT / ".env"

CREDIT_CAP = 50
MAX_RESULTS = 5
MAX_QUERY_CHARS = 200

_HOST = "api.tavily.com"
_PATH = "/search"
_TIMEOUT_SECONDS = 30
_MAX_RESPONSE_BYTES = 262_144
_MAX_ENV_BYTES = 65_536
_MAX_KEY_CHARS = 512
_MAX_CACHE_BYTES = 262_144
_TITLE_CHARS = 200
_URL_CHARS = 500
_SNIPPET_CHARS = 600
_ENV_NAME = "TAVILY_API_KEY"
_KEY_PATTERN = re.compile(r"tvly-[A-Za-z0-9_-]{8,}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
_ERROR_CODES = {
    "missing_api_key", "invalid_api_key", "invalid_query", "unauthorized",
    "rate_limited", "http_error", "timeout", "invalid_response", "credit_cap",
    "unsafe_path", "storage_error",
}

Transport = Callable[[dict, str], dict]


class TavilyError(ValueError):
    """A fixed, non-secret client, ledger or cache error."""

    def __init__(self, code: str):
        self.code = code if code in _ERROR_CODES else "invalid_response"
        super().__init__(self.code)


# --- credentials -----------------------------------------------------------

def _valid_key(value: object) -> bool:
    return (type(value) is str and len(value) <= _MAX_KEY_CHARS
            and _KEY_PATTERN.fullmatch(value) is not None)


def _read_env_file(path: Path) -> str | None:
    descriptor = None
    try:
        metadata = path.lstat()
        if not _safe_path(path) or _is_reparse(path) or not stat.S_ISREG(metadata.st_mode) \
                or metadata.st_size > _MAX_ENV_BYTES:
            raise TavilyError("invalid_api_key")
        flags = os.O_RDONLY
        for name in ("O_BINARY", "O_NOFOLLOW"):
            flags |= getattr(os, name, 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_size > _MAX_ENV_BYTES
                or (metadata.st_dev, metadata.st_ino) != (opened.st_dev, opened.st_ino)):
            raise TavilyError("invalid_api_key")
        chunks = []
        remaining = _MAX_ENV_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > _MAX_ENV_BYTES:
            raise TavilyError("invalid_api_key")
        text = raw.decode("utf-8")
        if (any(not char.isprintable() and char not in "\r\n" for char in text)
                or "\r" in text.replace("\r\n", "")):
            raise TavilyError("invalid_api_key")
    except TavilyError:
        raise
    except Exception:
        raise TavilyError("invalid_api_key") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)

    found: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        if "=" not in stripped:
            continue
        name, raw_value = stripped.split("=", 1)
        if name.strip() != _ENV_NAME:
            continue
        value = raw_value.strip()
        if value.startswith(("'", '"')):
            quote = value[0]
            if len(value) < 2 or value[-1] != quote:
                raise TavilyError("invalid_api_key")
            value = value[1:-1]
            if quote in value:
                raise TavilyError("invalid_api_key")
        elif "'" in value or '"' in value:
            raise TavilyError("invalid_api_key")
        if not _valid_key(value):
            raise TavilyError("invalid_api_key")
        found.append(value)
    if not found:
        return None
    if any(value != found[0] for value in found[1:]):
        raise TavilyError("invalid_api_key")
    return found[0]


def load_api_key(env_file: Path | None = None) -> str:
    """Load the key from the process environment, else from one dotenv file.

    An explicitly named file must agree with the environment when both exist.
    Without one, the repository's ignored ``.env`` is the fallback. The key is
    never logged, stored or included in any error.
    """
    environment = os.environ.get(_ENV_NAME)
    if environment is not None and not _valid_key(environment):
        raise TavilyError("invalid_api_key")
    if env_file is not None:
        selected = _read_env_file(Path(env_file))
        if environment is not None and selected is not None and environment != selected:
            raise TavilyError("invalid_api_key")
        result = selected if selected is not None else environment
    elif environment is not None:
        result = environment
    else:
        fallback = Path(DEFAULT_ENV_FILE)
        result = _read_env_file(fallback) if os.path.lexists(fallback) else None
    if result is None:
        raise TavilyError("missing_api_key")
    return result


# --- request and transport -------------------------------------------------

def _clean_query(query: object) -> str:
    if (type(query) is not str or not query.strip() or len(query) > MAX_QUERY_CHARS
            or not query.isascii() or not query.isprintable()):
        raise TavilyError("invalid_query")
    return query


def _request_body(query: str) -> dict:
    """The only request body this client can send."""
    return {
        "query": query,
        "search_depth": "basic",
        "max_results": MAX_RESULTS,
        "topic": "general",
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
        "auto_parameters": False,
        "include_usage": True,
    }


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def query_hash(query: str) -> str:
    """SHA-256 of the query together with every fixed request parameter."""
    return hashlib.sha256(_canonical(_request_body(_clean_query(query)))).hexdigest()


def _json_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError


def _decode_json(body: bytes) -> dict:
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=_json_pairs,
                           parse_constant=_reject_constant)
    except Exception:
        raise TavilyError("invalid_response") from None
    if type(value) is not dict:
        raise TavilyError("invalid_response")
    return value


def _default_transport(payload: dict, api_key: str) -> dict:
    if not _valid_key(api_key):
        raise TavilyError("invalid_api_key")
    try:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except Exception:
        raise TavilyError("invalid_response") from None
    headers = {"Accept": "application/json", "Content-Type": "application/json",
               "Authorization": f"Bearer {api_key}"}
    connection = http.client.HTTPSConnection(
        _HOST, timeout=_TIMEOUT_SECONDS, context=ssl.create_default_context())
    try:
        connection.request("POST", _PATH, body=body, headers=headers)
        response = connection.getresponse()
        status = response.status
        if status != 200:
            if status in (401, 403):
                raise TavilyError("unauthorized")
            if status in (429, 432, 433):
                raise TavilyError("rate_limited")
            raise TavilyError("http_error")
        response_body = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(response_body) > _MAX_RESPONSE_BYTES:
            raise TavilyError("invalid_response")
        return _decode_json(response_body)
    except TavilyError:
        raise
    except (TimeoutError, socket.timeout):
        raise TavilyError("timeout") from None
    except Exception:
        raise TavilyError("http_error") from None
    finally:
        connection.close()


def _transport_code(error: BaseException) -> str:
    if isinstance(error, TavilyError):
        return error.code if error.code in {
            "unauthorized", "rate_limited", "http_error", "timeout",
            "invalid_response", "invalid_api_key"} else "http_error"
    if isinstance(error, (TimeoutError, socket.timeout)):
        return "timeout"
    return "http_error"


# --- response normalization ------------------------------------------------

def _clean_text(value: object, limit: int) -> str | None:
    """Strip control and format characters, collapse whitespace, truncate."""
    if type(value) is not str:
        return None
    pieces = []
    for char in value:
        category = unicodedata.category(char)
        if category in ("Cc", "Zl", "Zp", "Zs"):
            pieces.append(" ")
        elif category in ("Cf", "Cs", "Co", "Cn"):
            continue
        else:
            pieces.append(char)
    text = " ".join("".join(pieces).split())
    return text[:limit].rstrip()


def _clean_url(value: object) -> str | None:
    if (type(value) is not str or not value or len(value) > _URL_CHARS
            or not value.isascii() or not value.isprintable() or " " in value):
        return None
    try:
        parts = urlsplit(value)
        port = parts.port
        host = parts.hostname
    except ValueError:
        return None
    if (parts.scheme != "https" or not host or "@" in parts.netloc
            or port not in (None, 443) or "\\" in value):
        return None
    return value


def _finite_score(value: object) -> float | None:
    if type(value) not in (int, float):
        return None
    number = float(value)
    return number if math.isfinite(number) and 0 <= number <= 1 else None


def _clean_result(title: object, url: object, snippet: object,
                  score: object) -> dict | None:
    """One allowlisted result, or None when any field is unusable."""
    clean_title = _clean_text(title, _TITLE_CHARS)
    clean_url = _clean_url(url)
    clean_snippet = _clean_text(snippet, _SNIPPET_CHARS)
    clean_score = _finite_score(score)
    if not clean_title or clean_url is None or clean_snippet is None or clean_score is None:
        return None
    return {"title": clean_title, "url": clean_url, "snippet": clean_snippet,
            "score": clean_score}


def _contains_secret(value: object, api_key: str) -> bool:
    if type(value) is str:
        return api_key in value
    if type(value) is list:
        return any(_contains_secret(item, api_key) for item in value)
    if type(value) is dict:
        return any(_contains_secret(key, api_key) or _contains_secret(item, api_key)
                   for key, item in value.items())
    return False


def _optional_metadata(response: dict) -> tuple[str | None, float | None, int | None]:
    request_id = response.get("request_id")
    if (type(request_id) is not str or not 0 < len(request_id) <= 100
            or not request_id.isascii() or not request_id.isprintable()):
        request_id = None
    elapsed = response.get("response_time")
    if (type(elapsed) not in (int, float) or not math.isfinite(float(elapsed))
            or not 0 <= elapsed <= 600):
        elapsed = None
    usage = response.get("usage")
    credits = usage.get("credits") if type(usage) is dict else None
    if type(credits) is not int or not 0 <= credits <= 100:
        credits = None
    return request_id, None if elapsed is None else float(elapsed), credits


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize(query: str, response: object, api_key: str) -> dict:
    """Reduce a raw provider response to the stored shape or reject it."""
    if type(response) is not dict or _contains_secret(response, api_key):
        raise TavilyError("invalid_response")
    raw_results = response.get("results")
    if type(raw_results) is not list or len(raw_results) > MAX_RESULTS:
        raise TavilyError("invalid_response")
    results = []
    for item in raw_results:
        if type(item) is not dict:
            continue
        cleaned = _clean_result(item.get("title"), item.get("url"),
                                item.get("content"), item.get("score"))
        if cleaned is not None:
            results.append(cleaned)
    request_id, elapsed, credits = _optional_metadata(response)
    return {
        "schema_version": 1,
        "query": query,
        "retrieved_at": _utc_now(),
        "request_id": request_id,
        "response_time": elapsed,
        # One reserved ledger entry is one basic-depth credit.
        "credits": 1 if credits is None else credits,
        "results": results,
    }


# --- ledger ----------------------------------------------------------------

def _ensure_directory(path: Path) -> None:
    root = Path(path)
    if not _safe_path(root):
        raise TavilyError("unsafe_path")
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception:
        raise TavilyError("unsafe_path") from None
    if not root.is_dir() or not _safe_path(root) or _is_reparse(root):
        raise TavilyError("unsafe_path")


def reserve_credit(ledger_root: Path, query_hash_value: str) -> int:
    """Exclusively consume one of the CREDIT_CAP ledger entries; return its number.

    The entry is created before the request and never released, so a failed or
    interrupted request still counts. The file names 001..050 are the cap.
    """
    if type(query_hash_value) is not str or _HASH.fullmatch(query_hash_value) is None:
        raise TavilyError("invalid_query")
    root = Path(ledger_root)
    _ensure_directory(root)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    for index in range(1, CREDIT_CAP + 1):
        destination = root / f"{index:03d}.json"
        try:
            descriptor = os.open(destination, flags, 0o600)
        except FileExistsError:
            continue
        except Exception:
            raise TavilyError("storage_error") from None
        entry = {"schema_version": 1, "index": index, "credits": 1,
                 "cap": CREDIT_CAP, "query_hash": query_hash_value,
                 "reserved_at": _utc_now()}
        try:
            stream = os.fdopen(descriptor, "wb")
            descriptor = None
            with stream:
                stream.write(_canonical(entry))
                stream.flush()
                os.fsync(stream.fileno())
            _fsync_directory(root)
        except KeyboardInterrupt:
            # The exclusive entry is deliberately retained after an interrupt.
            raise
        except Exception:
            # A partial entry still consumes the credit.
            raise TavilyError("storage_error") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
        return index
    raise TavilyError("credit_cap")


def credits_reserved(ledger_root: Path) -> int:
    """Number of ledger entries consumed so far (0 when no ledger exists)."""
    root = Path(ledger_root)
    if not root.is_dir():
        return 0
    return sum(1 for index in range(1, CREDIT_CAP + 1)
               if os.path.lexists(root / f"{index:03d}.json"))


# --- cache -----------------------------------------------------------------

_CACHE_KEYS = {"schema_version", "query", "retrieved_at", "request_id",
               "response_time", "credits", "results"}


def _validate_cached(value: object, query: str) -> dict:
    if type(value) is not dict or set(value) != _CACHE_KEYS:
        raise TavilyError("invalid_response")
    if (type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["query"] != query or type(value["retrieved_at"]) is not str
            or _UTC.fullmatch(value["retrieved_at"]) is None):
        raise TavilyError("invalid_response")
    request_id, elapsed, _ignored = _optional_metadata(
        {"request_id": value["request_id"], "response_time": value["response_time"]})
    if request_id != value["request_id"] or elapsed != (
            None if value["response_time"] is None else float(value["response_time"])):
        raise TavilyError("invalid_response")
    credits = value["credits"]
    if type(credits) is not int or not 0 <= credits <= 100:
        raise TavilyError("invalid_response")
    results = value["results"]
    if type(results) is not list or len(results) > MAX_RESULTS:
        raise TavilyError("invalid_response")
    cleaned = []
    for item in results:
        if type(item) is not dict or set(item) != {"title", "url", "snippet", "score"}:
            raise TavilyError("invalid_response")
        result = _clean_result(item["title"], item["url"], item["snippet"], item["score"])
        if result is None or result != {**item, "score": float(item["score"])}:
            raise TavilyError("invalid_response")
        cleaned.append(result)
    return {**value, "response_time": elapsed, "results": cleaned}


def _read_cache(cache_root: Path, key: str, query: str) -> dict | None:
    path = Path(cache_root) / f"{key}.json"
    try:
        if not _safe_path(path) or _is_reparse(path):
            return None
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_CACHE_BYTES:
            return None
        with path.open("rb") as stream:
            data = stream.read(_MAX_CACHE_BYTES + 1)
        if len(data) > _MAX_CACHE_BYTES:
            return None
        return _validate_cached(_decode_json(data), query)
    except (OSError, TavilyError, ValueError, TypeError, KeyError):
        return None


def _write_cache(cache_root: Path, key: str, entry: dict) -> None:
    root = Path(cache_root)
    _ensure_directory(root)
    target = root / f"{key}.json"
    if _is_reparse(target):
        raise TavilyError("unsafe_path")
    temporary = root / f".{key}.{secrets.token_hex(8)}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(_canonical(entry))
            stream.flush()
            os.fsync(stream.fileno())
        # Replace atomically: a corrupt or refreshed entry must be superseded.
        os.replace(temporary, target)
    except TavilyError:
        raise
    except OSError:
        raise TavilyError("storage_error") from None
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


# --- public entry point ----------------------------------------------------

def search(query: str, api_key: str, *, ledger_root: Path, cache_root: Path,
           refresh: bool = False, transport: Transport | None = None) -> dict:
    """Return the normalized result for one query, from cache when possible.

    A live request reserves a credit first, makes exactly one POST with the
    fixed body, and caches the normalized response. ``refresh`` skips the cache
    but still reserves a credit. The returned dict carries ``from_cache``.
    """
    if not _valid_key(api_key):
        raise TavilyError("invalid_api_key")
    clean = _clean_query(query)
    body = _request_body(clean)
    key = hashlib.sha256(_canonical(body)).hexdigest()
    if not refresh:
        cached = _read_cache(cache_root, key, clean)
        if cached is not None:
            result = dict(cached)
            result.pop("schema_version")
            result["from_cache"] = True
            return result
    reserve_credit(ledger_root, key)
    call = _default_transport if transport is None else transport
    try:
        response = call(dict(body), api_key)
    except Exception as exc:
        # The reserved credit stays consumed; no retry is attempted.
        raise TavilyError(_transport_code(exc)) from None
    entry = _normalize(clean, response, api_key)
    _write_cache(cache_root, key, entry)
    result = dict(entry)
    result.pop("schema_version")
    result["from_cache"] = False
    return result
