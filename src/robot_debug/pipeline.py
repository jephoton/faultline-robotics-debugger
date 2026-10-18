"""Pure helpers of the one-diagnosis pipeline (ADR 0035): probe grouping, merging, findings and texts.

Nothing here touches the cloud, the simulator or the run folder; the orchestrator and the control panel use
these to plan, merge and describe the work, and the tests exercise them directly.

Probe grouping
    One audit (``m6-threshold``) Job is limited by its deadline (``m6_experiment`` caps it at 2400 s, 3000 s
    for LIBERO-10), so ten families do not fit in one Job. :func:`probe_groups` splits the chosen families into the
    fewest balanced groups that each fit: image families first (they act on the pictures the policy
    receives), then the scene families (viewpoint, lighting; they act once, at reset).

Typical cost and time for the dry run
    The worst case is what the ledger reserves; the *typical* figures say what a Job usually takes and costs.
    They come from measured runs (see the constants below) and are estimates, not promises. A Job's typical
    container minutes are modelled by :func:`typical_container_minutes`; its typical cost is those minutes at
    the hourly rate plus the start allowance, as the ledger settles it (:func:`typical_cost`); its typical
    end-to-end minutes add the time to submit and download (:func:`typical_total_minutes`). GPU waits for
    capacity are not included.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from robot_debug import m6_experiment
from robot_debug.workloads import DEFAULT_AUDIT_SEARCH

# --- measured references behind the typical figures (container minutes / US$ at US$1.7468/h) ---------------
#   screen (the check):                                         10.6 min / US$0.43
#   audit blur+noise+darken+contrast, LIBERO-Object:            20.4 min / US$0.59 (12.7 min of testing)
#   audit jpeg+colour_cast+motion_blur+dead_pixels, LIBERO-Spatial: 24.3 min / US$0.82
#   audit viewpoint+lighting:                                    9.6 min / US$0.40
#   layout reduce Jobs:                                          18-21 min / US$0.65-0.72
#   rewording screen:                                            7-8 min / US$0.31-0.35
#   replay:                                                      10.2 min / US$0.41
# An audit Job is modelled as a fixed start-up plus a per-family cost (the measurements above give about
# 8 min plus 3-5 min per family; 4 is used), never more than the Job's own deadline.
TYPICAL_CHECK_MINUTES = 10.6
TYPICAL_LAYOUT_MINUTES = 19.5            # the middle of 18-21
TYPICAL_REWORDING_SCREEN_MINUTES = 7.5   # the middle of 7-8
TYPICAL_REWORDING_REDUCE_MINUTES = 19.5  # not measured: the layout figure; the Job is optional and never counted
TYPICAL_REPLAY_MINUTES = 10.2
TYPICAL_AUDIT_STARTUP_MINUTES = 8.0
TYPICAL_AUDIT_FAMILY_MINUTES = 4.0
TYPICAL_START_ALLOWANCE_MINUTES = 4.0    # ledger.DEFAULT_START_ALLOWANCE_SECONDS, billed on every Job
TYPICAL_OVERHEAD_MINUTES = 5.0           # submitting the Job and downloading its evidence, on this machine
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


def typical_container_minutes(kind: str, families: int = 0, deadline_seconds: Optional[float] = None) -> float:
    """Typical container minutes of one Job: ``check``, ``layout``, ``probe`` (``families`` of them),
    ``rewording-screen``, ``rewording-reduce`` or ``replay``. Clamped to the Job's deadline when given."""

    if kind == "probe":
        minutes = TYPICAL_AUDIT_STARTUP_MINUTES + TYPICAL_AUDIT_FAMILY_MINUTES * families
    else:
        minutes = {"check": TYPICAL_CHECK_MINUTES, "layout": TYPICAL_LAYOUT_MINUTES,
                   "rewording-screen": TYPICAL_REWORDING_SCREEN_MINUTES,
                   "rewording-reduce": TYPICAL_REWORDING_REDUCE_MINUTES, "replay": TYPICAL_REPLAY_MINUTES}[kind]
    if deadline_seconds is not None:
        minutes = min(minutes, deadline_seconds / 60.0)
    return minutes


def typical_cost(container_minutes: float, hourly_usd: float) -> float:
    """What a Job of this many container minutes costs: the minutes plus the start allowance at the rate."""

    return (container_minutes + TYPICAL_START_ALLOWANCE_MINUTES) / 60.0 * hourly_usd


def typical_total_minutes(container_minutes: float) -> float:
    """End to end for the person waiting: the container minutes plus submitting and downloading."""

    return container_minutes + TYPICAL_OVERHEAD_MINUTES


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
    ("audit", "no_longer_reproduces"): "no longer fails",
    ("audit", "reference_fails"): ("Inconclusive: the unperturbed control did not pass reliably, so no disturbance "
                                   "can be judged."),
    ("audit", "incomplete"): "Inconclusive: the replay Job did not finish, so nothing can be said about the policy.",
    ("paraphrase", "still_reproduces"): "the wording still fails",
    ("paraphrase", "no_longer_reproduces"): "no longer fails",
    ("paraphrase", "reference_fails"): ("Inconclusive: the original wording did not pass both control attempts, so "
                                        "a failing wording cannot be attributed to the wording."),
    ("paraphrase", "incomplete"): "Inconclusive: the replay Job did not finish, so nothing can be said about the policy.",
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
