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
from typing import Any, Callable, Optional, Union

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path: sys.path.insert(0, str(SOURCE_ROOT))
from robot_debug.reduce import GateDecision, Rect, candidates, classify_attempts
try:
    from scripts import run_failure_search as base
except ImportError:
    import run_failure_search as base

SESSION_DIRECTORY_NAME = "failure-reduction"
PARENT_RECT = Rect(.5, 0, .5, .5)
DELTAS = (.125, .0625)
PARENT_ATTEMPT_BUDGET = 5
CANDIDATE_ATTEMPT_BUDGET = 12
NOMINAL_CONTROLS = 5
TOTAL_VALID_EPISODE_LIMIT = 23
MODEL_ID = "GR00T N1.7"
STOP_REASONS = {"nominal_sentinel_failed", "parent_not_reproducible", "candidate_budget_exhausted", "local_minimum_reached", "reduced_failure_with_nominal_controls", "reduced_failure_nominal_controls_failed", "launch_cutoff_reached", "infrastructure_error", "invalid_evidence"}

def _rect_dict(rect: Rect) -> dict[str, float]: return {"x": rect.x, "y": rect.y, "width": rect.width, "height": rect.height}
def _geometry(rect: Rect) -> dict[str, float]: return dict(_rect_dict(rect), area=rect.area)
def _stage_rect(prefix: str, rect: Rect, attempt: int, delta: Optional[float] = None, edge: Optional[str] = None) -> str:
    geometry = "x{:04d}-y{:04d}-w{:04d}-h{:04d}".format(*(round(value * 1000) for value in (rect.x, rect.y, rect.width, rect.height)))
    return "{}-{}-attempt-{:02d}".format(prefix, geometry, attempt) if delta is None else "delta-{:04d}-{}-{}-attempt-{:02d}".format(round(delta * 1000), edge, geometry, attempt)

