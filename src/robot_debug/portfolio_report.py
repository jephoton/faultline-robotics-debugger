"""Fail-closed, provider-neutral comparison of portfolio diagnostic sessions."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Mapping

from robot_debug.portfolio_manifest import PortfolioManifest


_PHASES = ("apparent_failure", "reproducible_failure", "reduced_failure")
_VALID_OUTCOMES = {"success", "policy_failure"}


def compare_portfolios(sequential: Mapping[str, Any], adaptive: Mapping[str, Any]) -> dict[str, Any]:
    """Report a portfolio comparison without making unsupported speedup claims.

    Malformed durable evidence raises ``ValueError``. Contract mismatch and
    outcome/decision drift remain reportable, but always suppress speedup.
    """
    left = _validate_session(sequential, "sequential-jobs")
    right = _validate_session(adaptive, "adaptive-portfolio")
    same_manifest = left["manifest"] == right["manifest"] and left["manifest_integrity"] and right["manifest_integrity"]
    outcome_drift = _drift_ids(left["outcomes"], right["outcomes"])
    decision_drift = [job_id for job_id in left["job_ids"]
                      if left["decisions"][job_id] != right["decisions"].get(job_id)]
    limitations: list[str] = []
    if not same_manifest:
        limitations.append("frozen manifest hash or content differs; sessions are not comparable")
    if outcome_drift:
        limitations.append("durable episode outcomes differ; warm speedup is suppressed")
    if decision_drift:
        limitations.append("per-job flow decisions differ; warm speedup is suppressed")
    if left["unsafe_accounting"] or right["unsafe_accounting"]:
        limitations.append("accounting is incomplete or has invalid/uncertain attempts; warm speedup is suppressed")
    if not left["dry_run_known_live"] or not right["dry_run_known_live"]:
        limitations.append("dry_run is true or missing/unknown; synthetic timing cannot support a speedup claim")
    limitations.append("full VM allocation timing and reconciled billing are unavailable")

    comparable = same_manifest
    speedup_allowed = comparable and not outcome_drift and not decision_drift and not (
        left["unsafe_accounting"] or right["unsafe_accounting"]
    ) and left["dry_run_known_live"] and right["dry_run_known_live"]
    combined_statuses = {
        job_id: left["statuses"][job_id] if left["statuses"][job_id] == right["statuses"].get(job_id) else "status_drift"
        for job_id in left["job_ids"]
    }
    return {
        "schema_version": 1,
        "same_manifest": same_manifest,
        "comparable": comparable,
        "warm_diagnostic_speedup": left["elapsed"] / right["elapsed"] if speedup_allowed else None,
        "outcome_drift_case_ids": outcome_drift,
        "decision_drift_job_ids": decision_drift,
        "job_statuses": {"sequential": left["statuses"], "adaptive": right["statuses"]},
        "job_status_counts": dict(Counter(combined_statuses.values())),
        "successful_reports": {"sequential": _count(left["statuses"], "certified"),
                               "adaptive": _count(right["statuses"], "certified")},
        "task_coverage": {"sequential": len(left["job_ids"]), "adaptive": len(right["job_ids"])},
        "physical_attempts": _pair(left, right, "physical"),
        "valid_episodes": _pair(left, right, "valid"),
        "speculative_work": {"sequential": left["physical"] - left["valid"],
                             "adaptive": right["physical"] - right["valid"]},
        "warm_diagnostic_elapsed_seconds": _pair(left, right, "elapsed"),
        "warm_diagnostic_estimate_usd": _pair(left, right, "warm_cost"),
        "time_to_first_reproducible_report_seconds": _first_phase(left, right, "reproducible_failure"),
        "time_to_first_reduced_report_seconds": _first_phase(left, right, "reduced_failure"),
        "full_vm_allocation_estimated_compute_usd": None,
        "billed_cost_usd": None,
        "limitations": limitations,
    }


def _validate_session(raw: Mapping[str, Any], expected_mode: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or raw.get("mode") != expected_mode:
        raise ValueError(f"expected {expected_mode} portfolio summary")
    manifest_raw = raw.get("manifest")
    try:
        manifest = PortfolioManifest.from_mapping(manifest_raw)
    except (TypeError, ValueError) as error:
        raise ValueError("summary has an invalid frozen manifest") from error
    manifest_integrity = raw.get("manifest_hash") == manifest.config_hash
    job_ids = [job.job_id for job in manifest.jobs]
    jobs = raw.get("jobs")
    if not isinstance(jobs, Mapping) or set(jobs) != set(job_ids):
        raise ValueError("summary must contain exactly the frozen manifest jobs")
    elapsed = _positive(raw.get("elapsed_seconds"), "elapsed_seconds")
    physical = _count_value(raw.get("physical_attempts"), "physical_attempts")
    valid = _count_value(raw.get("valid_episodes"), "valid_episodes")
    if physical < valid:
        raise ValueError("physical_attempts cannot be less than valid_episodes")
    warm_cost = _nonnegative(raw.get("warm_diagnostic_estimate_usd"), "warm_diagnostic_estimate_usd")
    invalid = _count_value(raw.get("invalid_attempts"), "invalid_attempts")
    uncertain = _count_value(raw.get("uncertain_attempts"), "uncertain_attempts")
    outcomes = _durable_outcomes(raw.get("waves"), set(job_ids))
    statuses: dict[str, str] = {}
    decisions: dict[str, Any] = {}
    for job_id in job_ids:
        job = jobs[job_id]
        if not isinstance(job, Mapping) or job.get("job_id") != job_id or not isinstance(job.get("flow"), Mapping):
            raise ValueError("each job requires a durable flow summary")
        phase = job["flow"].get("phase")
        statuses[job_id] = _job_status(job, phase, raw.get("stop_reason"), outcomes[job_id])
        decisions[job_id] = job["flow"].get("decisions")
        _phase_times(job.get("phase_timestamps_seconds"), elapsed)
        if statuses[job_id] in {"certified", "no_failure", "nominal_failed"} and not outcomes[job_id]:
            raise ValueError("terminal job has no durable evidence")
    unsafe = raw.get("accounting_incomplete") is True or invalid > 0 or uncertain > 0 or any(
        record[1] != "valid" for record in outcomes.values() for record in record
    )
    return {"manifest": manifest.to_mapping(), "manifest_integrity": manifest_integrity,
            "job_ids": job_ids, "statuses": statuses, "decisions": decisions,
            "outcomes": {job_id: [(case_id, outcome) for case_id, _status, outcome in records]
                         for job_id, records in outcomes.items()},
            "elapsed": elapsed, "physical": physical, "valid": valid, "warm_cost": warm_cost,
            "unsafe_accounting": unsafe,
            "phases": {job_id: _phase_times(jobs[job_id].get("phase_timestamps_seconds"), elapsed) for job_id in job_ids},
            "dry_run_known_live": raw.get("dry_run") is False}


def _durable_outcomes(waves: object, job_ids: set[str]) -> dict[str, list[tuple[str, str, str]]]:
    if not isinstance(waves, list):
        raise ValueError("waves must be a list")
    result = {job_id: [] for job_id in job_ids}
    seen: set[str] = set()
    for wave in waves:
        if not isinstance(wave, Mapping) or not isinstance(wave.get("results"), list):
            raise ValueError("wave lacks durable results")
        for record in wave["results"]:
            if not isinstance(record, Mapping):
                raise ValueError("result must be a mapping")
            case_id = record.get("case_id")
            if not isinstance(case_id, str) or "--" not in case_id or case_id in seen:
                raise ValueError("result case IDs must be globally unique job-prefixed IDs")
            job_id, _ = case_id.split("--", 1)
            if job_id not in result:
                raise ValueError("result is not owned by a manifest job")
            seen.add(case_id)
            status = record.get("status")
            outcome = record.get("outcome")
            if status == "valid":
                if outcome not in _VALID_OUTCOMES or not _paths(record.get("evidence_paths")):
                    raise ValueError("valid result requires supported outcome and evidence")
            result[job_id].append((case_id, str(status), outcome if isinstance(outcome, str) else ""))
    return result


def _job_status(job: Mapping[str, Any], phase: object, portfolio_stop: object,
                records: list[tuple[str, str, str]]) -> str:
    if job.get("certified") is True and phase == "certified":
        return "certified"
    stop = job.get("terminal_status") or job["flow"].get("stop_reason")
    if stop == "no_apparent_failure":
        return "no_failure"
    if stop == "nominal_gate_failed":
        return "nominal_failed"
    if portfolio_stop == "shared_budget_exhausted" and phase not in {"stopped", "certified"}:
        return "budget_exhausted"
    if any(status != "valid" for _, status, _ in records):
        return "invalid_or_uncertain"
    return "incomplete"


def _phase_times(raw: object, elapsed: float) -> dict[str, float | None]:
    if not isinstance(raw, Mapping):
        raise ValueError("job lacks phase_timestamps_seconds")
    result: dict[str, float | None] = {}
    previous = 0.0
    for name in _PHASES:
        value = raw.get(name)
        if value is None:
            result[name] = None
        else:
            number = _nonnegative(value, f"phase_timestamps_seconds.{name}")
            if number > elapsed or number < previous:
                raise ValueError("phase timestamps must be monotonic and within elapsed time")
            result[name] = number
            previous = number
    return result


def _drift_ids(left: Mapping[str, list[tuple[str, str]]], right: Mapping[str, list[tuple[str, str]]]) -> list[str]:
    drift: list[str] = []
    for job_id in left:
        l = left[job_id]; r = right.get(job_id, [])
        for index in range(max(len(l), len(r))):
            a = l[index] if index < len(l) else None; b = r[index] if index < len(r) else None
            if a != b:
                for item in (a, b):
                    if item and item[0] not in drift:
                        drift.append(item[0])
    return drift


def _first_phase(left: Mapping[str, Any], right: Mapping[str, Any], phase: str) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for label, item in (("sequential", left), ("adaptive", right)):
        values = [times[phase] for times in item["phases"].values() if times[phase] is not None]
        result[label] = min(values) if values else None
    return result


def _pair(left: Mapping[str, Any], right: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {"sequential": left[field], "adaptive": right[field]}


def _count(statuses: Mapping[str, str], target: str) -> int:
    return sum(status == target for status in statuses.values())


def _paths(value: object) -> bool:
    return isinstance(value, (list, tuple)) and bool(value) and all(isinstance(path, str) and path for path in value)


def _count_value(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _positive(value: object, name: str) -> float:
    number = _nonnegative(value, name)
    if number == 0:
        raise ValueError(f"{name} must be positive")
    return number


def _nonnegative(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return float(value)
