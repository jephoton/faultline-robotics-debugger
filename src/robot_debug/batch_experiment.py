"""Phase runner and summary for the M3 batched-inference experiment (ADR 0025).

A *phase* is one ``(workers, max_batch_size)`` pair run over the whole frozen
equal-work manifest against a freshly started model server. This module owns the
phase loop, the work-stealing worker threads, the server timing statistics and the
per-worker-count verdicts; process, deadline and evidence mechanics are injected by
``job_workload.run_workload`` so they stay the single, already-tested path.
"""

from __future__ import annotations

from collections import deque
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Any, Callable, Deque, Dict, List, Mapping, Optional, Sequence, Tuple

from robot_debug.job_process import CleanupUnconfirmed, InfrastructureError, RunCancelled
from robot_debug.parallel_eval import build_manifest, manifest_hash

SPEEDUP_BAR = 1.15
KNOWN_OUTCOMES = {"nominal": "success", "mask": "policy_failure"}
VALID_OUTCOMES = frozenset(KNOWN_OUTCOMES.values())
# M3 used 300 s per item; an item is never started with less than this left, so a
# timeout is always the evaluator's own and never the Job deadline's.
ITEM_TIMEOUT_SECONDS = 300.0
FIRST_PHASE_MINIMUM_SECONDS = 240.0
PARITY_CAP_SECONDS = 420.0
SUMMARY_NAME = "batch_summary.json"

VERDICTS = ("works", "no_measurable_gain", "outcome_drift", "incomplete")


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


def memory_snapshot(
    meminfo: str = "/proc/meminfo", run: Callable[..., Any] = subprocess.run
) -> Dict[str, Optional[float]]:
    """Free host memory and GPU memory in MiB; every missing source reads as ``None``."""

    snapshot: Dict[str, Optional[float]] = {
        "mem_available_mb": None, "gpu_used_mb": None, "gpu_total_mb": None,
    }
    try:
        for line in Path(meminfo).read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                snapshot["mem_available_mb"] = round(int(line.split()[1]) / 1024.0, 1)
                break
    except (OSError, ValueError, IndexError):
        pass
    try:
        done = run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if done.returncode == 0:
            used, total = [float(part) for part in done.stdout.strip().splitlines()[0].split(",")]
            snapshot["gpu_used_mb"], snapshot["gpu_total_mb"] = used, total
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        pass
    return snapshot


_SQLITE_COMPANIONS = (".sqlite-wal", ".sqlite-shm")


def purge_sqlite_companions(root: Path) -> int:
    """Delete stray SQLite ``-wal``/``-shm`` files under ``root``; returns how many.

    A killed evaluator can leave them behind, and the evidence exporter refuses
    them, which would lose every phase's evidence.
    """

    removed = 0
    root = Path(root)
    if not root.is_dir():
        return 0
    for path in sorted(root.rglob("*")):
        if path.name.lower().endswith(_SQLITE_COMPANIONS) and (path.is_file() or path.is_symlink()):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def remove_tree_within(path: Path, root: Path) -> bool:
    """Remove ``path`` if it is a real directory inside ``root``; True when it is gone."""

    path, root = Path(path), Path(root)
    if not path.exists() and not path.is_symlink():
        return True
    try:
        if path.is_symlink() or not path.is_dir():
            return False
        path.resolve().relative_to(root.resolve())
        shutil.rmtree(str(path))
    except (OSError, ValueError):
        return False
    return not path.exists()


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
            started = float(item["t"])
            inference = float(item["inference_ms"])
            waits = [float(value) for value in item["wait_ms"]]
            if (
                not math.isfinite(started)
                or type(batch) is not int or batch < 1 or len(waits) != batch
                or not math.isfinite(inference) or inference < 0
                or any(not math.isfinite(value) or value < 0 for value in waits)
            ):
                raise ValueError("implausible timing record")
        except (ValueError, KeyError, TypeError):
            malformed += 1
            continue
        records.append({"t": started, "batch_size": batch, "inference_ms": inference, "wait_ms": waits})
    return records, malformed


