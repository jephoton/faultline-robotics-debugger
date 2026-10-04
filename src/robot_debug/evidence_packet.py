"""Small allowlisted projection of a structural case for offline explanation."""

from __future__ import annotations

import hashlib
import json
import math
import re

from .cases import normalize_case


class EvidencePacketError(ValueError):
    """The packet cannot safely represent the supplied evidence."""


_ERROR = "invalid evidence packet"
_ID = re.compile(r"[0-9a-f]{16}\Z")
_ROLES = {"nominal", "parent", "reduced", "other"}
_PAIRS = {
    ("success", "success"),
    ("task_failure", "policy_failure"),
    ("episode_timeout", "policy_failure"),
    ("infrastructure_error", "infrastructure_error"),
}


def _require(condition: bool) -> None:
    if not condition:
        raise EvidencePacketError(_ERROR)


def _keys(value: object, expected: set[str]) -> dict:
    _require(type(value) is dict and set(value) == expected)
    return value


def _index(value: object) -> int:
    _require(type(value) is int and 0 <= value <= 1_000_000)
    return value


def _number(value: object) -> float:
    _require(type(value) in (int, float))
    number = float(value)
    _require(math.isfinite(number))
    return 0.0 if number == 0 else number


def _canonical(value: dict) -> bytes:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    _require(len(encoded) <= 16_384)
    return encoded


def _validate(packet: dict) -> dict:
    value = _keys(packet, {"schema_version", "task", "reduced_mask", "episodes"})
    _require(type(value["schema_version"]) is int and value["schema_version"] == 1)
    task = _keys(value["task"], {"suite", "task_id", "reset_index"})
    _require(task["suite"] == "libero-object")
    normalized_task = {"suite": "libero-object", "task_id": _index(task["task_id"]),
                       "reset_index": _index(task["reset_index"])}

    mask = _keys(value["reduced_mask"], {"family", "rectangle", "fill_value"})
    _require(mask["family"] == "agentview-opaque-rectangle")
    rect = _keys(mask["rectangle"], {"x", "y", "width", "height"})
    normalized_rect = {key: _number(rect[key]) for key in ("x", "y", "width", "height")}
    x, y, width, height = (normalized_rect[key] for key in ("x", "y", "width", "height"))
    _require(0 <= x <= 1 and 0 <= y <= 1 and width > 0 and height > 0
             and x + width <= 1 and y + height <= 1)
    fill = mask["fill_value"]
    if fill is not None:
        _require(type(fill) is list and len(fill) == 3)
        _require(all(type(channel) is int and 0 <= channel <= 255 for channel in fill))
        fill = list(fill)

    episodes = value["episodes"]
    _require(type(episodes) is list and 1 <= len(episodes) <= 64)
    normalized_episodes = []
    seen = set()
    for item in episodes:
        episode = _keys(item, {"evidence_id", "role", "raw_outcome", "gate_outcome"})
        evidence_id = episode["evidence_id"]
        _require(type(evidence_id) is str and _ID.fullmatch(evidence_id) is not None
                 and evidence_id not in seen)
        seen.add(evidence_id)
        role, raw, gate = (episode[key] for key in ("role", "raw_outcome", "gate_outcome"))
        _require(type(role) is str and type(raw) is str and type(gate) is str)
        _require(role in _ROLES and (raw, gate) in _PAIRS)
        normalized_episodes.append({"evidence_id": evidence_id, "role": role,
                                    "raw_outcome": raw, "gate_outcome": gate})
    normalized_episodes.sort(key=lambda episode: episode["evidence_id"])
    result = {"schema_version": 1, "task": normalized_task,
              "reduced_mask": {"family": "agentview-opaque-rectangle",
                               "rectangle": normalized_rect, "fill_value": fill},
              "episodes": normalized_episodes}
    _canonical(result)
    return result


def validate_evidence_packet(packet: dict) -> dict:
    """Validate exact packet fields and return a detached canonical-order copy."""
    try:
        return _validate(packet)
    except Exception as exc:
        raise EvidencePacketError(_ERROR) from None


def make_evidence_packet(case: dict) -> dict:
    """Project structural source fields only; source claims remain unverified."""
    try:
        source = normalize_case(case)
        task = source["task"]
        perturbation = source["perturbation"]
        fill = perturbation["fill_value"]
        packet = {
            "schema_version": 1,
            "task": {"suite": task["suite"], "task_id": task["task_id"],
                     "reset_index": task["reset_index"]},
            "reduced_mask": {"family": perturbation["family"],
                             "rectangle": perturbation["rectangle"],
                             "fill_value": None if fill is None else [fill] * 3},
            "episodes": [
                {"evidence_id": item["episode_id"], "role": item["role"],
                 "raw_outcome": item["raw_outcome"], "gate_outcome": item["gate_outcome"]}
                for item in source["evidence"]["episodes"]
            ],
        }
        return validate_evidence_packet(packet)
    except Exception:
        raise EvidencePacketError(_ERROR) from None


def packet_identity(packet: dict) -> str:
    """SHA-256 of validated compact sorted UTF-8 JSON."""
    return hashlib.sha256(_canonical(validate_evidence_packet(packet))).hexdigest()
