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
# Stage names written by the M4 driver encode rectangles in thousandths,
# for example ``delta-0125-left-x0625-y0000-w0375-h0500-attempt-01``.
_STAGE_RECTANGLE = re.compile(r"(?:^|-)x(\d{4})-y(\d{4})-w(\d{4})-h(\d{4})(?:-|$)")
_VERSIONS = {1, 2}
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


def _rectangle(value: object) -> dict:
    rect = _keys(value, {"x", "y", "width", "height"})
    normalized = {key: _number(rect[key]) for key in ("x", "y", "width", "height")}
    x, y, width, height = (normalized[key] for key in ("x", "y", "width", "height"))
    _require(0 <= x <= 1 and 0 <= y <= 1 and width > 0 and height > 0
             and x + width <= 1 and y + height <= 1)
    return normalized


def _validate(packet: dict) -> dict:
    value = _keys(packet, {"schema_version", "task", "reduced_mask", "episodes"})
    version = value["schema_version"]
    _require(type(version) is int and version in _VERSIONS)
    task = _keys(value["task"], {"suite", "task_id", "reset_index"})
    _require(task["suite"] == "libero-object")
    normalized_task = {"suite": "libero-object", "task_id": _index(task["task_id"]),
                       "reset_index": _index(task["reset_index"])}

    mask = _keys(value["reduced_mask"], {"family", "rectangle", "fill_value"})
    _require(mask["family"] == "agentview-opaque-rectangle")
    normalized_rect = _rectangle(mask["rectangle"])
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
        fields = {"evidence_id", "role", "raw_outcome", "gate_outcome"}
        episode = _keys(item, fields | {"mask"} if version == 2 else fields)
        evidence_id = episode["evidence_id"]
        _require(type(evidence_id) is str and _ID.fullmatch(evidence_id) is not None
                 and evidence_id not in seen)
        seen.add(evidence_id)
        role, raw, gate = (episode[key] for key in ("role", "raw_outcome", "gate_outcome"))
        _require(type(role) is str and type(raw) is str and type(gate) is str)
        _require(role in _ROLES and (raw, gate) in _PAIRS)
        normalized = {"evidence_id": evidence_id, "role": role,
                      "raw_outcome": raw, "gate_outcome": gate}
        if version == 2:
            normalized["mask"] = None if episode["mask"] is None else _rectangle(episode["mask"])
        normalized_episodes.append(normalized)
    normalized_episodes.sort(key=lambda episode: episode["evidence_id"])
    result = {"schema_version": version, "task": normalized_task,
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


def _stage_rectangle(stage: object) -> dict | None:
    if type(stage) is not str:
        return None
    match = _STAGE_RECTANGLE.search(stage)
    if match is None:
        return None
    x, y, width, height = (int(group) / 1000 for group in match.groups())
    return {"x": x, "y": y, "width": width, "height": height}


def _episode_mask(item: dict, role: str, reduced: dict) -> dict | None:
    if role == "nominal":
        return None
    parsed = _stage_rectangle(item.get("stage"))
    if parsed is None and role == "reduced":
        return dict(reduced)
    return parsed


def make_evidence_packet(case: dict, schema_version: int = 1) -> dict:
    """Project structural source fields only; source claims remain unverified.

    Version 2 adds each episode's occlusion rectangle: parsed from the M4
    stage name, falling back to the case's reduced rectangle for the reduced
    role, and ``None`` for nominal or unparseable episodes.
    """
    try:
        _require(type(schema_version) is int and schema_version in _VERSIONS)
        source = normalize_case(case)
        task = source["task"]
        perturbation = source["perturbation"]
        fill = perturbation["fill_value"]
        reduced = perturbation["rectangle"]
        episodes = []
        for item in source["evidence"]["episodes"]:
            episode = {"evidence_id": item["episode_id"], "role": item["role"],
                       "raw_outcome": item["raw_outcome"], "gate_outcome": item["gate_outcome"]}
            if schema_version == 2:
                episode["mask"] = _episode_mask(item, item["role"], reduced)
            episodes.append(episode)
        packet = {
            "schema_version": schema_version,
            "task": {"suite": task["suite"], "task_id": task["task_id"],
                     "reset_index": task["reset_index"]},
            "reduced_mask": {"family": perturbation["family"],
                             "rectangle": perturbation["rectangle"],
                             "fill_value": None if fill is None else [fill] * 3},
            "episodes": episodes,
        }
        return validate_evidence_packet(packet)
    except Exception:
        raise EvidencePacketError(_ERROR) from None


def packet_identity(packet: dict) -> str:
    """SHA-256 of validated compact sorted UTF-8 JSON."""
    return hashlib.sha256(_canonical(validate_evidence_packet(packet))).hexdigest()
