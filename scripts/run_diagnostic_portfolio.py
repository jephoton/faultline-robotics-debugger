"""CLI boundary for local or contained portfolio diagnostic evaluation.

``--dry-run`` is synthetic local evidence and exits zero even when no failure
is certified.  A non-dry partial portfolio exits nonzero.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import threading
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
for entry in (str(PROJECT_ROOT), str(SOURCE_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from robot_debug.diagnostic_round import RoundLifecycle, RoundRequest
from robot_debug.portfolio_manifest import PortfolioManifest
from robot_debug.portfolio_runner import PortfolioLimits, run_portfolio
from scripts import run_failure_search as search
from scripts import run_parallel_eval as parallel


def load_manifest(path: Path | str) -> PortfolioManifest:
    """Load only the exact frozen manifest representation."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("manifest must be readable JSON") from error
    return PortfolioManifest.from_mapping(raw)


def _expected_job_id(global_case_id: str) -> str:
    if not isinstance(global_case_id, str) or "--" not in global_case_id:
        raise ValueError("portfolio request must have a job-prefixed global case ID")
    return global_case_id.split("--", 1)[0]


def production_evaluator(upstream_root: Path | str, task_ids: Mapping[str, int]) -> Callable[..., dict[str, Any]]:
    """Adapt the M3 contained launcher; task identity comes from the frozen job."""
    upstream = Path(upstream_root).resolve()
    frozen_tasks = dict(task_ids)

    def evaluate(request: RoundRequest, *, launch_observer: Callable[[int, str], None],
                 lifecycle: RoundLifecycle) -> dict[str, Any]:
        job_id = _expected_job_id(request.case_id)
        if job_id not in frozen_tasks:
            raise ValueError("request job ID is not present in the frozen manifest")
        completed = parallel._run_evaluator_safely(
            [search._resolve_evaluator_command(Path(sys.executable)), "run", "--config", str(request.config_path)],
            cwd=upstream, check=False, timeout=300, stop_event=lifecycle.stop_requested,
            interrupt_event=lifecycle.interrupt_event, launch_lock=lifecycle.launch_lock,
            launch_observer=launch_observer)
        if getattr(completed, "returncode", 0) not in (0, None):
            return {"status": "infrastructure_error", "outcome": None, "evidence_paths": []}
        parsed = search._load_stage_results(request.output_dir, expected_count=1)
        aggregates = [path for path in request.output_dir.rglob("*_aggregate.json")
                      if path.is_file() and path.stat().st_size > 0]
        if len(aggregates) != 1:
            raise ValueError("production evidence requires exactly one non-empty aggregate")
        try:
            aggregate = json.loads(aggregates[0].read_text(encoding="utf-8"))
            task = aggregate["tasks"][0]
            episode = task["episodes"][0]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise ValueError("aggregate task evidence is malformed") from error
        expected_task = frozen_tasks[job_id]
        if (type(episode.get("task_id")) is not int or episode["task_id"] != expected_task
                or ("task_id" in task and task["task_id"] != expected_task)
                or parsed[0].episode_index != 0):
            raise ValueError("aggregate task_id or episode_index does not match frozen job")
        traces = [path for path in request.output_dir.rglob("*.jsonl")
                  if path.is_file() and path.stat().st_size > 0]
        videos = [path for path in request.output_dir.rglob("*.mp4")
                  if path.is_file() and path.stat().st_size > 0]
        if not traces or not videos:
            raise ValueError("replayable production evidence requires non-empty trace and MP4")
        return {"status": "valid", "outcome": parsed[0].outcome,
                "evidence_paths": [str(aggregates[0]), str(traces[0]), str(videos[0])]}
    return evaluate


def dry_run_evaluator() -> Callable[..., dict[str, Any]]:
    counter = 9500
    def evaluate(request: RoundRequest, *, launch_observer: Callable[[int, str], None], **_: Any) -> dict[str, Any]:
        nonlocal counter
        counter += 1; launch_observer(counter, f"vla-eval-{counter}")
        request.output_dir.mkdir(parents=True)
        evidence = request.output_dir / "synthetic_aggregate.json"
        evidence.write_text(json.dumps({"synthetic": True, "case_id": request.case_id}), encoding="utf-8")
        return {"status": "valid", "outcome": "success", "evidence_paths": [str(evidence)]}
    return evaluate


def run_cli(*, manifest_path: Path | str, mode: str, results_root: Path | str,
            upstream_root: Path | str, project_root: Path | str, episodes: int,
            seconds: float, estimated_usd: float, hourly_rate: float, dry_run: bool,
            interrupt_event: threading.Event | None = None,
            max_workers: int | None = None) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    evaluator = (dry_run_evaluator() if dry_run else
                 production_evaluator(upstream_root, {job.job_id: job.task_id for job in manifest.jobs}))
    summary = run_portfolio(manifest=manifest, mode=mode, results_root=results_root,
                             project_root=project_root, evaluator=evaluator,
                             limits=PortfolioLimits(episodes, seconds, estimated_usd, hourly_rate),
                             interrupt_event=interrupt_event, dry_run=dry_run,
                             max_workers=max_workers)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path); parser.add_argument("--mode", required=True,
                        choices=("sequential-jobs", "adaptive-portfolio"))
    parser.add_argument("--results-root", required=True, type=Path); parser.add_argument("--upstream-root", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path); parser.add_argument("--episodes", required=True, type=int)
    parser.add_argument("--seconds", required=True, type=float); parser.add_argument("--estimated-usd", required=True, type=float)
    parser.add_argument("--hourly-rate", required=True, type=float); parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-workers", type=int, default=None)
    args = parser.parse_args(); interrupt_event = threading.Event(); previous: dict[int, Any] = {}
    if os.name == "posix" and threading.current_thread() is threading.main_thread():
        def request_interrupt(_signum: int, _frame: Any) -> None: interrupt_event.set()
        for signum in (signal.SIGINT, signal.SIGTERM): previous[signum] = signal.signal(signum, request_interrupt)
    try:
        summary = run_cli(manifest_path=args.manifest, mode=args.mode,
                          results_root=args.results_root, upstream_root=args.upstream_root,
                          project_root=args.project_root, episodes=args.episodes,
                          seconds=args.seconds, estimated_usd=args.estimated_usd,
                          hourly_rate=args.hourly_rate, dry_run=args.dry_run,
                          max_workers=args.max_workers, interrupt_event=interrupt_event)
    finally:
        for signum, handler in previous.items(): signal.signal(signum, handler)
    print(json.dumps({"summary": str(args.results_root / summary["session_id"] / "portfolio_summary.json"),
                      "status": "certified" if summary["certified"] else "partial",
                      "stop_reason": summary["stop_reason"]}))
    if not summary["certified"] and not args.dry_run:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
