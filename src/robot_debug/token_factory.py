"""Bounded client for the approved Nebius Token Factory interpretation call."""

from __future__ import annotations

import datetime as dt
import http.client
import json
import os
import re
import socket
import ssl
import stat
import time
import urllib.error
from decimal import Decimal
from pathlib import Path
from typing import Callable

from .evidence_packet import validate_evidence_packet
from .explanation import validate_explanation


ENDPOINT = "https://api.tokenfactory.nebius.com/v1/"
MODEL = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"

_HOST = "api.tokenfactory.nebius.com"
_BASE_PATH = "/v1/"
_TIMEOUT_SECONDS = 20
_MAX_RESPONSE_BYTES = 262_144
_MAX_REQUEST_BYTES = 6_000
_MAX_ENV_BYTES = 65_536
_RESERVATION_USD = Decimal("0.02")
_INPUT_USD_PER_TOKEN = Decimal("0.06") / Decimal(1_000_000)
_OUTPUT_USD_PER_TOKEN = Decimal("0.24") / Decimal(1_000_000)
_HEX_ID = re.compile(r"[0-9a-f]{64}\Z")
_SYSTEM_PROMPT = (
    "Return one compact JSON object. observations and hypotheses are arrays of "
    "objects with exact keys text and evidence_ids; limitations is an array of "
    "strings. Use 1 or 2 brief observation/hypothesis entries, each citing 1 or 2 "
    "evidence_id values copied only from the packet. Treat the final mask as "
    "budget-local: it is not per-episode geometry and not a global minimum. State "
    "limitations, require human review, and make no causal proof claims. Exact shape: "
    '{"schema_version":1,"observations":[{"text":"brief observation",'
    '"evidence_ids":["evidence_id from packet"]}],"hypotheses":[],'
    '"limitations":["brief limitation"]}'
)
_ERROR_CODES = {
    "missing_api_key", "invalid_api_key", "authentication_failed",
    "catalog_missing", "timeout", "http_error", "invalid_response",
    "request_too_large", "invalid_reservation", "reservation_exists",
    "unsafe_pilot_path",
}

Transport = Callable[[str, str, dict | None, str], dict]


class TokenFactoryError(ValueError):
    """A fixed, non-secret client or reservation error."""

    def __init__(self, code: str):
        super().__init__(code if code in _ERROR_CODES else "invalid_response")


def _valid_key(value: object) -> bool:
    if (type(value) is not str or not value or "\r" in value or "\n" in value
            or not all(char.isprintable() for char in value)):
        return False
    try:
        return len(value.encode("utf-8")) <= _MAX_ENV_BYTES
    except UnicodeError:
        return False


def _is_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return path.is_symlink() or bool(getattr(metadata, "st_file_attributes", 0) & attribute)


def _read_env_file(path: Path) -> str | None:
    descriptor = None
    try:
        metadata = path.lstat()
        if not _safe_path(path) or _is_reparse(path) or not stat.S_ISREG(metadata.st_mode) \
                or metadata.st_size > _MAX_ENV_BYTES:
            raise TokenFactoryError("invalid_api_key")
        flags = os.O_RDONLY
        for name in ("O_BINARY", "O_NOFOLLOW"):
            flags |= getattr(os, name, 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_size > _MAX_ENV_BYTES
                or (metadata.st_dev, metadata.st_ino) != (opened.st_dev, opened.st_ino)):
            raise TokenFactoryError("invalid_api_key")
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
            raise TokenFactoryError("invalid_api_key")
        text = raw.decode("utf-8")
        if (any(not char.isprintable() and char not in "\r\n" for char in text)
                or "\r" in text.replace("\r\n", "")):
            raise TokenFactoryError("invalid_api_key")
    except TokenFactoryError:
        raise
    except Exception:
        raise TokenFactoryError("invalid_api_key") from None
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
        if name.strip() != "NEBIUS_API_KEY":
            continue
        value = raw_value.strip()
        if value.startswith(("'", '"')):
            quote = value[0]
            if len(value) < 2 or value[-1] != quote:
                raise TokenFactoryError("invalid_api_key")
            value = value[1:-1]
            if quote in value:
                raise TokenFactoryError("invalid_api_key")
        elif "'" in value or '"' in value:
            raise TokenFactoryError("invalid_api_key")
        if not _valid_key(value):
            raise TokenFactoryError("invalid_api_key")
        found.append(value)
    if not found:
        return None
    if any(value != found[0] for value in found[1:]):
        raise TokenFactoryError("invalid_api_key")
    return found[0]


