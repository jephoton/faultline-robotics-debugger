"""Run one bounded M3 replay mode locally or against an already-running evaluator."""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import nullcontext
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Callable


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from robot_debug.parallel_eval import build_manifest, manifest_hash


_BASE_PATH = Path(__file__).with_name("run_failure_search.py")
_BASE_SPEC = importlib.util.spec_from_file_location("run_failure_search_base", _BASE_PATH)
base = importlib.util.module_from_spec(_BASE_SPEC)
sys.modules[_BASE_SPEC.name] = base
_BASE_SPEC.loader.exec_module(base)


class _LaunchCancelled(Exception):
    """A submitted item never started because another worker requested a stop."""


def _run_evaluator_safely(
    argv: list[str], *, cwd: Path, check: bool, timeout: float,
    process_factory: Callable[..., Any] = subprocess.Popen,
    docker_runner: Callable[..., Any] = subprocess.run,
    stop_event: threading.Event | None = None,
    launch_lock: threading.Lock | None = None,
) -> Any:
    """Own the evaluator PID so timeout can trigger the pinned CLI's SIGTERM cleanup.

    The pinned Docker CLI names its `--rm` container ``vla-eval-{os.getpid()}``.
    It handles SIGTERM by stopping that container with a ten-second grace period.
    An uncertain Docker query must never count as cleanup confirmation.
    """
    with launch_lock if launch_lock is not None else nullcontext():
        if stop_event is not None and stop_event.is_set():
            raise _LaunchCancelled()
        process = process_factory(argv, cwd=cwd)
    try:
        process.wait(timeout=timeout)
        return process
    except BaseException as error:
        if stop_event is not None:
            with launch_lock if launch_lock is not None else nullcontext():
                stop_event.set()
        container = f"vla-eval-{process.pid}"
        problems: list[str] = []
        reaped = False
        try:
            process.terminate()
            process.wait(timeout=20)  # Upstream docker stop -t 10 has a 15-second CLI timeout.
            reaped = True
        except subprocess.TimeoutExpired:
            problems.append("evaluator did not exit after SIGTERM")
        except Exception as cleanup_error:
            problems.append(f"SIGTERM/wait failed: {type(cleanup_error).__name__}: {cleanup_error}")

        def container_present() -> bool | None:
            try:
                result = docker_runner(["docker", "ps", "-a", "--format", "{{.Names}}"],
                    capture_output=True, text=True, check=False, timeout=15)
            except Exception as cleanup_error:
                problems.append(f"Docker inspection failed: {type(cleanup_error).__name__}: {cleanup_error}")
                return None
            if result.returncode != 0:
                problems.append(f"Docker inspection failed: {result.stderr}")
                return None
            return container in result.stdout.splitlines()

        present = container_present()
        if present is not False:
            try:
                removed = docker_runner(["docker", "rm", "-f", container],
                    capture_output=True, text=True, check=False, timeout=20)
                if removed.returncode != 0:
                    problems.append(f"Docker removal failed for {container}: {removed.stderr}")
            except Exception as cleanup_error:
                problems.append(f"Docker removal failed for {container}: {type(cleanup_error).__name__}: {cleanup_error}")

        if not reaped:
            try:
                process.kill()
                process.wait(timeout=5)
                reaped = True
            except Exception as cleanup_error:
                problems.append(f"evaluator reap failed: {type(cleanup_error).__name__}: {cleanup_error}")

        # Check after the parent has exited, so it cannot create a late container.
        absent = container_present() is False
        error.cleanup_confirmed = reaped and absent
        error.cleanup_error = "; ".join(problems) if not error.cleanup_confirmed else None
        if not error.cleanup_confirmed and not error.cleanup_error:
            error.cleanup_error = f"cannot confirm {container} was removed"
        raise


