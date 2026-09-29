"""Durable local core for a bounded, one-GPU diagnostic job portfolio."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import sys
import time
from typing import Any, Callable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from robot_debug.diagnostic_flow import DiagnosticFlow
from robot_debug.diagnostic_round import RoundRequest, run_round
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


def run_portfolio(*, manifest: PortfolioManifest, mode: str, results_root: Path | str,
                  project_root: Path | str, evaluator: Callable[..., Any], limits: PortfolioLimits,
                  monotonic_clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
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
    summary: dict[str, Any] = {"schema_version": 1, "session_id": session.name, "mode": mode,
        "manifest": manifest.to_mapping(), "manifest_hash": manifest.config_hash,
        "limits": asdict(limits), "cost_basis": "warm elapsed seconds times one full VM rate; not billed allocation cost",
        "waves": [], "jobs": {}, "physical_attempts": 0, "valid_episodes": 0,
        "invalid_attempts": 0, "uncertain_attempts": 0, "elapsed_seconds": 0.0,
        "warm_diagnostic_estimate_usd": 0.0, "certified": False, "stop_reason": None}

    def elapsed() -> float:
        return max(0.0, monotonic_clock() - started)

    def save(reason: str | None = None) -> None:
        if reason is not None:
            summary["stop_reason"] = reason
        summary["elapsed_seconds"] = elapsed()
        summary["warm_diagnostic_estimate_usd"] = elapsed() * limits.hourly_rate / 3600
        summary["certified"] = all(flow.certified for flow in flows.values())
        for job_id, flow in flows.items():
            job_summary = {"job_id": job_id, "flow": flow.snapshot(), "certified": flow.certified,
                           "buffered_case_ids": sorted(buffered[job_id])}
            summary["jobs"][job_id] = job_summary
            job_dir = session / "jobs" / job_id
            job_dir.mkdir(parents=True, exist_ok=True)
            _atomic_json(job_dir / "job_summary.json", job_summary)
        _atomic_json(session / "portfolio_summary.json", summary)

    save()
    cursor = 0
    wave_number = 0
    while True:
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
        ready: dict[str, tuple[str, ...] | None] = {}
        for job_id, flow in flows.items():
            if flow.phase in {"stopped", "certified"}:
                ready[job_id] = None; continue
            pending = flow.pending(search_limit=1 if flow.phase == "search" else None)
            ready[job_id] = tuple(case for case in pending if case not in buffered[job_id])
        wave = choose_wave(ready, cursor=cursor, slots=1 if mode == "sequential-jobs" else 4,
                           bounds=PortfolioBounds(remaining_episodes, remaining_seconds, remaining_dollars))
        cursor = wave.next_cursor
        if not wave.requests:
            summary["stop_reason"] = "no_ready_admitted_work"; break
        worker_choice = choose_workers(ready_count=len(wave.requests), seconds_left=remaining_seconds,
            dollars_left=remaining_dollars, hourly_rate=limits.hourly_rate,
            measured_seconds=({1: MEASURED_SECONDS[1]} if mode == "sequential-jobs" else MEASURED_SECONDS),
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
            search._write_config(**options)
            requests.append(RoundRequest(global_id, config, output)); owners[global_id] = (choice.job_id, choice.case_id)
        ledger = wave_root / "ledger.json"
        round_summary = run_round(tuple(requests), workers=worker_choice.workers, launch_cutoff=launch_window,
                                  evaluator=evaluator, ledger_path=ledger, round_root=wave_root)
        durable = json.loads(ledger.read_text(encoding="utf-8"))
        summary["physical_attempts"] += sum(record.get("state") != "prepared"
                                             for record in durable.get("attempt_records", {}).values())
        summary["valid_episodes"] += sum(result.status == "valid" for result in round_summary.results)
        summary["invalid_attempts"] += sum(result.status in {"invalid_evidence", "infrastructure_error"} for result in round_summary.results)
        summary["uncertain_attempts"] += sum(result.status == "uncertain" for result in round_summary.results)
        summary["waves"].append({"wave_id": wave_number, "cursor": cursor, "requests": [asdict(item) for item in wave.requests],
            "worker_choice": asdict(worker_choice), "ledger_path": str(ledger.relative_to(session)),
            "manifest_hash": round_summary.manifest_hash, "results": [asdict(result) for result in round_summary.results]})
        if not round_summary.certifying or len(round_summary.results) != len(requests):
            summary["stop_reason"] = round_summary.stop_reason or "invalid_or_uncertain_round"; save(); break
        bad = [result for result in round_summary.results if _status(result) not in {"success", "policy_failure"}]
        if bad:
            summary["stop_reason"] = _status(bad[0]); save(); break
        for result in round_summary.results:
            job_id, case_id = owners[result.case_id]
            buffered[job_id][case_id] = _status(result)
        for job_id, flow in flows.items():
            expected = flow.pending(search_limit=1 if flow.phase == "search" else None)
            if expected and set(expected).issubset(buffered[job_id]):
                outcomes = {case: buffered[job_id].pop(case) for case in expected}
                flow.apply_round(outcomes)
        save()
    save(summary["stop_reason"])
    return summary