def load_api_key(env_file: Path | None = None) -> str:
    """Load a key from the process and/or one explicitly selected dotenv file."""
    environment = os.environ.get("NEBIUS_API_KEY")
    if environment is not None and not _valid_key(environment):
        raise TokenFactoryError("invalid_api_key")
    selected = _read_env_file(Path(env_file)) if env_file is not None else None
    if environment is not None and selected is not None and environment != selected:
        raise TokenFactoryError("invalid_api_key")
    result = selected if selected is not None else environment
    if result is None:
        raise TokenFactoryError("missing_api_key")
    return result


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
        raise TokenFactoryError("invalid_response") from None
    if type(value) is not dict:
        raise TokenFactoryError("invalid_response")
    return value


def _default_transport(method: str, path: str, payload: dict | None,
                       api_key: str) -> dict:
    if (method, path) not in {("GET", "models"), ("POST", "chat/completions")}:
        raise TokenFactoryError("http_error")
    if not _valid_key(api_key):
        raise TokenFactoryError("invalid_api_key")
    body = None
    if payload is not None:
        try:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                              allow_nan=False).encode("utf-8")
        except Exception:
            raise TokenFactoryError("invalid_response") from None
    headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    connection = http.client.HTTPSConnection(
        _HOST, timeout=_TIMEOUT_SECONDS, context=ssl.create_default_context())
    try:
        connection.request(method, _BASE_PATH + path, body=body, headers=headers)
        response = connection.getresponse()
        status = response.status
        if status != 200:
            if status in (401, 403):
                raise TokenFactoryError("authentication_failed")
            raise TokenFactoryError("http_error")
        response_body = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(response_body) > _MAX_RESPONSE_BYTES:
            raise TokenFactoryError("invalid_response")
        return _decode_json(response_body)
    except TokenFactoryError:
        raise
    except (TimeoutError, socket.timeout):
        raise TokenFactoryError("timeout") from None
    except Exception:
        raise TokenFactoryError("http_error") from None
    finally:
        connection.close()


