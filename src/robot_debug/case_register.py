"""Register finished ``faultline diagnose`` runs as viewer-visible diagnoses.

The occlusion case store (:mod:`robot_debug.case_store`) binds each case to a private source
folder and revalidates it against that folder's vla-eval aggregates, a schema built for
perturbed-image episodes. A scenario or audit diagnosis has none of that evidence layout, so it
gets a small parallel index instead, ``<artifacts>/diagnoses/<case_id>/``, and the occlusion store
stays untouched::

    diagnosis.json      the index entry (summary fields, file names, video roles)
    report.md           the Markdown report
    case.json           the case record written by report_scenario_reduction.py (when there is one)
    explanation.json    the stored explanation record (when there is one)
    minimal-candidate.json   the replayable minimal scene (when there is one)
    videos/<role>.mp4   the original, minimal and reference videos found in the run's Job evidence

Everything is copied, so a diagnosis survives cleaning up the run folder, and the viewer serves
the videos under its artifact root (``/media/diagnoses/<case_id>/videos/<role>.mp4``). Entries hold
only relative names, never local paths. Registering the same run again replaces its entry.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Dict, List, Mapping, Optional

SCHEMA_VERSION = 1
INDEX_NAME = "diagnosis.json"
DIAGNOSES_DIR = "diagnoses"
VIDEO_ROLES = ("original", "minimal", "reference")
_CASE_ID = re.compile(r"[0-9a-f]{64}\Z")
_MAX_JSON_BYTES = 4 * 1024 * 1024
_MAX_REPORT_BYTES = 1024 * 1024
_MAX_VIDEO_BYTES = 256 * 1024 * 1024
_SPEC_FIELD = re.compile(r"^(mode|name):\s*([A-Za-z0-9_.-]+)\s*(?:#.*)?$", re.MULTILINE)


class RegisterError(ValueError):
    """The run folder cannot be registered; the message says why."""


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not path.is_file() or path.stat().st_size > _MAX_JSON_BYTES:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _spec_fields(run_dir: Path) -> Dict[str, str]:
    try:
        text = (run_dir / "spec.yaml").read_text(encoding="utf-8")
    except OSError:
        return {}
    return {key: value for key, value in _SPEC_FIELD.findall(text)}


def default_root(run_dir: Path) -> Path:
    """``artifacts/diagnoses`` beside ``artifacts/runs`` for a run folder under ``artifacts/runs``."""

    return Path(run_dir).resolve().parent.parent / DIAGNOSES_DIR


def _safe_child(base: Path, relative: Any) -> Optional[Path]:
    """``base/relative`` if it is an existing ordinary file inside ``base``, else ``None``."""

    if type(relative) is not str or not relative or "\\" in relative or relative.startswith("/"):
        return None
    if any(part in ("", ".", "..") for part in relative.split("/")):
        return None
    candidate = base / relative
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(base.resolve(strict=True))
    except (OSError, ValueError):
        return None
    if candidate.is_symlink() or not resolved.is_file():
        return None
    return resolved


def _job_scenario_dirs(run_dir: Path) -> List[Path]:
    """Every Job's ``scenario`` evidence folder, newest Job name first."""

    found = []
    jobs = run_dir / "jobs"
    if jobs.is_dir():
        for job in sorted((p for p in jobs.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
            evidence = job / "evidence" / "faultline-runs"
            if evidence.is_dir():
                for run in sorted((p for p in evidence.iterdir() if p.is_dir()), key=lambda p: p.name):
                    scenario = run / "scenario"
                    if scenario.is_dir():
                        found.append(scenario)
    return found


def _find_video(scenario_dirs: List[Path], relative: Any) -> Optional[Path]:
    for scenario in scenario_dirs:
        found = _safe_child(scenario, relative)
        if found is not None and found.suffix.lower() == ".mp4" and found.stat().st_size <= _MAX_VIDEO_BYTES:
            return found
    return None


def _case_identity(case: Optional[Mapping[str, Any]], run_dir: Path) -> str:
    if case is not None and isinstance(case.get("case_id"), str) and _CASE_ID.fullmatch(case["case_id"]):
        return case["case_id"]
    return hashlib.sha256(("diagnosis:" + run_dir.name).encode("utf-8")).hexdigest()


def _summary(case: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    case = case or {}
    minimal = case.get("minimal") if isinstance(case.get("minimal"), Mapping) else {}
    hypothesis = case.get("hypothesis") if isinstance(case.get("hypothesis"), Mapping) else {}
    return {
        "case_kind": case.get("kind"), "suite": case.get("suite"), "task_id": case.get("task_id"),
        "instruction": case.get("instruction"), "failing_start": case.get("failing_start"),
        "reference_start": case.get("reference_start"), "reduced": case.get("reduced"),
        "stop_reason": case.get("stop_reason"), "sentence": minimal.get("sentence"),
        "entity_minimal": minimal.get("entity_minimal"),
        "hypothesis_verdict": hypothesis.get("measured_verdict"),
    }


def register_run(run_dir: Any, root: Any = None) -> str:
    """Register one diagnosis run folder and return its case id.

    ``run_dir`` has the layout written by ``faultline diagnose`` (``spec.yaml``, ``report.md``,
    ``case.json``, ``minimal-candidate.json``, ``explanation.json`` and ``jobs/<job>/evidence/...``);
    every part is optional except that one of ``report.md`` or ``case.json`` must exist. ``root``
    is the diagnoses folder (default: ``diagnoses`` beside the run folder's ``runs`` parent).
    The case id is the case record's own id, or a digest of the run folder name for a run without
    a case (an audit).
    """

    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise RegisterError("the run folder does not exist")
    report_path, case_path = run_dir / "report.md", run_dir / "case.json"
    case = _read_json(case_path)
    if case_path.exists() and case is None:
        raise RegisterError("case.json is not a valid JSON object")
    if not report_path.is_file() and case is None:
        raise RegisterError("the run has neither a report nor a case record yet")
    if report_path.is_file() and report_path.stat().st_size > _MAX_REPORT_BYTES:
        raise RegisterError("report.md is too large")
    case_id = _case_identity(case, run_dir)
    target_root = Path(root) if root is not None else default_root(run_dir)
    target_root.mkdir(parents=True, exist_ok=True)
    target = target_root / case_id

    spec = _spec_fields(run_dir)
    staging = Path(tempfile.mkdtemp(prefix=".register-", dir=str(target_root)))
    try:
        files = {}  # type: Dict[str, Optional[str]]
        for key, name in (("report", "report.md"), ("case", "case.json"), ("explanation", "explanation.json"),
                          ("candidate", "minimal-candidate.json")):
            source = run_dir / name
            if source.is_file() and not source.is_symlink() and source.stat().st_size <= _MAX_JSON_BYTES:
                shutil.copyfile(str(source), str(staging / name))
                files[key] = name
            else:
                files[key] = None
        videos = {}  # type: Dict[str, Optional[Dict[str, Any]]]
        scenario_dirs = _job_scenario_dirs(run_dir)
        recorded = case.get("videos") if case is not None and isinstance(case.get("videos"), Mapping) else {}
        for role in VIDEO_ROLES:
            entry = recorded.get(role) if isinstance(recorded.get(role), Mapping) else None
            found = None if entry is None else _find_video(scenario_dirs, entry.get("video"))
            if found is None:
                videos[role] = None
                continue
            (staging / "videos").mkdir(exist_ok=True)
            shutil.copyfile(str(found), str(staging / "videos" / (role + ".mp4")))
            videos[role] = {"file": "videos/{}.mp4".format(role), "outcome": entry.get("outcome"),
                            "case_id": entry.get("case_id")}
        explanation = _read_json(run_dir / "explanation.json")
        index = {
            "schema_version": SCHEMA_VERSION, "kind": "diagnosis", "case_id": case_id,
            "name": spec.get("name") or run_dir.name, "run": run_dir.name,
            "mode": spec.get("mode") or ("scenario" if case is not None else None),
            "files": files, "videos": videos,
            "explanation_status": None if explanation is None else explanation.get("interpretation_status"),
        }
        index.update(_summary(case))
        (staging / INDEX_NAME).write_text(
            json.dumps(index, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        if target.exists():
            shutil.rmtree(str(target))
        os.replace(str(staging), str(target))
    except BaseException:
        shutil.rmtree(str(staging), ignore_errors=True)
        raise
    return case_id


def _entry(directory: Path) -> Optional[Dict[str, Any]]:
    document = _read_json(directory / INDEX_NAME)
    if (document is None or document.get("kind") != "diagnosis"
            or document.get("schema_version") != SCHEMA_VERSION
            or document.get("case_id") != directory.name):
        return None
    return document


def list_diagnoses(root: Any) -> List[Dict[str, Any]]:
    """The registered diagnoses (index entries), sorted by name then id; invalid entries are skipped."""

    base = Path(root)
    if not base.is_dir():
        return []
    entries = []
    for directory in base.iterdir():
        if directory.is_dir() and not directory.is_symlink() and _CASE_ID.fullmatch(directory.name):
            entry = _entry(directory)
            if entry is not None:
                entries.append(entry)
    return sorted(entries, key=lambda item: (str(item.get("name")), item["case_id"]))


def read_diagnosis(root: Any, case_id: str) -> Dict[str, Any]:
    """One entry with its report text and explanation record. ``KeyError`` when it is not registered."""

    if type(case_id) is not str or _CASE_ID.fullmatch(case_id) is None:
        raise KeyError(case_id)
    directory = Path(root) / case_id
    if directory.is_symlink():
        raise KeyError(case_id)
    entry = _entry(directory)
    if entry is None:
        raise KeyError(case_id)
    report = None
    if (entry.get("files") or {}).get("report"):
        try:
            report = (directory / "report.md").read_text(encoding="utf-8")
        except OSError:
            report = None
    entry = dict(entry)
    entry["report"] = report
    entry["explanation"] = _read_json(directory / "explanation.json") if (
        (entry.get("files") or {}).get("explanation")) else None
    return entry


__all__ = ["DIAGNOSES_DIR", "RegisterError", "VIDEO_ROLES", "default_root", "list_diagnoses",
           "read_diagnosis", "register_run"]
