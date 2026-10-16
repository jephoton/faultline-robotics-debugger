"""The optional policy checkpoint override of a workload (``policy.checkpoint`` in a spec).

By default a Job serves the pinned GR00T checkpoint of its suite (``job_entry.SUITE_CHECKPOINTS``).
A spec may instead name one Hugging Face model repository and one commit of it, so a saved case can be
replayed against a changed policy. The pair travels in the workload as ``checkpoint_id`` and
``checkpoint_revision``; both are present or both are absent, and absent keeps every existing workload
byte-identical.

Runs on the workstation (spec validation, workload builders) and inside the simulator image
(Python 3.8), so this module is standard library only.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional, Tuple

ID_KEY = "checkpoint_id"
REVISION_KEY = "checkpoint_revision"
FIELDS = (ID_KEY, REVISION_KEY)

# ``org/name`` with the characters Hugging Face allows, starting with a letter or digit.
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-]{0,95}/[A-Za-z0-9][A-Za-z0-9._\-]{0,95}\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")
# Pinned separately by the prefetch (the base model every GR00T checkpoint loads, and the vision-language
# model); a checkpoint override must not replace their pins.
RESERVED_IDS = ("nvidia/GR00T-N1.7-3B", "nvidia/Cosmos-Reason2-2B")


class CheckpointOverrideError(ValueError):
    """The override is invalid; the message names the problem and never echoes more than the id."""


def validate_id(checkpoint_id: Any) -> str:
    if type(checkpoint_id) is not str or _ID.fullmatch(checkpoint_id) is None or ".." in checkpoint_id:
        raise CheckpointOverrideError("must look like org/name (letters, digits, '.', '_' and '-')")
    if checkpoint_id in RESERVED_IDS:
        raise CheckpointOverrideError("may not be a model the prefetch pins separately")
    return checkpoint_id


def validate_revision(revision: Any) -> str:
    if type(revision) is not str or _REVISION.fullmatch(revision) is None:
        raise CheckpointOverrideError("must be a full 40-character lowercase hex commit")
    return revision


def validate_pair(checkpoint_id: Any, revision: Any) -> Tuple[str, str]:
    """``(id, revision)`` when both are well formed, else :class:`CheckpointOverrideError`."""

    try:
        return validate_id(checkpoint_id), validate_revision(revision)
    except CheckpointOverrideError as error:
        raise CheckpointOverrideError("checkpoint " + str(error)) from None


def from_config(config: Mapping[str, Any]) -> Optional[Tuple[str, str]]:
    """The validated ``(id, revision)`` of a workload configuration, or ``None`` when it has no override.

    Raises :class:`CheckpointOverrideError` when only one of the two fields is present or either is invalid.
    """

    present = [key for key in FIELDS if key in config]
    if not present:
        return None
    if len(present) != 2:
        raise CheckpointOverrideError("checkpoint_id and checkpoint_revision must be given together")
    return validate_pair(config[ID_KEY], config[REVISION_KEY])


def as_fields(pair: Optional[Tuple[str, str]]) -> Dict[str, str]:
    """The workload fields for an override (empty for none), so a builder can ``update`` with the result."""

    if pair is None:
        return {}
    checkpoint_id, revision = validate_pair(pair[0], pair[1])
    return {ID_KEY: checkpoint_id, REVISION_KEY: revision}


__all__ = [
    "CheckpointOverrideError", "FIELDS", "ID_KEY", "RESERVED_IDS", "REVISION_KEY", "as_fields",
    "from_config", "validate_id", "validate_pair", "validate_revision",
]
