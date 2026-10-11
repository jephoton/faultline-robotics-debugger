"""Injectable orchestration for one finite, closed-evidence workload."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import time
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

import yaml

from robot_debug.job_process import InfrastructureError
from robot_debug.job_runtime import JobRuntimeError, export_closed_evidence, validate_workload_config
from robot_debug.viewer.catalog import ArtifactCatalog
from scripts import run_failure_reduction, run_failure_search, run_position_grid_search


_CLEANUP_RESERVE_SECONDS = 14.0
# M4's certified reduced rectangle; the m5b mode re-runs it from the benchmark start.
CERTIFIED_M4_RECTANGLE = {"x": 0.625, "y": 0.0, "width": 0.375, "height": 0.375}
_MAX_EXTERNAL_RESET_BYTES = 512 * 1024


def _load_external_reset(source: object, destination: Path) -> Path:
    """Decode the injected gzip candidate, verify its pinned hashes and store it privately."""
    import gzip

    from robot_debug.external_reset import validate_external_reset

    if not isinstance(source, Path) or not source.is_file() or source.is_symlink():
        _fail("external reset candidate is missing")
    try:
        with gzip.open(str(source), "rb") as stream:
            data = stream.read(_MAX_EXTERNAL_RESET_BYTES + 1)
    except OSError as error:
        raise JobRuntimeError("external reset candidate is not gzip data") from error
    if len(data) > _MAX_EXTERNAL_RESET_BYTES:
        _fail("external reset candidate is too large")
    try:
        candidate = validate_external_reset(json.loads(data.decode("utf-8")))
    except (ValueError, UnicodeError) as error:
        raise JobRuntimeError("external reset candidate failed validation") from error
    destination.mkdir(mode=0o700)
    path = destination / "candidate.json"
    with path.open("x", encoding="utf-8") as handle:
        json.dump(candidate, handle, sort_keys=True)
    return path


@dataclass(frozen=True)
class WorkloadPaths:
    project_root: Path
    upstream_root: Path
    work_root: Path
    export_root: Path


def _fail(message: str) -> None:
    raise JobRuntimeError(message)


def _ordinary_root(value: object, label: str) -> Path:
    if isinstance(value, bytes):
        _fail("{} must be a filesystem path".format(label))
    try:
        path = Path(os.fspath(value))  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise JobRuntimeError("{} must be a filesystem path".format(label)) from error
    if not path.is_absolute():
        path = Path.cwd() / path
    current = path
    chain = []
    while True:
        if current.exists() or current.is_symlink():
            chain.append(current)
        if current.parent == current:
            break
        current = current.parent
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    for component in reversed(chain):
        try:
            info = component.lstat()
        except OSError as error:
            raise JobRuntimeError("{} could not be inspected".format(label)) from error
        if stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & reparse):
            _fail("{} must not contain links or reparse points".format(label))
    if not path.is_dir():
        _fail("{} must be an existing directory".format(label))
    try:
        return path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise JobRuntimeError("{} could not be resolved".format(label)) from error


def _validated_paths(paths: object) -> WorkloadPaths:
    if not isinstance(paths, WorkloadPaths):
        _fail("paths must be a WorkloadPaths value")
    validated = WorkloadPaths(
        _ordinary_root(paths.project_root, "project_root"),
        _ordinary_root(paths.upstream_root, "upstream_root"),
        _ordinary_root(paths.work_root, "work_root"),
        _ordinary_root(paths.export_root, "export_root"),
    )
    if (
        validated.work_root == validated.export_root
        or validated.work_root in validated.export_root.parents
        or validated.export_root in validated.work_root.parents
    ):
        _fail("work and export roots must not overlap")
    return validated


def _write_summary(run_root: Path, summary: Mapping[str, Any]) -> None:
    target = run_root / "workload_summary.json"
    temporary = run_root / ".workload_summary.json.tmp"
    payload = json.dumps(summary, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, target)


def _episode_key(episode: Any) -> Tuple[int, int]:
    return int(episode.task_id), int(episode.episode_index)


def _validate_generated_evidence(config_path: Path, run_root: Path) -> Sequence[Any]:
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, Mapping):
            raise ValueError("configuration is not a mapping")
        output_value = loaded["output_dir"]
        if not isinstance(output_value, str):
            raise ValueError("output_dir is not a string")
        output_dir = Path(output_value).resolve(strict=True)
        output_dir.relative_to(run_root)
        benchmarks = loaded["benchmarks"]
        expected_count = benchmarks[0]["episodes_per_task"]
        if type(expected_count) is not int or expected_count <= 0:
            raise ValueError("episode count is invalid")
        params = benchmarks[0].get("params", {})
        if not isinstance(params, Mapping):
            raise ValueError("benchmark params are invalid")
        requested_task_id = params.get("task_id", 0)
        if type(requested_task_id) is not int or requested_task_id < 0:
            raise ValueError("requested task identity is invalid")
        requested_keys = {
            (requested_task_id, episode_index)
            for episode_index in range(expected_count)
        }
        results = run_failure_search._load_stage_results(
            output_dir, expected_count=expected_count
        )
        aggregate_paths = sorted(output_dir.rglob("*_aggregate.json"))
        aggregate = json.loads(aggregate_paths[0].read_text(encoding="utf-8"))
        raw_episodes = aggregate["tasks"][0]["episodes"]
        aggregate_keys = []
        for item in raw_episodes:
            task_id = item["task_id"]
            episode_index = item.get("episode_idx", item.get("episode_id"))
            if (
                type(task_id) is not int
                or type(episode_index) is not int
                or task_id < 0
                or episode_index < 0
            ):
                raise ValueError("aggregate episode identity is invalid")
            aggregate_keys.append((task_id, episode_index))
        if len(set(aggregate_keys)) != expected_count or set(aggregate_keys) != requested_keys:
            raise ValueError("aggregate identities do not match the requested episodes")
        snapshot = ArtifactCatalog(output_dir).snapshot()
        if snapshot.warnings:
            raise ValueError("artifact catalog reported warnings")
        catalog = {_episode_key(item): item for item in snapshot.episodes}
        if set(catalog) != requested_keys:
            raise ValueError("catalog episodes do not match the requested episodes")
        for key in requested_keys:
            item = catalog[key]
            if item.video_path is None or item.trace_path is None:
                raise ValueError("episode media is incomplete")
            for relative in (item.video_path, item.trace_path):
                media = (output_dir / relative).resolve(strict=True)
                media.relative_to(output_dir)
                if not media.is_file() or media.stat().st_size <= 0:
                    raise ValueError("episode media is empty")
        return results
    except (OSError, RuntimeError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise InfrastructureError("generated evidence is invalid") from error


def _driver_reason(summary: object) -> Optional[str]:
    if not isinstance(summary, Mapping):
        return "workload_failed"
    invalid_stops = {
        "invalid_evidence",
        "nominal_invalid_evidence",
        "sweep_invalid_evidence",
        "replay_invalid_evidence",
        "grid_invalid_evidence",
        "control_invalid_evidence",
    }
    infrastructure_stops = {
        "infrastructure_error",
        "nominal_infrastructure_error",
        "sweep_infrastructure_error",
        "replay_infrastructure_error",
        "grid_infrastructure_error",
        "control_infrastructure_error",
    }
    stop_reason = summary.get("stop_reason")
    if isinstance(stop_reason, str) and stop_reason in invalid_stops:
        return "invalid_evidence"
    if isinstance(stop_reason, str) and stop_reason in infrastructure_stops:
        return "evaluator_failed"
    if stop_reason == "launch_cutoff_reached":
        return "deadline_exhausted"
    completed = summary.get("completed")
    stages = completed.get("stages", ()) if isinstance(completed, Mapping) else ()
    if isinstance(stages, Sequence) and not isinstance(stages, (str, bytes)):
        for stage in stages:
            if not isinstance(stage, Mapping):
                continue
            if stage.get("status") == "invalid_evidence" or stage.get("invalid_evidence") is not None:
                return "invalid_evidence"
            if stage.get("status") == "infrastructure_error" or stage.get("infrastructure_error") is not None:
                return "evaluator_failed"
    outcomes = summary.get("outcomes", ())
    if isinstance(outcomes, Sequence) and not isinstance(outcomes, (str, bytes)):
        for outcome in outcomes:
            if isinstance(outcome, Mapping) and outcome.get("outcome") == "infrastructure_error":
                return "evaluator_failed"
    return None


def run_workload(
    config: object,
    *,
    paths: WorkloadPaths,
    model_factory: Callable[..., Any],
    evaluator_factory: Callable[..., Callable[..., Any]],
    exporter: Callable[..., Dict[str, Any]] = export_closed_evidence,
    clock: Callable[[], float] = time.monotonic,
    absolute_deadline: Optional[float] = None,
    external_reset_source: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run one workload while keeping process and cloud mechanics injectable."""

    accepted = validate_workload_config(config)
    if absolute_deadline is not None:
        if type(absolute_deadline) not in (int, float):
            _fail("absolute_deadline must be a finite number")
        try:
            absolute_deadline = float(absolute_deadline)
        except OverflowError as error:
            raise JobRuntimeError("absolute_deadline must be a finite number") from error
        if not math.isfinite(absolute_deadline):
            _fail("absolute_deadline must be a finite number")
    roots = _validated_paths(paths)
    run_id = accepted["run_id"]
    run_root = roots.work_root / run_id
    destination = roots.export_root / run_id
    if run_root.exists() or run_root.is_symlink() or destination.exists() or destination.is_symlink():
        _fail("workload run and export destinations must be new")
    try:
        run_root.mkdir(mode=0o700)
    except FileExistsError as error:
        raise JobRuntimeError("workload run destination must be new") from error

    started = clock()
    duration_deadline = started + float(accepted["deadline_seconds"])
    deadline = duration_deadline if absolute_deadline is None else min(duration_deadline, absolute_deadline)
    launch_deadline = deadline - _CLEANUP_RESERVE_SECONDS
    reason = "completed"
    status = "complete"
    pilot_outcomes = []
    model = None
    interrupted = False
    cleanup_confirmed = True
    latch: Dict[str, Optional[str]] = {"reason": None}

    def remaining() -> float:
        return launch_deadline - clock()

    def latch_failure(code: str) -> None:
        if latch["reason"] is None:
            latch["reason"] = code

    external_candidate = None
    reduction_stop_reason = None
    grid_summary: Optional[Dict[str, Any]] = None
    try:
        if accepted["mode"] in ("m5b", "m5b-grid"):
            try:
                external_candidate = _load_external_reset(
                    external_reset_source, run_root / "external-reset")
            except JobRuntimeError:
                reason, status = "external_reset_invalid", "partial"
        if reason != "completed":
            pass
        elif remaining() <= 0:
            reason, status = "deadline_exhausted", "partial"
        else:
            try:
                model = model_factory(log_root=run_root / "logs")
            except Exception:
                reason, status = "model_start_failed", "partial"
            if reason == "completed":
                if remaining() <= 0:
                    reason, status = "deadline_exhausted", "partial"
                else:
                    try:
                        model.start()
                    except Exception:
                        reason, status = "model_start_failed", "partial"
            if reason == "completed":
                try:
                    model.wait_ready(deadline=launch_deadline)
                except Exception:
                    reason, status = "readiness_failed", "partial"
            if reason == "completed":
                if remaining() <= 0:
                    reason, status = "deadline_exhausted", "partial"
                else:
                    try:
                        model.check_alive()
                    except Exception:
                        reason, status = "model_died", "partial"
            def bounded_runner(command: Sequence[str], *, cwd: object, check: bool = False) -> Any:
                nonlocal cleanup_confirmed
                if latch["reason"] is not None:
                    raise InfrastructureError("workload infrastructure failure is latched")
                if remaining() <= 0:
                    latch_failure("deadline_exhausted")
                    raise InfrastructureError("launch deadline exhausted")
                try:
                    model.check_alive()
                except Exception as error:
                    latch_failure("model_died")
                    raise InfrastructureError("model is not alive") from error
                remaining_after_liveness = remaining()
                if remaining_after_liveness <= 0:
                    latch_failure("deadline_exhausted")
                    raise InfrastructureError("launch deadline exhausted")
                remaining_at_factory = remaining()
                if remaining_at_factory <= 0:
                    latch_failure("deadline_exhausted")
                    raise InfrastructureError("launch deadline exhausted")
                try:
                    command_runner = evaluator_factory(
                        timeout_seconds=remaining_at_factory,
                        log_root=run_root / "logs",
                    )
                except KeyboardInterrupt:
                    raise
                except Exception as error:
                    latch_failure("evaluator_failed")
                    raise InfrastructureError("evaluator setup failed") from error
                try:
                    model.check_alive()
                except Exception as error:
                    latch_failure("model_died")
                    raise InfrastructureError("model died before evaluation") from error
                if remaining() <= 0:
                    latch_failure("deadline_exhausted")
                    raise InfrastructureError("launch deadline exhausted")
                try:
                    completed = command_runner(command, cwd=roots.upstream_root, check=False)
                except KeyboardInterrupt:
                    raise
                except subprocess.TimeoutExpired as error:
                    latch_failure("evaluator_failed")
                    raise InfrastructureError("evaluator timed out") from error
                except InfrastructureError as error:
                    cleanup_confirmed = False
                    latch_failure("cleanup_unconfirmed")
                    raise InfrastructureError("evaluator cleanup is unconfirmed") from error
                except BaseException as error:
                    cleanup_confirmed = False
                    latch_failure("cleanup_unconfirmed")
                    raise InfrastructureError("evaluator cleanup is unconfirmed") from error
                try:
                    model.check_alive()
                except Exception as error:
                    latch_failure("model_died")
                    raise InfrastructureError("model died during evaluation") from error
                if remaining() <= 0:
                    latch_failure("deadline_exhausted")
                    raise InfrastructureError("launch deadline exhausted")
                if getattr(completed, "returncode", 0) not in (0, None):
                    latch_failure("evaluator_failed")
                    raise InfrastructureError("evaluator returned nonzero")
                try:
                    config_path = Path(command[-1])
                    results = _validate_generated_evidence(config_path, run_root)
                except Exception as error:
                    latch_failure("invalid_evidence")
                    raise InfrastructureError("evidence validation failed") from error
                if any(item.outcome == "infrastructure_error" for item in results):
                    latch_failure("evaluator_failed")
                    raise InfrastructureError("aggregate reports infrastructure failure")
                return completed

            if reason == "completed":
                mode = accepted["mode"]
                if mode in ("pilot", "m5b"):
                    configs = run_root / mode / "configs"
                    configs.mkdir(parents=True)
                    if mode == "pilot":
                        specifications = (
                            ("nominal", {}),
                            ("masked", {"x": 0.5, "y": 0.0, "width": 0.375, "height": 0.375}),
                        )
                    else:
                        specifications = (("certified-m4", dict(CERTIFIED_M4_RECTANGLE)),)
                    for stage, geometry in specifications:
                        if latch["reason"] is not None:
                            break
                        output = run_root / mode / "runs" / stage
                        config_path = configs / (stage + ".yaml")
                        run_failure_search._write_config(
                            config_path=config_path,
                            output_dir=output,
                            project_root=roots.project_root,
                            stage_name=stage,
                            episode_indices=(0,),
                            task_id=0,
                            seed=7,
                            **geometry
                        )
                        try:
                            bounded_runner(
                                ["vla-eval", "run", "--config", str(config_path)],
                                cwd=roots.upstream_root,
                                check=False,
                            )
                        except InfrastructureError:
                            break
                        result = run_failure_search._load_stage_results(output, expected_count=1)[0]
                        pilot_outcomes.append(
                            {
                                "stage": stage,
                                "success": result.success,
                                "steps": result.steps,
                                "elapsed_seconds": result.elapsed_seconds,
                                "episode_index": result.episode_index,
                                "outcome": result.outcome,
                            }
                        )
                    if mode == "m5b" and latch["reason"] is None:
                        driver_summary = run_failure_reduction.run_session(
                            upstream_root=roots.upstream_root,
                            project_root=roots.project_root,
                            results_root=run_root / "m5b" / "external",
                            launch_cutoff_seconds=max(0.0, remaining()),
                            command_runner=bounded_runner,
                            monotonic_clock=clock,
                            external_reset_candidate=external_candidate,
                        )
                        reduction_stop_reason = driver_summary.get("stop_reason")
                        driver_failure = _driver_reason(driver_summary)
                        if driver_failure is not None:
                            latch_failure(driver_failure)
                elif mode == "m5b-grid":
                    # Find a failing position from the external start, then shrink
                    # it from the same start only if the grid confirmed it.
                    grid_summary = run_position_grid_search.run_session(
                        upstream_root=roots.upstream_root,
                        project_root=roots.project_root,
                        results_root=run_root / "m5b-grid" / "grid",
                        launch_cutoff_seconds=max(0.0, remaining()),
                        command_runner=bounded_runner,
                        monotonic_clock=clock,
                        external_reset_candidate=external_candidate,
                    )
                    driver_failure = _driver_reason(grid_summary)
                    if driver_failure is not None:
                        latch_failure(driver_failure)
                    elif (grid_summary.get("stop_reason") == "reproducible_failure_with_nominal_controls"
                          and latch["reason"] is None):
                        found = grid_summary["confirmed_failure"]
                        driver_summary = run_failure_reduction.run_session(
                            upstream_root=roots.upstream_root,
                            project_root=roots.project_root,
                            results_root=run_root / "m5b-grid" / "reduce",
                            launch_cutoff_seconds=max(0.0, remaining()),
                            command_runner=bounded_runner,
                            monotonic_clock=clock,
                            external_reset_candidate=external_candidate,
                            parent_rectangle={key: found[key] for key in ("x", "y", "width", "height")},
                        )
                        reduction_stop_reason = driver_summary.get("stop_reason")
                        driver_failure = _driver_reason(driver_summary)
                        if driver_failure is not None:
                            latch_failure(driver_failure)
                else:
                    drivers = {
                        "search": run_failure_search.run_session,
                        "grid": run_position_grid_search.run_session,
                        "reduce": run_failure_reduction.run_session,
                    }
                    driver_summary = drivers[mode](
                        upstream_root=roots.upstream_root,
                        project_root=roots.project_root,
                        results_root=run_root,
                        launch_cutoff_seconds=max(0.0, remaining()),
                        command_runner=bounded_runner,
                        monotonic_clock=clock,
                    )
                    driver_failure = _driver_reason(driver_summary)
                    if driver_failure is not None:
                        latch_failure(driver_failure)
            if latch["reason"] is not None:
                reason, status = str(latch["reason"]), "partial"
    except KeyboardInterrupt:
        interrupted = True
        reason, status = "interrupted", "partial"
    except Exception:
        reason, status = "workload_failed", "partial"
    finally:
        if model is not None:
            try:
                model.close()
            except KeyboardInterrupt:
                interrupted = True
                cleanup_confirmed = False
            except BaseException:
                cleanup_confirmed = False

    if not cleanup_confirmed:
        reason, status = "cleanup_unconfirmed", "partial"
    elapsed = max(0.0, clock() - started)
    summary: Dict[str, Any] = {
        "schema_version": 1,
        "backend": "nebius-serverless",
        "mode": accepted["mode"],
        "run_id": run_id,
        "status": status,
        "stop_reason": reason,
        "elapsed_seconds": elapsed,
    }
    if pilot_outcomes:
        summary["pilot_outcomes"] = pilot_outcomes
    if accepted["mode"] in ("m5b", "m5b-grid"):
        summary["reduction_stop_reason"] = reduction_stop_reason
    if grid_summary is not None:
        summary["grid_stop_reason"] = grid_summary.get("stop_reason")
        found = grid_summary.get("confirmed_failure")
        summary["grid_failure_rectangle"] = None if not found else {
            key: found[key] for key in ("x", "y", "width", "height")}
        summary["grid_rejected_failures"] = len(grid_summary.get("rejected_failures") or [])
    _write_summary(run_root, summary)
    if cleanup_confirmed:
        exporter(
            run_root,
            destination,
            status=status,
            cleanup_confirmed=True,
        )
    if interrupted:
        raise KeyboardInterrupt
    return summary


__all__ = ["WorkloadPaths", "run_workload"]
