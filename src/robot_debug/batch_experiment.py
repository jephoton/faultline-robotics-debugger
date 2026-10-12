"""Phase runner and summary for the M3 batched-inference experiment (ADR 0025).

A *phase* is one ``(workers, max_batch_size)`` pair run over the whole frozen
equal-work manifest against a freshly started model server. This module owns the
phase loop, the work-stealing worker threads, the server timing statistics and the
verdict; process, deadline and evidence mechanics are injected by
``job_workload.run_workload`` so they stay the single, already-tested path.
"""

from __future__ import annotations

from collections import deque
import json
import math
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Deque, Dict, List, Mapping, Optional, Sequence, Tuple

from robot_debug.job_process import InfrastructureError, RunCancelled
from robot_debug.parallel_eval import build_manifest, manifest_hash

SPEEDUP_BAR = 1.15
KNOWN_OUTCOMES = {"nominal": "success", "mask": "policy_failure"}
VALID_OUTCOMES = frozenset(KNOWN_OUTCOMES.values())
ITEM_TIMEOUT_SECONDS = 480.0
FIRST_PHASE_MINIMUM_SECONDS = 240.0
PARITY_CAP_SECONDS = 420.0
SUMMARY_NAME = "batch_summary.json"

VERDICTS = ("works", "no_measurable_gain", "outcome_drift", "parity_failed", "incomplete")


# ---------------------------------------------------------------------------
# Pure statistics
# ---------------------------------------------------------------------------


def percentile(values: Sequence[float], q: float) -> Optional[float]:
    """Linear-interpolation percentile (q in 0..100); ``None`` for no data."""

    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * (q / 100.0)
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _round(value: Optional[float], digits: int = 3) -> Optional[float]:
    return None if value is None else round(float(value), digits)


def read_timing_records(path: Path) -> Tuple[List[Dict[str, Any]], int]:
    """Parse the server's JSONL timing log; returns (records, malformed line count)."""

    records: List[Dict[str, Any]] = []
    malformed = 0
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return records, 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            batch = item["batch_size"]
            inference = float(item["inference_ms"])
            waits = [float(value) for value in item["wait_ms"]]
            if (
                type(batch) is not int or batch < 1 or len(waits) != batch
                or not math.isfinite(inference) or inference < 0
                or any(not math.isfinite(value) or value < 0 for value in waits)
            ):
                raise ValueError("implausible timing record")
        except (ValueError, KeyError, TypeError):
            malformed += 1
            continue
        records.append({"batch_size": batch, "inference_ms": inference, "wait_ms": waits})
    return records, malformed


def timing_stats(path: Path, warm_elapsed_seconds: Optional[float]) -> Optional[Dict[str, Any]]:
    """Server-side statistics for one phase, or ``None`` when no timing was logged."""

    records, malformed = read_timing_records(path)
    if not records:
        return None
    batch_sizes = [record["batch_size"] for record in records]
    inference = [record["inference_ms"] for record in records]
    waits = [value for record in records for value in record["wait_ms"]]
    busy_seconds = sum(inference) / 1000.0
    share = None
    if warm_elapsed_seconds is not None and warm_elapsed_seconds > 0:
        share = busy_seconds / warm_elapsed_seconds
    return {
        "calls": len(records),
        "items_served": sum(batch_sizes),
        "mean_batch_size": _round(sum(batch_sizes) / len(batch_sizes)),
        "p95_batch_size": _round(percentile(batch_sizes, 95)),
        "max_batch_size_observed": max(batch_sizes),
        "inference_ms_p50": _round(percentile(inference, 50)),
        "inference_ms_p95": _round(percentile(inference, 95)),
        "wait_ms_p50": _round(percentile(waits, 50)),
        "wait_ms_p95": _round(percentile(waits, 95)),
        "busy_seconds": _round(busy_seconds),
        "gpu_busy_share": _round(share, 4),
        "malformed_lines": malformed,
    }


def drift_ids(results: Sequence[Mapping[str, Any]]) -> List[str]:
    """Case IDs whose valid outcome differs from the known result for their kind."""

    drifted = []
    for result in results:
        outcome = result.get("outcome")
        if result.get("status") == "valid" and outcome != KNOWN_OUTCOMES.get(str(result.get("kind"))):
            drifted.append(str(result["case_id"]))
    return sorted(drifted)


