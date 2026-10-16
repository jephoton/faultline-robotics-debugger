"""The "All evidence" catalog, scanned once and cached (ADR 0033).

``ArtifactCatalog.snapshot()`` walks every ``*_aggregate.json`` under the artifact root and globs for each
episode's video and trace, which takes tens of seconds on a full ``artifacts/`` folder, and the old pages asked
for it on every request. :class:`CachedArtifactCatalog` keeps the last snapshot, keyed on the newest
modification time anywhere under the root, and lets only one thread scan at a time: concurrent callers wait on
the same lock and then share the result instead of starting a scan of their own.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from robot_debug.viewer.catalog import ArtifactCatalog, CatalogSnapshot, EpisodeView
from robot_debug.viewer.processes import scrub_text

RECHECK_SECONDS = 10.0                   # how long a snapshot is trusted before the tree is looked at again


def newest_modification(root: Path) -> float:
    """The newest modification time of any file or folder under ``root`` (links are not followed)."""

    newest = 0.0
    pending = [str(root)]
    while pending:
        try:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    try:
                        newest = max(newest, entry.stat(follow_symlinks=False).st_mtime)
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(entry.path)
                    except OSError:
                        continue
        except OSError:
            continue
    return newest


class CachedArtifactCatalog(ArtifactCatalog):
    """An :class:`ArtifactCatalog` whose ``snapshot()`` is cached and scanned by one thread at a time."""

    def __init__(self, artifact_root: Path, *, recheck_seconds: float = RECHECK_SECONDS,
                 stamp: Optional[Callable[[Path], float]] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__(artifact_root)
        self._recheck, self._clock = float(recheck_seconds), clock
        self._stamp_of = stamp or newest_modification
        self._lock = threading.Lock()
        self._cached: Optional[CatalogSnapshot] = None
        self._stamp: Optional[float] = None
        self._checked_at = 0.0
        self.scans = 0

    def snapshot(self) -> CatalogSnapshot:
        with self._lock:                                   # later callers wait here, then reuse the result
            now = self._clock()
            if self._cached is not None and now - self._checked_at < self._recheck:
                return self._cached
            stamp = self._stamp_of(self.artifact_root)
            if self._cached is None or stamp != self._stamp:
                self._cached = super().snapshot()
                self.scans += 1
                self._stamp = stamp
            self._checked_at = self._clock()
            return self._cached


def _episode_row(episode: EpisodeView) -> Dict[str, Any]:
    perturbation = dict(episode.perturbation) if isinstance(episode.perturbation, dict) else {}
    return {
        "episode_id": episode.episode_id, "run_name": episode.run_name, "benchmark": episode.benchmark,
        "created_at": episode.created_at, "instruction": episode.instruction, "outcome": episode.outcome,
        "steps": episode.steps, "elapsed_seconds": episode.elapsed_seconds, "task_id": episode.task_id,
        "episode_index": episode.episode_index, "perturbation": perturbation,
        "failure_detail": None if episode.failure_detail is None else scrub_text(str(episode.failure_detail)),
        "video_url": None if episode.video_path is None else "/media/" + episode.video_path,
        "trace_url": None if episode.trace_path is None else "/api/episodes/{}/trace".format(episode.episode_id),
    }


def evidence_payload(snapshot: CatalogSnapshot) -> Dict[str, Any]:
    """``GET /api/evidence``: every episode with a video link and its outcome (no paths, no raw provenance)."""

    warnings: List[str] = [scrub_text(str(w)) for w in snapshot.warnings]
    return {"episodes": [_episode_row(e) for e in snapshot.episodes], "warnings": warnings}
