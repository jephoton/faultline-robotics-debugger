"""The cases of a pipeline run (ADR 0035): the audit case, the wording case and the clips each one shows.

Pure functions over the Jobs' summaries; nothing here touches the cloud or the run folder. The orchestrator
writes what they return, and :mod:`robot_debug.case_register` finds the clips they name.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from robot_debug.pipeline import severity_text

# Kept equal to ``viewer.library.FAMILY_LABELS`` (a test enforces it): the viewer does not import the Job-side
# modules this package's neighbours pull in, so the table is repeated rather than shared.
FAMILY_LABELS = {
    "darken": "Darkening", "noise": "Gaussian noise", "blur": "Gaussian blur", "contrast": "Contrast reduction",
    "jpeg": "JPEG compression", "colour_cast": "Colour cast", "motion_blur": "Motion blur",
    "dead_pixels": "Dead pixels", "viewpoint": "Camera viewpoint", "lighting": "Scene lighting",
}
REPLAY_ATTEMPTS = 5
REPLAY_REQUIRED_FAILURES = 4


def _severity_key(value: Any) -> Optional[float]:
    return round(float(value), 6) if type(value) in (int, float) else None


def _records(summary: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    return [r for r in (summary.get("items") or ())
            if isinstance(r, Mapping) and r.get("status", "valid") == "valid"
            and r.get("outcome") in ("success", "policy_failure") and isinstance(r.get("case_id"), str)]


def _clip(job: str, record: Mapping[str, Any], label: str) -> Dict[str, Any]:
    return {"case_id": record["case_id"], "outcome": record.get("outcome"), "job": job, "label": label}


def audit_videos(job_summaries: Sequence[Tuple[str, Mapping[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    """The clips an audit case shows, chosen from the group summaries' episode records.

    ``job_summaries`` holds ``(job_name, summary)`` in run order. One clip per role, no more:

    * ``control``: the first unperturbed control attempt of the first group (the first failing one if a
      control failed), labelled "Unperturbed control" (the page shows the outcome beside it);
    * ``<family>@<severity>`` per tested family: at its threshold, the first failing attempt
      ("Gaussian blur at s = 0.50"); for a family that held to the top, the first attempt at the
      highest severity tried ("Scene lighting at s = 1.00").

    A summary with no episode records yields no clip. The entries name the Job and the episode's ``case_id``;
    the registration finds the mp4 under that Job's evidence.
    """

    videos: Dict[str, Dict[str, Any]] = {}
    for job, summary in job_summaries:
        nominal = sorted((r for r in _records(summary) if r.get("kind") == "nominal"), key=lambda r: r["case_id"])
        if nominal and "control" not in videos:
            failed = [r for r in nominal if r["outcome"] == "policy_failure"]
            record = (failed or nominal)[0]
            videos["control"] = _clip(job, record, "Unperturbed control")
    for job, summary in job_summaries:
        records = _records(summary)
        for family, result in (summary.get("families") or {}).items():
            if not isinstance(result, Mapping):
                continue
            label = FAMILY_LABELS.get(family, family)
            threshold = _severity_key(result.get("threshold_severity"))
            levels = [v for v in (_severity_key(l.get("severity")) for l in result.get("levels") or ()
                                  if isinstance(l, Mapping)) if v is not None]
            severity = threshold if threshold is not None else (max(levels) if levels else None)
            if severity is None:
                continue
            at_level = sorted((r for r in records if r.get("family") == family
                               and _severity_key(r.get("severity")) == severity),
                              key=lambda r: (r.get("attempt") or 0, r["case_id"]))
            if not at_level:
                continue
            if threshold is not None:
                chosen = next((r for r in at_level if r["outcome"] == "policy_failure"), None)
            else:
                chosen = next((r for r in at_level if r["outcome"] == "success"), at_level[0])
            if chosen is None:
                continue
            videos["{}@{}".format(family, severity_text(severity))] = _clip(
                job, chosen, "{} at s = {}".format(label, severity_text(severity)))
    return videos


def audit_replay_block(groups: Sequence[Tuple[str, str, Mapping[str, Any]]]) -> Optional[Dict[str, Any]]:
    """What a replay of an audit case needs: per group, the families that failed and their thresholds.

    ``groups`` holds ``(step, job_name, summary)``. ``None`` when no family failed (nothing to replay).
    """

    found = []
    for step, _job, summary in groups:
        families = summary.get("families") or {}
        order = [n for n in ((summary.get("config") or {}).get("families") or ()) if n in families]
        failing = []
        for family in order + [n for n in families if n not in order]:
            severity = _severity_key((families.get(family) or {}).get("threshold_severity"))
            if severity is not None:
                failing.append({"family": family, "severity": severity})
        if failing:
            found.append({"step": step, "families": failing})
    if not found:
        return None
    return {"kind": "audit", "attempts": REPLAY_ATTEMPTS, "required_failures": REPLAY_REQUIRED_FAILURES,
            "groups": found}


def audit_case(*, merged: Mapping[str, Any], suite: str, task: int, start: int, run: str,
               requested: Sequence[str], groups: Sequence[Tuple[str, str, Mapping[str, Any]]],
               summary_path: str, checkpoint: Optional[Tuple[str, str]] = None,
               videos: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """The audit case record of a pipeline run: the stand-alone audit case's shape plus the groups, the clips
    and the replay block. ``summary_path`` is the merged summary, relative to the run folder."""

    families = {name: {"threshold_severity": (merged["families"].get(name) or {}).get("threshold_severity"),
                       "stop_reason": (merged["families"].get(name) or {}).get("stop_reason")}
                for name in sorted(requested)}
    identity = json.dumps({"suite": suite, "task": task, "start": start, "families": sorted(requested),
                           "run": run, "kind": "stress-test"}, sort_keys=True, separators=(",", ":"))
    case: Dict[str, Any] = {
        "schema_version": 1, "kind": "audit", "case_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "suite": suite, "task_id": task, "start_index": start, "families": families,
        "stop_reason": merged.get("stop_reason"), "complete": bool(merged.get("complete")),
        "groups": [{"step": step, "job_name": job,
                    "families": list((summary.get("config") or {}).get("families") or ())}
                   for step, job, summary in groups],
        "summary": summary_path,
    }
    if checkpoint is not None:
        case["checkpoint"] = {"id": checkpoint[0], "revision": checkpoint[1], "pinned": True}
    replay = audit_replay_block(groups)
    if replay is not None:
        case["replay"] = replay
    if videos:
        case["videos"] = copy.deepcopy(dict(videos))
    return case


def wording_rows(summary: Mapping[str, Any], original: str) -> List[Dict[str, Any]]:
    from robot_debug import paraphrase as pp

    rows = []
    for row in summary.get("instructions") or ():
        entry = {key: row.get(key) for key in ("label", "kind", "text", "outcomes", "failures", "decision",
                                                "edit_count")}
        entry["meaning_check"] = (pp.meaning_check(original, row["text"]) if row.get("kind") == "paraphrase"
                                  and isinstance(row.get("text"), str) else None)
        rows.append(entry)
    return rows


def wording_videos(summary: Mapping[str, Any], job: str) -> Dict[str, Dict[str, Any]]:
    """Clips for a wording case that found no failure: the original wording's first control attempt and one
    rewording's first attempt (the first failing one if any rewording failed, else the first rewording)."""

    videos: Dict[str, Dict[str, Any]] = {}
    rows = [r for r in summary.get("instructions") or () if isinstance(r, Mapping)]

    def clip(attempt: Optional[Mapping[str, Any]], label: str) -> Optional[Dict[str, Any]]:
        if attempt is None or not isinstance(attempt.get("video"), str):
            return None
        return {"case_id": attempt.get("case_id"), "outcome": attempt.get("outcome"), "video": attempt["video"],
                "job": job, "label": label}

    control = next((r for r in rows if r.get("kind") == "original"), None)
    if control and control.get("attempts"):
        attempt = control["attempts"][0]
        found = clip(attempt, "Original wording")
        if found:
            videos["control"] = found
    wordings = [r for r in rows if r.get("kind") == "paraphrase" and r.get("attempts")]
    failing = [r for r in wordings if any(a.get("outcome") == "policy_failure" for a in r["attempts"])]
    if wordings:
        row = (failing or wordings)[0]
        attempts = row["attempts"]
        attempt = next((a for a in attempts if a.get("outcome") == "policy_failure"), attempts[0])
        found = clip(attempt, 'Reworded "{}"'.format(row.get("text")))
        if found:
            videos["reworded"] = found
    return videos


