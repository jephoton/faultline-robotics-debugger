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
            # The Nebius and local backends download a Job's export prefix straight into
            # ``evidence/``; older hand-run downloads kept ``faultline-runs/<job>/`` inside it.
            # Scenario Jobs export under ``scenario/``, paraphrase Jobs under ``language/``.
            for kind in ("scenario", "language"):
                direct = job / "evidence" / kind
                if direct.is_dir():
                    found.append(direct)
            evidence = job / "evidence" / "faultline-runs"
            if evidence.is_dir():
                for run in sorted((p for p in evidence.iterdir() if p.is_dir()), key=lambda p: p.name):
                    for kind in ("scenario", "language"):
                        scenario = run / kind
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


def _case_route(run_route: Any, case: Optional[Mapping[str, Any]], pipeline_case: bool) -> Any:
    """The route shown for one case. A probing run has one route, but each of its cases is judged on its own
    control: a flaky stress test is ``flaky`` and a passing one is ``probes`` even when the wording control
    failed, and the other way round."""

    if not pipeline_case or not isinstance(case, Mapping) or run_route not in ("probes", "flaky"):
        return run_route
    if case.get("kind") == "audit":
        return "flaky" if case.get("stop_reason") == "nominal_controls_failed" else "probes"
    if case.get("kind") == "paraphrase_reduction":
        return "flaky" if case.get("stop_reason") == "control_not_passing" else "probes"
    return run_route


