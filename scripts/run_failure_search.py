"""Run the accepted, bounded first-failure search through the evaluator CLI."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path, PureWindowsPath
import subprocess
import sys
import time
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Union


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from robot_debug.session import EpisodeResult, classify_aggregate, is_reproducible, should_launch_next


SESSION_DIRECTORY_NAME = "first-failure-search"
SWEEP_SIDES = (0.25, 0.30, 0.35, 0.40, 0.45, 0.50)
NOMINAL_EPISODE_INDICES = tuple(range(20))


def _resolve_evaluator_command(interpreter: Path) -> str:
    """Prefer the evaluator installed beside the active Python interpreter."""

    sibling = Path(interpreter).with_name("vla-eval")
    if sibling.is_file():
        return str(sibling)
    return "vla-eval"


@dataclass(frozen=True)
class StageResult:
    """The parsed evidence, or a durable infrastructure error, for one stage."""

    results: Sequence[EpisodeResult]
    infrastructure_error: Optional[str] = None
    invalid_evidence: Optional[str] = None


def run_session(
    *,
    upstream_root: Union[Path, str],
    project_root: Union[Path, str],
    results_root: Union[Path, str],
    launch_cutoff_seconds: float = 1560,
    command_runner: Callable[..., Any] = subprocess.run,
    monotonic_clock: Callable[[], float] = time.monotonic,
) -> Dict[str, Any]:
    """Launch the bounded search and return its atomically persisted summary."""

    started_at = monotonic_clock()
    should_launch_next(0.0, launch_cutoff_seconds)
    upstream_root = Path(upstream_root).resolve()
    project_root = Path(project_root).resolve()
    session_dir = _prepare_session_directory(Path(results_root).resolve())
    configs_dir = session_dir / "configs"
    configs_dir.mkdir()

    summary: Dict[str, Any] = {
        "planned": {
            "nominal_episode_indices": list(NOMINAL_EPISODE_INDICES),
            "sweep_sides": list(SWEEP_SIDES),
            "replays_per_failure": 5,
            "launch_cutoff_seconds": launch_cutoff_seconds,
        },
        "completed": {"stages": [], "nominal_successes": 0, "replay_outcomes": []},
        "outcomes": [],
        "elapsed_seconds": 0.0,
        "stop_reason": None,
        "reproducible": None,
    }

    def elapsed() -> float:
        return monotonic_clock() - started_at

    def save(stop_reason: Optional[str] = None) -> None:
        if stop_reason is not None:
            summary["stop_reason"] = stop_reason
        summary["elapsed_seconds"] = elapsed()
        _atomic_write_json(session_dir / "session_summary.json", summary)

    def launch(
        stage_name: str, *, episode_indices: Sequence[int], side: Optional[float]
    ) -> Optional[StageResult]:
        if not should_launch_next(elapsed(), launch_cutoff_seconds):
            save("launch_cutoff_reached")
            return None
        output_dir = session_dir / "runs" / stage_name
        config_path = configs_dir / (stage_name + ".yaml")
        _write_config(
            config_path=config_path,
            output_dir=output_dir,
            project_root=project_root,
            stage_name=stage_name,
            episode_indices=episode_indices,
            side=side,
        )
        try:
            completed_process = command_runner(
                [
                    _resolve_evaluator_command(Path(sys.executable)),
                    "run",
                    "--config",
                    str(config_path),
                ],
                cwd=upstream_root,
                check=False,
            )
        except Exception as error:
            return record_stage(
                stage_name, episode_indices, (), "command_runner: {}".format(error)
            )
        returncode = getattr(completed_process, "returncode", 0)
        if returncode not in (0, None):
            return record_stage(
                stage_name,
                episode_indices,
                (),
                "evaluator returned nonzero status {}".format(returncode),
                returncode=returncode,
            )
        try:
            results = _load_stage_results(output_dir, expected_count=len(episode_indices))
        except Exception as error:
            return record_stage(
                stage_name,
                episode_indices,
                (),
                "aggregate evidence error: {}: {}".format(
                    type(error).__name__, error
                ),
                returncode=returncode,
            )
        if not any(result.outcome == "infrastructure_error" for result in results):
            actual_indices = tuple(result.episode_index for result in results)
            if actual_indices != tuple(episode_indices):
                return record_stage(
                    stage_name,
                    episode_indices,
                    results,
                    invalid_evidence="aggregate episode indices do not match stage plan",
                    returncode=returncode,
                )
        return record_stage(
            stage_name, episode_indices, results, returncode=returncode
        )

    def record_stage(
        stage_name: str,
        episode_indices: Sequence[int],
        results: Sequence[EpisodeResult],
        infrastructure_error: Optional[str] = None,
        invalid_evidence: Optional[str] = None,
        *,
        returncode: Optional[int] = None,
    ) -> StageResult:
        summary["completed"]["stages"].append(
            {
                "stage": stage_name,
                "planned_episode_indices": list(episode_indices),
                "completed_episodes": len(results),
                "status": (
                    "infrastructure_error"
                    if infrastructure_error is not None
                    else "invalid_evidence" if invalid_evidence is not None else "completed"
                ),
                "infrastructure_error": infrastructure_error,
                "invalid_evidence": invalid_evidence,
                "returncode": returncode,
            }
        )
        summary["outcomes"].extend(
            {"stage": stage_name, **asdict(result)} for result in results
        )
        save()
        return StageResult(
            results=results,
            infrastructure_error=infrastructure_error,
            invalid_evidence=invalid_evidence,
        )

    nominal_stage = launch(
        "nominal", episode_indices=NOMINAL_EPISODE_INDICES, side=None
    )
    if nominal_stage is None:
        return summary
    if nominal_stage.infrastructure_error is not None:
        save("nominal_infrastructure_error")
        return summary
    nominal = nominal_stage.results
    summary["completed"]["nominal_successes"] = sum(result.success for result in nominal)
    save()
    if nominal_stage.invalid_evidence is not None:
        save("nominal_invalid_evidence")
        return summary
    if any(result.outcome == "infrastructure_error" for result in nominal):
        save("nominal_infrastructure_error")
        return summary
    if summary["completed"]["nominal_successes"] < 16:
        save("nominal_success_gate_failed")
        return summary

    for side in SWEEP_SIDES:
        stage_name = "sweep-{:.2f}".format(side)
        sweep_stage = launch(stage_name, episode_indices=(0,), side=side)
        if sweep_stage is None:
            return summary
        if sweep_stage.infrastructure_error is not None:
            save("sweep_infrastructure_error")
            return summary
        if sweep_stage.invalid_evidence is not None:
            save("sweep_invalid_evidence")
            return summary
        result = sweep_stage.results[0]
        if result.outcome == "infrastructure_error":
            save("sweep_infrastructure_error")
            return summary
        if result.outcome != "policy_failure":
            continue

        replay_outcomes = []
        for replay_index in range(1, 6):
            replay_stage = launch(
                "replay-{}".format(replay_index), episode_indices=(0,), side=side
            )
            if replay_stage is None:
                return summary
            if replay_stage.infrastructure_error is not None:
                save("replay_infrastructure_error")
                return summary
            if replay_stage.invalid_evidence is not None:
                save("replay_invalid_evidence")
                return summary
            replay_result = replay_stage.results[0]
            replay_outcomes.append(replay_result.outcome)
            summary["completed"]["replay_outcomes"] = replay_outcomes
            if replay_result.outcome == "infrastructure_error":
                save("replay_infrastructure_error")
                return summary
            save()

        summary["reproducible"] = is_reproducible(replay_outcomes)
        save(
            "reproducible_policy_failure"
            if summary["reproducible"]
            else "policy_failure_not_reproducible"
        )
        return summary

    save("no_policy_failure_in_sweep")
    return summary


def _prepare_session_directory(
    results_root: Path, *, session_directory_name: str = SESSION_DIRECTORY_NAME
) -> Path:
    if not isinstance(session_directory_name, str) or not session_directory_name:
        raise ValueError("session directory must be a single directory name")
    session_directory = Path(session_directory_name)
    if (
        session_directory.drive
        or PureWindowsPath(session_directory_name).drive
        or len(PureWindowsPath(session_directory_name).parts) != 1
        or session_directory.is_absolute()
        or len(session_directory.parts) != 1
        or session_directory_name in (".", "..")
    ):
        raise ValueError("session directory must be a single directory name")
    results_root.mkdir(parents=True, exist_ok=True)
    resolved_results_root = results_root.resolve()
    session_dir = resolved_results_root / session_directory
    if session_dir.is_symlink():
        raise ValueError("refusing symlinked session directory: {}".format(session_dir))
    if session_dir.exists():
        if not session_dir.is_dir() or any(session_dir.iterdir()):
            raise ValueError("refusing nonempty session directory: {}".format(session_dir))
    else:
        session_dir.mkdir()
    resolved_session_dir = session_dir.resolve()
    try:
        resolved_session_dir.relative_to(resolved_results_root)
    except ValueError as error:
        raise ValueError("session directory escapes results root") from error
    return resolved_session_dir


def _load_stage_results(output_dir: Path, *, expected_count: int) -> list[EpisodeResult]:
    aggregate_paths = sorted(output_dir.rglob("*_aggregate.json"))
    if len(aggregate_paths) != 1:
        raise ValueError("expected exactly one aggregate in {}".format(output_dir))
    aggregate = json.loads(
        aggregate_paths[0].read_text(encoding="utf-8"),
        parse_constant=_reject_json_constant,
    )
    tasks = aggregate.get("tasks") if isinstance(aggregate, Mapping) else None
    if not isinstance(tasks, list) or len(tasks) != 1 or not isinstance(tasks[0], Mapping):
        raise ValueError("aggregate must contain exactly one task")
    episodes = tasks[0].get("episodes")
    if not isinstance(episodes, list) or len(episodes) != expected_count:
        raise ValueError("aggregate episode count does not match stage plan")
    return [classify_aggregate({"tasks": [{"episodes": [raw]}]}) for raw in episodes]


def _reject_json_constant(value: str) -> None:
    raise ValueError("non-standard JSON constant: {}".format(value))


def _write_config(
    *,
    config_path: Path,
    output_dir: Path,
    project_root: Path,
    stage_name: str,
    episode_indices: Sequence[int],
    task_id: int = 0,
    seed: int = 7,
    side: Optional[float] = None,
    x: Optional[float] = None,
    y: Optional[float] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
) -> None:
    for name, value in (("task_id", task_id), ("seed", seed)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("{} must be a nonnegative integer".format(name))
    params = [
        "      suite: libero_object",
        "      seed: {}".format(seed),
        "      env_seed: {}".format(seed),
        "      num_steps_wait: 10",
    ]
    if task_id != 0:
        params.append("      task_id: {}".format(task_id))
    if side is not None:
        if width is not None or height is not None:
            raise ValueError("side cannot be combined with width or height")
        _validate_finite_number("side", side)
        if side <= 0:
            raise ValueError("side must be greater than zero")
        if (x is None) != (y is None):
            raise ValueError("x and y must be supplied together")
        if x is None:
            x = (1.0 - side) / 2.0
            y = x
        else:
            _validate_finite_number("x", x)
            _validate_finite_number("y", y)
        width = side
        height = side
    elif width is None and height is None:
        if x is not None or y is not None:
            raise ValueError("x and y require an enabled occlusion")
    else:
        if width is None or height is None:
            raise ValueError("width and height must be supplied together")
        if x is None or y is None:
            raise ValueError("rectangular occlusion requires x and y")
        _validate_finite_number("width", width)
        _validate_finite_number("height", height)
        _validate_finite_number("x", x)
        _validate_finite_number("y", y)
        if width <= 0 or height <= 0:
            raise ValueError("width and height must be greater than zero")
    if width is not None and height is not None:
        if x < 0 or y < 0 or x + width > 1 or y + height > 1:
            raise ValueError("occlusion must remain within image bounds")
        params.extend(
            [
                "      agentview_occlusion:",
                "        enabled: true",
                "        x: {:.6f}".format(x),
                "        y: {:.6f}".format(y),
                "        width: {:.6f}".format(width),
                "        height: {:.6f}".format(height),
                "        color: [0, 0, 0]",
                "        opacity: 1.0",
            ]
        )
    text = "\n".join(
        [
            "# Generated bounded failure-search stage: {}".format(stage_name),
            'server:',
            '  url: "ws://localhost:8000"',
            "docker:",
            '  image: "ghcr.io/allenai/vla-evaluation-harness/libero@sha256:d0c45bc5a3720d569180e6b8dd92510da895f16c3cc509ccc76e4b4ffbb9e0f0"',
            "  user: root",
            "  volumes:",
            "    - {}".format(
                _yaml_scalar("{}:/workspace/robot-debug-src:ro".format(project_root / "src"))
            ),
            "  env:",
            "    - PYTHONPATH=/workspace/robot-debug-src:/workspace/src",
            "output_dir: {}".format(_yaml_scalar(output_dir)),
            "render: gpu",
            "benchmarks:",
            "  - name: {}".format(stage_name),
            "    benchmark: \"robot_debug.libero:DiagnosticLIBEROBenchmark\"",
            "    mode: sync",
            "    episodes_per_task: {}".format(len(episode_indices)),
            "    max_tasks: 1",
            "    paced: false",
            "    throughput_mode: false",
            "    recording:",
            "      record_video: true",
            "      record_step: true",
            "      video_fps: 20",
            "    params:",
            *params,
            "",
        ]
    )
    config_path.write_text(text, encoding="utf-8")


def _validate_finite_number(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("{} must be a finite number".format(name))
    if not math.isfinite(value):
        raise ValueError("{} must be a finite number".format(name))


def _yaml_scalar(value: Any) -> str:
    """Return a JSON-style double-quoted scalar, valid in YAML 1.2."""

    return json.dumps(str(value), ensure_ascii=True)


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary_path = path.with_name(path.name + ".tmp")
    temporary_path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8"
    )
    os.replace(temporary_path, path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-root", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--results-root", required=True, type=Path)
    parser.add_argument("--launch-cutoff-seconds", type=float, default=1560)
    arguments = parser.parse_args()
    run_session(**vars(arguments))


if __name__ == "__main__":
    main()
