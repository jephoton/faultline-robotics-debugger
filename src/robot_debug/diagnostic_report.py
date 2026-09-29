"""Fail-closed comparison of one-worker and adaptive diagnostic sessions.

This module deliberately accepts decoded summary dictionaries, not paths or
provider records.  It has no cloud authority.  A provider-billed cost remains
unknown until an external billing record is reconciled.
"""

from __future__ import annotations

import json
import math
from typing import Any, Mapping

from robot_debug.diagnostic_flow import DiagnosticFlow
from robot_debug.reduce import Rect


_SCENARIO_FIELDS = (
    "config_hash", "model_id", "task_id", "seed", "perturbation_family",
    "search", "deltas", "gate_rules",
)
_PHASE_FIELDS = ("apparent_failure", "reproducible_failure", "reduced_failure")


def compare_sessions(sequential_summary: Mapping[str, Any], adaptive_summary: Mapping[str, Any]) -> dict[str, Any]:
    """Compare complete certified sessions without overstating a speedup.

    Mismatched frozen contracts and incomplete, uncertain, or unevidenced
    records are invalid inputs and raise ``ValueError``.  A matching contract
    with different terminal results returns an auditable report but no speedup
    claim.
    """
    sequential = _validate_summary(sequential_summary, "sequential")
    adaptive = _validate_summary(adaptive_summary, "adaptive")
    if sequential["scenario_contract"] != adaptive["scenario_contract"]:
        raise ValueError("sessions have unequal scenario_contract values")

    same_terminal_result = sequential["terminal"] == adaptive["terminal"]
    outcome_drift_case_ids = _outcome_drift_case_ids(sequential["ordered_outcomes"], adaptive["ordered_outcomes"])
    limitations: list[str] = []
    if not same_terminal_result:
        limitations.append("terminal diagnostic results differ; no speedup claim is valid")

    phase_metrics: dict[str, dict[str, float | None]] = {}
    for phase in _PHASE_FIELDS:
        values = {"sequential": sequential["phases"][phase], "adaptive": adaptive["phases"][phase]}
        phase_metrics[phase] = values
        missing = [policy for policy, value in values.items() if value is None]
        if missing:
            limitations.append(
                f"phase timestamps unavailable for {', '.join(missing)} ({phase}); metric is null where absent"
            )

    if outcome_drift_case_ids:
        limitations.append("ordered episode outcomes differ; no warm diagnostic speedup claim is valid")
    if sequential["dry_run"] or adaptive["dry_run"]:
        limitations.append("fake dry-run timing is not evidence of live diagnostic speedup")
    if sequential["dry_run"] != adaptive["dry_run"]:
        limitations.append("a fake dry-run and a live session are not comparable execution modes")
    limitations.append(
        "full VM allocation timestamps are unavailable; warm diagnostic cost is not a billed or full-allocation cost"
    )
    comparable = (same_terminal_result and not outcome_drift_case_ids
                  and sequential["dry_run"] == adaptive["dry_run"])
    speedup = (sequential["elapsed_seconds"] / adaptive["elapsed_seconds"]
               if comparable and not sequential["dry_run"] else None)
    return {
        "schema_version": 1,
        "sequential_session_id": sequential["session_id"],
        "adaptive_session_id": adaptive["session_id"],
        "comparable": comparable,
        "same_terminal_result": same_terminal_result,
        "outcome_drift_case_ids": outcome_drift_case_ids,
        "warm_diagnostic_speedup": speedup,
        "time_to_apparent_failure_seconds": phase_metrics["apparent_failure"],
        "time_to_reproducible_failure_seconds": phase_metrics["reproducible_failure"],
        "time_to_reduced_failure_seconds": phase_metrics["reduced_failure"],
        "end_to_end_seconds": _pair(sequential, adaptive, "elapsed_seconds"),
        "valid_episodes": _pair(sequential, adaptive, "valid_episodes"),
        "physical_attempts": _pair(sequential, adaptive, "physical_attempts"),
        "invalid_attempts": _pair(sequential, adaptive, "invalid_attempts"),
        "uncertain_attempts": _pair(sequential, adaptive, "uncertain_attempts"),
        "warm_diagnostic_estimated_compute_usd": _pair(sequential, adaptive, "warm_diagnostic_estimated_compute_usd"),
        "warm_diagnostic_estimated_cost_to_reduced_failure_usd": _pair(
            sequential, adaptive, "warm_diagnostic_estimated_cost_to_reduced_failure_usd"
        ),
        "full_vm_allocation_estimated_compute_usd": None,
        "final_area_percent": _pair(sequential, adaptive, "final_area_percent"),
        "billed_cost_usd": None,
        "warm_diagnostic_cost_rate_basis": "full_vm_hourly_rate_usd * warm_diagnostic_elapsed_seconds / 3600",
        "limitations": limitations,
    }