def wording_case_without_failure(*, screen: Mapping[str, Any], run: str, stop_reason: Optional[str],
                                 job: str) -> Dict[str, Any]:
    """The wording case of a rewording probe that produced no verified failing wording: it records what was
    tried ("these rewordings pass") and why it ended. Not replayable; its ``minimal`` is ``None``."""

    original = screen["original"]
    identity = json.dumps({"suite": screen.get("suite"), "task": screen["task_id"],
                           "start": screen["init_state_index"], "original": original, "run": run,
                           "kind": "rewording-screen"}, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": 1, "kind": "paraphrase_reduction",
        "case_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "suite": screen.get("suite"), "checkpoint": copy.deepcopy(screen.get("checkpoint")),
        "task_id": screen["task_id"], "start_index": screen["init_state_index"], "instruction": original,
        "paraphrase": None, "failure": False, "reduced": False, "stop_reason": stop_reason, "minimal": None,
        "replay": None, "videos": wording_videos(screen, job), "screen": wording_rows(screen, original),
        "evidence": [], "explanation": None,
        "measurements": {"total_seconds": screen.get("total_seconds")},
    }


def with_wording_clips(case: Dict[str, Any], screen: Mapping[str, Any], job: str) -> Dict[str, Any]:
    """A reduced-wording case with labels on its clips (the reduction recorded original, reference and minimal)
    and, when it recorded none, the control and rewording clips of the screen."""

    labels = {"original": "Failing rewording", "reference": "Original wording",
              "minimal": "Minimal wording change"}
    videos = case.get("videos") if isinstance(case.get("videos"), dict) else {}
    if not videos:
        videos = wording_videos(screen, job)
    else:
        for role, entry in videos.items():
            if isinstance(entry, dict) and role in labels and "label" not in entry:
                entry["label"] = labels[role]
                entry.setdefault("job", None)
    case["videos"] = videos
    return case