def timing_stats(
    path: Path, warm_elapsed_seconds: Optional[float], min_t: Optional[float] = None
) -> Optional[Dict[str, Any]]:
    """Server-side statistics for one phase, or ``None`` when no timing was logged.

    ``min_t`` drops calls that started before it (the untimed warm-up episode). Server
    ``t`` and the Job clock are the same host's monotonic clock.
    """

    records, malformed = read_timing_records(path)
    before_launch = 0
    if min_t is not None:
        before_launch = sum(1 for record in records if record["t"] < min_t)
        records = [record for record in records if record["t"] >= min_t]
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
        "model_call_busy_share": _round(share, 4),
        "malformed_lines": malformed,
        "calls_before_timed_launch_excluded": before_launch,
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
    """One verdict per worker count that has an unbatched and a batched phase.

    Verdicts: ``outcome_drift`` (a valid outcome in either phase differs from the known
    result, which takes precedence because throughput cannot then be claimed),
    ``incomplete`` (a phase missing, unfinished or with unequal work), otherwise
    ``works`` when batched throughput is at least the bar above unbatched, else
    ``no_measurable_gain``. There is deliberately no single overall verdict.
    """

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
            "drift_ids": sorted(set(unbatched.get("drift_ids") or []) | set(batched.get("drift_ids") or [])),
        }
        comparable = not (
            unbatched.get("status") != "complete" or batched.get("status") != "complete"
            or unbatched.get("valid_count") != batched.get("valid_count")
            or not unbatched.get("episodes_per_minute") or not batched.get("episodes_per_minute")
        )
        if comparable:
            entry["speedup"] = round(batched["episodes_per_minute"] / unbatched["episodes_per_minute"], 4)
        else:
            entry["status"] = "incomplete"
        if entry["drift_ids"]:
            entry["verdict"] = "outcome_drift"
        elif not comparable:
            entry["verdict"] = "incomplete"
        else:
            entry["verdict"] = "works" if entry["speedup"] >= SPEEDUP_BAR else "no_measurable_gain"
        comparisons.append(entry)
    return comparisons


def parity_gate(parity: Optional[Mapping[str, Any]]) -> str:
    """The smoke gate: ``passed``, ``failed`` or ``not_run`` (measurement Jobs)."""

    if parity is None:
        return "not_run"
    return "passed" if parity.get("passed") else "failed"


