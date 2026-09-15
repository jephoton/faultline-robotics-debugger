"""Run the approved fixed-area position-grid failure search."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable, Dict, Optional, Sequence, Union


SCRIPTS_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

import run_failure_search as base


SESSION_DIRECTORY_NAME = "position-grid-search"
GRID_SIDE = 0.50
EPISODE_INDEX = 0
REPLAYS_PER_FAILURE = 5
MATCHED_NOMINAL_CONTROLS = 5


@dataclass(frozen=True)
class GridPoint:
    stage: str
    x: float
    y: float


GRID_POINTS = (
    GridPoint("grid-x000-y050", 0.00, 0.50),
    GridPoint("grid-x050-y050", 0.50, 0.50),
    GridPoint("grid-x000-y000", 0.00, 0.00),
    GridPoint("grid-x050-y000", 0.50, 0.00),
    GridPoint("grid-x025-y050", 0.25, 0.50),
    GridPoint("grid-x000-y025", 0.00, 0.25),
    GridPoint("grid-x050-y025", 0.50, 0.25),
    GridPoint("grid-x025-y000", 0.25, 0.00),
)


def _nominal_perturbation():
    return {"enabled": False}


def _perturbation(point):
    return {
        "enabled": True,
        "x": point.x,
        "y": point.y,
        "width": GRID_SIDE,
        "height": GRID_SIDE,
        "color": [0, 0, 0],
        "opacity": 1.0,
    }


def run_session(
    *,
    upstream_root: Union[Path, str],
    project_root: Union[Path, str],
    results_root: Union[Path, str],
    launch_cutoff_seconds: float = 1320,
    command_runner: Callable[..., Any] = subprocess.run,
    monotonic_clock: Callable[[], float] = time.monotonic,
) -> Dict[str, Any]:
    """Run the fixed sequence and persist evidence after every decision."""

    started_at = monotonic_clock()
    base.should_launch_next(0.0, launch_cutoff_seconds)
    upstream_root = Path(upstream_root).resolve()
    project_root = Path(project_root).resolve()
    session_dir = base._prepare_session_directory(
        Path(results_root).resolve(), session_directory_name=SESSION_DIRECTORY_NAME
    )
    configs_dir = session_dir / "configs"
    configs_dir.mkdir()
    summary = {
        "planned": {
            "episode_index": EPISODE_INDEX,
            "seed": 7,
            "env_seed": 7,
            "grid_side": GRID_SIDE,
            "grid_area_fraction": 0.25,
            "grid_positions": [asdict(point) for point in GRID_POINTS],
            "replays_per_failure": REPLAYS_PER_FAILURE,
            "matched_nominal_controls": MATCHED_NOMINAL_CONTROLS,
            "launch_cutoff_seconds": launch_cutoff_seconds,
        },
        "completed": {
            "stages": [],
            "sentinel_outcome": None,
            "positions_attempted": [],
            "replay_outcomes": [],
            "control_outcomes": [],
        },
        "outcomes": [],
        "first_apparent_failure": None,
        "reproducible": None,
        "nominal_controls_passed": None,
        "elapsed_seconds": 0.0,
        "stop_reason": None,
    }

    def elapsed():
        return monotonic_clock() - started_at

    def save(stop_reason=None):
        if stop_reason is not None:
            summary["stop_reason"] = stop_reason
        summary["elapsed_seconds"] = elapsed()
        base._atomic_write_json(session_dir / "session_summary.json", summary)

    def record_stage(stage_name, episode_indices, result, perturbation, infrastructure_error=None,
                     invalid_evidence=None, returncode=None):
        summary["completed"]["stages"].append(
            {
                "stage": stage_name,
                "perturbation": perturbation,
                "planned_episode_indices": list(episode_indices),
                "completed_episodes": len(result),
                "status": "infrastructure_error" if infrastructure_error is not None else (
                    "invalid_evidence" if invalid_evidence is not None else "completed"),
                "infrastructure_error": infrastructure_error,
                "invalid_evidence": invalid_evidence,
                "returncode": returncode,
            }
        )
        summary["outcomes"].extend(
            dict({"stage": stage_name, "perturbation": perturbation}, **asdict(item))
            for item in result
        )
        save()
        return base.StageResult(result, infrastructure_error, invalid_evidence)

    def launch(stage_name, *, point=None):
        if not base.should_launch_next(elapsed(), launch_cutoff_seconds):
            save("launch_cutoff_reached")
            return None
        episode_indices = (EPISODE_INDEX,)
        perturbation = _nominal_perturbation() if point is None else _perturbation(point)
        output_dir = session_dir / "runs" / stage_name
        config_path = configs_dir / (stage_name + ".yaml")
        base._write_config(
            config_path=config_path,
            output_dir=output_dir,
            project_root=project_root,
            stage_name=stage_name,
            episode_indices=episode_indices,
            side=None if point is None else GRID_SIDE,
            x=None if point is None else point.x,
            y=None if point is None else point.y,
        )
        try:
            completed = command_runner(
                [base._resolve_evaluator_command(Path(sys.executable)), "run", "--config", str(config_path)],
                cwd=upstream_root, check=False,
            )
        except Exception as error:
            return record_stage(stage_name, episode_indices, (), perturbation,
                                infrastructure_error="command_runner: {}".format(error))
        returncode = getattr(completed, "returncode", 0)
        if returncode not in (0, None):
            return record_stage(stage_name, episode_indices, (), perturbation,
                                infrastructure_error="evaluator returned nonzero status {}".format(returncode), returncode=returncode)
        try:
            results = base._load_stage_results(output_dir, expected_count=1)
        except Exception as error:
            return record_stage(stage_name, episode_indices, (), perturbation,
                                infrastructure_error="aggregate evidence error: {}: {}".format(type(error).__name__, error), returncode=returncode)
        if not any(item.outcome == "infrastructure_error" for item in results):
            if tuple(item.episode_index for item in results) != episode_indices:
                return record_stage(stage_name, episode_indices, results, perturbation,
                                    invalid_evidence="aggregate episode indices do not match stage plan", returncode=returncode)
        return record_stage(stage_name, episode_indices, results, perturbation, returncode=returncode)

    sentinel = launch("nominal-sentinel")
    if sentinel is None:
        return summary
    if sentinel.results:
        summary["completed"]["sentinel_outcome"] = sentinel.results[0].outcome
        save()
    if sentinel.infrastructure_error is not None or (sentinel.results and sentinel.results[0].outcome == "infrastructure_error"):
        save("nominal_sentinel_infrastructure_error")
        return summary
    if sentinel.invalid_evidence is not None:
        save("nominal_sentinel_invalid_evidence")
        return summary
    if sentinel.results[0].outcome != "success":
        save("nominal_sentinel_failed")
        return summary

    candidate = None
    for point in GRID_POINTS:
        grid_stage = launch(point.stage, point=point)
        if grid_stage is None:
            return summary
        summary["completed"]["positions_attempted"].append(point.stage)
        save()
        if grid_stage.infrastructure_error is not None or (grid_stage.results and grid_stage.results[0].outcome == "infrastructure_error"):
            save("grid_infrastructure_error")
            return summary
        if grid_stage.invalid_evidence is not None:
            save("grid_invalid_evidence")
            return summary
        if grid_stage.results[0].outcome == "policy_failure":
            candidate = point
            summary["first_apparent_failure"] = {
                "stage": point.stage, "x": point.x, "y": point.y,
                "width": GRID_SIDE, "height": GRID_SIDE,
            }
            save()
            break
    if candidate is None:
        save("no_policy_failure_in_grid")
        return summary

    for index in range(1, REPLAYS_PER_FAILURE + 1):
        replay = launch("replay-{}".format(index), point=candidate)
        if replay is None:
            return summary
        if replay.infrastructure_error is not None or (replay.results and replay.results[0].outcome == "infrastructure_error"):
            save("replay_infrastructure_error")
            return summary
        if replay.invalid_evidence is not None:
            save("replay_invalid_evidence")
            return summary
        summary["completed"]["replay_outcomes"].append(replay.results[0].outcome)
        save()
    summary["reproducible"] = base.is_reproducible(summary["completed"]["replay_outcomes"])
    save()
    if not summary["reproducible"]:
        save("policy_failure_not_reproducible")
        return summary

    for index in range(1, MATCHED_NOMINAL_CONTROLS + 1):
        control = launch("nominal-control-{}".format(index))
        if control is None:
            return summary
        if control.infrastructure_error is not None or (control.results and control.results[0].outcome == "infrastructure_error"):
            save("control_infrastructure_error")
            return summary
        if control.invalid_evidence is not None:
            save("control_invalid_evidence")
            return summary
        summary["completed"]["control_outcomes"].append(control.results[0].outcome)
        save()
    summary["nominal_controls_passed"] = sum(
        outcome == "success" for outcome in summary["completed"]["control_outcomes"]
    ) >= 4
    save("reproducible_failure_with_nominal_controls" if summary["nominal_controls_passed"] else "reproducible_failure_nominal_controls_failed")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-root", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--results-root", required=True, type=Path)
    parser.add_argument("--launch-cutoff-seconds", type=float, default=1320)
    run_session(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
