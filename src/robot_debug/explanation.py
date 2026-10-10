"""Offline structural interpretation checks and deterministic reported facts."""

from __future__ import annotations

import json

from .evidence_packet import packet_identity, validate_evidence_packet


class ExplanationValidationError(ValueError):
    """Supplied interpretation does not match the offline response contract."""


_ERROR = "invalid explanation"
_ROLES = ("nominal", "parent", "reduced", "other")
_RAW = ("success", "task_failure", "episode_timeout", "infrastructure_error")
_GATE = ("success", "policy_failure", "infrastructure_error")
_DISCLAIMER = (
    "Facts count reported evidence only. The reduced mask is budget-local; "
    "these inputs provide no causal proof. Supplied interpretation requires human review."
)
_LINE_BREAKS = "\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029"


def _require(condition: bool) -> None:
    if not condition:
        raise ExplanationValidationError(_ERROR)


def _keys(value: object, expected: set[str]) -> dict:
    _require(type(value) is dict and set(value) == expected)
    return value


def _text(value: object) -> str:
    _require(type(value) is str and 0 < len(value) <= 600 and bool(value.strip())
             and not any(char in value for char in _LINE_BREAKS))
    value.encode("utf-8")
    return value


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ExplanationValidationError(_ERROR)


def _validate_response(response_json: str, packet: dict) -> dict:
    _require(type(response_json) is str)
    _require(len(response_json.encode("utf-8")) <= 16_384)
    response = json.loads(response_json, object_pairs_hook=_unique_pairs,
                          parse_constant=_reject_constant)
    value = _keys(response, {"schema_version", "observations", "hypotheses", "limitations"})
    _require(type(value["schema_version"]) is int and value["schema_version"] == 1)
    ids = {item["evidence_id"] for item in packet["episodes"]}
    result = {"schema_version": 1}
    for field, maximum in (("observations", 4), ("hypotheses", 3)):
        entries = value[field]
        _require(type(entries) is list and len(entries) <= maximum)
        checked = []
        for entry in entries:
            item = _keys(entry, {"text", "evidence_ids"})
            citations = item["evidence_ids"]
            _require(type(citations) is list and 1 <= len(citations) <= 64)
            _require(all(type(citation) is str and citation in ids for citation in citations))
            _require(len(set(citations)) == len(citations))
            checked.append({"text": _text(item["text"]), "evidence_ids": list(citations)})
        result[field] = checked
    limitations = value["limitations"]
    _require(type(limitations) is list and len(limitations) <= 6)
    result["limitations"] = [_text(item) for item in limitations]
    json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
    return result


def validate_explanation(response_json: str, packet: dict) -> dict:
    """Check JSON structure and citation membership, not the prose's truth."""
    validated_packet = validate_evidence_packet(packet)
    try:
        return _validate_response(response_json, validated_packet)
    except Exception:
        raise ExplanationValidationError(_ERROR) from None


def deterministic_summary(packet: dict) -> dict:
    """Count each reported episode once by role, raw and gate outcome."""
    validated = validate_evidence_packet(packet)
    counts = {
        role: {"raw_outcomes": {outcome: 0 for outcome in _RAW},
               "gate_outcomes": {outcome: 0 for outcome in _GATE}}
        for role in _ROLES
    }
    for episode in validated["episodes"]:
        row = counts[episode["role"]]
        row["raw_outcomes"][episode["raw_outcome"]] += 1
        row["gate_outcomes"][episode["gate_outcome"]] += 1
    rectangle = validated["reduced_mask"]["rectangle"]
    return {"total_episodes": len(validated["episodes"]),
            "counts_by_role": counts,
            "reduced_mask_area_fraction": rectangle["width"] * rectangle["height"]}


def mask_groups(packet: dict) -> list:
    """Group v2 episodes by role and exact mask; a pure function of the packet."""
    validated = validate_evidence_packet(packet)
    if validated["schema_version"] != 2:
        raise ValueError("mask groups require a version 2 packet")
    groups: dict = {}
    for episode in validated["episodes"]:
        mask = episode["mask"]
        key = (episode["role"], json.dumps(mask, sort_keys=True))
        group = groups.setdefault(key, {
            "role": episode["role"], "mask": mask,
            "area_fraction": None if mask is None else mask["width"] * mask["height"],
            "episodes": 0, "successes": 0, "policy_failures": 0,
            "infrastructure_errors": 0, "evidence_ids": [],
        })
        group["episodes"] += 1
        group[{"success": "successes", "policy_failure": "policy_failures",
               "infrastructure_error": "infrastructure_errors"}[episode["gate_outcome"]]] += 1
        group["evidence_ids"].append(episode["evidence_id"])
    order = {"nominal": 0, "parent": 1, "reduced": 2, "other": 3}
    result = []
    for key in sorted(groups, key=lambda item: (order[item[0]], item[1])):
        group = groups[key]
        group["evidence_ids"].sort()
        result.append(group)
    return result


def interpretation_context(packet: dict) -> dict:
    """Everything sent to the model for a v2 packet, derived only from the packet."""
    validated = validate_evidence_packet(packet)
    groups = mask_groups(validated)

    def tally(selected: list) -> dict:
        return {key: sum(group[key] for group in selected)
                for key in ("episodes", "successes", "policy_failures", "infrastructure_errors")}

    masked = [group for group in groups if group["mask"] is not None]
    totals = {"all": tally(groups),
              "nominal_unmasked": tally([g for g in groups if g["mask"] is None]),
              "masked": tally(masked),
              "distinct_masks_tested": len({json.dumps(g["mask"], sort_keys=True) for g in masked}),
              "masks_with_successes": [g["mask"] for g in masked if g["successes"] > 0],
              "masks_with_only_failures": [g["mask"] for g in masked
                                           if g["successes"] == 0 and g["policy_failures"] > 0]}
    return {"counts_by_role": deterministic_summary(validated)["counts_by_role"],
            "totals": totals,
            "mask_groups": groups,
            "packet": validated}


def build_offline_report(packet: dict, response_json: str | None = None) -> dict:
    """Keep packet facts even when optional supplied interpretation is invalid."""
    validated = validate_evidence_packet(packet)
    report = {"schema_version": 1, "packet_id": packet_identity(validated),
              "facts": deterministic_summary(validated),
              "interpretation_status": "absent", "interpretation": None,
              "error_code": None, "disclaimer": _DISCLAIMER}
    if response_json is None:
        return report
    try:
        report["interpretation"] = _validate_response(response_json, validated)
    except Exception:
        report["interpretation_status"] = "rejected"
        report["error_code"] = "invalid_explanation"
    else:
        report["interpretation_status"] = "validated-structure"
    return report
