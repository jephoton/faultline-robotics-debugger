"""Fetch the GR00T model inputs into a fresh, job-private Hugging Face cache.

Runs only in the image's model environment, before the offline model server.
Pinned repositories are fetched by commit and the private cache's ``main``
reference is pointed at that commit, matching the historical VM's offline
``local_files_only`` check. Cosmos-Reason2-2B is pinned too, to the commit every Job
recorded before it was pinned.

One Job serves one suite from one model server, so ``--suite`` selects which
suite checkpoint is fetched (default ``libero_object``, the historical set);
``--suite all`` fetches every pinned checkpoint. ``--checkpoint-id`` with ``--checkpoint-revision`` (both or
neither) fetches that exact repository at that commit instead of the suite's pinned checkpoint, for a spec
that tests another policy (``policy.checkpoint``); the base model and Cosmos stay pinned.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from types import ModuleType
from typing import Dict, Optional, Sequence, Tuple


# Must equal ``robot_debug.job_entry.SUITE_CHECKPOINTS`` (a test enforces it).
SUITE_CHECKPOINTS = {
    "libero_object": "nvidia/gr00t17-lerobot-libero_object-640",
    "libero_10": "nvidia/gr00t17-lerobot-libero_10-640",
    "libero_spatial": "nvidia/gr00t17-lerobot-libero_spatial-640",
    "libero_goal": "nvidia/gr00t17-lerobot-libero_goal-640",
}
DEFAULT_SUITE = "libero_object"
BASE_MODEL = "nvidia/GR00T-N1.7-3B"
PINNED_REVISIONS = {
    "nvidia/gr00t17-lerobot-libero_object-640": "1499db357f6ca3762b56c2e8c00b530eb9a09444",
    # Resolved from the Hugging Face model API (current main) on October 13, 2026.
    "nvidia/gr00t17-lerobot-libero_10-640": "5ee08ab09fac5c5ef2388a14c882ea825ac861db",
    # Resolved from the Hugging Face model API (current main) on October 15, 2026.
    "nvidia/gr00t17-lerobot-libero_spatial-640": "32a6ec786d6509df31b40392b4e4dcdda78c0f11",
    "nvidia/gr00t17-lerobot-libero_goal-640": "436c57c0eb7a90be54270abf3977668b2084ad75",
    BASE_MODEL: "2fc962b973bccdd5d8ce4f67cc63b264d6886495",
}
# Fetched for every suite. Kept apart from PINNED_REVISIONS, which lists the per-suite model inputs
# (a test compares those with the design record); fetched and recorded the same way, as pinned.
SHARED_PINNED_REVISIONS = {
    "nvidia/Cosmos-Reason2-2B": "9ce19a195e423419c349abfc86fd07178b230561",
}


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


def fetch(hub: ModuleType, cache: Path, suite: Optional[str] = None,
          checkpoint: Optional[Tuple[str, str]] = None) -> Dict[str, Dict[str, object]]:
    resolution: Dict[str, Dict[str, object]] = {}
    pins = dict(pinned_for_suite(suite))
    if checkpoint is not None:
        identifier, revision = checkpoint
        if identifier == BASE_MODEL or identifier in SHARED_PINNED_REVISIONS:
            raise ValueError("a checkpoint override cannot replace a separately pinned model: " + identifier)
        # The override replaces the suite's own checkpoint; the base model stays pinned.
        pins = {BASE_MODEL: PINNED_REVISIONS[BASE_MODEL], identifier: revision}
    pins.update(SHARED_PINNED_REVISIONS)
    for repository, revision in pins.items():
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
    return resolution


def main(argv: Optional[Sequence[str]] = None, hub: Optional[ModuleType] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--suite", choices=sorted(SUITE_CHECKPOINTS) + ["all"], default=DEFAULT_SUITE)
    parser.add_argument("--checkpoint-id", help="serve this repository instead of the suite's checkpoint")
    parser.add_argument("--checkpoint-revision", help="the 40-character commit of --checkpoint-id")
    args = parser.parse_args(argv)
    checkpoint = None
    if args.checkpoint_id is not None or args.checkpoint_revision is not None:
        if args.checkpoint_id is None or args.checkpoint_revision is None:
            parser.error("--checkpoint-id and --checkpoint-revision go together")
        if re.fullmatch(r"[0-9a-f]{40}", args.checkpoint_revision) is None or re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._\-]{0,95}/[A-Za-z0-9][A-Za-z0-9._\-]{0,95}", args.checkpoint_id) is None \
                or ".." in args.checkpoint_id:
            parser.error("--checkpoint-id must look like org/name and --checkpoint-revision be a full commit")
        checkpoint = (args.checkpoint_id, args.checkpoint_revision)
    if hub is None:
        import huggingface_hub as hub  # type: ignore[no-redef]
        import huggingface_hub.constants  # noqa: F401
    cache = Path(hub.constants.HF_HUB_CACHE)
    try:
        resolution = fetch(hub, cache, args.suite, checkpoint)
    except ValueError as error:
        parser.error(str(error))
    payload = json.dumps({"schema_version": 1, "repositories": resolution}, sort_keys=True, indent=2)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(payload + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
