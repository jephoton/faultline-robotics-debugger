"""Run one bounded M3 replay mode locally or against an already-running evaluator."""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
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


def run_mode(
    *,
    upstream_root: Path | str,
    project_root: Path | str,
    results_root: Path | str,
    workers: int,
    repeats_per_case: int = 8,
    launch_cutoff_seconds: float = 1560,
    item_timeout_seconds: float = 300,
    command_runner: Callable[..., Any] = subprocess.run,
    monotonic_clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Run a fixed manifest once, stopping future launches on unsafe evidence."""
    if isinstance(workers, bool) or not isinstance(workers, int) or workers not in (1, 2, 4):
        raise ValueError("workers must be one of 1, 2, or 4")
    if item_timeout_seconds <= 0:
        raise ValueError("item_timeout_seconds must be positive")
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

    def execute(item: dict[str, Any], config: Path, output: Path, attempt_started: float) -> dict[str, Any]:
        record = {"case_id": item["case_id"], "kind": item["kind"], "task_id": 0, "episode_index": 0,
                  "config_path": str(config.relative_to(session)), "output_path": str(output.relative_to(session)),
                  "started_seconds": attempt_started, "ended_seconds": None, "duration_seconds": None,
                  "status": None, "outcome": None, "replayable": False}
        try:
            process = command_runner([base._resolve_evaluator_command(Path(sys.executable)), "run", "--config", str(config)],
                cwd=upstream_root, check=False, timeout=item_timeout_seconds)
        except subprocess.TimeoutExpired as error:
            record.update(status="infrastructure_error", infrastructure_error=f"timeout: {error}")
        except Exception as error:
            record.update(status="infrastructure_error", infrastructure_error=f"command_runner: {type(error).__name__}: {error}")
        else:
            returncode = getattr(process, "returncode", 0)
            record["returncode"] = returncode
            if returncode not in (0, None):
                record.update(status="infrastructure_error", infrastructure_error=f"evaluator returned nonzero status {returncode}")
            else:
                try:
                    result = base._load_stage_results(output, expected_count=1)[0]
                    raw = json.loads(next(output.rglob("*_aggregate.json")).read_text(encoding="utf-8"))
                    task = raw["tasks"][0]
                    task_ids = (task.get("task_id"), task["episodes"][0].get("task_id"))
                    present_task_ids = [task_id for task_id in task_ids if task_id is not None]
                    if (not present_task_ids or any(type(task_id) is not int or task_id != 0 for task_id in present_task_ids)
                            or result.episode_index != 0):
                        raise ValueError("aggregate task_id or episode_index does not match M3 item")
                    if result.outcome not in {"success", "policy_failure"}:
                        raise ValueError("aggregate did not contain a completed policy outcome")
                    record.update(status="valid", outcome=result.outcome,
                        replayable=any(path.is_file() for path in output.rglob("*.mp4")))
                except Exception as error:
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
            while not stopped and len(active) < workers:
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
                if elapsed() >= launch_cutoff_seconds:
                    summary["in_flight_ids"].remove(item["case_id"])
                    stopped = True
                    summary["stop_reason"] = "launch_cutoff_reached"
                    save()
                    break
                active[executor.submit(execute, item, config, output, attempt_started)] = item["case_id"]
            if not active:
                break
            done, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                case_id = active.pop(future)
                summary["in_flight_ids"].remove(case_id)
                record = future.result()
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
    run_mode(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