class ReductionSession:
    """Durable, deterministic reduction state machine with bounded launches."""
    def __init__(self, *, upstream_root: Path, project_root: Path, results_root: Path, launch_cutoff_seconds: float, command_runner: Callable[..., Any], monotonic_clock: Callable[[], float]) -> None:
        self.upstream_root, self.project_root, self.results_root = upstream_root, project_root, results_root
        self.launch_cutoff_seconds, self.command_runner, self.clock = launch_cutoff_seconds, command_runner, monotonic_clock
        self.started_at = self.clock(); self.session_dir, self.summary = self._open_or_create()
        self.prior_elapsed = float(self.summary.get("elapsed_seconds", 0.0))
        self.configs_dir = self.session_dir / "configs"; self.configs_dir.mkdir(exist_ok=True)

    @staticmethod
    def _plan() -> dict[str, Any]:
        return {"session_directory_name": SESSION_DIRECTORY_NAME, "parent_rectangle": _rect_dict(PARENT_RECT), "deltas": list(DELTAS), "parent_attempt_budget": PARENT_ATTEMPT_BUDGET, "candidate_attempt_budget": CANDIDATE_ATTEMPT_BUDGET, "nominal_controls": NOMINAL_CONTROLS, "total_valid_episode_limit": TOTAL_VALID_EPISODE_LIMIT, "model_identity": MODEL_ID, "launch_cutoff_seconds": None}

    def _open_or_create(self) -> tuple[Path, dict[str, Any]]:
        root = self.results_root.resolve(); existing = root / SESSION_DIRECTORY_NAME; summary_path = existing / "session_summary.json"
        if existing.exists() and summary_path.exists():
            if existing.is_symlink(): raise ValueError("refusing symlinked session directory: {}".format(existing))
            summary = json.loads(summary_path.read_text(encoding="utf-8")); actual, expected = dict(summary.get("planned", {})), self._plan()
            actual.pop("launch_cutoff_seconds", None); expected.pop("launch_cutoff_seconds", None)
            if actual != expected: raise ValueError("stored reduction plan constants or parent geometry do not match")
            return existing.resolve(), summary
        directory = base._prepare_session_directory(root, session_directory_name=SESSION_DIRECTORY_NAME)
        plan = self._plan(); plan["launch_cutoff_seconds"] = self.launch_cutoff_seconds
        return directory, {"schema_version": 1, "planned": plan, "model_identity": MODEL_ID, "repository_revision": self._repository_revision(), "completed": {"stages": [], "decisions": [], "sentinel_outcome": None, "control_outcomes": []}, "outcomes": [], "lineage": [], "certified_rectangle": _rect_dict(PARENT_RECT), "geometry": {"parent": _geometry(PARENT_RECT), "current": _geometry(PARENT_RECT), "final": _geometry(PARENT_RECT)}, "candidate_valid_attempts": 0, "valid_episode_count": 0, "config_paths": [], "elapsed_seconds": 0.0, "reduction_search": {"active_delta": DELTAS[0], "current_rectangle": _rect_dict(PARENT_RECT)}, "reduction_search_stop": None, "stop_reason": None}

    def elapsed(self) -> float: return self.prior_elapsed + max(0.0, self.clock() - self.started_at)
    def _valid_count(self) -> int: return sum(len(stage.get("results", [])) for stage in self.summary["completed"]["stages"] if stage["status"] == "completed")
    def save(self, stop_reason: Optional[str] = None) -> None:
        if stop_reason is not None:
            if stop_reason not in STOP_REASONS: raise ValueError("unknown stop reason: {}".format(stop_reason))
            self.summary["stop_reason"] = stop_reason
        current = Rect(**self.summary["certified_rectangle"])
        self.summary["geometry"]["current"] = _geometry(current); self.summary["geometry"]["final"] = _geometry(current)
        self.summary["candidate_valid_attempts"] = self._candidate_attempt_count(); self.summary["valid_episode_count"] = self._valid_count(); self.summary["elapsed_seconds"] = self.elapsed()
        if self.summary["valid_episode_count"] > TOTAL_VALID_EPISODE_LIMIT: raise RuntimeError("valid episode cap exceeded")
        base._atomic_write_json(self.session_dir / "session_summary.json", self.summary)

    def _saved_stage(self, name: str) -> Optional[base.StageResult]:
        for stage in self.summary["completed"]["stages"]:
            if stage["stage"] == name: return base.StageResult([SimpleNamespace(**item) for item in stage.get("results", [])], stage.get("infrastructure_error"), stage.get("invalid_evidence"))
        return None
    def _record_stage(self, stage: dict[str, Any]) -> base.StageResult:
        self.summary["completed"]["stages"].append(stage)
        for item in stage["results"]: self.summary["outcomes"].append(dict(item, stage=stage["stage"], rectangle=stage["rectangle"]))
        self.save(); return base.StageResult([SimpleNamespace(**item) for item in stage["results"]], stage["infrastructure_error"], stage["invalid_evidence"])
    def _invalid_task_id(self, output_dir: Path) -> bool:
        paths = sorted(output_dir.rglob("*_aggregate.json"))
        try:
            raw = json.loads(paths[0].read_text(encoding="utf-8")); return raw["tasks"][0]["episodes"][0].get("task_id") != 0
        except (IndexError, KeyError, TypeError, json.JSONDecodeError): return True

    def launch(self, name: str, *, rect: Optional[Rect]) -> Optional[base.StageResult]:
        saved = self._saved_stage(name)
        if saved is not None: return saved
        if self._valid_count() >= TOTAL_VALID_EPISODE_LIMIT or not base.should_launch_next(self.elapsed(), self.launch_cutoff_seconds): self.save("launch_cutoff_reached"); return None
        output_dir, config_path = self.session_dir / "runs" / name, self.configs_dir / (name + ".yaml")
        kwargs: dict[str, Any] = {"config_path": config_path, "output_dir": output_dir, "project_root": self.project_root, "stage_name": name, "episode_indices": (0,)}
        if rect is not None: kwargs.update(x=rect.x, y=rect.y, width=rect.width, height=rect.height)
        base._write_config(**kwargs)
        stage = {"stage": name, "rectangle": None if rect is None else _rect_dict(rect), "area": None if rect is None else rect.area, "planned_episode_indices": [0], "config_path": "configs/{}.yaml".format(name), "output_path": "runs/{}".format(name), "results": [], "status": "completed", "infrastructure_error": None, "invalid_evidence": None}
        self.summary["config_paths"].append(stage["config_path"])
        try:
            completed = self.command_runner([base._resolve_evaluator_command(Path(sys.executable)), "run", "--config", str(config_path)], cwd=self.upstream_root, check=False)
        except KeyboardInterrupt:
            self.save()
            raise
        except Exception as error:
            stage["status"] = "infrastructure_error"; stage["infrastructure_error"] = "command_runner: {}".format(error); return self._record_stage(stage)
        if getattr(completed, "returncode", 0) not in (0, None):
            stage["status"] = "infrastructure_error"; stage["infrastructure_error"] = "evaluator returned nonzero status {}".format(completed.returncode); return self._record_stage(stage)
        try:
            results = base._load_stage_results(output_dir, expected_count=1)
            if results[0].episode_index != 0 or self._invalid_task_id(output_dir): raise ValueError("aggregate task or episode index does not match stage plan")
        except Exception as error:
            stage["status"] = "invalid_evidence"; stage["invalid_evidence"] = "{}: {}".format(type(error).__name__, error); return self._record_stage(stage)
        if results[0].outcome == "infrastructure_error":
            stage["status"] = "infrastructure_error"; stage["infrastructure_error"] = "aggregate reports infrastructure error"
        else: stage["results"] = [asdict(item) for item in results]
        return self._record_stage(stage)

    def _record_decision(self, *, label: str, edge: Optional[str], delta: Optional[float], rect: Rect, outcomes: list[str], decision: str) -> None:
        decisions = self.summary["completed"]["decisions"]
        decisions[:] = [item for item in decisions if not (item["label"] == label and item.get("edge") == edge and item.get("delta") == delta and item["rectangle"] == _rect_dict(rect))]
        decisions.append({"label": label, "edge": edge, "delta": delta, "rectangle": _rect_dict(rect), "area": rect.area, "outcomes": outcomes, "decision": decision}); self.save()
    def _candidate_attempt_count(self) -> int: return sum(1 for stage in self.summary["completed"]["stages"] if stage["stage"].startswith("delta-") and stage["status"] == "completed")
    def _gate_error(self, stage: base.StageResult) -> bool:
        if stage.infrastructure_error: self.save("infrastructure_error"); return True
        if stage.invalid_evidence: self.save("invalid_evidence"); return True
        return False
    def run_gate(self, *, label: str, rect: Rect, edge: Optional[str] = None, delta: Optional[float] = None) -> GateDecision | None:
        for saved in self.summary["completed"]["decisions"]:
            if saved["label"] == label and saved.get("edge") == edge and saved.get("delta") == delta and saved["rectangle"] == _rect_dict(rect):
                if saved["decision"] == GateDecision.PASS.value: return GateDecision.PASS
                if saved["decision"] == GateDecision.REJECT.value: return GateDecision.REJECT
                if saved["decision"] == "inconclusive_budget_exhausted": return GateDecision.PENDING
        outcomes: list[str] = []
        for attempt in range(1, 6):
            stage = self._saved_stage(_stage_rect(label, rect, attempt, delta, edge))
            if stage is None: break
            if self._gate_error(stage): return None
            outcomes.append(stage.results[0].outcome)
        decision = classify_attempts(outcomes)
        if decision is not GateDecision.PENDING: self._record_decision(label=label, edge=edge, delta=delta, rect=rect, outcomes=outcomes, decision=decision.value); return decision
        while len(outcomes) < 5:
            if label == "candidate" and self._candidate_attempt_count() >= CANDIDATE_ATTEMPT_BUDGET:
                self._record_decision(label=label, edge=edge, delta=delta, rect=rect, outcomes=outcomes, decision="inconclusive_budget_exhausted"); return GateDecision.PENDING
            stage = self.launch(_stage_rect(label, rect, len(outcomes) + 1, delta, edge), rect=rect)
            if stage is None or self._gate_error(stage): return None
            outcomes.append(stage.results[0].outcome); decision = classify_attempts(outcomes)
            if decision is not GateDecision.PENDING: self._record_decision(label=label, edge=edge, delta=delta, rect=rect, outcomes=outcomes, decision=decision.value); return decision
        self._record_decision(label=label, edge=edge, delta=delta, rect=rect, outcomes=outcomes, decision="inconclusive_budget_exhausted"); return GateDecision.PENDING

    def run_sentinel(self) -> bool:
        stage = self.launch("nominal-sentinel", rect=None)
        if stage is None or self._gate_error(stage): return False
        outcome = stage.results[0].outcome; self.summary["completed"]["sentinel_outcome"] = outcome; self.save()
        if outcome != "success": self.save("nominal_sentinel_failed"); return False
        return True
    def _accept(self, candidate, delta: float) -> None:
        self.summary["certified_rectangle"] = _rect_dict(candidate.rect); self.summary["reduction_search"] = {"active_delta": delta, "current_rectangle": _rect_dict(candidate.rect)}; self.summary["lineage"].append({"edge": candidate.edge, "delta": delta, "rectangle": _rect_dict(candidate.rect), "area": candidate.rect.area}); self.save()
    def run_candidates(self) -> bool:
        search = self.summary["reduction_search"]
        current = Rect(**search["current_rectangle"]); delta_index = DELTAS.index(search["active_delta"])
        while delta_index < len(DELTAS):
            delta, accepted = DELTAS[delta_index], False
            for candidate in candidates(current, delta=delta):
                decision = self.run_gate(label="candidate", rect=candidate.rect, edge=candidate.edge, delta=delta)
                if decision is None: return False
                if decision is GateDecision.PASS: self._accept(candidate, delta); current, accepted = candidate.rect, True; break
                if decision is GateDecision.PENDING:
                    self.summary["reduction_search_stop"] = "candidate_budget_exhausted"; self.save()
                    if self.summary["lineage"]: return True
                    self.save("candidate_budget_exhausted"); return False
            if accepted: continue  # Binding greedy restart rule: same delta, new parent.
            delta_index += 1
            if delta_index < len(DELTAS):
                self.summary["reduction_search"] = {"active_delta": DELTAS[delta_index], "current_rectangle": _rect_dict(current)}; self.save()
        self.summary["reduction_search_stop"] = "local_minimum_reached"; self.save()
        if self.summary["lineage"]: return True
        self.save("local_minimum_reached"); return False
    def run_controls(self) -> bool:
        outcomes = self.summary["completed"]["control_outcomes"]
        for attempt in range(len(outcomes) + 1, NOMINAL_CONTROLS + 1):
            stage = self.launch("nominal-control-attempt-{:02d}".format(attempt), rect=None)
            if stage is None or self._gate_error(stage): return False
            outcomes.append(stage.results[0].outcome); self.save()
        self.save("reduced_failure_with_nominal_controls" if all(item == "success" for item in outcomes) else "reduced_failure_nominal_controls_failed"); return True
    def _repository_revision(self) -> str:
        try: return subprocess.run(["git", "-C", str(self.project_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        except Exception: return "unknown"
    def _write_manifest(self) -> None:
        if not self.summary["lineage"]: return
        final = Rect(**self.summary["certified_rectangle"]); stage = next(item for item in self.summary["completed"]["stages"] if item["rectangle"] == _rect_dict(final) and item["stage"].startswith("delta-"))
        manifest = {"schema_version": 1, "task_id": 0, "episode_index": 0, "seed": 7, "expected_outcome": "policy_failure", "acceptance_rule": {"failures": 4, "attempts": 5}, "rectangle": _rect_dict(final), "source_summary": "session_summary.json", "replay_command": "vla-eval run --config {}".format(stage["config_path"]), "repository_revision": self.summary["repository_revision"], "model_identity": MODEL_ID}
        base._atomic_write_json(self.session_dir / "replay_case.json", manifest)
    def run(self) -> dict[str, Any]:
        if self.summary["stop_reason"]:
            if self.summary["stop_reason"] in {"reduced_failure_with_nominal_controls", "reduced_failure_nominal_controls_failed"}: self._write_manifest()
            return self.summary
        if not self.run_sentinel(): return self.summary
        parent = self.run_gate(label="parent", rect=PARENT_RECT)
        if parent is None: return self.summary
        if parent is not GateDecision.PASS: self.save("parent_not_reproducible"); return self.summary
        if self.summary["reduction_search_stop"] and not self.summary["lineage"]:
            self.save(self.summary["reduction_search_stop"])
            return self.summary
        if self.summary["reduction_search_stop"] is None and not self.run_candidates(): return self.summary
        self.run_controls()
        if self.summary["stop_reason"] in {"reduced_failure_with_nominal_controls", "reduced_failure_nominal_controls_failed"}: self._write_manifest()
        return self.summary

def run_session(*, upstream_root: Union[Path, str], project_root: Union[Path, str], results_root: Union[Path, str], launch_cutoff_seconds: float = 1320, command_runner: Callable[..., Any] = subprocess.run, monotonic_clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    return ReductionSession(upstream_root=Path(upstream_root).resolve(), project_root=Path(project_root).resolve(), results_root=Path(results_root).resolve(), launch_cutoff_seconds=launch_cutoff_seconds, command_runner=command_runner, monotonic_clock=monotonic_clock).run()
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--upstream-root", required=True, type=Path); parser.add_argument("--project-root", required=True, type=Path); parser.add_argument("--results-root", required=True, type=Path); parser.add_argument("--launch-cutoff-seconds", type=float, default=1320); run_session(**vars(parser.parse_args()))
if __name__ == "__main__": main()