def _validate_summary(summary: Mapping[str, Any], expected_policy: str) -> dict[str, Any]:
    if not isinstance(summary, Mapping):
        raise ValueError("session summary must be a mapping")
    if summary.get("schema_version") != 1:
        raise ValueError("unsupported or missing session summary schema_version")
    session_id = _text(summary.get("session_id"), "session_id")
    if summary.get("policy") != expected_policy:
        raise ValueError(f"expected {expected_policy} summary")
    if summary.get("status") != "complete":
        raise ValueError("only complete sessions may be compared")
    if summary.get("certified") is not True or summary.get("controls_passed") is not True:
        raise ValueError("only certified sessions with passed controls may be compared")
    if summary.get("stop_reason") is not None:
        raise ValueError("a complete certified session cannot have a stop_reason")
    dry_run = summary.get("dry_run", False)
    if type(dry_run) is not bool:
        raise ValueError("dry_run must be a boolean when present")
    contract = summary.get("scenario_contract")
    if not isinstance(contract, Mapping) or set(contract) != set(_SCENARIO_FIELDS):
        raise ValueError("scenario_contract must contain exactly the frozen comparison fields")
    _validate_contract(contract)
    flow = _restore_and_check_flow(summary.get("flow"), contract, summary.get("certified_rectangle"))
    if not _path_list(summary.get("config_paths")):
        raise ValueError("complete summary must include config_paths")

    elapsed = _positive_number(summary.get("elapsed_seconds"), "elapsed_seconds")
    hourly_rate = _nonnegative_number(summary.get("full_vm_hourly_rate_usd"), "full_vm_hourly_rate_usd")
    valid = _nonnegative_count(summary.get("valid_episodes"), "valid_episodes")
    physical = _nonnegative_count(summary.get("physical_attempts"), "physical_attempts")
    invalid = _nonnegative_count(summary.get("invalid_attempts"), "invalid_attempts")
    uncertain = _nonnegative_count(summary.get("uncertain_attempts"), "uncertain_attempts")
    if physical != valid + invalid + uncertain:
        raise ValueError("complete session physical_attempts must equal recorded attempts")
    if invalid or uncertain:
        raise ValueError("invalid or uncertain attempts cannot support a comparison claim")

    rectangle = _rectangle(summary.get("certified_rectangle"))
    evidence_valid_count, ordered_outcomes = _require_certifying_evidence(summary.get("rounds"), summary.get("evidence_paths"))
    if valid != evidence_valid_count:
        raise ValueError("valid_episodes must equal the recorded valid round results")
    if flow.snapshot()["rounds"] != _flow_rounds_from_results(summary["rounds"]):
        raise ValueError("flow snapshot rounds do not match durable ordered results")
    phases = _phases(summary.get("phase_timestamps_seconds"), elapsed)
    normalized_contract = _canonical_json(contract, "scenario_contract")
    return {
        "session_id": session_id,
        "dry_run": dry_run,
        "scenario_contract": normalized_contract,
        "elapsed_seconds": elapsed,
        "valid_episodes": valid,
        "physical_attempts": physical,
        "invalid_attempts": invalid,
        "uncertain_attempts": uncertain,
        # This is the observed warm diagnostic window, not the VM allocation lifetime.
        "warm_diagnostic_estimated_compute_usd": hourly_rate * elapsed / 3600,
        "warm_diagnostic_estimated_cost_to_reduced_failure_usd": (
            None if phases["reduced_failure"] is None else hourly_rate * phases["reduced_failure"] / 3600
        ),
        "final_area_percent": rectangle["width"] * rectangle["height"] * 100,
        "terminal": (True, True, rectangle),
        "phases": phases,
        "ordered_outcomes": ordered_outcomes,
    }


