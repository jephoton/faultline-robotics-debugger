"""Durable local core for a bounded, one-GPU diagnostic job portfolio."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import sys
import threading
import time
from typing import Any, Callable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from robot_debug.diagnostic_flow import DiagnosticFlow
from robot_debug.diagnostic_round import RoundRequest, run_round
from robot_debug.attempt_ledger import AttemptLedger
from robot_debug.portfolio_manifest import PortfolioManifest
from robot_debug.portfolio_policy import PortfolioBounds, choose_wave
from robot_debug.reduce import Rect, candidates
from robot_debug.worker_policy import choose_workers
from scripts import run_failure_search as search
from scripts.run_position_grid_search import GRID_POINTS, GRID_SIDE


SEARCH = tuple((point.stage, Rect(point.x, point.y, GRID_SIDE, GRID_SIDE)) for point in GRID_POINTS)
DELTAS = (.125, .0625)
MEASURED_SECONDS = {1: 610.247 / 16, 2: 310.472 / 16, 4: 164.256 / 16}
SHUTDOWN_RESERVE_SECONDS = 20.0


@dataclass(frozen=True)
class PortfolioLimits:
    episodes: int
    seconds: float
    estimated_usd: float
    hourly_rate: float

    def __post_init__(self) -> None:
        if isinstance(self.episodes, bool) or not isinstance(self.episodes, int) or self.episodes <= 0:
            raise ValueError("episodes must be a positive integer")
        for name, value in (("seconds", self.seconds), ("estimated_usd", self.estimated_usd),
                            ("hourly_rate", self.hourly_rate)):
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value <= 0):
                raise ValueError(f"{name} must be a finite positive number")


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def _rect_for(flow: DiagnosticFlow, case_id: str) -> Rect | None:
    if flow.phase == "search":
        return dict(SEARCH)[case_id]
    if flow.phase in {"confirm", "reduction_parent", "reduce_candidate"}:
        if flow.phase == "reduce_candidate":
            return candidates(flow.current_rect, delta=flow.deltas[flow.delta_index])[flow.candidate_index].rect
        return flow.current_rect
    return None


def _status(result: Any) -> str:
    return result.outcome if result.status == "valid" and result.outcome else result.status


def _launched_attempts(case_ids: list[str], durable: Mapping[str, Any]) -> int:
    """Validate the authoritative ledger before counting its launch intents."""
    if not isinstance(durable, Mapping):
        raise ValueError("ledger snapshot must be a mapping")
    ledger = AttemptLedger.from_snapshot(case_ids, dict(durable))
    return sum(record["state"] != "prepared" for record in ledger.attempts.values())


def run_portfolio(*, manifest: PortfolioManifest, mode: str, results_root: Path | str,
                  project_root: Path | str, evaluator: Callable[..., Any], limits: PortfolioLimits,
                  monotonic_clock: Callable[[], float] = time.monotonic,
                  interrupt_event: threading.Event | None = None, dry_run: bool = False,
                  max_workers: int | None = None) -> dict[str, Any]:
    """Run global durable waves; a bad round stops all jobs fail-closed.

    This core intentionally has no production evaluator or resume path.  The
    caller supplies a local evaluator; each wave delegates launch containment
    and its durable ledger to ``run_round``.
    """
    if not isinstance(manifest, PortfolioManifest):
        raise ValueError("manifest must be PortfolioManifest")
    if mode not in {"sequential-jobs", "adaptive-portfolio"}:
        raise ValueError("mode must be sequential-jobs or adaptive-portfolio")
    if not isinstance(limits, PortfolioLimits) or not callable(evaluator):
        raise ValueError("limits and evaluator are required")
    if interrupt_event is not None and not isinstance(interrupt_event, threading.Event):
        raise ValueError("interrupt_event must be a threading.Event")
    if not isinstance(dry_run, bool):
        raise ValueError("dry_run must be a boolean")
    if max_workers is not None and (isinstance(max_workers, bool)
                                    or not isinstance(max_workers, int)
                                    or max_workers not in MEASURED_SECONDS):
        raise ValueError("max_workers must be one of 1, 2, or 4")
    worker_cap = 1 if mode == "sequential-jobs" else max_workers
    root = Path(results_root).resolve()
    project = Path(project_root).resolve()
    session = root / f"portfolio-{mode}-{manifest.config_hash[:12]}"
    if session.exists():
        raise ValueError("refusing existing portfolio session; unsafe resume is disabled")
    (session / "waves").mkdir(parents=True)
    started = monotonic_clock()
    flows = {job.job_id: DiagnosticFlow(search=SEARCH, deltas=DELTAS, nominal_count=1,
             candidate_attempt_budget=12, control_count=5,
             config_hash=f"{manifest.config_hash}:{job.job_id}") for job in manifest.jobs}
    buffered: dict[str, dict[str, str]] = {job.job_id: {} for job in manifest.jobs}
    phase_times: dict[str, dict[str, float | None]] = {
        job.job_id: {"apparent_failure": None, "reproducible_failure": None,
                     "reduced_failure": None, "terminal": None}
        for job in manifest.jobs
    }
    summary: dict[str, Any] = {"schema_version": 1, "session_id": session.name, "mode": mode,
        "manifest": manifest.to_mapping(), "manifest_hash": manifest.config_hash,
        "dry_run": dry_run, "synthetic": dry_run,
        "execution_kind": "dry_run" if dry_run else "live",
        "max_workers": worker_cap,
        "limits": asdict(limits), "cost_basis": "warm elapsed seconds times one full VM rate; not billed allocation cost",
        "waves": [], "jobs": {}, "physical_attempts": 0, "valid_episodes": 0,
        "invalid_attempts": 0, "uncertain_attempts": 0, "elapsed_seconds": 0.0,
        "warm_diagnostic_estimate_usd": 0.0, "max_observed_evaluator_calls": 0,
        "accounting_incomplete": False,
        "certified": False, "stop_reason": None}
    evaluator_lock = threading.Lock()
    active_evaluator_calls = 0
    max_evaluator_calls = 0

    def elapsed() -> float:
        return max(0.0, monotonic_clock() - started)

    def save(reason: str | None = None) -> None:
        if reason is not None:
            summary["stop_reason"] = reason
        summary["elapsed_seconds"] = elapsed()
        summary["warm_diagnostic_estimate_usd"] = elapsed() * limits.hourly_rate / 3600
        summary["max_observed_evaluator_calls"] = max_evaluator_calls
        summary["certified"] = (not summary["accounting_incomplete"]
                                 and not str(summary["stop_reason"] or "").startswith("runner_exception")
                                 and all(flow.certified for flow in flows.values()))
        for job_id, flow in flows.items():
            job_summary = {"job_id": job_id, "flow": flow.snapshot(), "certified": flow.certified,
                           "buffered_case_ids": sorted(buffered[job_id]),
                           "phase_timestamps_seconds": phase_times[job_id],
                           "terminal_status": "certified" if flow.certified else flow.stop_reason}
            summary["jobs"][job_id] = job_summary
            job_dir = session / "jobs" / job_id
            job_dir.mkdir(parents=True, exist_ok=True)
            _atomic_json(job_dir / "job_summary.json", job_summary)
        _atomic_json(session / "portfolio_summary.json", summary)

    save()

    def reconcile_exception(error: BaseException, ledger_path: Path | None = None,
                            case_ids: list[str] | None = None) -> None:
        """Persist a fail-closed partial record before propagating unexpected errors."""
        if ledger_path is not None and ledger_path.is_file():
            try:
                durable = json.loads(ledger_path.read_text(encoding="utf-8"))
                if case_ids is None:
                    raise ValueError("expected case IDs are required for ledger accounting")
                launched = _launched_attempts(case_ids, durable)
                summary["physical_attempts"] += launched
            except (OSError, json.JSONDecodeError, TypeError, AttributeError, ValueError):
                summary["physical_attempts"] = None
                summary["accounting_incomplete"] = True
        elif ledger_path is not None:
            summary["accounting_incomplete"] = True
            summary["physical_attempts"] = None
        summary["certified"] = False
        summary["stop_reason"] = f"runner_exception: {type(error).__name__}: {error}"
        save(summary["stop_reason"])
    cursor = 0
    wave_number = 0
    while True:
        if interrupt_event is not None and interrupt_event.is_set():
            summary["stop_reason"] = "interrupted"; break
        active = [job_id for job_id, flow in flows.items() if flow.phase not in {"stopped", "certified"}]
        if not active:
            if summary["stop_reason"] is None:
                summary["stop_reason"] = "all_jobs_terminal"
            break
        remaining_episodes = limits.episodes - summary["physical_attempts"]
        remaining_seconds = limits.seconds - elapsed()
        remaining_dollars = limits.estimated_usd - elapsed() * limits.hourly_rate / 3600
        if remaining_episodes <= 0 or remaining_seconds <= 0 or remaining_dollars <= 0:
            summary["stop_reason"] = "shared_budget_exhausted"; break
        # Full frozen manifest keys are retained even for stopped jobs; this is
        # required by the policy's dynamic-readiness fairness guarantee.
        sequential_owner = active[0] if mode == "sequential-jobs" else None
        ready: dict[str, tuple[str, ...] | None] = {}
        for job_id, flow in flows.items():
            if flow.phase in {"stopped", "certified"} or job_id != sequential_owner and sequential_owner is not None:
                ready[job_id] = None; continue
            pending = flow.pending(search_limit=1 if flow.phase == "search" else None)
            ready[job_id] = tuple(case for case in pending if case not in buffered[job_id])
        # A bounded adaptive screen must first obtain one nominal outcome for
        # every frozen job; otherwise an early task can consume the next slot
        # with search work before a later task has been screened.
        if (mode == "adaptive-portfolio" and max_workers is not None
                and any(flows[job_id].phase == "nominal" and cases for job_id, cases in ready.items())):
            ready = {job_id: cases if flows[job_id].phase == "nominal" else None
                     for job_id, cases in ready.items()}
        wave = choose_wave(ready, cursor=cursor, slots=1 if mode == "sequential-jobs" else (max_workers or 4),
                           bounds=PortfolioBounds(remaining_episodes, remaining_seconds, remaining_dollars))
        cursor = wave.next_cursor
        if not wave.requests:
            summary["stop_reason"] = "no_ready_admitted_work"; break
        worker_choice = choose_workers(ready_count=len(wave.requests), seconds_left=remaining_seconds,
            dollars_left=remaining_dollars, hourly_rate=limits.hourly_rate,
            measured_seconds={workers: seconds for workers, seconds in MEASURED_SECONDS.items()
                              if worker_cap is None or workers <= worker_cap},
            shutdown_reserve_seconds=SHUTDOWN_RESERVE_SECONDS)
        if worker_choice.workers == 0:
            summary["stop_reason"] = "shared_budget_exhausted"; break
        launch_window = min(remaining_seconds, remaining_dollars * 3600 / limits.hourly_rate) - SHUTDOWN_RESERVE_SECONDS
        if launch_window <= 0:
            summary["stop_reason"] = "shared_budget_exhausted"; break
        wave_number += 1
        wave_root = session / "waves" / f"wave-{wave_number:04d}"
        (wave_root / "configs").mkdir(parents=True)
        requests: list[RoundRequest] = []
        owners: dict[str, tuple[str, str]] = {}
        jobs = {job.job_id: job for job in manifest.jobs}
        for choice in wave.requests:
            global_id = f"{choice.job_id}--{choice.case_id}"
            output = wave_root / "runs" / choice.job_id / choice.case_id
            config = wave_root / "configs" / f"{global_id}.yaml"
            rect = _rect_for(flows[choice.job_id], choice.case_id)
            options: dict[str, Any] = {"config_path": config, "output_dir": output, "project_root": project,
                "stage_name": global_id, "episode_indices": (0,), "task_id": jobs[choice.job_id].task_id,
                "seed": jobs[choice.job_id].seed}
            if rect is not None:
                options.update(x=rect.x, y=rect.y, width=rect.width, height=rect.height)
            try:
                search._write_config(**options)
            except BaseException as error:
                reconcile_exception(error)
                raise
            requests.append(RoundRequest(global_id, config, output)); owners[global_id] = (choice.job_id, choice.case_id)
        ledger = wave_root / "ledger.json"
        def observed_evaluator(*args: Any, **kwargs: Any) -> Any:
            nonlocal active_evaluator_calls, max_evaluator_calls
            with evaluator_lock:
                active_evaluator_calls += 1
                max_evaluator_calls = max(max_evaluator_calls, active_evaluator_calls)
            try:
                return evaluator(*args, **kwargs)
            finally:
                with evaluator_lock:
                    active_evaluator_calls -= 1
        try:
            round_summary = run_round(tuple(requests), workers=worker_choice.workers, launch_cutoff=launch_window,
                                      evaluator=observed_evaluator, ledger_path=ledger, round_root=wave_root,
                                      interrupt_event=interrupt_event)
            durable = json.loads(ledger.read_text(encoding="utf-8"))
        except BaseException as error:
            reconcile_exception(error, ledger, [request.case_id for request in requests])
            raise
        try:
            launched_attempts = _launched_attempts(
                [request.case_id for request in requests], durable)
            summary["physical_attempts"] += launched_attempts
        except ValueError as error:
            reconcile_exception(error, ledger, [request.case_id for request in requests])
            raise
        summary["valid_episodes"] += sum(result.status == "valid" for result in round_summary.results)
        summary["invalid_attempts"] += sum(result.status in {"invalid_evidence", "infrastructure_error"} for result in round_summary.results)
        summary["uncertain_attempts"] += sum(result.status == "uncertain" for result in round_summary.results)
        summary["waves"].append({"wave_id": wave_number, "cursor": cursor, "requests": [asdict(item) for item in wave.requests],
            "worker_choice": asdict(worker_choice), "ledger_path": str(ledger.relative_to(session)),
            "launched_attempts": launched_attempts,
            "attempt_accounting_validated": True,
            "timing_source": "M3 fixed-manifest warm per-episode measurements; not task-specific",
            "manifest_hash": round_summary.manifest_hash, "results": [asdict(result) for result in round_summary.results]})
        if not round_summary.certifying or len(round_summary.results) != len(requests):
            summary["stop_reason"] = round_summary.stop_reason or "invalid_or_uncertain_round"; save(); break
        bad = [result for result in round_summary.results if _status(result) not in {"success", "policy_failure"}]
        if bad:
            summary["stop_reason"] = _status(bad[0]); save(); break
        try:
            for result in round_summary.results:
                job_id, case_id = owners[result.case_id]
                buffered[job_id][case_id] = _status(result)
        except BaseException as error:
            reconcile_exception(error)
            raise
        for job_id, flow in flows.items():
            expected = flow.pending(search_limit=1 if flow.phase == "search" else None)
            if expected and set(expected).issubset(buffered[job_id]):
                outcomes = {case: buffered[job_id].pop(case) for case in expected}
                previous_phase = flow.phase
                prior_decisions = len(flow.decisions)
                try:
                    flow.apply_round(outcomes)
                except BaseException as error:
                    # This ledger was already counted immediately after the
                    # durable read above; do not double-count it on routing.
                    reconcile_exception(error)
                    raise
                marked = elapsed()
                timestamps = phase_times[job_id]
                if previous_phase == "search" and flow.phase == "confirm":
                    timestamps["apparent_failure"] = marked
                if previous_phase == "confirm" and flow.phase == "reduction_sentinel":
                    timestamps["reproducible_failure"] = marked
                if (timestamps["reduced_failure"] is None
                        and any(item.get("decision") == "pass" for item in flow.decisions[prior_decisions:])):
                    timestamps["reduced_failure"] = marked
                if flow.phase in {"stopped", "certified"} and timestamps["terminal"] is None:
                    timestamps["terminal"] = marked
        save()
    save(summary["stop_reason"])
    return summary
