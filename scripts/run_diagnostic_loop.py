"""Run the accepted one-GPU adaptive diagnostic loop without provisioning hardware.

The public ``run_session`` accepts an evaluator only for local tests.  The CLI's
``--dry-run`` uses the same adapter with deterministic local evidence; a live
run retains M3's process-group/container containment through
``_run_evaluator_safely``.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Mapping

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from robot_debug.diagnostic_flow import DiagnosticFlow
from robot_debug.diagnostic_round import RoundLifecycle, RoundRequest, run_round
from robot_debug.reduce import Rect, candidates
from robot_debug.worker_policy import WorkerChoice, choose_workers

try:
    from scripts import run_failure_search as search
    from scripts import run_parallel_eval as parallel
except ImportError:  # Direct execution from scripts/ remains supported.
    import run_failure_search as search
    import run_parallel_eval as parallel

from scripts.run_position_grid_search import GRID_POINTS, GRID_SIDE


MODEL_ID = "GR00T N1.7"
TASK_ID = 0
SEED = 7
SEARCH = tuple((point.stage, Rect(point.x, point.y, GRID_SIDE, GRID_SIDE)) for point in GRID_POINTS)
DELTAS = (.125, .0625)
MEASURED_SECONDS = {1: 610.247 / 16, 2: 310.472 / 16, 4: 164.256 / 16}
SHUTDOWN_RESERVE_SECONDS = 20.0


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def _contract() -> dict[str, Any]:
    frozen = {"model_id": MODEL_ID, "task_id": TASK_ID, "seed": SEED,
              "perturbation_family": "agentview_rect_occlusion",
              "search": [(case, asdict(rect)) for case, rect in SEARCH],
              "deltas": list(DELTAS),
              "gate_rules": {"confirmation": "four_failures_of_exactly_five",
                             "reduction": "four_failures_or_two_successes_of_at_most_five",
                             "controls_required": True}}
    encoded = json.dumps(frozen, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {**frozen, "config_hash": hashlib.sha256(encoded).hexdigest()}


def _rect_for(flow: DiagnosticFlow, case_id: str) -> Rect | None:
    if flow.phase == "search":
        return dict(SEARCH)[case_id]
    if flow.phase in {"confirm", "reduction_parent", "reduce_candidate"}:
        if flow.phase == "reduce_candidate":
            return candidates(flow.current_rect, delta=flow.deltas[flow.delta_index])[flow.candidate_index].rect
        return flow.current_rect
    return None


def _result_status(result: Any) -> str:
    return result.status if result.status != "valid" else (result.outcome or "invalid_evidence")


def _safe_number(name: str, value: object, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite {'positive' if positive else 'nonnegative'} number")
    number = float(value)
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise ValueError(f"{name} must be a finite {'positive' if positive else 'nonnegative'} number")
    return number


def run_session(*, upstream_root: Path | str, project_root: Path | str,
                results_root: Path | str, policy: str, launch_cutoff_seconds: float,
                episode_limit: int, hourly_rate_usd: float, max_estimated_usd: float,
                evaluator: Callable[..., Any], monotonic_clock: Callable[[], float] = time.monotonic,
                dry_run: bool = False, interrupt_event: threading.Event | None = None) -> dict[str, Any]:
    """Persist an immutable bounded session; invalid or uncertain rounds stop it."""
    if policy not in {"sequential", "adaptive"}:
        raise ValueError("policy must be sequential or adaptive")
    cutoff = _safe_number("launch_cutoff_seconds", launch_cutoff_seconds, positive=True)
    rate = _safe_number("hourly_rate_usd", hourly_rate_usd, positive=True)
    budget = _safe_number("max_estimated_usd", max_estimated_usd, positive=True)
    if isinstance(episode_limit, bool) or not isinstance(episode_limit, int) or episode_limit <= 0:
        raise ValueError("episode_limit must be a positive integer")
    if not callable(evaluator):
        raise ValueError("evaluator must be callable")
    if interrupt_event is not None and not isinstance(interrupt_event, threading.Event):
        raise ValueError("interrupt_event must be a threading.Event")
    upstream, project, root = Path(upstream_root).resolve(), Path(project_root).resolve(), Path(results_root).resolve()
    contract = _contract()
    session = root / f"diagnostic-{policy}-{contract['config_hash'][:12]}"
    if session.exists():
        raise ValueError("refusing existing diagnostic session; partial rounds are non-resumable")
    (session / "rounds").mkdir(parents=True)
    started = monotonic_clock()
    flow = DiagnosticFlow(search=SEARCH, deltas=DELTAS, nominal_count=1,
                          candidate_attempt_budget=12, control_count=5,
                          config_hash=contract["config_hash"])
    summary: dict[str, Any] = {
        "schema_version": 1, "session_id": session.name, "policy": policy,
        "status": "partial", "stop_reason": None, "dry_run": dry_run,
        "scenario_contract": contract, "full_vm_hourly_rate_usd": rate,
        "flow": flow.snapshot(), "rounds": [], "certified": False,
        "certified_rectangle": None, "controls_passed": False,
        "valid_episodes": 0, "physical_attempts": 0, "invalid_attempts": 0,
        "uncertain_attempts": 0, "elapsed_seconds": 0.0, "estimated_compute_usd": 0.0,
        "warm_diagnostic_estimate_usd": 0.0,
        "cost_basis": "warm diagnostic elapsed seconds times full VM hourly rate; not allocation or billed cost",
        "phase_timestamps_seconds": {"apparent_failure": None, "reproducible_failure": None,
                                      "reduced_failure": None},
        "config_paths": [], "evidence_paths": [],
    }

    def elapsed() -> float:
        return max(0.0, monotonic_clock() - started)

    def save(reason: str | None = None) -> None:
        if reason is not None:
            summary["stop_reason"] = reason
        summary["flow"] = flow.snapshot()
        summary["certified"] = flow.certified
        summary["controls_passed"] = flow.certified
        summary["certified_rectangle"] = asdict(flow.current_rect) if flow.certified and flow.current_rect else None
        summary["status"] = "complete" if flow.certified else "partial"
        summary["elapsed_seconds"] = elapsed()
        summary["estimated_compute_usd"] = summary["elapsed_seconds"] * rate / 3600
        summary["warm_diagnostic_estimate_usd"] = summary["estimated_compute_usd"]
        _atomic_json(session / "session_summary.json", summary)

    save()
    round_number = 0
    while not flow.certified and flow.phase != "stopped":
        if interrupt_event is not None and interrupt_event.is_set():
            flow._stop("interrupted")
            break
        pending = flow.pending(search_limit=4 if flow.phase == "search" else None)
        if not pending:
            break
        if elapsed() >= cutoff:
            flow._stop("launch_cutoff_reached")
            break
        if summary["physical_attempts"] + len(pending) > episode_limit:
            flow._stop("episode_limit_reached")
            break
        remaining_seconds = cutoff - elapsed()
        remaining_dollars = budget - (elapsed() * rate / 3600)
        measured_choice = choose_workers(ready_count=len(pending), seconds_left=remaining_seconds,
                                         dollars_left=max(0.0, remaining_dollars), hourly_rate=rate,
                                         measured_seconds=( {1: MEASURED_SECONDS[1]} if policy == "sequential"
                                                            else MEASURED_SECONDS ),
                                         shutdown_reserve_seconds=SHUTDOWN_RESERVE_SECONDS)
        choice = (WorkerChoice(1, "fixed sequential baseline; " + measured_choice.reason,
                               measured_choice.predicted_seconds, measured_choice.predicted_cost_usd)
                  if policy == "sequential" and measured_choice.workers else measured_choice)
        if choice.workers == 0:
            flow._stop("budget_or_deadline_prevents_launch")
            break
        # The shared scheduler consults this cutoff before *each* submit.
        # Reserve the same shutdown/evidence window used by worker policy so
        # a late wave cannot begin merely because this round started in time.
        round_launch_window = min(cutoff - elapsed(),
                                  max(0.0, remaining_dollars * 3600 / rate)) - SHUTDOWN_RESERVE_SECONDS
        if round_launch_window <= 0:
            flow._stop("budget_or_deadline_prevents_launch")
            break
        round_number += 1
        round_root = session / "rounds" / f"round-{round_number:04d}"
        (round_root / "configs").mkdir(parents=True)
        requests = []
        for case_id in pending:
            output = round_root / "runs" / case_id
            config = round_root / "configs" / f"{case_id}.yaml"
            rect = _rect_for(flow, case_id)
            kwargs: dict[str, Any] = {"config_path": config, "output_dir": output,
                                      "project_root": project, "stage_name": case_id,
                                      "episode_indices": (0,)}
            if rect is not None:
                kwargs.update(x=rect.x, y=rect.y, width=rect.width, height=rect.height)
            search._write_config(**kwargs)
            requests.append(RoundRequest(case_id, config, output))
            summary["config_paths"].append(str(config.relative_to(session)))
        ledger_path = round_root / "ledger.json"
        round_summary = run_round(tuple(requests), workers=choice.workers,
                                  launch_cutoff=round_launch_window, evaluator=evaluator,
                                  ledger_path=ledger_path, round_root=round_root,
                                  interrupt_event=interrupt_event)
        results = {item.case_id: _result_status(item) for item in round_summary.results}
        # Ledger intent is the authoritative physical-attempt boundary; a
        # completed record alone cannot prove that no late launch happened.
        durable = json.loads(ledger_path.read_text(encoding="utf-8"))
        launched = sum(record.get("state") != "prepared"
                       for record in durable.get("attempt_records", {}).values())
        summary["physical_attempts"] += launched
        summary["valid_episodes"] += sum(item.status == "valid" for item in round_summary.results)
        summary["invalid_attempts"] += sum(item.status in {"invalid_evidence", "infrastructure_error"} for item in round_summary.results)
        summary["uncertain_attempts"] += sum(item.status == "uncertain" for item in round_summary.results)
        evidence = [path for item in round_summary.results for path in item.evidence_paths]
        summary["evidence_paths"].extend(evidence)
        summary["rounds"].append({"round_id": round_number, "case_ids": list(pending),
                                  "worker_choice": asdict(choice), "ledger_path": str(ledger_path.relative_to(session)),
                                  "manifest_hash": round_summary.manifest_hash, "results": [asdict(item) for item in round_summary.results]})
        if not round_summary.certifying or set(results) != set(pending) or any(value not in {"success", "policy_failure"} for value in results.values()):
            flow._stop(round_summary.stop_reason or "invalid_or_uncertain_round")
            save(flow.stop_reason)
            break
        previous = flow.phase
        flow.apply_round(results)
        if previous == "search" and flow.phase == "confirm":
            summary["phase_timestamps_seconds"]["apparent_failure"] = elapsed()
        if previous == "confirm" and flow.phase == "reduction_sentinel":
            summary["phase_timestamps_seconds"]["reproducible_failure"] = elapsed()
        if (previous == "reduce_candidate" and summary["phase_timestamps_seconds"]["reduced_failure"] is None
                and any(item.get("decision") == "pass" for item in flow.decisions)):
            summary["phase_timestamps_seconds"]["reduced_failure"] = elapsed()
        save(flow.stop_reason)
    if flow.phase == "stopped":
        save(flow.stop_reason)
    else:
        save()
    return summary


def _fake_evaluator(outcomes: Mapping[str, str]) -> Callable[..., dict[str, Any]]:
    counter = 9000
    def evaluate(request: RoundRequest, *, launch_observer: Callable[[int, str], None], **_: Any) -> dict[str, Any]:
        nonlocal counter
        counter += 1; launch_observer(counter, f"vla-eval-{counter}")
        key = next((prefix for prefix in outcomes if request.case_id.startswith(prefix)), "default")
        outcome = outcomes.get(key, "policy_failure")
        request.output_dir.mkdir(parents=True)
        evidence = request.output_dir / "fake_aggregate.json"
        evidence.write_text(json.dumps({"case_id": request.case_id, "outcome": outcome}), encoding="utf-8")
        return {"status": "valid", "outcome": outcome, "evidence_paths": [str(evidence)]}
    return evaluate


def run_local_fixture(*, policy: str, outcomes: Mapping[str, str], results_root: Path | str) -> dict[str, Any]:
    root = Path(results_root)
    return run_session(upstream_root=root, project_root=Path(__file__).resolve().parents[1], results_root=root,
                       policy=policy, launch_cutoff_seconds=600, episode_limit=100,
                       hourly_rate_usd=1.0, max_estimated_usd=10.0,
                       evaluator=_fake_evaluator(outcomes), dry_run=True)


def _production_evaluator(upstream: Path) -> Callable[..., dict[str, Any]]:
    def evaluate(request: RoundRequest, *, launch_observer: Callable[[int, str], None], lifecycle: RoundLifecycle) -> dict[str, Any]:
        completed = parallel._run_evaluator_safely([
            search._resolve_evaluator_command(Path(sys.executable)), "run", "--config", str(request.config_path)],
            cwd=upstream, check=False, timeout=300, stop_event=lifecycle.stop_requested,
            interrupt_event=lifecycle.interrupt_event, launch_lock=lifecycle.launch_lock,
            launch_observer=launch_observer)
        if getattr(completed, "returncode", 0) not in (0, None):
            return {"status": "infrastructure_error", "outcome": None, "evidence_paths": []}
        parsed = search._load_stage_results(request.output_dir, expected_count=1)
        aggregates = list(request.output_dir.rglob("*_aggregate.json"))
        if len(aggregates) != 1:
            raise ValueError("expected exactly one aggregate evidence file")
        aggregate = json.loads(aggregates[0].read_text(encoding="utf-8"))
        task = aggregate["tasks"][0]
        episode = task["episodes"][0]
        if (type(episode.get("task_id")) is not int or episode["task_id"] != TASK_ID
                or ("task_id" in task and task["task_id"] != TASK_ID)
                or parsed[0].episode_index != 0):
            raise ValueError("aggregate task_id or episode_index does not match frozen scenario")
        traces = [path for path in request.output_dir.rglob("*.jsonl")
                  if path.is_file() and path.stat().st_size > 0]
        videos = [path for path in request.output_dir.rglob("*.mp4")
                  if path.is_file() and path.stat().st_size > 0]
        if not traces or not videos:
            raise ValueError("replayable production evidence requires non-empty trace and MP4")
        return {"status": "valid", "outcome": parsed[0].outcome,
                "evidence_paths": [str(aggregates[0]), str(traces[0]), str(videos[0])]}
    return evaluate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-root", required=True, type=Path); parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--results-root", required=True, type=Path); parser.add_argument("--policy", required=True, choices=("sequential", "adaptive"))
    parser.add_argument("--launch-cutoff-seconds", required=True, type=float); parser.add_argument("--episode-limit", required=True, type=int)
    parser.add_argument("--hourly-rate-usd", required=True, type=float); parser.add_argument("--max-estimated-usd", required=True, type=float)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    evaluator = _fake_evaluator({"nominal": "success", "control": "success", "reduction-sentinel": "success", "default": "policy_failure"}) if args.dry_run else _production_evaluator(args.upstream_root.resolve())
    interrupt_event = threading.Event()
    previous_handlers: dict[int, Any] = {}
    if os.name == "posix" and threading.current_thread() is threading.main_thread():
        def request_interrupt(_signum: int, _frame: Any) -> None:
            interrupt_event.set()
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.signal(signum, request_interrupt)
    try:
        summary = run_session(**vars(args), evaluator=evaluator, interrupt_event=interrupt_event)
    finally:
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)
    print(json.dumps({"summary": str(args.results_root / summary["session_id"] / "session_summary.json"), "status": summary["status"], "stop_reason": summary["stop_reason"]}))
    if not summary["certified"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
