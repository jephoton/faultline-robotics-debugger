"""Normalize harness artifacts into stable, read-only viewer records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence


@dataclass(frozen=True)
class EpisodeView:
    episode_id: str
    run_name: str
    benchmark: str
    created_at: str
    instruction: str
    outcome: str
    steps: int
    elapsed_seconds: float
    task_id: int
    episode_index: int
    seed: Optional[int]
    env_seed: Optional[int]
    perturbation: Mapping[str, Any]
    provenance: Mapping[str, Any]
    failure_detail: Optional[str]
    video_path: Optional[str]
    trace_path: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CatalogSnapshot:
    episodes: Sequence[EpisodeView]
    warnings: Sequence[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "episodes": [episode.to_dict() for episode in self.episodes],
            "warnings": list(self.warnings),
        }


class ArtifactCatalog:
    """Discover aggregate files without ever changing the source artifacts."""

    def __init__(self, artifact_root: Path) -> None:
        self.artifact_root = artifact_root.resolve()

    def snapshot(self) -> CatalogSnapshot:
        episodes_by_identity = {}
        warnings = []
        if not self.artifact_root.is_dir():
            return CatalogSnapshot(episodes=[], warnings=["Artifact directory is unavailable"])

        for aggregate_path in sorted(self.artifact_root.rglob("*_aggregate.json")):
            try:
                resolved_aggregate = aggregate_path.resolve()
                relative = resolved_aggregate.relative_to(self.artifact_root).as_posix()
                aggregate = json.loads(resolved_aggregate.read_text(encoding="utf-8"))
                benchmark = aggregate["benchmark"]
                params = aggregate.get("config", {}).get("params", {})
                server = aggregate.get("server_info", {})
                for task in aggregate["tasks"]:
                    for raw in task["episodes"]:
                        task_id = int(raw["task_id"])
                        episode_index = int(raw.get("episode_idx", raw.get("episode_id", 0)))
                        eval_id = aggregate.get("eval_id")
                        identity = "{}:{}:{}".format(
                            eval_id if eval_id else relative, task_id, episode_index
                        )
                        episode_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
                        stem = "task{:04d}_ep{:04d}_*".format(task_id, episode_index)
                        media_directories = (
                            resolved_aggregate.parent / "episodes" / benchmark,
                            resolved_aggregate.parent,
                        )
                        video = next(
                            (
                                match
                                for directory in media_directories
                                for match in sorted(directory.glob(stem + ".mp4"))
                            ),
                            None,
                        )
                        trace = next(
                            (
                                match
                                for directory in media_directories
                                for match in sorted(directory.glob(stem + ".jsonl"))
                            ),
                            None,
                        )
                        reason = raw.get("failure_reason")
                        if reason == "exception":
                            outcome = "infrastructure_error"
                        elif raw.get("metrics", {}).get("success") is True:
                            outcome = "success"
                        elif reason == "timeout":
                            outcome = "episode_timeout"
                        else:
                            outcome = "task_failure"
                        candidate = EpisodeView(
                                episode_id=episode_id,
                                run_name=resolved_aggregate.parent.name,
                                benchmark=benchmark,
                                created_at=aggregate.get("created_at", ""),
                                instruction=raw.get("name", task.get("task", "Unknown task")),
                                outcome=outcome,
                                steps=int(raw.get("steps", 0)),
                                elapsed_seconds=float(raw.get("elapsed_sec", 0)),
                                task_id=task_id,
                                episode_index=episode_index,
                                seed=params.get("seed"),
                                env_seed=params.get("env_seed"),
                                perturbation=params.get("agentview_occlusion", {"enabled": False}),
                                provenance={
                                    "simulator_harness": aggregate.get("harness_version"),
                                    "server_harness": server.get("harness_version"),
                                    "model_server": server.get("model_server"),
                                    "benchmark_class": aggregate.get("config", {}).get("benchmark"),
                                    "eval_id": aggregate.get("eval_id"),
                                    "checkpoint_revision": None,
                                },
                                failure_detail=raw.get("failure_detail"),
                                video_path=(
                                    video.resolve().relative_to(self.artifact_root).as_posix()
                                    if video is not None
                                    else None
                                ),
                                trace_path=(
                                    trace.resolve().relative_to(self.artifact_root).as_posix()
                                    if trace is not None
                                    else None
                                ),
                        )
                        existing = episodes_by_identity.get(identity)
                        candidate_media = sum(
                            item is not None for item in (candidate.video_path, candidate.trace_path)
                        )
                        existing_media = (
                            sum(item is not None for item in (existing.video_path, existing.trace_path))
                            if existing is not None
                            else -1
                        )
                        if candidate_media > existing_media:
                            episodes_by_identity[identity] = candidate
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
                warnings.append("{}: {}".format(aggregate_path.name, type(error).__name__))

        episodes = list(episodes_by_identity.values())
        episodes.sort(key=lambda item: (item.created_at, item.episode_id), reverse=True)
        return CatalogSnapshot(episodes=episodes, warnings=warnings)

    def list_episodes(self) -> Sequence[EpisodeView]:
        return self.snapshot().episodes

    def get_episode(self, episode_id: str) -> EpisodeView:
        for episode in self.list_episodes():
            if episode.episode_id == episode_id:
                return episode
        raise KeyError(episode_id)

    def load_trace(self, episode_id: str) -> Dict[str, Any]:
        episode = self.get_episode(episode_id)
        if episode.trace_path is None:
            return {"points": [], "warnings": ["Trace not recorded"]}

        lines = self._resolve_path(episode.trace_path).read_text(encoding="utf-8").splitlines()
        points = []
        warnings = []
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                point = json.loads(line)
                if not isinstance(point, dict) or "step" not in point:
                    raise ValueError("trace point requires step")
                points.append(point)
            except (ValueError, json.JSONDecodeError):
                if index == len(lines) - 1:
                    warnings.append("Incomplete final trace line; earlier points retained")
                else:
                    raise ValueError("Invalid trace line {}".format(index + 1))
        return {"points": points, "warnings": warnings}

    def _resolve_path(self, relative_path: str) -> Path:
        candidate = (self.artifact_root / relative_path).resolve()
        try:
            candidate.relative_to(self.artifact_root)
        except ValueError:
            raise ValueError("artifact path escapes artifact root")
        if not candidate.is_file():
            raise FileNotFoundError(relative_path)
        return candidate

    def resolve_media(self, relative_path: str) -> Path:
        candidate = self._resolve_path(relative_path)
        if candidate.suffix.lower() not in {".mp4", ".webm", ".png", ".jpg", ".jpeg"}:
            raise ValueError("file type is not public viewer media")
        return candidate
