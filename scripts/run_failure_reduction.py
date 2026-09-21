"""Run the bounded, resumable rectangle failure-reduction session."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import Any, Callable, Dict, Optional, Sequence, Union


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from robot_debug.reduce import GateDecision, Rect, candidates, classify_attempts

try:
    from scripts import run_failure_search as base
except ImportError:  # Support executing this file directly from the source tree.
    import run_failure_search as base


SESSION_DIRECTORY_NAME = "failure-reduction"
PARENT_RECT = Rect(.5, 0, .5, .5)
DELTAS = (.125, .0625)
PARENT_ATTEMPT_BUDGET = 5
CANDIDATE_ATTEMPT_BUDGET = 12
NOMINAL_CONTROLS = 5
TOTAL_VALID_EPISODE_LIMIT = 23
STOP_REASONS = {
    "nominal_sentinel_failed", "parent_not_reproducible",
    "candidate_budget_exhausted", "local_minimum_reached",
    "reduced_failure_with_nominal_controls",
    "reduced_failure_nominal_controls_failed", "launch_cutoff_reached",
    "infrastructure_error", "invalid_evidence",
}


def _rect_dict(rect: Rect) -> dict[str, float]:
    return {"x": rect.x, "y": rect.y, "width": rect.width, "height": rect.height}


def _stage_rect(prefix: str, rect: Rect, attempt: int, delta: Optional[float] = None, edge: Optional[str] = None) -> str:
    geometry = "x{:04d}-y{:04d}-w{:04d}-h{:04d}".format(
        round(rect.x * 1000), round(rect.y * 1000), round(rect.width * 1000), round(rect.height * 1000)
    )
    if delta is None:
        return "{}-{}-attempt-{:02d}".format(prefix, geometry, attempt)
    return "delta-{:04d}-{}-{}-attempt-{:02d}".format(round(delta * 1000), edge, geometry, attempt)


class ReductionSession:
    """Durably execute one fixed-budget reduction state machine."""

    def __init__(self, *, upstream_root: Path, project_root: Path, results_root: Path,
                 launch_cutoff_seconds: float, command_runner: Callable[..., Any],
                 monotonic_clock: Callable[[], float]) -> None:
        self.upstream_root, self.project_root = upstream_root, project_root
        self.results_root = results_root
        self.launch_cutoff_seconds = launch_cutoff_seconds
        self.command_runner, self.clock = command_runner, monotonic_clock
        self.started_at = self.clock()
        self.session_dir, self.summary = self._open_or_create()
        self.configs_dir = self.session_dir / "configs"
        self.configs_dir.mkdir(exist_ok=True)

    @staticmethod
    def _plan() -> dict[str, Any]:
        return {
            "session_directory_name": SESSION_DIRECTORY_NAME, "parent_rectangle": _rect_dict(PARENT_RECT),
            "deltas": list(DELTAS), "parent_attempt_budget": PARENT_ATTEMPT_BUDGET,
            "candidate_attempt_budget": CANDIDATE_ATTEMPT_BUDGET, "nominal_controls": NOMINAL_CONTROLS,
            "total_valid_episode_limit": TOTAL_VALID_EPISODE_LIMIT, "launch_cutoff_seconds": None,
        }

    def _open_or_create(self) -> tuple[Path, dict[str, Any]]:
        root = self.results_root.resolve()
        existing = root / SESSION_DIRECTORY_NAME
        summary_path = existing / "session_summary.json"
        if existing.exists() and summary_path.exists():
            if existing.is_symlink():
                raise ValueError("refusing symlinked session directory: {}".format(existing))
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            expected = self._plan()
            actual = dict(summary.get("planned", {}))
            actual.pop("launch_cutoff_seconds", None)
            expected.pop("launch_cutoff_seconds", None)
            if actual != expected:
                raise ValueError("stored reduction plan constants or parent geometry do not match")
            return existing.resolve(), summary
        session_dir = base._prepare_session_directory(root, session_directory_name=SESSION_DIRECTORY_NAME)
        plan = self._plan(); plan["launch_cutoff_seconds"] = self.launch_cutoff_seconds
        return session_dir, {
            "schema_version": 1, "planned": plan,
            "completed": {"stages": [], "decisions": [], "sentinel_outcome": None, "control_outcomes": []},
            "outcomes": [], "lineage": [], "certified_rectangle": _rect_dict(PARENT_RECT),
            "candidate_valid_attempts": 0, "elapsed_seconds": 0.0, "stop_reason": None,
        }

    def elapsed(self) -> float:
        return self.clock() - self.started_at

    def save(self, stop_reason: Optional[str] = None) -> None:
        if stop_reason is not None:
            if stop_reason not in STOP_REASONS:
                raise ValueError("unknown stop reason: {}".format(stop_reason))
            self.summary["stop_reason"] = stop_reason
        self.summary["elapsed_seconds"] = self.elapsed()
        base._atomic_write_json(self.session_dir / "session_summary.json", self.summary)

    def _saved_stage(self, stage_name: str) -> Optional[base.StageResult]:
        for stage in self.summary["completed"]["stages"]:
            if stage["stage"] == stage_name:
                results = [SimpleNamespace(**item) for item in stage.get("results", [])]
                return base.StageResult(results, stage.get("infrastructure_error"), stage.get("invalid_evidence"))
        return None

    def launch(self, stage_name: str, *, rect: Optional[Rect]) -> Optional[base.StageResult]:
        saved = self._saved_stage(stage_name)
        if saved is not None:
            return saved
        if not base.should_launch_next(self.elapsed(), self.launch_cutoff_seconds):
            self.save("launch_cutoff_reached")
            return None
        output_dir = self.session_dir / "runs" / stage_name
        config_path = self.configs_dir / (stage_name + ".yaml")
        kwargs: dict[str, Any] = {"config_path": config_path, "output_dir": output_dir,
            "project_root": self.project_root, "stage_name": stage_name, "episode_indices": (0,)}
        if rect is not None:
            kwargs.update(x=rect.x, y=rect.y, width=rect.width, height=rect.height)
        base._write_config(**kwargs)
        stage: dict[str, Any] = {"stage": stage_name, "rectangle": None if rect is None else _rect_dict(rect),
            "planned_episode_indices": [0], "results": [], "status": "completed",
            "infrastructure_error": None, "invalid_evidence": None}
        try:
            completed = self.command_runner([base._resolve_evaluator_command(Path(sys.executable)), "run", "--config", str(config_path)], cwd=self.upstream_root, check=False)
            returncode = getattr(completed, "returncode", 0)
            if returncode not in (0, None):
                raise RuntimeError("evaluator returned nonzero status {}".format(returncode))
            results = base._load_stage_results(output_dir, expected_count=1)
            if results[0].episode_index != 0:
                stage["status"] = "invalid_evidence"; stage["invalid_evidence"] = "aggregate episode indices do not match stage plan"
                result = base.StageResult((), invalid_evidence=stage["invalid_evidence"])
            elif results[0].outcome == "infrastructure_error":
                stage["status"] = "infrastructure_error"; stage["infrastructure_error"] = "aggregate reports infrastructure error"
                result = base.StageResult(results, infrastructure_error=stage["infrastructure_error"])
            else:
                stage["results"] = [asdict(item) for item in results]
                result = base.StageResult(results)
        except KeyboardInterrupt:
            raise
        except Exception as error:
            stage["status"] = "infrastructure_error"; stage["infrastructure_error"] = "{}: {}".format(type(error).__name__, error)
            result = base.StageResult((), infrastructure_error=stage["infrastructure_error"])
        self.summary["completed"]["stages"].append(stage)
        for item in stage["results"]:
            self.summary["outcomes"].append(dict(item, stage=stage_name, rectangle=stage["rectangle"]))
        self.save()
        return result

    def run_sentinel(self) -> bool:
        stage = self.launch("nominal-sentinel", rect=None)
        if stage is None:
            return False
        if stage.infrastructure_error:
            self.save("infrastructure_error"); return False
        if stage.invalid_evidence:
            self.save("invalid_evidence"); return False
        outcome = stage.results[0].outcome
        self.summary["completed"]["sentinel_outcome"] = outcome
        self.save()
        if outcome != "success":
            self.save("nominal_sentinel_failed"); return False
        return True

    def run_gate(self, *, label: str, rect: Rect, budget: int, delta: Optional[float] = None,
                 edge: Optional[str] = None) -> GateDecision | None:
        for saved in self.summary["completed"]["decisions"]:
            if (saved["label"] == label and saved.get("edge") == edge and
                    saved["rectangle"] == _rect_dict(rect)):
                if saved["decision"] == GateDecision.PASS.value:
                    return GateDecision.PASS
                if saved["decision"] == GateDecision.REJECT.value:
                    return GateDecision.REJECT
                if saved["decision"] == "inconclusive_budget_exhausted":
                    return GateDecision.PENDING
        outcomes: list[str] = []
        for attempt in range(1, budget + 1):
            name = _stage_rect(label, rect, attempt, delta, edge)
            stage = self.launch(name, rect=rect)
            if stage is None:
                return None
            if stage.infrastructure_error:
                self.save("infrastructure_error"); return None
            if stage.invalid_evidence:
                self.save("invalid_evidence"); return None
            outcomes.append(stage.results[0].outcome)
            if label != "parent":
                self.summary["candidate_valid_attempts"] = self._candidate_attempt_count()
            decision = classify_attempts(outcomes)
            if decision is not GateDecision.PENDING:
                self.summary["completed"]["decisions"].append({"label": label, "edge": edge,
                    "rectangle": _rect_dict(rect), "outcomes": outcomes, "decision": decision.value})
                self.save()
                return decision
        self.summary["completed"]["decisions"].append({"label": label, "edge": edge,
            "rectangle": _rect_dict(rect), "outcomes": outcomes, "decision": "inconclusive_budget_exhausted"})
        self.save()
        return GateDecision.PENDING

    def _candidate_attempt_count(self) -> int:
        """Count durable valid candidate attempts, including work before resume."""
        return sum(
            1 for stage in self.summary["completed"]["stages"]
            if stage["stage"].startswith("delta-") and stage["status"] == "completed"
        )

    def run_candidates(self) -> bool:
        if self.summary["lineage"]:
            return True
        current = Rect(**self.summary["certified_rectangle"])
        consumed = self._candidate_attempt_count()
        self.summary["candidate_valid_attempts"] = consumed
        for delta in DELTAS:
            for candidate in candidates(current, delta=delta):
                remaining = CANDIDATE_ATTEMPT_BUDGET - consumed
                if remaining <= 0:
                    self.save("candidate_budget_exhausted"); return False
                decision = self.run_gate(label="candidate", rect=candidate.rect, budget=min(5, remaining), delta=delta, edge=candidate.edge)
                consumed = self._candidate_attempt_count()
                self.summary["candidate_valid_attempts"] = consumed
                if decision is None:
                    return False
                if decision is GateDecision.PASS:
                    self.summary["certified_rectangle"] = _rect_dict(candidate.rect)
                    self.summary["lineage"].append({"edge": candidate.edge, "delta": delta, "rectangle": _rect_dict(candidate.rect)})
                    self.save()
                    return True
                if decision is GateDecision.PENDING:
                    self.save("candidate_budget_exhausted"); return False
        self.save("local_minimum_reached")
        return False

    def run_controls(self) -> bool:
        outcomes = self.summary["completed"]["control_outcomes"]
        for attempt in range(len(outcomes) + 1, NOMINAL_CONTROLS + 1):
            stage = self.launch("nominal-control-attempt-{:02d}".format(attempt), rect=None)
            if stage is None: return False
            if stage.infrastructure_error:
                self.save("infrastructure_error"); return False
            if stage.invalid_evidence:
                self.save("invalid_evidence"); return False
            outcomes.append(stage.results[0].outcome)
            self.save()
        self.save("reduced_failure_with_nominal_controls" if outcomes.count("success") >= 4 else "reduced_failure_nominal_controls_failed")
        return True

    def _write_manifest(self) -> None:
        if not self.summary["lineage"]:
            return
        final = Rect(**self.summary["certified_rectangle"])
        stage = next(
            item for item in self.summary["completed"]["stages"]
            if item["rectangle"] == _rect_dict(final) and item["stage"].startswith("delta-")
        )
        config = self.configs_dir / (stage["stage"] + ".yaml")
        manifest = {"schema_version": 1, "task_id": 0, "episode_index": 0, "seed": 7,
            "expected_outcome": "policy_failure", "acceptance_rule": {"failures": 4, "attempts": 5},
            "rectangle": _rect_dict(final), "source_summary": "session_summary.json",
            "replay_command": "vla-eval run --config {}".format(config.relative_to(self.session_dir).as_posix()),
            "repository_revision": self._repository_revision()}
        base._atomic_write_json(self.session_dir / "replay_case.json", manifest)

    def _repository_revision(self) -> str:
        try:
            return subprocess.run(["git", "-C", str(self.project_root), "rev-parse", "HEAD"], capture_output=True, check=True, text=True).stdout.strip()
        except Exception:
            return "unknown"

    def run(self) -> dict[str, Any]:
        if self.summary["stop_reason"]:
            return self.summary
        if not self.run_sentinel(): return self.summary
        parent = self.run_gate(label="parent", rect=PARENT_RECT, budget=PARENT_ATTEMPT_BUDGET)
        if parent is None: return self.summary
        if parent is not GateDecision.PASS:
            self.save("parent_not_reproducible"); return self.summary
        if not self.run_candidates(): return self.summary
        self.run_controls()
        if self.summary["stop_reason"] in {"reduced_failure_with_nominal_controls", "reduced_failure_nominal_controls_failed"}:
            self._write_manifest()
        return self.summary


def run_session(*, upstream_root: Union[Path, str], project_root: Union[Path, str],
                results_root: Union[Path, str], launch_cutoff_seconds: float = 1320,
                command_runner: Callable[..., Any] = subprocess.run,
                monotonic_clock: Callable[[], float] = time.monotonic) -> Dict[str, Any]:
    """Run or resume the fixed bounded failure-reduction session."""
    return ReductionSession(upstream_root=Path(upstream_root).resolve(), project_root=Path(project_root).resolve(),
        results_root=Path(results_root).resolve(), launch_cutoff_seconds=launch_cutoff_seconds,
        command_runner=command_runner, monotonic_clock=monotonic_clock).run()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-root", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--results-root", required=True, type=Path)
    parser.add_argument("--launch-cutoff-seconds", type=float, default=1320)
    run_session(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
