"""Run one bounded M3 replay mode locally or against an already-running evaluator."""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import nullcontext
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Callable


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from robot_debug.parallel_eval import build_manifest, manifest_hash, summarize_modes


_FROZEN_M3_MANIFEST_HASH = manifest_hash(build_manifest(8))


_BASE_PATH = Path(__file__).with_name("run_failure_search.py")
_BASE_SPEC = importlib.util.spec_from_file_location("run_failure_search_base", _BASE_PATH)
base = importlib.util.module_from_spec(_BASE_SPEC)
sys.modules[_BASE_SPEC.name] = base
_BASE_SPEC.loader.exec_module(base)


class _LaunchCancelled(Exception):
    """A submitted item never started because another worker requested a stop."""


class _EvaluatorInterrupted(Exception):
    """An active evaluator was cancelled by the session owner."""


def _run_evaluator_safely(
    argv: list[str], *, cwd: Path, check: bool, timeout: float,
    process_factory: Callable[..., Any] = subprocess.Popen,
    docker_runner: Callable[..., Any] = subprocess.run,
    stop_event: threading.Event | None = None,
    interrupt_event: threading.Event | None = None,
    launch_lock: threading.Lock | None = None,
) -> Any:
    """Own the evaluator PID so timeout can trigger the pinned CLI's SIGTERM cleanup.

    The pinned Docker CLI names its `--rm` container ``vla-eval-{os.getpid()}``.
    It handles SIGTERM by stopping that container with a ten-second grace period.
    An uncertain Docker query must never count as cleanup confirmation.
    """
    with launch_lock if launch_lock is not None else nullcontext():
        if ((stop_event is not None and stop_event.is_set())
                or (interrupt_event is not None and interrupt_event.is_set())):
            raise _LaunchCancelled()
        process = process_factory(argv, cwd=cwd)
    try:
        if interrupt_event is None:
            process.wait(timeout=timeout)
        else:
            deadline = time.monotonic() + timeout
            while True:
                if interrupt_event.is_set():
                    raise _EvaluatorInterrupted("session interrupted")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(argv, timeout)
                try:
                    process.wait(timeout=min(remaining, 0.2))
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(argv, timeout) from None
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
    interrupt_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Run a fixed manifest once, stopping future launches on unsafe evidence."""
    if isinstance(workers, bool) or not isinstance(workers, int) or workers not in (1, 2, 4):
        raise ValueError("workers must be one of 1, 2, or 4")
    _positive_finite_seconds("launch_cutoff_seconds", launch_cutoff_seconds)
    _positive_finite_seconds("item_timeout_seconds", item_timeout_seconds)
    stop_requested = threading.Event()
    if interrupt_event is None:
        interrupt_event = threading.Event()
    launch_lock = threading.Lock()

    def request_stop() -> None:
        with launch_lock:
            stop_requested.set()

    if command_runner is None:
        def command_runner(argv: list[str], *, cwd: Path, check: bool, timeout: float) -> Any:
            return _run_evaluator_safely(argv, cwd=cwd, check=check, timeout=timeout,
                stop_event=stop_requested, interrupt_event=interrupt_event, launch_lock=launch_lock)
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
        except _EvaluatorInterrupted as error:
            request_stop()
            cleanup_confirmed = getattr(error, "cleanup_confirmed", False)
            cleanup_error = getattr(error, "cleanup_error", None)
            record.update(status="infrastructure_error", cleanup_confirmed=cleanup_confirmed,
                infrastructure_error="session interrupted"
                + (f"; cleanup risk: {cleanup_error}" if cleanup_error else ""))
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
    executor = ThreadPoolExecutor(max_workers=workers)
    interrupted = False
    try:
        while True:
            while not stopped and not stop_requested.is_set() and not interrupt_event.is_set() and len(active) < workers:
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
                if elapsed() >= launch_cutoff_seconds or stop_requested.is_set() or interrupt_event.is_set():
                    summary["in_flight_ids"].remove(item["case_id"])
                    if not stop_requested.is_set():
                        stopped = True
                        summary["stop_reason"] = "launch_cutoff_reached"
                    save()
                    break
                with launch_lock:
                    if stop_requested.is_set() or interrupt_event.is_set():
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
            if interrupt_event.is_set():
                interrupted = True
                break
            done, _ = wait(active, timeout=0.2, return_when=FIRST_COMPLETED)
            for future in done:
                case_id = active[future]
                record = future.result()
                active.pop(future)
                summary["in_flight_ids"].remove(case_id)
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
        if interrupt_event.is_set():
            interrupted = True
    except KeyboardInterrupt:
        interrupted = True
        interrupt_event.set()
    finally:
        if interrupted or interrupt_event.is_set():
            interrupt_event.set()
            request_stop()
            summary["stop_reason"] = "interrupted"
            for future, case_id in list(active.items()):
                if future.cancel():
                    active.pop(future)
                    summary["in_flight_ids"].remove(case_id)
            save()
            # The default evaluator's graceful and forced cleanup is bounded by
            # its subprocess/Docker timeouts. Keep uncertain workers in_flight.
            deadline = time.monotonic() + 90
            while active and time.monotonic() < deadline:
                done, _ = wait(active, timeout=min(0.2, max(0, deadline - time.monotonic())),
                    return_when=FIRST_COMPLETED)
                for future in done:
                    case_id = active.pop(future)
                    summary["in_flight_ids"].remove(case_id)
                    try:
                        record = future.result()
                    except BaseException as error:
                        record = {"case_id": case_id, "status": "infrastructure_error",
                            "cleanup_confirmed": False,
                            "infrastructure_error": f"cleanup risk: worker ended with {type(error).__name__}: {error}"}
                    if record is not None:
                        summary["results"].append(record)
                        if record["status"] == "valid":
                            summary["valid_count"] += 1
                        if (record["status"] == "infrastructure_error"
                                and record.get("cleanup_confirmed") is not True):
                            summary["stop_reason"] = "interrupted_cleanup_risk"
                    save()
            if active:
                summary["stop_reason"] = "interrupted_cleanup_risk"
                save()
            executor.shutdown(wait=False, cancel_futures=True)
        else:
            executor.shutdown(wait=True)
    if summary["stop_reason"] is None and len(summary["results"]) != len(items):
        summary["stop_reason"] = "partial"
    save()
    return summary


def report_mode_summaries(
    mode_summary_paths: list[Path | str], *, hourly_rate_usd: float | None = None,
    billable_seconds: dict[int, float] | None = None, output_dir: Path | str | None = None,
) -> Path:
    """Validate three durable summaries and write a comparable M3 report.

    Source files are only read.  A manifest path must be a relative path below
    its summary directory, so a summary cannot make this command inspect an
    unrelated filesystem location.
    """
    if not isinstance(mode_summary_paths, list) or len(mode_summary_paths) != 3:
        raise ValueError("exactly three mode summary paths are required")
    sources = [Path(path).resolve() for path in mode_summary_paths]
    if len(set(sources)) != 3:
        raise ValueError("mode summary paths must be distinct")
    records = [_load_report_record(source) for source in sources]
    # Validate the full comparison before indexing a record by worker count for
    # cost attribution.  This keeps malformed worker values fail-closed.
    summarize_modes([{**record, "cost_usd": None} for record in records])
    _validate_cost_inputs(hourly_rate_usd, billable_seconds)
    if hourly_rate_usd is not None:
        assert billable_seconds is not None
        for record in records:
            workers = record["workers"]
            record["cost_usd"] = hourly_rate_usd * billable_seconds[workers] / 3600
    else:
        for record in records:
            record["cost_usd"] = None

    metrics = summarize_modes(records)
    by_workers = {record["workers"]: record for record in records}
    if output_dir is None:
        output_root = sources[0].parent.parent
    else:
        output_root = Path(output_dir).resolve()
    json_path = output_root / "m3_comparison.json"
    markdown_path = output_root / "m3_comparison.md"
    input_paths = set(sources) | {record["_manifest_path"] for record in records}
    if json_path in input_paths or markdown_path in input_paths:
        raise ValueError("report output would collide with an input summary or manifest")
    if json_path.exists() or markdown_path.exists():
        raise ValueError("report output already exists; choose a new output directory")
    output_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "manifest_hash": records[0]["manifest_hash"],
        "work_count": len(records[0]["case_ids"]),
        "cost_rate_basis": "unavailable" if hourly_rate_usd is None else "hourly_rate_usd * billable_seconds / 3600",
        "modes": [
            {
                **metric,
                "invalid_count": len(by_workers[metric["workers"]]["results"]) - metric["valid_count"],
                "billable_seconds": None if billable_seconds is None else billable_seconds[metric["workers"]],
                "cost_usd": by_workers[metric["workers"]]["cost_usd"],
                "hourly_rate_usd": hourly_rate_usd,
                "source_summary_path": str(by_workers[metric["workers"]]["_source_path"]),
            }
            for metric in metrics
        ],
    }
    base._atomic_write_json(json_path, payload)
    markdown_path.write_text(_markdown_comparison(payload), encoding="utf-8")
    return json_path


def _load_report_record(source: Path) -> dict[str, Any]:
    if not source.is_file():
        raise ValueError(f"mode summary is not a file: {source}")
    try:
        record = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read mode summary: {source}") from error
    if (
        not isinstance(record, dict)
        or record.get("stop_reason") is not None
        or record.get("in_flight_ids", [])
    ):
        raise ValueError("mode summary is partial or invalid")
    manifest_name = record.get("manifest_path")
    if not isinstance(manifest_name, str) or not manifest_name or Path(manifest_name).is_absolute():
        raise ValueError("mode summary must name a relative manifest path")
    manifest_path = (source.parent / manifest_name).resolve()
    try:
        manifest_path.relative_to(source.parent)
    except ValueError as error:
        raise ValueError("manifest path escapes the mode summary directory") from error
    if not manifest_path.is_file():
        raise ValueError("mode manifest is not a file")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        actual_hash = manifest_hash(manifest)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise ValueError("mode manifest is invalid") from error
    if actual_hash != record.get("manifest_hash"):
        raise ValueError("mode manifest digest does not match its summary")
    if actual_hash != _FROZEN_M3_MANIFEST_HASH or manifest != build_manifest(8):
        raise ValueError("mode manifest is not the frozen M3 workload")
    manifest_ids = [item.get("case_id") if isinstance(item, dict) else None for item in manifest]
    if record.get("case_ids") != manifest_ids or record.get("planned_ids") != manifest_ids:
        raise ValueError("mode summary items do not match its manifest")
    manifest_kinds = {item["case_id"]: item["kind"] for item in manifest}
    results = record.get("results")
    if not isinstance(results, list) or any(
        not isinstance(result, dict) or result.get("kind") != manifest_kinds.get(result.get("case_id"))
        for result in results
    ):
        raise ValueError("mode result kinds do not match the frozen manifest")
    record["_source_path"] = source
    record["_manifest_path"] = manifest_path
    return record


def _validate_cost_inputs(hourly_rate_usd: float | None, billable_seconds: dict[int, float] | None) -> None:
    if (hourly_rate_usd is None) != (billable_seconds is None):
        raise ValueError("hourly rate and all billable seconds must be supplied together")
    if hourly_rate_usd is None:
        return
    if isinstance(hourly_rate_usd, bool) or not isinstance(hourly_rate_usd, (int, float)) or not math.isfinite(hourly_rate_usd) or hourly_rate_usd < 0:
        raise ValueError("hourly_rate_usd must be a finite non-negative number")
    if set(billable_seconds or {}) != {1, 2, 4}:
        raise ValueError("billable_seconds must contain workers 1, 2, and 4")
    for workers, seconds in billable_seconds.items():
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError(f"billable seconds for {workers} must be finite and positive")


def _markdown_comparison(payload: dict[str, Any]) -> str:
    lines = [
        "# M3 fixed replay comparison",
        "",
        f"Manifest: `{payload['manifest_hash']}`; work items: {payload['work_count']}; cost basis: {payload['cost_rate_basis']}.",
        "",
        "| Workers | Valid | Invalid | Elapsed (s) | Throughput/hour | Speedup | Efficiency | Billable (s) | Cost (USD) | Cost/valid | Nominal outcomes | Mask outcomes | Drift |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for mode in payload["modes"]:
        cost = "unavailable" if mode["cost_usd"] is None else f"{mode['cost_usd']:.6f}"
        cost_per_valid = "unavailable" if mode["cost_per_valid"] is None else f"{mode['cost_per_valid']:.6f}"
        billable = "unavailable" if mode["billable_seconds"] is None else f"{mode['billable_seconds']:.3f}"
        drift = ", ".join(mode["drift_case_ids"]) or "none"
        nominal = _format_outcomes(mode["outcome_counts"].get("nominal", {}))
        mask = _format_outcomes(mode["outcome_counts"].get("mask", {}))
        lines.append(
            f"| {mode['workers']} | {mode['valid_count']} | {mode['invalid_count']} | {mode['elapsed_seconds']:.3f} | "
            f"{mode['throughput_per_hour']:.3f} | {mode['speedup']:.3f} | {mode['efficiency']:.3f} | {billable} | {cost} | {cost_per_valid} | {nominal} | {mask} | {drift} |"
        )
    return "\n".join(lines) + "\n"


def _format_outcomes(counts: dict[str, int]) -> str:
    return f"success={counts.get('success', 0)}, policy_failure={counts.get('policy_failure', 0)}"


def _parse_billable_seconds(value: str) -> tuple[int, float]:
    try:
        workers_text, seconds_text = value.split("=", 1)
        workers = int(workers_text)
        seconds = float(seconds_text)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError("billable seconds must be WORKERS=SECONDS") from error
    return workers, seconds


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        report_parser = argparse.ArgumentParser(description="Validate and compare three complete M3 replay modes.")
        report_parser.add_argument("--mode-summary", required=True, action="append", type=Path)
        report_parser.add_argument("--output-dir", type=Path)
        report_parser.add_argument("--hourly-rate-usd", type=float)
        report_parser.add_argument("--billable-seconds", action="append", type=_parse_billable_seconds)
        report_args = report_parser.parse_args(sys.argv[2:])
        billable = None
        if report_args.billable_seconds is not None:
            billable = {}
            for workers, seconds in report_args.billable_seconds:
                if workers in billable:
                    report_parser.error("billable seconds may name each worker count only once")
                billable[workers] = seconds
        try:
            report_path = report_mode_summaries(
                report_args.mode_summary, hourly_rate_usd=report_args.hourly_rate_usd,
                billable_seconds=billable, output_dir=report_args.output_dir,
            )
        except ValueError as error:
            report_parser.error(str(error))
        print(f"comparison: {report_path}")
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-root", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--results-root", required=True, type=Path)
    parser.add_argument("--workers", required=True, type=int, choices=(1, 2, 4))
    parser.add_argument("--launch-cutoff-seconds", required=True, type=float)
    parser.add_argument("--item-timeout-seconds", required=True, type=float)
    args = parser.parse_args()
    interrupt_event = threading.Event()
    previous_handlers = {}
    if os.name == "posix" and threading.current_thread() is threading.main_thread():
        def request_interrupt(signum: int, frame: Any) -> None:
            interrupt_event.set()
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.signal(signum, request_interrupt)
    try:
        summary = run_mode(**vars(args), interrupt_event=interrupt_event)
    finally:
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)
    path = args.results_root.resolve() / f"m3-workers-{args.workers}" / "session_summary.json"
    print(f"summary: {path} | stop: {summary['stop_reason'] or 'complete'} | valid: {summary['valid_count']}/{len(summary['planned_ids'])} | attempts: {len(summary['results'])}")
    if summary["stop_reason"] is not None or summary["valid_count"] != len(summary["planned_ids"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