def outcomes_by_kind(results: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, int]]:
    counts: Dict[str, Dict[str, int]] = {}
    for result in results:
        if result.get("status") != "valid":
            continue
        kind = counts.setdefault(str(result["kind"]), {})
        kind[str(result["outcome"])] = kind.get(str(result["outcome"]), 0) + 1
    return counts


def phase_label(index: int, workers: int, max_batch_size: int) -> str:
    return "phase-{:02d}-w{:02d}-b{:02d}".format(index + 1, workers, max_batch_size)


def estimate_phase_seconds(completed: Sequence[Mapping[str, Any]], workers: int) -> Optional[float]:
    """Conservative duration estimate from finished phases, or ``None`` without any.

    Throughput never scales better than linearly with workers, so a phase with
    fewer workers than a finished one is bounded by that phase's duration times
    the worker ratio. Phases with at least as many workers are bounded by their
    own duration (including server startup).
    """

    estimate: Optional[float] = None
    for phase in completed:
        total = phase.get("total_seconds")
        done_workers = phase.get("workers")
        if not isinstance(total, (int, float)) or not isinstance(done_workers, int):
            continue
        scaled = float(total) * max(1.0, done_workers / float(workers))
        estimate = scaled if estimate is None else max(estimate, scaled)
    return estimate


# ---------------------------------------------------------------------------
# Summary and verdict
# ---------------------------------------------------------------------------