def _require_certifying_evidence(rounds: object, evidence_paths: object) -> tuple[int, list[tuple[str, str]]]:
    if not isinstance(rounds, list) or not rounds:
        raise ValueError("complete summary must include rounds")
    if not _path_list(evidence_paths):
        raise ValueError("complete summary must include top-level evidence_paths")
    total_valid = 0
    ordered_outcomes: list[tuple[str, str]] = []
    for round_record in rounds:
        if not isinstance(round_record, Mapping):
            raise ValueError("round must be a mapping")
        _round_id(round_record.get("round_id"))
        _text(round_record.get("manifest_hash"), "manifest_hash")
        _text(round_record.get("ledger_path"), "ledger_path")
        case_ids = round_record.get("case_ids")
        if (not isinstance(case_ids, list) or not case_ids
                or any(not isinstance(case_id, str) or not case_id for case_id in case_ids)
                or len(case_ids) != len(set(case_ids))):
            raise ValueError("round case_ids must be unique non-empty strings")
        choice = round_record.get("worker_choice")
        if not isinstance(choice, Mapping) or set(choice) != {
            "workers", "reason", "predicted_seconds", "predicted_cost_usd"
        }:
            raise ValueError("round must include a complete worker_choice")
        if choice["workers"] not in (0, 1, 2, 4):
            raise ValueError("worker_choice.workers must be 0, 1, 2, or 4")
        _text(choice["reason"], "worker_choice.reason")
        _nonnegative_number(choice["predicted_seconds"], "worker_choice.predicted_seconds")
        _nonnegative_number(choice["predicted_cost_usd"], "worker_choice.predicted_cost_usd")
        results = round_record.get("results")
        if not isinstance(results, list) or not results:
            raise ValueError("round must have durable results")
        result_ids: list[str] = []
        for result in results:
            if not isinstance(result, Mapping) or result.get("status") != "valid":
                raise ValueError("all comparison results must be valid")
            result_ids.append(_text(result.get("case_id"), "result.case_id"))
            if result.get("outcome") not in {"success", "policy_failure"}:
                raise ValueError("valid result outcomes must be success or policy_failure")
            if not _path_list(result.get("evidence_paths")):
                raise ValueError("every valid result needs evidence_paths")
        if len(result_ids) != len(set(result_ids)) or set(result_ids) != set(case_ids):
            raise ValueError("round case_ids must exactly match result case_ids")
        by_id = {result["case_id"]: result["outcome"] for result in results}
        ordered_outcomes.extend((case_id, by_id[case_id]) for case_id in case_ids)
        total_valid += len(results)
    return total_valid, ordered_outcomes


def _phases(raw: object, elapsed: float) -> dict[str, float | None]:
    if raw is None:
        return {field: None for field in _PHASE_FIELDS}
    if not isinstance(raw, Mapping):
        raise ValueError("phase_timestamps_seconds must be a mapping when present")
    result: dict[str, float | None] = {}
    previous: float | None = None
    for field in _PHASE_FIELDS:
        value = raw.get(field)
        if value is None:
            result[field] = None
        else:
            timestamp = _nonnegative_number(value, f"phase_timestamps_seconds.{field}")
            if timestamp > elapsed:
                raise ValueError("phase timestamp cannot exceed elapsed_seconds")
            if previous is not None and timestamp < previous:
                raise ValueError("phase timestamps must be monotonic")
            result[field] = timestamp
            previous = timestamp
    return result


def _rectangle(raw: object) -> dict[str, float]:
    if not isinstance(raw, Mapping) or set(raw) != {"x", "y", "width", "height"}:
        raise ValueError("certified_rectangle must have x, y, width, and height")
    rectangle = {field: _nonnegative_number(raw[field], f"certified_rectangle.{field}")
                 for field in ("x", "y", "width", "height")}
    if rectangle["width"] == 0 or rectangle["height"] == 0 or rectangle["x"] + rectangle["width"] > 1 or rectangle["y"] + rectangle["height"] > 1:
        raise ValueError("certified_rectangle must be a nonempty unit rectangle")
    return rectangle


def _validate_contract(contract: Mapping[str, Any]) -> None:
    if not isinstance(contract["config_hash"], str) or not contract["config_hash"]:
        raise ValueError("scenario_contract.config_hash must be a non-empty string")
    if not isinstance(contract["model_id"], str) or not contract["model_id"]:
        raise ValueError("scenario_contract.model_id must be a non-empty string")
    _nonnegative_count(contract["task_id"], "scenario_contract.task_id")
    _nonnegative_count(contract["seed"], "scenario_contract.seed")
    if not isinstance(contract["perturbation_family"], str) or not contract["perturbation_family"]:
        raise ValueError("scenario_contract.perturbation_family must be a non-empty string")
    if not isinstance(contract["search"], (Mapping, list)) or not contract["search"]:
        raise ValueError("scenario_contract.search must be a non-empty mapping or ordered list")
    if not isinstance(contract["deltas"], list) or not contract["deltas"]:
        raise ValueError("scenario_contract.deltas must be a non-empty list")
    for delta in contract["deltas"]:
        _positive_number(delta, "scenario_contract.deltas entry")
    if not isinstance(contract["gate_rules"], Mapping) or not contract["gate_rules"]:
        raise ValueError("scenario_contract.gate_rules must be a non-empty mapping")
    for field in _SCENARIO_FIELDS:
        _json_value(contract[field], f"scenario_contract.{field}")


