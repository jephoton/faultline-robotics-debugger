"""Fetch the GR00T model inputs into a fresh, job-private Hugging Face cache.

Runs only in the image's model environment, before the offline model server.
Pinned repositories are fetched by commit and the private cache's ``main``
reference is pointed at that commit, matching the historical VM's offline
``local_files_only`` check. Cosmos was never pinned historically, so its
current ``main`` is fetched and its resolved commit recorded.

One Job serves one suite from one model server, so ``--suite`` selects which
suite checkpoint is fetched (default ``libero_object``, the historical set);
``--suite all`` fetches every pinned checkpoint.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Dict, Optional, Sequence


# Must equal ``robot_debug.job_entry.SUITE_CHECKPOINTS`` (a test enforces it).
SUITE_CHECKPOINTS = {
    "libero_object": "nvidia/gr00t17-lerobot-libero_object-640",
    "libero_10": "nvidia/gr00t17-lerobot-libero_10-640",
}
DEFAULT_SUITE = "libero_object"
BASE_MODEL = "nvidia/GR00T-N1.7-3B"
PINNED_REVISIONS = {
    "nvidia/gr00t17-lerobot-libero_object-640": "1499db357f6ca3762b56c2e8c00b530eb9a09444",
    # Resolved from the Hugging Face model API (current main) on October 13, 2026.
    "nvidia/gr00t17-lerobot-libero_10-640": "5ee08ab09fac5c5ef2388a14c882ea825ac861db",
    BASE_MODEL: "2fc962b973bccdd5d8ce4f67cc63b264d6886495",
}
RESOLVED_REPOSITORIES = ("nvidia/Cosmos-Reason2-2B",)


def pinned_for_suite(suite: Optional[str]) -> Dict[str, str]:
    """The pinned repositories one Job needs: its suite checkpoint plus the base model.

    ``None`` means the historical default suite; ``"all"`` means every pin.
    """

    if suite == "all":
        return dict(PINNED_REVISIONS)
    name = DEFAULT_SUITE if suite is None else suite
    if name not in SUITE_CHECKPOINTS:
        raise ValueError("unknown suite: {!r}".format(suite))
    checkpoint = SUITE_CHECKPOINTS[name]
    return {checkpoint: PINNED_REVISIONS[checkpoint], BASE_MODEL: PINNED_REVISIONS[BASE_MODEL]}


def _repository_dir(cache: Path, repository: str) -> Path:
    return cache / ("models--" + repository.replace("/", "--"))


def fetch(hub: ModuleType, cache: Path, suite: Optional[str] = None) -> Dict[str, Dict[str, object]]:
    resolution: Dict[str, Dict[str, object]] = {}
    for repository, revision in pinned_for_suite(suite).items():
        downloaded = Path(hub.snapshot_download(repo_id=repository, revision=revision))
        if downloaded.name != revision:
            raise RuntimeError("pinned snapshot did not match its revision: " + repository)
        refs = _repository_dir(cache, repository) / "refs"
        refs.mkdir(parents=True, exist_ok=True)
        (refs / "main").write_text(revision, encoding="ascii")
        offline = Path(hub.snapshot_download(repo_id=repository, local_files_only=True))
        if offline.name != revision:
            raise RuntimeError("offline resolution did not match the pinned revision: " + repository)
        resolution[repository] = {"revision": revision, "pinned": True}
    for repository in RESOLVED_REPOSITORIES:
        downloaded = Path(hub.snapshot_download(repo_id=repository, revision="main"))
        offline = Path(hub.snapshot_download(repo_id=repository, local_files_only=True))
        if offline.name != downloaded.name:
            raise RuntimeError("offline resolution did not match the fetched revision: " + repository)
        resolution[repository] = {"revision": downloaded.name, "pinned": False}
    return resolution


def main(argv: Optional[Sequence[str]] = None, hub: Optional[ModuleType] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--suite", choices=sorted(SUITE_CHECKPOINTS) + ["all"], default=DEFAULT_SUITE)
    args = parser.parse_args(argv)
    if hub is None:
        import huggingface_hub as hub  # type: ignore[no-redef]
        import huggingface_hub.constants  # noqa: F401
    cache = Path(hub.constants.HF_HUB_CACHE)
    resolution = fetch(hub, cache, args.suite)
    payload = json.dumps({"schema_version": 1, "repositories": resolution}, sort_keys=True, indent=2)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(payload + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
