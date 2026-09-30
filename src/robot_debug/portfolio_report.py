"""Fail-closed comparison of frozen multi-job diagnostic portfolios."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Mapping

from robot_debug.diagnostic_flow import DiagnosticFlow
from robot_debug.portfolio_manifest import PortfolioManifest
from robot_debug.reduce import Rect
from robot_debug.session import is_reproducible


_PHASES = ("apparent_failure", "reproducible_failure", "reduced_failure")
_OUTCOMES = {"success", "policy_failure"}
_LIMITS = ("episodes", "seconds", "estimated_usd", "hourly_rate")


def compare_portfolios(sequential: Mapping[str, Any], adaptive: Mapping[str, Any]) -> dict[str, Any]:
    """Compare two durable sessions, withholding speedup unless evidence agrees."""
    left = _session(sequential, "sequential-jobs")
    right = _session(adaptive, "adaptive-portfolio")
    same_manifest = left["manifest"] == right["manifest"] and left["manifest_ok"] and right["manifest_ok"]
    same_limits = left["limits"] == right["limits"]
    outcome_drift = _drift(left["outcomes"], right["outcomes"])
    decision_drift = [job for job in left["job_ids"] if left["decisions"][job] != right["decisions"][job]]
    status_drift = [job for job in left["job_ids"] if left["statuses"][job] != right["statuses"][job]]
    limitations: list[str] = ["full VM allocation timing and reconciled billed cost are unavailable"]
    if not same_manifest:
        limitations.append("frozen manifest hash or content differs")
    if not same_limits:
        limitations.append("shared episode, wall-time, dollar, or hourly-rate limits differ")
    if outcome_drift:
        limitations.append("durable episode outcomes differ")
    if decision_drift:
        limitations.append("replayed per-job flow decisions differ")
    if status_drift:
        limitations.append("per-job terminal statuses differ")
    if not left["live"] or not right["live"]:
        limitations.append("exact live markers are absent or contradictory; timing is not product evidence")
    if not left["accounting_validated"] or not right["accounting_validated"]:
        limitations.append("per-wave validated launched accounting is unavailable")
    if left["unsafe"] or right["unsafe"]:
        limitations.append("session is incomplete, budget-exhausted, invalid, or uncertain")
    allowed = (same_manifest and same_limits and not outcome_drift and not decision_drift and not status_drift
               and left["live"] and right["live"] and left["accounting_validated"] and right["accounting_validated"]
               and not left["unsafe"] and not right["unsafe"])
    combined = {job: left["statuses"][job] if job not in status_drift else "status_drift" for job in left["job_ids"]}
    return {
        "schema_version": 2, "same_manifest": same_manifest, "same_limits": same_limits,
        "comparable": same_manifest and same_limits,
        "warm_diagnostic_speedup": left["elapsed"] / right["elapsed"] if allowed else None,
        "outcome_drift_case_ids": outcome_drift, "decision_drift_job_ids": decision_drift,
        "job_status_drift_job_ids": status_drift,
        "job_statuses": {"sequential": left["statuses"], "adaptive": right["statuses"]},
        "job_status_counts": dict(Counter(combined.values())),
        "successful_reports": {"sequential": _count(left["statuses"], "certified"),
                               "adaptive": _count(right["statuses"], "certified")},
        "task_coverage": {"sequential": len(left["evidence_jobs"]), "adaptive": len(right["evidence_jobs"])},
        "physical_attempts": _pair(left, right, "physical"), "valid_episodes": _pair(left, right, "valid"),
        "speculative_valid_work": _pair(left, right, "speculative_valid"),
        "unvalidated_attempts": _pair(left, right, "unvalidated"),
        "warm_diagnostic_elapsed_seconds": _pair(left, right, "elapsed"),
        "warm_diagnostic_estimate_usd": _pair(left, right, "warm_cost"),
        "time_to_first_reproducible_report_seconds": _first_phase(left, right, "reproducible_failure"),
        "time_to_first_reduced_report_seconds": _first_phase(left, right, "reduced_failure"),
        "full_vm_allocation_estimated_compute_usd": None, "billed_cost_usd": None, "limitations": limitations,
    }


def _session(raw: Mapping[str, Any], mode: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or raw.get("mode") != mode:
        raise ValueError(f"expected {mode} portfolio summary")
    try:
        manifest = PortfolioManifest.from_mapping(raw.get("manifest"))
    except (TypeError, ValueError) as error:
        raise ValueError("invalid frozen manifest") from error
    jobs = raw.get("jobs"); job_ids = [item.job_id for item in manifest.jobs]
    if not isinstance(jobs, Mapping) or set(jobs) != set(job_ids):
        raise ValueError("summary must contain exactly the frozen manifest jobs")
    limits = _limits(raw.get("limits")); elapsed = _positive(raw.get("elapsed_seconds"), "elapsed_seconds")
    physical = _integer(raw.get("physical_attempts"), "physical_attempts")
    valid = _integer(raw.get("valid_episodes"), "valid_episodes")
    invalid = _integer(raw.get("invalid_attempts"), "invalid_attempts")
    uncertain = _integer(raw.get("uncertain_attempts"), "uncertain_attempts")
    outcomes, valid_records, launched, accounting_validated = _waves(raw.get("waves"), set(job_ids))
    if valid != valid_records:
        raise ValueError("valid_episodes must equal valid wave result count")
    if physical < sum(len(records) for records in outcomes.values()):
        raise ValueError("physical_attempts cannot be less than durable wave result count")
    if accounting_validated and physical != launched:
        raise ValueError("physical_attempts must equal attested launched_attempts")
    statuses: dict[str, str] = {}; decisions: dict[str, Any] = {}; phases: dict[str, dict[str, float | None]] = {}
    for job_id in job_ids:
        job = jobs[job_id]
        if not isinstance(job, Mapping) or job.get("job_id") != job_id or not isinstance(job.get("flow"), Mapping):
            raise ValueError("each job requires a durable flow summary")
        flow = _restore(job["flow"])
        if flow.config_hash != f"{manifest.config_hash}:{job_id}":
            raise ValueError("flow config_hash does not bind the frozen manifest and job")
        expected_certified = flow.certified
        expected_terminal = "certified" if expected_certified else flow.stop_reason
        if job.get("certified") is not expected_certified:
            raise ValueError("job certified flag differs from replayed flow")
        if job.get("terminal_status") != expected_terminal:
            raise ValueError("job terminal_status differs from replayed flow")
        records = outcomes[job_id]
        terminal = flow.phase in {"stopped", "certified"}
        if terminal and _flow_records(flow, job_id) != records:
            raise ValueError("terminal flow rounds do not match job-prefixed wave records")
        statuses[job_id] = _status(flow, raw.get("stop_reason"), records)
        decisions[job_id] = flow.decisions
        phases[job_id] = _phase_times(job.get("phase_timestamps_seconds"), elapsed, flow)
    unsafe = (raw.get("accounting_incomplete") is not False or invalid > 0 or uncertain > 0
              or raw.get("stop_reason") == "shared_budget_exhausted"
              or any(status in {"incomplete", "invalid_or_uncertain", "budget_exhausted"} for status in statuses.values()))
    return {"manifest": manifest.to_mapping(), "manifest_ok": raw.get("manifest_hash") == manifest.config_hash,
            "limits": limits, "job_ids": job_ids, "statuses": statuses, "decisions": decisions,
            "outcomes": {job: [(case, outcome) for case, _status, outcome in records] for job, records in outcomes.items()},
            "evidence_jobs": {job for job, records in outcomes.items() if any(status == "valid" for _, status, _ in records)},
            "elapsed": elapsed, "physical": physical, "valid": valid,
            "warm_cost": _number(raw.get("warm_diagnostic_estimate_usd"), "warm_diagnostic_estimate_usd"),
            "speculative_valid": max(0, valid - _flow_record_count(jobs, job_ids)),
            "unvalidated": max(0, physical - launched), "accounting_validated": accounting_validated,
            "live": raw.get("dry_run") is False and raw.get("synthetic") is False and raw.get("execution_kind") == "live",
            "unsafe": unsafe, "phases": phases}


def _restore(snapshot: Mapping[str, Any]) -> DiagnosticFlow:
    config = snapshot.get("config") if isinstance(snapshot, Mapping) else None
    if not isinstance(config, Mapping) or not isinstance(config.get("search"), list):
        raise ValueError("flow snapshot lacks replayable config")
    try:
        search = tuple((item[0], Rect(**item[1])) for item in config["search"])
        return DiagnosticFlow.restore(snapshot, search=search, deltas=tuple(config["deltas"]),
                                      nominal_count=config["nominal_count"], candidate_attempt_budget=config["candidate_attempt_budget"],
                                      control_count=config["control_count"], config_hash=config["config_hash"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("flow snapshot cannot be replayed") from error


def _waves(waves: object, job_ids: set[str]) -> tuple[dict[str, list[tuple[str, str, str]]], int, int, bool]:
    if not isinstance(waves, list):
        raise ValueError("waves must be a list")
    results = {job: [] for job in job_ids}
    seen: set[str] = set()
    valid = launched = 0
    validated = bool(waves)
    for wave in waves:
        if not isinstance(wave, Mapping) or not isinstance(wave.get("results"), list):
            raise ValueError("wave lacks results")
        count = wave.get("launched_attempts")
        if (not isinstance(count, int) or isinstance(count, bool) or count < len(wave["results"])
                or wave.get("attempt_accounting_validated") is not True
                or not _path(wave.get("ledger_path"))):
            validated = False
        else:
            launched += count
        for record in wave["results"]:
            if not isinstance(record, Mapping):
                raise ValueError("result must be a mapping")
            case = record.get("case_id")
            if not isinstance(case, str) or "--" not in case or case in seen:
                raise ValueError("result IDs must be unique and job-prefixed")
            job, _local = case.split("--", 1)
            if job not in results:
                raise ValueError("result belongs to unknown job")
            status = record.get("status")
            outcome = record.get("outcome")
            if status == "valid":
                if outcome not in _OUTCOMES or not _paths(record.get("evidence_paths")):
                    raise ValueError("valid result requires outcome and evidence")
                valid += 1
            stored_outcome = outcome if isinstance(outcome, str) else ""
            results[job].append((case, str(status), stored_outcome))
            seen.add(case)
    return results, valid, launched, validated


def _flow_records(flow: DiagnosticFlow, job: str) -> list[tuple[str, str, str]]:
    return [(f"{job}--{case}", "valid", outcome)
            for round_record in flow.rounds for case, outcome in zip(round_record["case_ids"], round_record["outcomes"])]


def _flow_record_count(jobs: Mapping[str, Any], job_ids: list[str]) -> int:
    return sum(sum(len(round_record["case_ids"]) for round_record in jobs[job]["flow"].get("rounds", [])) for job in job_ids)


def _status(flow: DiagnosticFlow, stop: object, records: list[tuple[str, str, str]]) -> str:
    if flow.certified:
        return "certified"
    reason = flow.stop_reason
    if reason == "no_apparent_failure":
        return "no_failure"
    if reason == "nominal_gate_failed":
        return "nominal_failed"
    if stop == "shared_budget_exhausted" and flow.phase not in {"stopped", "certified"}:
        return "budget_exhausted"
    if any(status != "valid" for _, status, _ in records):
        return "invalid_or_uncertain"
    return "incomplete"


def _limits(raw: object) -> tuple[int | float, ...]:
    if not isinstance(raw, Mapping) or set(raw) != set(_LIMITS):
        raise ValueError("limits must contain frozen bounds")
    return (_integer(raw["episodes"], "limits.episodes"), *(_positive(raw[name], f"limits.{name}") for name in _LIMITS[1:]))


def _phase_times(raw: object, elapsed: float, flow: DiagnosticFlow) -> dict[str, float | None]:
    if not isinstance(raw, Mapping): raise ValueError("job lacks phase_timestamps_seconds")
    confirmation = next((round_record["outcomes"] for round_record in flow.rounds
                         if any(case.startswith("confirm-") for case in round_record["case_ids"])), None)
    expected = {
        "apparent_failure": any(item.get("phase") == "search" for item in flow.decisions),
        "reproducible_failure": confirmation is not None and is_reproducible(confirmation),
        "reduced_failure": any(item.get("phase") == "reduce_candidate" and item.get("decision") == "pass"
                               for item in flow.decisions),
        "terminal": flow.phase in {"stopped", "certified"},
    }
    if set(raw) != set((*_PHASES, "terminal")):
        raise ValueError("phase_timestamps_seconds must contain every gate")
    result = {}; prior = 0.0
    for phase in (*_PHASES, "terminal"):
        value = raw.get(phase)
        if value is None:
            if expected[phase]: raise ValueError(f"{phase} timestamp is required by replayed flow")
            result[phase] = None
        else:
            number = _number(value, f"phase_timestamps_seconds.{phase}")
            if number < prior or number > elapsed: raise ValueError("phase timestamps must be monotonic and within elapsed")
            if not expected[phase]: raise ValueError(f"{phase} timestamp has no replayed gate")
            result[phase] = number; prior = number
    return result


def _drift(left: Mapping[str, list[tuple[str, str]]], right: Mapping[str, list[tuple[str, str]]]) -> list[str]:
    drift = []
    for job, left_records in left.items():
        right_records = right[job]
        for index in range(max(len(left_records), len(right_records))):
            for record in (left_records[index] if index < len(left_records) else None, right_records[index] if index < len(right_records) else None):
                if record and record[0] not in drift and (index >= len(left_records) or index >= len(right_records) or left_records[index] != right_records[index]): drift.append(record[0])
    return drift


def _first_phase(left: Mapping[str, Any], right: Mapping[str, Any], phase: str) -> dict[str, float | None]:
    return {label: min(values) if (values := [times[phase] for times in item["phases"].values() if times[phase] is not None]) else None for label, item in (("sequential", left), ("adaptive", right))}


def _pair(left: Mapping[str, Any], right: Mapping[str, Any], name: str) -> dict[str, Any]: return {"sequential": left[name], "adaptive": right[name]}
def _count(values: Mapping[str, str], target: str) -> int: return sum(value == target for value in values.values())
def _path(value: object) -> bool: return isinstance(value, str) and bool(value)
def _paths(value: object) -> bool: return isinstance(value, (list, tuple)) and bool(value) and all(_path(item) for item in value)
def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be non-negative integer")
    return value
def _positive(value: object, name: str) -> float:
    number = _number(value, name)
    if number <= 0:
        raise ValueError(f"{name} must be positive")
    return number
def _number(value: object, name: str) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0):
        raise ValueError(f"{name} must be finite non-negative")
    return float(value)
