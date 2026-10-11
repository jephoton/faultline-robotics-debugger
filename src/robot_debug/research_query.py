"""Deterministic public-research queries built from allowlisted case descriptors.

Only fixed product constants, the suite, the reduced occlusion rectangle's
coarse placement and rounded area reach a query. No episode identifier, stage
name, path, log text or recording can influence the output.
"""

from __future__ import annotations

import math

from .evidence_packet import EvidencePacketError, validate_evidence_packet


class ResearchQueryError(ValueError):
    """The packet cannot produce safe research queries."""


_ERROR = "cannot build research queries"
_MAX_QUERY = 200
_SUITE_NAMES = {"libero-object": "LIBERO-Object"}
# Fixed wording for known LIBERO-Object tasks; anything else is generic.
_TASK_WORDING = {0: "pick up the alphabet soup and place it in the basket"}
_GENERIC_TASK = "pick-and-place"
_TEMPLATES = (
    "vision-language-action policy robustness to camera occlusion robot manipulation",
    "GR00T N1 {suite} visual perturbation failure",
    "robot policy fails when {region} {area}% of camera image is occluded pick-and-place",
)


def task_wording(task_id: int) -> str:
    """Fixed natural-language task description, generic for unknown tasks."""
    return _TASK_WORDING.get(task_id, _GENERIC_TASK)


def region_phrase(rectangle: dict) -> str:
    """Placement by rectangle centre over fixed thirds; origin top-left."""
    centre_x = rectangle["x"] + rectangle["width"] / 2
    centre_y = rectangle["y"] + rectangle["height"] / 2
    row = "upper" if centre_y * 3 < 1 else "lower" if centre_y * 3 > 2 else "middle"
    column = "left" if centre_x * 3 < 1 else "right" if centre_x * 3 > 2 else "center"
    if row == "middle":
        return "center" if column == "center" else "middle-" + column
    return row + "-" + column


def area_percent(rectangle: dict) -> int:
    """Image-area percentage rounded half up to a whole number, at least 1."""
    percent = rectangle["width"] * rectangle["height"] * 100
    return max(1, int(math.floor(percent + 0.5)))


def build_queries(packet: dict) -> list[str]:
    """Return three fixed-template queries for a validated v2 evidence packet."""
    try:
        validated = validate_evidence_packet(packet)
    except EvidencePacketError:
        raise ResearchQueryError(_ERROR) from None
    if validated["schema_version"] != 2:
        raise ResearchQueryError(_ERROR)
    rectangle = validated["reduced_mask"]["rectangle"]
    values = {
        "suite": _SUITE_NAMES[validated["task"]["suite"]],
        "region": region_phrase(rectangle),
        "area": area_percent(rectangle),
    }
    queries = [template.format(**values) for template in _TEMPLATES]
    for query in queries:
        if len(query) > _MAX_QUERY or not query.isascii() or not query.isprintable():
            raise ResearchQueryError(_ERROR)
    return queries
