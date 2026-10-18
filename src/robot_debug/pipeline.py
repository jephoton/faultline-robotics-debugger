"""Pure helpers of the one-diagnosis pipeline (ADR 0035): probe grouping, merging, findings and texts.

Nothing here touches the cloud, the simulator or the run folder; the orchestrator and the control panel use
these to plan, merge and describe the work, and the tests exercise them directly.

Probe grouping
    One audit (``m6-threshold``) Job is limited by its deadline (``m6_experiment`` caps it at 2400 s, 3000 s
    for LIBERO-10), so ten families do not fit in one Job. :func:`probe_groups` splits the chosen families into the
    fewest balanced groups that each fit: image families first (they act on the pictures the policy
    receives), then the scene families (viewpoint, lighting; they act once, at reset).

Cost rule for the dry run
    ``typical_usd`` of a Job is ``TYPICAL_FRACTION`` (0.5) of its worst case. That is the ratio the
    October 18 measurements gave for probe Jobs (about US$0.4-0.9 spent against US$1.2-1.4 reserved). It is
    an estimate, not a promise; where nothing has been measured (the layout reduction) the typical cost is
    unknown and reported as ``None``.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from robot_debug import m6_experiment
from robot_debug.workloads import DEFAULT_AUDIT_SEARCH

TYPICAL_FRACTION = 0.5
ROUTES = ("layout", "probes", "passes", "flaky")
BRANCHES = ("check", "layout", "probes")


class ProbeGroup(NamedTuple):
    step: str                          # the run step (and Job name part), for example ``probe-image-1``
    kind: str                          # ``image`` or ``scene``
    families: Tuple[str, ...]
    deadline_seconds: int


def _fits(suite: str, families: Sequence[str]) -> Optional[int]:
    """The recommended deadline of an audit Job for these families, or ``None`` when it does not fit."""

    config = {"families": list(families), "sweep": list(DEFAULT_AUDIT_SEARCH["sweep"]),
              "attempts": DEFAULT_AUDIT_SEARCH["attempts"],
              "bisection_steps": DEFAULT_AUDIT_SEARCH["bisection_steps"], "suite": suite}
    try:
        return m6_experiment.recommended_deadline_seconds("m6-threshold", config)
    except ValueError:
        return None


def _balanced(items: Sequence[str], groups: int) -> List[List[str]]:
    base, extra = divmod(len(items), groups)
    result, position = [], 0
    for index in range(groups):
        size = base + (1 if index < extra else 0)
        result.append(list(items[position:position + size]))
        position += size
    return result


def probe_groups(suite: str, families: Sequence[str]) -> List[ProbeGroup]:
    """Split ``families`` into audit Jobs that each fit the deadline cap of ``suite``.

    Image families and scene families never share a Job. Each kind uses the fewest balanced groups that
    fit (ten families on LIBERO-Object: image 4 + 4, scene 2). Raises ``ValueError`` when a single family
    cannot fit.
    """

    chosen = set(families)
    ordered = [name for name in m6_experiment.FAMILIES if name in chosen]
    result: List[ProbeGroup] = []
    for kind, members in (("image", m6_experiment.IMAGE_FAMILIES), ("scene", m6_experiment.SCENE_FAMILIES)):
        names = [name for name in ordered if name in members]
        if not names:
            continue
        for count in range(1, len(names) + 1):
            groups = _balanced(names, count)
            deadlines = [_fits(suite, group) for group in groups]
            if all(deadline is not None for deadline in deadlines):
                break
        else:
            raise ValueError("a single {} family does not fit in one audit Job on {}".format(kind, suite))
        for number, (group, deadline) in enumerate(zip(groups, deadlines), 1):
            result.append(ProbeGroup("probe-{}-{}".format(kind, number), kind, tuple(group), int(deadline)))
    return result


def severity_text(value: float) -> str:
    """A severity with at least two decimals and no trailing zeros beyond them: 0.5 -> 0.50, 0.4125 -> 0.4125."""

    text = "{:.4f}".format(float(value)).rstrip("0")
    whole, _dot, fraction = text.partition(".")
    return "{}.{}".format(whole, fraction.ljust(2, "0"))


def typical_cost(worst_case_usd: float) -> float:
    return round(worst_case_usd * TYPICAL_FRACTION, 2)


# --------------------------------------------------------------------------------------
# Audit summaries from several Jobs
# --------------------------------------------------------------------------------------


def merge_audit_summaries(summaries: Sequence[Mapping[str, Any]], requested: Sequence[str]) -> Dict[str, Any]:
    """One ``m6-threshold``-shaped summary from the group summaries, in the order the groups ran.

    ``requested`` is every family the pipeline meant to test; a family no group reached (the run stopped
    first) appears as ``not_run``, which the case page words as "not tested". The unperturbed control kept is
    the first one that failed, else the first. ``complete`` holds only when every group completed.
    """

    families: Dict[str, Any] = {}
    nominal: Optional[Mapping[str, Any]] = None
    stop_reason: Optional[str] = None
    order: List[str] = []
    complete = bool(summaries)
    for summary in summaries:
        families.update(copy.deepcopy(dict(summary.get("families") or {})))
        order.extend(name for name in ((summary.get("config") or {}).get("families") or ()) if name not in order)
        control = summary.get("nominal_controls")
        failed = isinstance(control, Mapping) and bool((control.get("outcomes") or {}).get("policy_failure"))
        if isinstance(control, Mapping) and (nominal is None or (failed and not _control_failed(nominal))):
            nominal = control
        if stop_reason is None and summary.get("stop_reason"):
            stop_reason = str(summary["stop_reason"])
        complete = complete and bool(summary.get("complete")) and not summary.get("stop_reason")
    for name in requested:
        if name not in families:
            families[name] = {"threshold_severity": None, "stop_reason": "not_run", "levels": []}
            complete = False
        if name not in order:
            order.append(name)
    config = copy.deepcopy(dict((summaries[0].get("config") or {}) if summaries else {}))
    config["families"] = order
    return {"schema_version": 1, "mode": "m6-threshold", "config": config, "families": families,
            "nominal_controls": copy.deepcopy(dict(nominal)) if nominal else None,
            "stop_reason": stop_reason, "complete": complete}


def _control_failed(control: Mapping[str, Any]) -> bool:
    return bool((control.get("outcomes") or {}).get("policy_failure"))


def audit_control_failed(summary: Mapping[str, Any]) -> bool:
    """The audit Job stopped because its unperturbed control did not pass: the start is flaky."""

    return summary.get("stop_reason") == "nominal_controls_failed"


# --------------------------------------------------------------------------------------
# Replay texts
# --------------------------------------------------------------------------------------

REPLAY_TEXTS = {
    ("audit", "no_longer_reproduces"): "The stress test no longer fails: no family fails at its threshold.",
    ("audit", "reference_fails"): ("Inconclusive: the unperturbed control did not pass reliably, so no disturbance "
                                   "can be judged."),
    ("audit", "invalid_scene"): "Inconclusive: a scene was invalid, so the replay says nothing about the policy.",
    ("paraphrase", "still_reproduces"): "The wording still fails.",
    ("paraphrase", "no_longer_reproduces"): "The wording no longer fails.",
    ("paraphrase", "reference_fails"): ("Inconclusive: the original wording did not pass both control attempts, so "
                                        "a failing wording cannot be attributed to the wording."),
}


def audit_replay_text(failing: Sequence[Tuple[str, float]], gone: Sequence[str]) -> str:
    """The audit replay verdict sentence: ``still fails at s = 0.50 (blur)`` for each family that still fails."""

    if not failing:
        return "no longer fails"
    parts = ["still fails at s = {} ({})".format(severity_text(severity), family) for family, severity in failing]
    text = "; ".join(parts)
    if gone:
        text += "; no longer fails: {}".format(", ".join(gone))
    return text


def replay_kind_text(kind: str, verdict: Optional[str]) -> Optional[str]:
    return REPLAY_TEXTS.get((kind, verdict))
