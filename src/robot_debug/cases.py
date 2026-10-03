"""Structural case records and deterministic recipe identity.

This module validates the record's shape and stored identity only. It never
opens referenced files or certifies historical failure, replay, or badges.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any


class CaseValidationError(ValueError):
    """A case record violates the structural schema or its stored identity."""


_TOP = {
    "schema_version", "source", "task", "policy", "runtime", "perturbation",
    "protocol", "evidence", "measurements", "capabilities", "limitations",
}
_SOURCE = {"adapter", "summary", "replay"}
_TASK = {"suite", "task_id", "reset_index", "seed", "env_seed", "reset_strategy"}
_POLICY = {"model_id", "checkpoint_revision", "provenance"}
_RUNTIME = {
    "project_revision", "upstream_harness_revision", "simulator_image_digest",
    "provenance",
}
_PERTURBATION = {"family", "rectangle", "fill_value"}
_RECTANGLE = {"x", "y", "width", "height"}
_PROTOCOL = {"failures", "max_attempts", "reject_successes", "nominal_controls"}
_RECIPE_FIELDS = (
    ("task", "seed"), ("task", "env_seed"),
    ("policy", "model_id"), ("policy", "checkpoint_revision"),
    ("runtime", "project_revision"), ("runtime", "upstream_harness_revision"),
    ("runtime", "simulator_image_digest"), ("perturbation", "fill_value"),
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _object(value: Any, required: set[str], optional: set[str], label: str) -> dict:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise CaseValidationError(f"{label} must be a map with string keys")
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing or extra:
        raise CaseValidationError(f"{label} has missing {sorted(missing)} or unknown {sorted(extra)} keys")
    return value


def _string(value: Any, label: str, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value:
        raise CaseValidationError(f"{label} must be a nonempty string")
    return value


def _integer(value: Any, label: str, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        raise CaseValidationError(f"{label} must be an integer within range")
    return value


def _json_copy(value: Any, label: str, active: set[int] | None = None) -> Any:
    if value is None or isinstance(value, (str, bool)) or type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise CaseValidationError(f"{label} must contain finite numbers")
        return value
    if isinstance(value, (list, dict)):
        if active is None:
            active = set()
        if id(value) in active:
            raise CaseValidationError(f"{label} must not contain cycles")
        active.add(id(value))
        try:
            if isinstance(value, list):
                return [_json_copy(item, label, active) for item in value]
            if any(not isinstance(key, str) for key in value):
                raise CaseValidationError(f"{label} must have string keys")
            return {key: _json_copy(item, label, active) for key, item in value.items()}
        finally:
            active.remove(id(value))
    raise CaseValidationError(f"{label} must contain only JSON values")


def _metadata_map(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise CaseValidationError(f"{label} must be a map")
    return _json_copy(value, label)


def _reference(value: Any, label: str) -> dict:
    ref = _object(value, {"path", "sha256"}, set(), label)
    path = _string(ref["path"], f"{label}.path")
    if (
        path.startswith("/") or "\\" in path or ":" in path
        or any(part in ("", ".", "..") for part in path.split("/"))
    ):
        raise CaseValidationError(f"{label}.path must be a portable relative POSIX path")
    digest = _string(ref["sha256"], f"{label}.sha256")
    if _SHA256.fullmatch(digest) is None:
        raise CaseValidationError(f"{label}.sha256 must be lowercase SHA-256")
    return {"path": path, "sha256": digest}


def _rectangle(value: Any) -> dict:
    rect = _object(value, _RECTANGLE, set(), "perturbation.rectangle")
    result = {}
    for key in _RECTANGLE:
        number = rect[key]
        if type(number) not in (int, float):
            raise CaseValidationError(f"perturbation.rectangle.{key} must be finite numeric")
        try:
            result[key] = float(number)
        except OverflowError as exc:
            raise CaseValidationError(f"perturbation.rectangle.{key} must be finite numeric") from exc
        if not math.isfinite(result[key]):
            raise CaseValidationError(f"perturbation.rectangle.{key} must be finite numeric")
        if result[key] == 0:
            result[key] = 0.0
    x, y, width, height = (result[key] for key in ("x", "y", "width", "height"))
    if not (0 <= x <= 1 and 0 <= y <= 1 and width > 0 and height > 0
            and x + width <= 1 and y + height <= 1):
        raise CaseValidationError("perturbation.rectangle must lie within the unit image")
    return result


def _identity_parts(case: dict) -> dict:
    return {
        "source": {"adapter": case["source"]["adapter"]},
        "task": case["task"],
        "policy": {key: case["policy"][key] for key in ("model_id", "checkpoint_revision")},
        "runtime": {key: case["runtime"][key] for key in (
            "project_revision", "upstream_harness_revision", "simulator_image_digest")},
        "perturbation": case["perturbation"],
        "protocol": case["protocol"],
    }


def _identity_hash(case: dict) -> str:
    canonical = json.dumps(
        _identity_parts(case), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize(value: dict, check_stored_id: bool) -> dict:
    raw = _object(value, _TOP, {"case_id"}, "case")
    if _integer(raw["schema_version"], "schema_version") != 1:
        raise CaseValidationError("schema_version must be 1")

    source = _object(raw["source"], _SOURCE, {"profile"}, "source")
    if source["adapter"] != "existing-m4-v1":
        raise CaseValidationError("source.adapter must be existing-m4-v1")
    normalized_source = {
        "adapter": source["adapter"],
        "summary": _reference(source["summary"], "source.summary"),
        "replay": _reference(source["replay"], "source.replay"),
    }
    if "profile" in source:
        normalized_source["profile"] = (
            None if source["profile"] is None else _reference(source["profile"], "source.profile")
        )

    task = _object(raw["task"], _TASK, set(), "task")
    if task["suite"] != "libero-object" or task["reset_strategy"] != "libero-init-state-index":
        raise CaseValidationError("task suite or reset strategy is unsupported")
    normalized_task = dict(task)
    for key in ("task_id", "reset_index"):
        _integer(task[key], f"task.{key}", 0)
    for key in ("seed", "env_seed"):
        if task[key] is not None:
            _integer(task[key], f"task.{key}")

    policy = _object(raw["policy"], _POLICY, set(), "policy")
    normalized_policy = {
        "model_id": _string(policy["model_id"], "policy.model_id", True),
        "checkpoint_revision": _string(policy["checkpoint_revision"], "policy.checkpoint_revision", True),
        "provenance": _metadata_map(policy["provenance"], "policy.provenance"),
    }
    runtime = _object(raw["runtime"], _RUNTIME, set(), "runtime")
    normalized_runtime = {
        key: _string(runtime[key], f"runtime.{key}", True)
        for key in ("project_revision", "upstream_harness_revision", "simulator_image_digest")
    }
    digest = normalized_runtime["simulator_image_digest"]
    if digest is not None and _DIGEST.fullmatch(digest) is None:
        raise CaseValidationError("runtime.simulator_image_digest must be sha256:<lowercase hex>")
    normalized_runtime["provenance"] = _metadata_map(runtime["provenance"], "runtime.provenance")

    perturbation = _object(raw["perturbation"], _PERTURBATION, set(), "perturbation")
    if perturbation["family"] != "agentview-opaque-rectangle":
        raise CaseValidationError("perturbation.family is unsupported")
    fill = perturbation["fill_value"]
    if fill is not None:
        _integer(fill, "perturbation.fill_value", 0)
        if fill > 255:
            raise CaseValidationError("perturbation.fill_value exceeds 255")
    normalized_perturbation = {
        "family": perturbation["family"],
        "rectangle": _rectangle(perturbation["rectangle"]),
        "fill_value": fill,
    }

    protocol = _object(raw["protocol"], _PROTOCOL, set(), "protocol")
    expected_protocol = {
        "failures": 4, "max_attempts": 5, "reject_successes": 2, "nominal_controls": 5,
    }
    for key, expected in expected_protocol.items():
        if _integer(protocol[key], f"protocol.{key}") != expected:
            raise CaseValidationError(f"protocol.{key} must be {expected}")

    limitations = raw["limitations"]
    if not isinstance(limitations, list) or any(not isinstance(item, str) for item in limitations):
        raise CaseValidationError("limitations must be a list of strings")
    normalized = {
        "schema_version": 1,
        "source": normalized_source,
        "task": normalized_task,
        "policy": normalized_policy,
        "runtime": normalized_runtime,
        "perturbation": normalized_perturbation,
        "protocol": dict(protocol),
        "evidence": _metadata_map(raw["evidence"], "evidence"),
        "measurements": _metadata_map(raw["measurements"], "measurements"),
        "capabilities": _metadata_map(raw["capabilities"], "capabilities"),
        "limitations": list(limitations),
    }
    computed = _identity_hash(normalized)
    if check_stored_id and "case_id" in raw and raw["case_id"] != computed:
        raise CaseValidationError("stored case_id does not match the case recipe")
    normalized["case_id"] = computed
    return normalized


def normalize_case(value: dict) -> dict:
    """Validate and independently copy a structural case, filling its case ID.

    Positive claims in capabilities or evidence remain unverified data.
    """
    return _normalize(value, check_stored_id=True)


def case_identity(value: dict) -> str:
    """Hash normalized identity inputs, ignoring any stored case ID."""
    return _normalize(value, check_stored_id=False)["case_id"]


def recipe_missing(value: dict) -> list[str]:
    """List unavailable replay recipe inputs; an empty list proves no run claim."""
    normalized = normalize_case(value)
    return sorted(
        f"{group}.{field}" for group, field in _RECIPE_FIELDS
        if normalized[group][field] is None
    )