def _role_stem(role: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", role).strip("-") or "clip"


def _episode_videos(base: Path) -> List[Path]:
    """Every ordinary mp4 under one Job's evidence folder (links and oversize files left out)."""

    found = []
    try:
        for path in sorted(base.rglob("*.mp4")):
            if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_VIDEO_BYTES:
                continue
            try:
                path.resolve().relative_to(base.resolve())
            except (OSError, ValueError):
                continue
            found.append(path)
    except OSError:
        return []
    return found


def _find_episode_video(run_dir: Path, job: Any, case_id: Any,
                        cache: Dict[Path, List[Path]]) -> Optional[Path]:
    """The clip of one episode of an audit Job: the mp4 whose path holds the episode's ``case_id`` as a folder
    (``evidence/.../runs/<case_id>/...``). Looks in the named Job's evidence first, then in the others."""

    if type(case_id) is not str or not case_id or "/" in case_id or "\\" in case_id:
        return None
    jobs = run_dir / "jobs"
    bases = []
    if type(job) is str and job and "/" not in job and "\\" not in job and (jobs / job / "evidence").is_dir():
        bases.append(jobs / job / "evidence")
    if jobs.is_dir():
        bases += [p / "evidence" for p in sorted(jobs.iterdir()) if p.is_dir() and (p / "evidence").is_dir()
                  and (p / "evidence") not in bases]
    for base in bases:
        if base not in cache:
            cache[base] = _episode_videos(base)
        for path in cache[base]:
            if case_id in path.relative_to(base).parts:
                return path
    return None


def _ordered_roles(recorded: Mapping[str, Any]) -> List[str]:
    """The clips' display order: the control first, then the reduction's clips, then the rest alphabetically."""

    roles = [role for role in recorded if type(role) is str]
    first = [role for role in ("control",) + VIDEO_ROLES if role in roles]
    return first + sorted(role for role in roles if role not in first)


def register_run(run_dir: Any, root: Any = None, *, source: Any = None, label: Optional[str] = None,
                 order: int = 0) -> str:
    """Register one diagnosis run folder and return its case id.

    ``run_dir`` has the layout written by ``faultline diagnose`` (``spec.yaml``, ``report.md``,
    ``case.json``, ``minimal-candidate.json``, ``explanation.json`` and ``jobs/<job>/evidence/...``);
    every part is optional except that one of ``report.md`` or ``case.json`` must exist. ``root``
    is the diagnoses folder (default: ``diagnoses`` beside the run folder's ``runs`` parent).
    The case id is the case record's own id, or a digest of the run folder name for a run without
    a case (an audit).

    ``source`` is the folder holding the case's own files when a run has several (``cases/audit``; see
    :func:`register_cases`); the Job evidence and the spec still come from ``run_dir``. ``label`` is
    appended to the entry's name and ``order`` is its place among the run's cases.
    """

    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise RegisterError("the run folder does not exist")
    source_dir = run_dir if source is None else Path(source)
    if not source_dir.is_dir():
        raise RegisterError("the case folder does not exist")
    report_path, case_path = source_dir / "report.md", source_dir / "case.json"
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
                          ("candidate", "minimal-candidate.json"), ("replay_inputs", "replay-inputs.json"),
                          ("research", "research.json")):
            candidate_file = source_dir / name
            if (candidate_file.is_file() and not candidate_file.is_symlink()
                    and candidate_file.stat().st_size <= _MAX_JSON_BYTES):
                shutil.copyfile(str(candidate_file), str(staging / name))
                files[key] = name
            else:
                files[key] = None
        videos = {}  # type: Dict[str, Optional[Dict[str, Any]]]
        scenario_dirs = _job_scenario_dirs(run_dir)
        episode_cache = {}  # type: Dict[Path, List[Path]]
        recorded = case.get("videos") if case is not None and isinstance(case.get("videos"), Mapping) else {}
        for role in VIDEO_ROLES:
            videos[role] = None                  # the three scenario roles are always listed, found or not
        for role in _ordered_roles(recorded):
            entry = recorded.get(role) if isinstance(recorded.get(role), Mapping) else None
            if entry is None:
                continue
            if isinstance(entry.get("video"), str):
                found = _find_video(scenario_dirs, entry.get("video"))
            else:
                found = _find_episode_video(run_dir, entry.get("job"), entry.get("case_id"), episode_cache)
            if found is None:
                continue
            stem = _role_stem(role)
            (staging / "videos").mkdir(exist_ok=True)
            shutil.copyfile(str(found), str(staging / "videos" / (stem + ".mp4")))
            videos[role] = {"file": "videos/{}.mp4".format(stem), "outcome": entry.get("outcome"),
                            "case_id": entry.get("case_id")}
            if isinstance(entry.get("label"), str):
                videos[role]["label"] = entry["label"][:200]
        explanation = _read_json(source_dir / "explanation.json")
        header = (_read_json(run_dir / "steps.json") or {}).get("run")
        route = _case_route(header.get("route") if isinstance(header, Mapping) else None, case, source is not None)
        index = {
            "schema_version": SCHEMA_VERSION, "kind": "diagnosis", "case_id": case_id,
            "name": (spec.get("name") or run_dir.name) + ("" if label is None else " - " + label),
            "run": run_dir.name,
            "mode": spec.get("mode") or ("scenario" if case is not None else None),
            "files": files, "videos": videos, "order": order,
            "route": route if route in ("layout", "probes", "passes", "flaky") else None,
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


CASE_FOLDERS = (("audit", "stress test"), ("wording", "rewordings"))      # route order: the stress test first


def register_cases(run_dir: Any, root: Any = None) -> List[str]:
    """Register every case of a run folder and return their ids, in route order.

    A single-case run (the layout diagnosis, the stand-alone modes) keeps ``case.json`` and ``report.md`` at the
    top and registers exactly as :func:`register_run`. A pipeline run that probed keeps one folder per case,
    ``cases/audit/`` and ``cases/wording/``, each with its own ``case.json``, ``report.md`` and (when it can be
    replayed) ``replay-inputs.json``; each is registered, sharing the run's Job evidence and spec.
    """

    run_dir = Path(run_dir)
    folders = [(run_dir / "cases" / name, label) for name, label in CASE_FOLDERS
               if (run_dir / "cases" / name).is_dir()]
    if not folders:
        return [register_run(run_dir, root)]
    ids = [register_run(run_dir, root, source=folder, label=label, order=order)
           for order, (folder, label) in enumerate(folders)]
    _drop_superseded(run_dir, root, ids)
    return ids


def _drop_superseded(run_dir: Path, root: Any, keep: List[str]) -> None:
    """Remove this run's earlier entries that a later segment replaced under a new case id.

    A run stopped part-way registers what it has (a wording case for a screen whose reduction has not run);
    the resumed run finishes the case under its own id, so the interim entry would otherwise be listed twice."""

    base = Path(root) if root is not None else default_root(run_dir)
    for entry in list_diagnoses(base):
        if entry.get("run") == run_dir.name and entry["case_id"] not in keep:
            shutil.rmtree(str(base / entry["case_id"]), ignore_errors=True)


def _retitle_audit_report(run_dir: Path, folder: Path) -> None:
    """Give an audit report written under the legacy M6 title its stress-test title.

    Only the first line changes, and only when it is exactly the legacy title: the title is rebuilt from the
    summary the case names (its suite, task and start), so a report that cannot be matched is left alone."""

    case = _read_json(folder / "case.json")
    report = folder / "report.md"
    if case is None or case.get("kind") != "audit" or not report.is_file():
        return
    summary = _read_json(_safe_child(run_dir, case.get("summary")) or run_dir / "none")
    if summary is None:
        return
    try:
        from robot_debug.orchestrator import _load_script

        module = _load_script("report_m6_experiment")
        title = module.stress_test_title([summary])
        legacy = "# " + module.LEGACY_TITLE
    except Exception:           # noqa: BLE001 - without the report script the old title simply stays
        return
    text = report.read_text(encoding="utf-8")
    first, separator, rest = text.partition(chr(10))
    if title is None or first.rstrip(chr(13)) != legacy:
        return
    temporary = report.with_name("report.md.tmp")
    temporary.write_text("# " + title + separator + rest, encoding="utf-8", newline="")
    os.replace(str(temporary), str(report))


def _record_checkpoint(folder: Path) -> None:
    """Record the suite's pinned checkpoint in an audit or wording case written before cases recorded one.

    Only a case with no usable checkpoint changes (one that names no checkpoint or no revision): a run with a
    ``policy.checkpoint`` override always recorded its own, and is left as it is. The case id does not depend
    on the checkpoint."""

    case = _read_json(folder / "case.json")
    if case is None or case.get("kind") not in ("audit", "paraphrase_reduction"):
        return
    try:
        from robot_debug.orchestrator import with_recorded_checkpoint

        updated = with_recorded_checkpoint(case)
    except Exception:           # noqa: BLE001 - without the project scripts the case stays as it was
        return
    if updated == case:
        return
    temporary = folder / "case.json.tmp"
    temporary.write_text(json.dumps(updated, indent=1, sort_keys=True, allow_nan=False) + chr(10),
                         encoding="utf-8", newline="")
    os.replace(str(temporary), str(folder / "case.json"))


def reregister_run(run_dir: Any, root: Any = None) -> List[str]:
    """Register a finished run again from its folder, for cases registered before the clips existed.

    An audit case made before the pipeline (or by the stand-alone audit mode) has no ``videos`` in its
    ``case.json``; this reads the Job summary the case names, attaches the control and per-family clips
    (:func:`robot_debug.pipeline_cases.audit_videos`) and registers the run again, replacing its entry. Cases
    that already have clips, and every other kind, are registered unchanged. Returns the case ids. Nothing is
    deleted and no cloud call is made; the coordinator decides when to run it on real artifacts.
    """

    run_dir = Path(run_dir)
    for folder in (run_dir, run_dir / "cases" / "audit", run_dir / "cases" / "wording"):
        _retitle_audit_report(run_dir, folder)
        _record_checkpoint(folder)
    case_path = run_dir / "case.json"
    case = _read_json(case_path)
    if isinstance(case, dict) and case.get("kind") == "audit" and not case.get("videos"):
        summary = _read_json(_safe_child(run_dir, case.get("summary")) or run_dir / "none")
        job = case.get("job_name")
        if isinstance(summary, dict) and isinstance(job, str):
            from robot_debug.pipeline_cases import audit_videos

            videos = audit_videos([(job, summary)])
            if videos:
                case = dict(case, videos=videos)
                temporary = case_path.with_name("case.json.tmp")
                temporary.write_text(json.dumps(case, indent=1, sort_keys=True, allow_nan=False) + "\n",
                                     encoding="utf-8", newline="\n")
                os.replace(str(temporary), str(case_path))
    return register_cases(run_dir, root)


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


__all__ = ["CASE_FOLDERS", "DIAGNOSES_DIR", "RegisterError", "VIDEO_ROLES", "default_root", "list_diagnoses",
           "read_diagnosis", "register_cases", "register_run", "reregister_run"]