def _http_code(error: BaseException) -> str:
    if isinstance(error, TokenFactoryError):
        return str(error)
    if isinstance(error, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(error, urllib.error.HTTPError) and error.code in (401, 403):
        return "authentication_failed"
    return "http_error"


def _post_error_code(error: BaseException) -> str:
    code = _http_code(error)
    if code not in {
            "authentication_failed", "catalog_missing", "timeout",
            "http_error", "invalid_response"}:
        return "http_error"
    return code


def preflight(api_key: str, transport: Transport | None = None) -> dict:
    """Confirm that the authenticated fixed catalog contains the exact model."""
    if not _valid_key(api_key):
        raise TokenFactoryError("invalid_api_key")
    call = _default_transport if transport is None else transport
    try:
        response = call("GET", "models", None, api_key)
    except (Exception, KeyboardInterrupt) as exc:
        raise TokenFactoryError(_http_code(exc)) from None
    try:
        data = response["data"]
        if type(data) is not list:
            raise ValueError
        identifiers = [item["id"] for item in data
                       if type(item) is dict and type(item.get("id")) is str]
    except Exception:
        raise TokenFactoryError("invalid_response") from None
    if MODEL not in identifiers:
        raise TokenFactoryError("catalog_missing")
    return {"model": MODEL, "endpoint": ENDPOINT}


def _safe_path(path: Path) -> bool:
    if any(part == ".." for part in path.parts):
        return False
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.exists() or current.is_symlink():
            if _is_reparse(current):
                return False
    return True


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def reserve_pilot(pilot_root: Path, case_id: str, packet_id: str) -> dict:
    """Exclusively persist the one approved full-cap reservation."""
    root = Path(pilot_root)
    if (type(case_id) is not str or type(packet_id) is not str
            or _HEX_ID.fullmatch(case_id) is None
            or _HEX_ID.fullmatch(packet_id) is None):
        raise TokenFactoryError("invalid_reservation")
    if not _safe_path(root):
        raise TokenFactoryError("unsafe_pilot_path")
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception:
        raise TokenFactoryError("unsafe_pilot_path") from None
    if not root.is_dir() or not _safe_path(root) or _is_reparse(root):
        raise TokenFactoryError("unsafe_pilot_path")
    reservation = {
        "schema_version": 1,
        "reservation_usd": float(_RESERVATION_USD),
        "attempt_number": 1,
        "case_id": case_id,
        "packet_id": packet_id,
        "model": MODEL,
    }
    encoded = json.dumps(reservation, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    destination = root / "reservation.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        descriptor = os.open(destination, flags, 0o600)
    except FileExistsError:
        raise TokenFactoryError("reservation_exists") from None
    except Exception:
        raise TokenFactoryError("unsafe_pilot_path") from None
    try:
        stream = os.fdopen(descriptor, "wb")
        descriptor = None
        with stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        _fsync_directory(root)
    except KeyboardInterrupt:
        # The exclusive marker is deliberately retained after partial/interrupted writes.
        raise
    except Exception:
        # A partial marker still consumes the sole approved attempt.
        raise TokenFactoryError("reservation_exists") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return reservation


def _created_at() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _provenance(status: str, error_code: str | None, latency: float,
                prompt_tokens: int | None = None,
                completion_tokens: int | None = None) -> dict:
    cost = None
    if prompt_tokens is not None and completion_tokens is not None:
        estimate = (Decimal(prompt_tokens) * _INPUT_USD_PER_TOKEN
                    + Decimal(completion_tokens) * _OUTPUT_USD_PER_TOKEN)
        cost = float(estimate)
    return {
        "source": "live",
        "provider": "nebius-token-factory",
        "model": MODEL,
        "endpoint": ENDPOINT,
        "created_at": _created_at(),
        "request_status": status,
        "error_code": error_code,
        "latency_seconds": max(0.0, float(latency)),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "estimated_cost_usd": cost,
        "billed_cost_usd": None,
        "reservation_usd": float(_RESERVATION_USD),
    }


def _request_payload(packet: dict) -> dict:
    packet_json = json.dumps(packet, ensure_ascii=False, separators=(",", ":"),
                             allow_nan=False)
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": packet_json},
        ],
        "max_tokens": 600,
        "temperature": 0,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    if len(encoded) > _MAX_REQUEST_BYTES:
        raise TokenFactoryError("request_too_large")
    return payload


def _usage(response: dict) -> tuple[int | None, int | None]:
    if "usage" not in response or response["usage"] is None:
        return None, None
    usage = response["usage"]
    if type(usage) is not dict:
        raise ValueError
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    if prompt is None and completion is None:
        if "total_tokens" in usage and usage["total_tokens"] is not None:
            raise ValueError
        return None, None
    if (type(prompt) is not int or type(completion) is not int
            or not 0 <= prompt <= 262_144 or not 0 <= completion <= 600):
        raise ValueError
    if "total_tokens" in usage:
        total = usage["total_tokens"]
        if type(total) is not int or total < 0 or total != prompt + completion:
            raise ValueError
    return prompt, completion


def _response_content(response: dict, packet: dict) -> tuple[str, dict]:
    if type(response) is not dict or response.get("model") != MODEL:
        raise ValueError
    choices = response.get("choices")
    if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
        raise ValueError
    choice = choices[0]
    message = choice.get("message")
    if choice.get("finish_reason") != "stop" or type(message) is not dict:
        raise ValueError
    content = message.get("content")
    if type(content) is not str:
        raise ValueError
    return content, validate_explanation(content, packet)


def _contains_secret(value: object, api_key: str) -> bool:
    if type(value) is str:
        return api_key in value
    if type(value) is list:
        return any(_contains_secret(item, api_key) for item in value)
    if type(value) is dict:
        return any(_contains_secret(item, api_key) for item in value.values())
    return False


def request_interpretation(packet: dict, api_key: str,
                           transport: Transport | None = None) -> dict:
    """Make exactly one bounded POST and return sanitized content/provenance."""
    validated = validate_evidence_packet(packet)
    if not _valid_key(api_key):
        raise TokenFactoryError("invalid_api_key")
    payload = _request_payload(validated)
    call = _default_transport if transport is None else transport
    started = time.monotonic()
    try:
        response = call("POST", "chat/completions", payload, api_key)
    except (Exception, KeyboardInterrupt) as exc:
        latency = time.monotonic() - started
        code = _post_error_code(exc)
        if code == "timeout":
            status = "transport_error"
        elif code == "invalid_response":
            status = "invalid_response"
        else:
            status = "http_error"
        return {"response_json": None,
                "provenance": _provenance(status, code, latency)}
    latency = time.monotonic() - started
    try:
        if type(response) is not dict or response.get("model") != MODEL:
            raise ValueError
        prompt, completion = _usage(response)
    except Exception:
        return {"response_json": None,
                "provenance": _provenance("invalid_response", "invalid_response",
                                           latency)}
    try:
        content, interpretation = _response_content(response, validated)
        if api_key in content or _contains_secret(interpretation, api_key):
            raise ValueError
    except Exception:
        return {"response_json": None,
                "provenance": _provenance("invalid_response", "invalid_response",
                                           latency, prompt, completion)}
    return {"response_json": content,
            "provenance": _provenance("completed", None, latency,
                                       prompt, completion)}