def compare_phases(phases: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """One comparison per worker count that has an unbatched and a batched phase."""

    by_key = {(p["workers"], p["max_batch_size"]): p for p in phases}
    comparisons = []
    for workers in sorted({p["workers"] for p in phases}):
        unbatched = by_key.get((workers, 1))
        batched = by_key.get((workers, workers))
        if unbatched is None or batched is None:
            continue
        entry: Dict[str, Any] = {
            "workers": workers,
            "unbatched_episodes_per_minute": unbatched.get("episodes_per_minute"),
            "batched_episodes_per_minute": batched.get("episodes_per_minute"),
            "speedup": None,
            "status": "compared",
            "verdict": None,
        }
        if (
            unbatched.get("status") != "complete" or batched.get("status") != "complete"
            or unbatched.get("valid_count") != batched.get("valid_count")
            or not unbatched.get("episodes_per_minute") or not batched.get("episodes_per_minute")
        ):
            entry["status"] = "incomplete"
        else:
            entry["speedup"] = round(batched["episodes_per_minute"] / unbatched["episodes_per_minute"], 4)
            entry["verdict"] = "works" if entry["speedup"] >= SPEEDUP_BAR else "no_measurable_gain"
        comparisons.append(entry)
    return comparisons


def overall_verdict(
    phases: Sequence[Mapping[str, Any]],
    comparisons: Sequence[Mapping[str, Any]],
    parity: Optional[Mapping[str, Any]],
) -> str:
    """ADR 0025 verdict; precedence parity, drift, then the 15% bar."""

    if parity is not None and not parity.get("passed"):
        return "parity_failed"
    if any(phase.get("drift_ids") for phase in phases):
        return "outcome_drift"
    compared = [c for c in comparisons if c["status"] == "compared"]
    if not compared:
        return "incomplete"
    if any(c["verdict"] == "works" for c in compared):
        return "works"
    return "no_measurable_gain"


def build_summary(
    *,
    mode: str,
    repeats_per_kind: int,
    planned: Sequence[Sequence[int]],
    phases: Sequence[Mapping[str, Any]],
    parity: Optional[Mapping[str, Any]],
    stop_reason: Optional[str],
) -> Dict[str, Any]:
    comparisons = compare_phases(phases)
    summary: Dict[str, Any] = {
        "schema_version": 1,
        "mode": mode,
        "manifest_hash": manifest_hash(build_manifest(repeats_per_kind)),
        "items_per_phase": 2 * repeats_per_kind,
        "repeats_per_kind": repeats_per_kind,
        "speedup_bar": SPEEDUP_BAR,
        "known_outcomes": dict(KNOWN_OUTCOMES),
        "planned_phases": [list(pair) for pair in planned],
        "parity": None if parity is None else dict(parity),
        "parity_note": None if parity is not None else "parity is checked by the smoke Job, not this one",
        "phases": [dict(phase) for phase in phases],
        "comparisons": comparisons,
        "all_phases_complete": len(phases) == len(planned) and all(p.get("status") == "complete" for p in phases),
        "stop_reason": stop_reason,
        "verdict": overall_verdict(phases, comparisons, parity),
    }
    if mode == "m3-batch-smoke":
        batched = [p for p in phases if p["max_batch_size"] > 1]
        observed = max(
            [(p.get("timing") or {}).get("max_batch_size_observed", 0) for p in batched] or [0]
        )
        summary["smoke"] = {
            "parity_passed": bool(parity and parity.get("passed")),
            "batched_phase_complete": bool(batched) and all(p.get("status") == "complete" for p in batched),
            "no_outcome_drift": not any(p.get("drift_ids") for p in phases),
            "max_batch_size_observed": observed,
            "batching_engaged": observed > 1,
        }
        smoke = summary["smoke"]
        smoke["passed"] = bool(
            smoke["parity_passed"] and smoke["batched_phase_complete"] and smoke["no_outcome_drift"]
        )
    return summary


def write_summary(batch_root: Path, summary: Mapping[str, Any]) -> None:
    target = Path(batch_root) / SUMMARY_NAME
    temporary = Path(batch_root) / ("." + SUMMARY_NAME + ".tmp")
    payload = json.dumps(summary, sort_keys=True, indent=2, allow_nan=False) + "\n"
    temporary.write_bytes(payload.encode("utf-8"))
    os.replace(str(temporary), str(target))


# ---------------------------------------------------------------------------
# Phase execution
# ---------------------------------------------------------------------------


class PhaseFailure(Exception):
    """A phase could not start its server; carries the safe reason code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def run_phases(
    *,
    mode: str,
    phases: Sequence[Sequence[int]],
    repeats_per_kind: int,
    batch_root: Path,
    log_root: Path,
    project_root: Path,
    model_factory: Callable[..., Any],
    set_model: Callable[[Any], None],
    run_item: Callable[..., Any],
    failure: Callable[[], Optional[str]],
    remaining: Callable[[], float],
    launch_deadline: float,
    clock: Callable[[], float] = time.monotonic,
    progress: Callable[..., None] = lambda _event, **_fields: None,
    parity_runner: Optional[Callable[..., Mapping[str, Any]]] = None,
    write_config: Optional[Callable[..., None]] = None,
    load_result: Optional[Callable[[Path], Any]] = None,
    item_timeout: float = ITEM_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Run the planned phases in order and return the summary.

    ``run_item(command, item_timeout=..., cancel=...)`` is the bounded evaluator
    runner from ``run_workload``: it checks the deadline and the model, validates
    the generated evidence and raises ``InfrastructureError`` on any problem
    (``RunCancelled`` when this module cancelled the evaluator). ``failure()``
    returns the latched failure code, if any. Exceptions that mean cleanup could
    not be confirmed propagate to the caller untouched.
    """

    if write_config is None or load_result is None:
        from scripts import run_failure_search

        write_config = write_config or run_failure_search._write_config
        load_result = load_result or (
            lambda output: run_failure_search._load_stage_results(output, expected_count=1)[0]
        )
    batch_root = Path(batch_root)
    batch_root.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(repeats_per_kind)
    digest = manifest_hash(manifest)
    planned = [list(pair) for pair in phases]
    records: List[Dict[str, Any]] = []
    parity: Optional[Dict[str, Any]] = None
    stop_reason: Optional[str] = None

    def save() -> Dict[str, Any]:
        summary = build_summary(
            mode=mode, repeats_per_kind=repeats_per_kind, planned=planned,
            phases=records, parity=parity, stop_reason=stop_reason,
        )
        write_summary(batch_root, summary)
        return summary

    def not_run(index: int, status: str) -> None:
        workers, size = planned[index]
        records.append({
            "index": index, "label": phase_label(index, workers, size), "workers": workers,
            "max_batch_size": size, "status": status, "manifest_hash": digest,
            "planned": len(manifest), "valid_count": 0, "drift_ids": [],
        })

    if mode == "m3-batch-smoke":
        parity = _run_parity(parity_runner, batch_root, log_root, planned[0][1], remaining, progress)
        if not parity.get("passed"):
            stop_reason = "parity_failed" if parity.get("error") is None else "parity_error"
            for index in range(len(planned)):
                not_run(index, "not_run")
            return save()

    deadline_skipped = False
    for index, (workers, size) in enumerate(planned):
        if stop_reason is not None or failure() is not None:
            not_run(index, "not_run")
            continue
        estimate = estimate_phase_seconds(records, workers)
        available = remaining()
        needed = FIRST_PHASE_MINIMUM_SECONDS if estimate is None else estimate
        if available < needed:
            not_run(index, "deadline_skipped")
            deadline_skipped = True
            progress("batch_phase_skipped", phase=index + 1, workers=workers, max_batch_size=size,
                     remaining_seconds=round(available, 1), needed_seconds=round(needed, 1))
            continue
        progress("batch_phase_start", phase=index + 1, workers=workers, max_batch_size=size)
        try:
            record = _run_phase(
                index=index, workers=workers, size=size, manifest=manifest, digest=digest,
                batch_root=batch_root, log_root=log_root, project_root=project_root,
                model_factory=model_factory, set_model=set_model, run_item=run_item,
                launch_deadline=launch_deadline, clock=clock, write_config=write_config,
                load_result=load_result, item_timeout=item_timeout,
            )
        except PhaseFailure as error:
            not_run(index, "start_failed")
            records[-1]["stop_reason"] = error.reason
            stop_reason = error.reason
            save()
            continue
        records.append(record)
        progress(
            "batch_phase_done", phase=index + 1, workers=workers, max_batch_size=size,
            status=record["status"], valid=record["valid_count"],
            episodes_per_minute=record.get("episodes_per_minute"),
            warm_elapsed_seconds=record.get("warm_elapsed_seconds"),
        )
        if record["status"] != "complete":
            stop_reason = failure() or "phase_incomplete"
        save()
    if stop_reason is None and deadline_skipped:
        stop_reason = "deadline_exhausted"
    summary = save()
    progress(
        "batch_summary", verdict=summary["verdict"], comparisons=summary["comparisons"],
        all_phases_complete=summary["all_phases_complete"],
    )
    return summary


def _run_parity(
    runner: Optional[Callable[..., Mapping[str, Any]]],
    batch_root: Path,
    log_root: Path,
    max_batch_size: int,
    remaining: Callable[[], float],
    progress: Callable[..., None],
) -> Dict[str, Any]:
    if runner is None:
        return {"passed": False, "error": "parity runner unavailable"}
    budget = min(PARITY_CAP_SECONDS, remaining())
    if budget <= 0:
        return {"passed": False, "error": "no time remains for the parity check"}
    progress("batch_parity_start", timeout_seconds=round(budget, 1))
    try:
        result = dict(runner(
            output=batch_root / "parity.json", log_root=log_root,
            max_batch_size=max_batch_size, timeout_seconds=budget,
        ))
    except InfrastructureError as error:
        result = {"passed": False, "error": "{}: {}".format(type(error).__name__, str(error)[:200])}
    result["passed"] = result.get("passed") is True
    progress("batch_parity_done", passed=result["passed"], max_abs_diff=result.get("max_abs_diff"),
             error=result.get("error"))
    return result


def _run_phase(
    *,
    index: int,
    workers: int,
    size: int,
    manifest: Sequence[Mapping[str, Any]],
    digest: str,
    batch_root: Path,
    log_root: Path,
    project_root: Path,
    model_factory: Callable[..., Any],
    set_model: Callable[[Any], None],
    run_item: Callable[..., Any],
    launch_deadline: float,
    clock: Callable[[], float],
    write_config: Callable[..., None],
    load_result: Callable[[Path], Any],
    item_timeout: float,
) -> Dict[str, Any]:
    label = phase_label(index, workers, size)
    phase_dir = batch_root / label
    configs = phase_dir / "configs"
    runs = phase_dir / "runs"
    configs.mkdir(parents=True)
    runs.mkdir()
    timing_path = phase_dir / "server-timing.jsonl"
    phase_started = clock()
    cancel = threading.Event()
    stop = threading.Event()
    lock = threading.Lock()
    pending: Deque[Mapping[str, Any]] = deque(manifest)
    results: List[Dict[str, Any]] = []
    model: Any = None

    try:
        try:
            model = model_factory(log_root=log_root, server="faultline", max_batch_size=size,
                                  timing_log=timing_path)
        except Exception as error:
            raise PhaseFailure("model_start_failed") from error
        set_model(model)
        try:
            model.start()
        except Exception as error:
            raise PhaseFailure("model_start_failed") from error
        try:
            model.wait_ready(deadline=launch_deadline)
        except Exception as error:
            raise PhaseFailure("readiness_failed") from error
        try:
            model.check_alive()
        except Exception as error:
            raise PhaseFailure("model_died") from error
        ready_at = clock()

        def evaluate(item: Mapping[str, Any]) -> Dict[str, Any]:
            case_id = str(item["case_id"])
            record: Dict[str, Any] = {
                "case_id": case_id, "kind": item["kind"], "status": "infrastructure_error",
                "outcome": None, "started_seconds": round(clock() - ready_at, 3),
            }
            try:
                config_path = configs / (case_id + ".yaml")
                output = runs / case_id
                rectangle = item["rectangle"] or {}
                write_config(
                    config_path=config_path, output_dir=output, project_root=project_root,
                    stage_name="m3-" + case_id, episode_indices=(0,), **rectangle
                )
                run_item(
                    ["vla-eval", "run", "--config", str(config_path)],
                    item_timeout=item_timeout, cancel=cancel,
                )
                result = load_result(output)
                outcome = getattr(result, "outcome", None)
                if outcome in VALID_OUTCOMES and getattr(result, "episode_index", 0) == 0:
                    record.update(status="valid", outcome=outcome,
                                  steps=getattr(result, "steps", None))
                else:
                    record["status"] = "invalid_evidence"
            except RunCancelled:
                record["status"] = "cancelled"
            except InfrastructureError:
                record["status"] = "infrastructure_error"
            except Exception:
                record["status"] = "infrastructure_error"
            record["ended_seconds"] = round(clock() - ready_at, 3)
            return record

        def worker() -> None:
            while not stop.is_set() and not cancel.is_set():
                with lock:
                    item = pending.popleft() if pending else None
                if item is None:
                    return
                record = evaluate(item)
                with lock:
                    results.append(record)
                if record["status"] != "valid":
                    stop.set()
                    cancel.set()

        threads = [threading.Thread(target=worker, name="m3-batch-worker-{}".format(i), daemon=True)
                   for i in range(workers)]
        try:
            for thread in threads:
                thread.start()
            for thread in threads:
                while thread.is_alive():
                    thread.join(0.5)
        except BaseException:
            cancel.set()
            stop.set()
            for thread in threads:
                if thread.is_alive():
                    thread.join(30)
            raise
    finally:
        if model is not None:
            # If this raises, the model stays registered so the workload's own
            # cleanup retries it and records the failure.
            model.close()
            set_model(None)

    finished = [r for r in results if r.get("ended_seconds") is not None]
    valid = [r for r in results if r["status"] == "valid"]
    warm = None
    if finished:
        warm = max(r["ended_seconds"] for r in finished) - min(r["started_seconds"] for r in finished)
        warm = max(warm, 1e-6)
    complete = len(valid) == len(manifest) and not pending
    record = {
        "index": index, "label": label, "workers": workers, "max_batch_size": size,
        "status": "complete" if complete else "incomplete",
        "manifest_hash": digest, "planned": len(manifest), "attempted": len(results),
        "valid_count": len(valid),
        "outcomes_by_kind": outcomes_by_kind(results),
        "drift_ids": drift_ids(results),
        "warm_elapsed_seconds": _round(warm),
        "startup_seconds": _round(ready_at - phase_started),
        "total_seconds": _round(clock() - phase_started),
        "episodes_per_minute": _round(len(valid) / warm * 60.0, 4) if complete and warm else None,
        "timing": timing_stats(timing_path, warm),
        "items": sorted(results, key=lambda r: r["case_id"]),
    }
    return record