def _positive_finite_seconds(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")


def run_mode(
    *,
    upstream_root: Path | str,
    project_root: Path | str,
    results_root: Path | str,
    workers: int,
    repeats_per_case: int = 8,
    launch_cutoff_seconds: float = 1560,
    item_timeout_seconds: float = 300,
    command_runner: Callable[..., Any] | None = None,
    monotonic_clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Run a fixed manifest once, stopping future launches on unsafe evidence."""
    if isinstance(workers, bool) or not isinstance(workers, int) or workers not in (1, 2, 4):
        raise ValueError("workers must be one of 1, 2, or 4")
    _positive_finite_seconds("launch_cutoff_seconds", launch_cutoff_seconds)
    _positive_finite_seconds("item_timeout_seconds", item_timeout_seconds)
    stop_requested = threading.Event()
    launch_lock = threading.Lock()

    def request_stop() -> None:
        with launch_lock:
            stop_requested.set()

    if command_runner is None:
        def command_runner(argv: list[str], *, cwd: Path, check: bool, timeout: float) -> Any:
            return _run_evaluator_safely(argv, cwd=cwd, check=check, timeout=timeout,
                stop_event=stop_requested, launch_lock=launch_lock)
    upstream_root = Path(upstream_root).resolve()
    project_root = Path(project_root).resolve()
    started = monotonic_clock()
    items = build_manifest(repeats_per_case)
    session = base._prepare_session_directory(
        Path(results_root).resolve(), session_directory_name=f"m3-workers-{workers}"
    )
    configs = session / "configs"
    runs = session / "runs"
    configs.mkdir()
    runs.mkdir()
    manifest_path = session / "manifest.json"
    manifest_path.write_text(json.dumps(items, sort_keys=True, separators=(",", ":"), allow_nan=False), encoding="utf-8")

    summary: dict[str, Any] = {
        "workers": workers, "manifest_hash": manifest_hash(items), "manifest_path": "manifest.json",
        "case_ids": [item["case_id"] for item in items], "planned_ids": [item["case_id"] for item in items],
        "in_flight_ids": [], "results": [], "valid_count": 0, "cost_usd": None,
        "elapsed_seconds": 0.0, "stop_reason": None,
    }

    def elapsed() -> float:
        return monotonic_clock() - started

    def save() -> None:
        summary["elapsed_seconds"] = elapsed()
        base._atomic_write_json(session / "session_summary.json", summary)

    def item_paths(item: dict[str, Any]) -> tuple[Path, Path]:
        case_id = item["case_id"]
        config = configs / f"{case_id}.yaml"
        output = runs / case_id
        for path in (config, output):
            try:
                path.resolve().relative_to(session)
            except ValueError as error:
                raise ValueError("item path escapes session") from error
        return config, output

    def execute(item: dict[str, Any], config: Path, output: Path, attempt_started: float) -> dict[str, Any] | None:
        with launch_lock:
            if stop_requested.is_set():
                return None
        record = {"case_id": item["case_id"], "kind": item["kind"], "task_id": 0, "episode_index": 0,
                  "config_path": str(config.relative_to(session)), "output_path": str(output.relative_to(session)),
                  "started_seconds": attempt_started, "ended_seconds": None, "duration_seconds": None,
                  "status": None, "outcome": None, "replayable": False}
        try:
            process = command_runner([base._resolve_evaluator_command(Path(sys.executable)), "run", "--config", str(config)],
                cwd=upstream_root, check=False, timeout=item_timeout_seconds)
        except _LaunchCancelled:
            return None
        except subprocess.TimeoutExpired as error:
            request_stop()
            cleanup_confirmed = getattr(error, "cleanup_confirmed", False)
            cleanup_error = getattr(error, "cleanup_error", None)
            if not cleanup_confirmed and not cleanup_error:
                cleanup_error = "evaluator container cleanup was not confirmed"
            record.update(status="infrastructure_error", cleanup_confirmed=cleanup_confirmed,
                infrastructure_error=f"timeout: {error}" + (f"; cleanup risk: {cleanup_error}" if cleanup_error else ""))
        except Exception as error:
            request_stop()
            cleanup_confirmed = getattr(error, "cleanup_confirmed", None)
            cleanup_error = getattr(error, "cleanup_error", None)
            record.update(status="infrastructure_error", cleanup_confirmed=cleanup_confirmed,
                infrastructure_error=f"command_runner: {type(error).__name__}: {error}"
                + (f"; cleanup risk: {cleanup_error}" if cleanup_error else ""))
        else:
            returncode = getattr(process, "returncode", 0)
            record["returncode"] = returncode
            if returncode not in (0, None):
                request_stop()
                record.update(status="infrastructure_error", infrastructure_error=f"evaluator returned nonzero status {returncode}")
            else:
                try:
                    result = base._load_stage_results(output, expected_count=1)[0]
                    raw = json.loads(next(output.rglob("*_aggregate.json")).read_text(encoding="utf-8"))
                    task = raw["tasks"][0]
                    # The pinned harness writes task_id on each episode; the real
                    # aggregate task wrapper may omit it. Validate both when present.
                    episode_task_id = task["episodes"][0].get("task_id")
                    top_task_id = task.get("task_id")
                    if (type(episode_task_id) is not int or episode_task_id != 0
                            or ("task_id" in task and (type(top_task_id) is not int or top_task_id != 0))
                            or result.episode_index != 0):
                        raise ValueError("aggregate task_id or episode_index does not match M3 item")
                    if result.outcome not in {"success", "policy_failure"}:
                        raise ValueError("aggregate did not contain a completed policy outcome")
                    record.update(status="valid", outcome=result.outcome,
                        replayable=any(path.is_file() for path in output.rglob("*.mp4")))
                except Exception as error:
                    request_stop()
                    record.update(status="invalid_evidence", invalid_evidence=f"aggregate evidence error: {type(error).__name__}: {error}")
        record["ended_seconds"] = elapsed()
        record["duration_seconds"] = record["ended_seconds"] - attempt_started
        return record

    pending = iter(items)
    active: dict[Any, str] = {}
    stopped = False
    save()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        while True:
            while not stopped and not stop_requested.is_set() and len(active) < workers:
                if elapsed() >= launch_cutoff_seconds:
                    stopped = True; summary["stop_reason"] = "launch_cutoff_reached"; save(); break
                try:
                    item = next(pending)
                except StopIteration:
                    break
                config, output = item_paths(item)
                base._write_config(config_path=config, output_dir=output, project_root=project_root,
                    stage_name=f"m3-{item['case_id']}", episode_indices=(0,), **({} if item["rectangle"] is None else item["rectangle"]))
                attempt_started = elapsed()
                summary["in_flight_ids"].append(item["case_id"]); save()
                if elapsed() >= launch_cutoff_seconds or stop_requested.is_set():
                    summary["in_flight_ids"].remove(item["case_id"])
                    if not stop_requested.is_set():
                        stopped = True
                        summary["stop_reason"] = "launch_cutoff_reached"
                    save()
                    break
                with launch_lock:
                    if stop_requested.is_set():
                        cancelled = True
                    else:
                        active[executor.submit(execute, item, config, output, attempt_started)] = item["case_id"]
                        cancelled = False
                if cancelled:
                    summary["in_flight_ids"].remove(item["case_id"])
                    save()
                    break
            if not active:
                break
            done, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                case_id = active.pop(future)
                summary["in_flight_ids"].remove(case_id)
                record = future.result()
                if record is None:
                    save()
                    continue
                summary["results"].append(record)
                if record["status"] == "valid":
                    summary["valid_count"] += 1
                else:
                    stopped = True
                    summary["stop_reason"] = record["status"]
                save()
    if summary["stop_reason"] is None and len(summary["results"]) != len(items):
        summary["stop_reason"] = "partial"
    save()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-root", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--results-root", required=True, type=Path)
    parser.add_argument("--workers", required=True, type=int, choices=(1, 2, 4))
    parser.add_argument("--launch-cutoff-seconds", required=True, type=float)
    parser.add_argument("--item-timeout-seconds", required=True, type=float)
    args = parser.parse_args()
    summary = run_mode(**vars(args))
    path = args.results_root.resolve() / f"m3-workers-{args.workers}" / "session_summary.json"
    print(f"summary: {path} | stop: {summary['stop_reason'] or 'complete'} | valid: {summary['valid_count']}/{len(summary['planned_ids'])} | attempts: {len(summary['results'])}")
    if summary["stop_reason"] is not None or summary["valid_count"] != len(summary["planned_ids"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