def _restore_and_check_flow(raw: object, contract: Mapping[str, Any], rectangle: object) -> DiagnosticFlow:
    """Replay the stored pure flow and bind it to the reported terminal result."""
    if not isinstance(raw, Mapping):
        raise ValueError("complete summary must include a flow snapshot")
    config = raw.get("config")
    if not isinstance(config, Mapping):
        raise ValueError("flow snapshot must include its frozen config")
    if config.get("config_hash") != contract["config_hash"]:
        raise ValueError("flow snapshot config_hash differs from scenario_contract")
    if _canonical_json(config.get("search"), "flow.config.search") != _canonical_json(contract["search"], "scenario_contract.search"):
        raise ValueError("flow snapshot search differs from scenario_contract")
    if _canonical_json(config.get("deltas"), "flow.config.deltas") != _canonical_json(contract["deltas"], "scenario_contract.deltas"):
        raise ValueError("flow snapshot deltas differ from scenario_contract")
    search_raw = config.get("search")
    if not isinstance(search_raw, list):
        raise ValueError("flow snapshot search must be a list")
    try:
        search = tuple((case_id, Rect(**geometry)) for case_id, geometry in search_raw)
        flow = DiagnosticFlow.restore(
            raw, search=search, deltas=config["deltas"], nominal_count=config["nominal_count"],
            candidate_attempt_budget=config["candidate_attempt_budget"], control_count=config["control_count"],
            config_hash=config["config_hash"],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("flow snapshot cannot be replayed") from error
    if not flow.certified or flow.phase != "certified" or flow.stop_reason is not None:
        raise ValueError("complete summary flow must be certified and unstopped")
    if _canonical_json(flow.snapshot()["current_rect"], "flow.current_rect") != _canonical_json(rectangle, "certified_rectangle"):
        raise ValueError("flow terminal rectangle differs from certified_rectangle")
    return flow


def _flow_rounds_from_results(rounds: object) -> list[dict[str, list[str]]]:
    if not isinstance(rounds, list):
        raise ValueError("rounds must be a list")
    result: list[dict[str, list[str]]] = []
    for round_record in rounds:
        if not isinstance(round_record, Mapping):
            raise ValueError("round must be a mapping")
        results = round_record.get("results")
        case_ids = round_record.get("case_ids")
        if not isinstance(results, list) or not isinstance(case_ids, list):
            raise ValueError("round results are malformed")
        by_id = {item["case_id"]: item["outcome"] for item in results if isinstance(item, Mapping)}
        result.append({"case_ids": list(case_ids), "outcomes": [by_id.get(case_id) for case_id in case_ids]})
    return result


def _outcome_drift_case_ids(sequential: list[tuple[str, str]], adaptive: list[tuple[str, str]]) -> list[str]:
    """Return stable IDs for changed or differently ordered durable outcomes."""
    drift: list[str] = []
    for index in range(max(len(sequential), len(adaptive))):
        left = sequential[index] if index < len(sequential) else None
        right = adaptive[index] if index < len(adaptive) else None
        if left == right:
            continue
        for item in (left, right):
            if item is not None and item[0] not in drift:
                drift.append(item[0])
    return drift


def _pair(sequential: Mapping[str, Any], adaptive: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {"sequential": sequential[field], "adaptive": adaptive[field]}


def _path_list(value: object) -> bool:
    return isinstance(value, (list, tuple)) and bool(value) and all(isinstance(item, str) and item for item in value)


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _round_id(value: object) -> str | int:
    if isinstance(value, str) and value:
        return value
    if not isinstance(value, bool) and isinstance(value, int) and value >= 0:
        return value
    raise ValueError("round_id must be a non-empty string or non-negative integer")


def _nonnegative_count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _positive_number(value: object, name: str) -> float:
    number = _nonnegative_number(value, name)
    if number == 0:
        raise ValueError(f"{name} must be positive")
    return number


def _nonnegative_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return float(value)


def _json_value(value: object, name: str) -> None:
    """Reject mutable/ambiguous or non-JSON values before equality comparison."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{name} must be finite JSON")
    if value is None or isinstance(value, (str, int, float, bool)):
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _json_value(item, name)
        return
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError(f"{name} must have string keys")
        for item in value.values():
            _json_value(item, name)
        return
    raise ValueError(f"{name} must be JSON-compatible")


def _canonical_json(value: object, name: str) -> Any:
    """Normalize driver in-memory tuples to their atomic-JSON representation."""
    try:
        return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be JSON-compatible") from error