def build_summary(
    *,
    mode: str,
    repeats_per_kind: int,
    planned: Sequence[Sequence[int]],
    phases: Sequence[Mapping[str, Any]],
    parity: Optional[Mapping[str, Any]],
    stop_reason: Optional[str],
    extra: Optional[Mapping[str, Any]] = None,
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
        "parity_gate": parity_gate(parity),
        "passing_worker_counts": [c["workers"] for c in comparisons if c["verdict"] == "works"],
    }
    if extra:
        summary.update(extra)
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
    prefetch: Optional[Callable[[], Any]] = None,
    snapshot: Callable[[], Mapping[str, Any]] = memory_snapshot,
    server_clock: Callable[[], float] = time.monotonic,
) -> Dict[str, Any]:
    """Run the planned phases in order and return the summary.

    The first phase that runs starts with ONE untimed warm-up episode (the first
    nominal item under its own run id, one worker): it is recorded separately and
    excluded from every phase metric, including the server timing statistics
    (``server_clock`` must read the same monotonic clock as the server's ``t``).

    ``prefetch()`` downloads the pinned inputs once, before parity and before the
    first phase, and is timed separately so it never counts toward a phase.
    ``run_item(command, item_timeout=..., cancel=...)`` is the bounded evaluator
    runner from ``run_workload``: it checks the deadline and the model, validates
    the generated evidence and raises ``InfrastructureError`` on any problem
    (``RunCancelled`` when this module cancelled the evaluator). ``failure()``
    returns the latched failure code, if any. A server cleanup that cannot be
    confirmed propagates to the caller untouched.
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
    scrub = {"companions_removed": 0}
    extra: Dict[str, Any] = {"prefetch_seconds": None, "cleanup_unconfirmed": False, "warmup": None}
    warmup_slot: Dict[str, Any] = {}

    def save() -> Dict[str, Any]:
        extra["sqlite_companions_removed"] = scrub["companions_removed"]
        extra["warmup"] = dict(warmup_slot) if warmup_slot else None
        summary = build_summary(
            mode=mode, repeats_per_kind=repeats_per_kind, planned=planned,
            phases=records, parity=parity, stop_reason=stop_reason, extra=extra,
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

    blocked = False
    try:
        if prefetch is not None:
            started = clock()
            progress("batch_prefetch_start")
            try:
                prefetch()
            except Exception as error:
                stop_reason, blocked = "prefetch_failed", True
                progress("batch_prefetch_failed", error=type(error).__name__)
            extra["prefetch_seconds"] = _round(clock() - started)
            if not blocked:
                progress("batch_prefetch_done", seconds=extra["prefetch_seconds"])
        if mode == "m3-batch-smoke" and not blocked:
            parity = _run_parity(
                parity_runner, batch_root, log_root, planned[0][1], remaining, progress, extra
            )
            if not parity.get("passed"):
                stop_reason = "parity_failed" if parity.get("error") is None else "parity_error"
                if extra["cleanup_unconfirmed"]:
                    stop_reason = "cleanup_unconfirmed"
                blocked = True
        if blocked:
            for index in range(len(planned)):
                not_run(index, "not_run")

        deadline_skipped = False
        warmup_reported = False
        for index, (workers, size) in enumerate(planned):
            if blocked:
                break
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
            progress("batch_phase_start", phase=index + 1, workers=workers, max_batch_size=size,
                     **dict(snapshot()))
            try:
                record = _run_phase(
                    index=index, workers=workers, size=size, manifest=manifest, digest=digest,
                    batch_root=batch_root, log_root=log_root, project_root=project_root,
                    model_factory=model_factory, set_model=set_model, run_item=run_item,
                    launch_deadline=launch_deadline, clock=clock, write_config=write_config,
                    load_result=load_result, item_timeout=item_timeout, remaining=remaining,
                    snapshot=snapshot, scrub=scrub,
                    warmup=warmup_slot if not warmup_slot else None, server_clock=server_clock,
                )
            except PhaseFailure as error:
                not_run(index, "start_failed")
                records[-1]["stop_reason"] = error.reason
                stop_reason = error.reason
                save()
                continue
            records.append(record)
            if warmup_slot and not warmup_reported:
                warmup_reported = True
                progress("batch_warmup_done", case_id=warmup_slot.get("case_id"),
                         status=warmup_slot.get("status"), outcome=warmup_slot.get("outcome"),
                         duration_seconds=warmup_slot.get("duration_seconds"))
            progress(
                "batch_phase_done", phase=index + 1, workers=workers, max_batch_size=size,
                status=record["status"], valid=record["valid_count"],
                episodes_per_minute=record.get("episodes_per_minute"),
                warm_elapsed_seconds=record.get("warm_elapsed_seconds"),
                **dict(record.get("memory_end") or {}),
            )
            if record["status"] != "complete":
                stop_reason = failure() or (
                    "deadline_exhausted" if record.get("deadline_stopped") else "phase_incomplete"
                )
            save()
        if stop_reason is None and deadline_skipped:
            stop_reason = "deadline_exhausted"
    finally:
        # Last line of defence: the exporter rejects SQLite companions anywhere.
        scrub["companions_removed"] += purge_sqlite_companions(batch_root)
        summary = save()
    progress(
        "batch_summary", passing_worker_counts=summary["passing_worker_counts"],
        parity_gate=summary["parity_gate"], comparisons=summary["comparisons"],
        all_phases_complete=summary["all_phases_complete"],
        sqlite_companions_removed=summary["sqlite_companions_removed"],
    )
    return summary


def _parity_error_result(error: BaseException) -> Dict[str, Any]:
    if isinstance(error, CleanupUnconfirmed):
        code = "cleanup_unconfirmed"
    elif isinstance(error, InfrastructureError):
        code = "infrastructure_error"
    else:
        code = "exception"
    return {
        "schema_version": 1, "passed": False, "error_code": code,
        "error": "{}: {}".format(type(error).__name__, str(error)[:200]),
    }


def _run_parity(
    runner: Optional[Callable[..., Mapping[str, Any]]],
    batch_root: Path,
    log_root: Path,
    max_batch_size: int,
    remaining: Callable[[], float],
    progress: Callable[..., None],
    extra: Dict[str, Any],
) -> Dict[str, Any]:
    """Run the parity check; a verdict file and a result dict exist whatever happens."""

    output = batch_root / "parity.json"
    wrote_here = False
    if runner is None:
        result: Dict[str, Any] = {"schema_version": 1, "passed": False, "error_code": "unavailable",
                                  "error": "parity runner unavailable"}
        wrote_here = True
    else:
        # The budget is taken after prefetch, so a slow download cannot starve it.
        budget = min(PARITY_CAP_SECONDS, remaining())
        if budget <= 0:
            result = {"schema_version": 1, "passed": False, "error_code": "no_time",
                      "error": "no time remains for the parity check"}
            wrote_here = True
        else:
            progress("batch_parity_start", timeout_seconds=round(budget, 1))
            try:
                result = dict(runner(
                    output=output, log_root=log_root, max_batch_size=max_batch_size,
                    timeout_seconds=budget,
                ))
            except Exception as error:
                result = _parity_error_result(error)
                wrote_here = True
                if isinstance(error, CleanupUnconfirmed):
                    extra["cleanup_unconfirmed"] = True
    result["passed"] = result.get("passed") is True
    if wrote_here or not output.exists():
        output.write_bytes((json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8"))
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
    remaining: Callable[[], float],
    snapshot: Callable[[], Mapping[str, Any]],
    scrub: Dict[str, int],
    warmup: Optional[Dict[str, Any]] = None,
    server_clock: Callable[[], float] = time.monotonic,
) -> Dict[str, Any]:
    label = phase_label(index, workers, size)
    phase_dir = batch_root / label
    configs = phase_dir / "configs"
    runs = phase_dir / "runs"
    configs.mkdir(parents=True)
    runs.mkdir()
    timing_path = phase_dir / "server-timing.jsonl"
    phase_started = clock()
    memory_start = dict(snapshot())
    cancel = threading.Event()
    stop = threading.Event()
    deadline_stop = threading.Event()
    lock = threading.Lock()
    pending: Deque[Mapping[str, Any]] = deque(manifest)
    results: List[Dict[str, Any]] = []
    model: Any = None
    server_argv: Optional[List[str]] = None
    warmup_seconds = 0.0
    launch_t: Optional[float] = None

    try:
        try:
            try:
                model = model_factory(log_root=log_root, server="faultline", max_batch_size=size,
                                      timing_log=timing_path)
            except Exception as error:
                raise PhaseFailure("model_start_failed") from error
            set_model(model)
            argv = getattr(model, "argv", None)
            if argv is not None:
                server_argv = list(argv)[1:]
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

            def evaluate(
                item: Mapping[str, Any], *, case_id: Optional[str] = None,
                configs_dir: Path = configs, runs_dir: Path = runs,
            ) -> Dict[str, Any]:
                case_id = str(item["case_id"]) if case_id is None else case_id
                record: Dict[str, Any] = {
                    "case_id": case_id, "kind": item["kind"], "status": "infrastructure_error",
                    "outcome": None, "started_seconds": round(clock() - ready_at, 3),
                }
                try:
                    config_path = configs_dir / (case_id + ".yaml")
                    output = runs_dir / case_id
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
                except InfrastructureError as error:
                    timed_out = isinstance(error.__cause__, subprocess.TimeoutExpired)
                    record["status"] = "timed_out" if timed_out else "infrastructure_error"
                except Exception:
                    record["status"] = "infrastructure_error"
                record["ended_seconds"] = round(clock() - ready_at, 3)
                return record

            def worker() -> None:
                while not stop.is_set() and not cancel.is_set():
                    # Never start an item that the Job deadline could cut short.
                    if remaining() < item_timeout:
                        deadline_stop.set()
                        stop.set()
                        return
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

            if warmup is not None:
                # One untimed episode on this first server: engine start-up, CUDA
                # kernels and caches are warm before anything is measured.
                first = manifest[0]
                warm_base = batch_root / "warmup"
                warm_base.mkdir(parents=True, exist_ok=True)
                (warm_base / "configs").mkdir(exist_ok=True)
                (warm_base / "runs").mkdir(exist_ok=True)
                warm_started = clock()
                if remaining() < item_timeout:
                    outcome_record: Dict[str, Any] = {
                        "case_id": "warmup-" + str(first["case_id"]), "kind": first["kind"],
                        "status": "skipped_deadline", "outcome": None,
                    }
                    deadline_stop.set()
                else:
                    try:
                        outcome_record = evaluate(
                            first, case_id="warmup-" + str(first["case_id"]),
                            configs_dir=warm_base / "configs", runs_dir=warm_base / "runs",
                        )
                    except BaseException:
                        # Interrupted mid-evaluator: its group was terminated, so its
                        # directory may be half-written; drop it before re-raising.
                        remove_tree_within(warm_base / "runs" / ("warmup-" + str(first["case_id"])), batch_root)
                        raise
                warmup_seconds = clock() - warm_started
                outcome_record.pop("started_seconds", None)
                outcome_record.pop("ended_seconds", None)
                outcome_record["duration_seconds"] = _round(warmup_seconds)
                outcome_record["matches_known_outcome"] = (
                    None if outcome_record["outcome"] is None
                    else outcome_record["outcome"] == KNOWN_OUTCOMES.get(str(first["kind"]))
                )
                if outcome_record["status"] in ("cancelled", "timed_out"):
                    outcome_record["run_dir_removed"] = remove_tree_within(
                        warm_base / "runs" / outcome_record["case_id"], batch_root
                    )
                warmup.update(outcome_record)
                if outcome_record["status"] != "valid":
                    stop.set()
                    cancel.set()
            launch_t = server_clock()
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
    finally:
        # Killed evaluators can leave SQLite companions (and half-written media)
        # behind; remove their run directories and any stray companions before
        # anything is exported, including on interruption.
        for entry in results:
            if entry["status"] in ("cancelled", "timed_out"):
                entry["run_dir_removed"] = remove_tree_within(runs / entry["case_id"], phase_dir)
        scrub["companions_removed"] += purge_sqlite_companions(phase_dir)

    memory_end = dict(snapshot())
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
        "total_seconds": _round(clock() - phase_started - warmup_seconds),
        "episodes_per_minute": _round(len(valid) / warm * 60.0, 4) if complete and warm else None,
        "timing": timing_stats(timing_path, warm, min_t=launch_t),
        "server_argv": server_argv,
        "memory_start": memory_start,
        "memory_end": memory_end,
        "deadline_stopped": deadline_stop.is_set(),
        "items": sorted(results, key=lambda r: r["case_id"]),
    }
    return record
