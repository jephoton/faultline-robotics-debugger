"""The library read model of the control panel (ADR 0033, API contract version 1).

A *library item* is one finished piece of work the sidebar lists: a registered diagnosis
(``d-<case id>``), a finished run that left no case (``r-<run folder>``, for example a paraphrase run that
found no failure) or the September occlusion case (``m-<case id>``). :class:`Library` builds the list
(:meth:`Library.list`) and one item's full page (:meth:`Library.detail`) from the files the CLI already
keeps: ``diagnoses/<id>/``, ``runs/<run>/`` and the case store.

Everything returned here is the *public projection*: never a Job id, a project, subnet, registry or bucket
name, an access key, an absolute path or anything from ``backend-state.json``. The same shapes are written
to the static export (``faultline export``), so the gallery and the local tool share one page.
"""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from robot_debug.case_register import list_diagnoses, read_diagnosis
from robot_debug.viewer import processes
from robot_debug.viewer.stop_reasons import needs_attention, stop_text

VERDICTS = ("reproduces", "no_failure", "stopped", "failed", "incomplete")
KIND_LETTERS = {"scenario": "S", "audit": "A", "paraphrase": "L", "occlusion": "M"}
VIDEO_LABELS = {"original": "Original failing start", "minimal": "Minimal cause", "reference": "Passing reference"}
FAMILY_LABELS = {
    "darken": "Darkening", "noise": "Gaussian noise", "blur": "Gaussian blur", "contrast": "Contrast reduction",
    "jpeg": "JPEG compression", "colour_cast": "Colour cast", "motion_blur": "Motion blur",
    "dead_pixels": "Dead pixels", "viewpoint": "Camera viewpoint", "lighting": "Scene lighting",
}
HYPOTHESIS_TEXT = {
    "confirmed": "The model's top suspect was necessary, sufficient and the only survivor.",
    "necessary_not_sufficient": "The model's top suspect was needed but not enough on its own.",
    "sufficient_not_necessary": "The model's top suspect was enough on its own but not needed.",
    "not_in_final": "The model's top suspect was not part of the minimal cause.",
    "inconclusive": "The reruns could not settle whether the model's top suspect mattered.",
}
FILE_LABELS = (("report", "report.md"), ("case", "case.json"), ("explanation", "explanation.json"),
               ("candidate", "minimal-candidate.json"), ("replay_inputs", "replay-inputs.json"))
FILE_NAMES = frozenset(name for _key, name in FILE_LABELS)
_CASE_ID = re.compile(r"[0-9a-f]{64}\Z")
_STAMP = re.compile(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z\Z")
_MAX_JSON_BYTES = 4 * 1024 * 1024
_MAX_TEXT_BYTES = 1024 * 1024
InspectCase = Callable[[Path, str], Mapping[str, Any]]


# --------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------


def _inside_folder(folder: Path, relative: str) -> Optional[Path]:
    """``relative`` resolved under ``folder``, or ``None`` when it names anything outside it (``..`` in either
    slash style, an absolute path, a drive letter, a link out)."""

    if "\x00" in relative:
        return None
    try:
        base = Path(folder).resolve()
        resolved = (base / relative).resolve()
    except (OSError, ValueError):
        return None
    return resolved if base in resolved.parents else None


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not path.is_file() or path.stat().st_size > _MAX_JSON_BYTES:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _read_text(path: Path) -> Optional[str]:
    try:
        if not path.is_file() or path.stat().st_size > _MAX_TEXT_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _str(value: Any) -> Optional[str]:
    return value if isinstance(value, str) else None


def _int(value: Any) -> Optional[int]:
    return value if type(value) is int else None


def _number(value: Any) -> Optional[float]:
    return float(value) if type(value) in (int, float) else None


def stamp_to_iso(run_name: Any) -> Optional[str]:
    """``2026-10-16T06:45:28Z`` from the stamp a run folder name ends with, else ``None``."""

    if not isinstance(run_name, str):
        return None
    match = _STAMP.search(run_name)
    if match is None:
        return None
    try:
        dt.datetime(*(int(part) for part in match.groups()))
    except ValueError:
        return None
    year, month, day, hour, minute, second = match.groups()
    return "{}-{}-{}T{}:{}:{}Z".format(year, month, day, hour, minute, second)


def fault_code(kind: str, key: str, digits: int = 4) -> str:
    """The display-only fault code, ``FL-S-AFB5``: kind letter plus the first hex digits of the case id (or of
    the sha256 of the run folder name for an item with no case). It never replaces the id."""

    if not re.fullmatch(r"[0-9a-fA-F]+", key or "") or len(key) < digits:
        key = hashlib.sha256(str(key).encode("utf-8")).hexdigest()
    return "FL-{}-{}".format(KIND_LETTERS.get(kind, "S"), key[:digits].upper())


def assign_fault_codes(items: List[Dict[str, Any]], keys: Mapping[str, str]) -> None:
    """Set ``fault_code`` on every item: four hex digits, six where two items would share a code."""

    short = {item["id"]: fault_code(item["kind"], keys[item["id"]], 4) for item in items}
    counts: Dict[str, int] = {}
    for code in short.values():
        counts[code] = counts.get(code, 0) + 1
    for item in items:
        code = short[item["id"]]
        item["fault_code"] = code if counts[code] == 1 else fault_code(item["kind"], keys[item["id"]], 6)


def _plural(count: int, word: str) -> str:
    return "{} {}{}".format(count, word, "" if count == 1 else "s")


def _percent(value: float) -> str:
    return "{:.0f}".format(value * 100)


# --------------------------------------------------------------------------------------
# Minimal cause: what the reduction kept, in units a person can picture
# --------------------------------------------------------------------------------------


def _one_decimal(value: float) -> str:
    """Round half away from zero, as people (and the report's 3.65 -> 3.7) expect, not to the nearest float."""

    return str(Decimal(repr(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _magnitude(row: Mapping[str, Any], part: str, fraction: float) -> str:
    if part == "position" and _number(row.get("position_cm")) is not None:
        return "{} cm".format(_one_decimal(row["position_cm"] * fraction))
    if part == "rotation" and _number(row.get("rotation_deg")) is not None:
        return "{}°".format(_one_decimal(row["rotation_deg"] * fraction))
    if part == "joints":
        joints = [j for j in _list(row.get("joints")) if isinstance(j, Mapping) and _number(j.get("offset")) is not None]
        if not joints:
            return "joints"
        biggest = max(joints, key=lambda j: abs(j["offset"]))
        unit = biggest.get("unit")
        size = abs(biggest["offset"]) * fraction
        text = "{}°".format(_one_decimal(size)) if unit == "deg" else "{:.3g} {}".format(size, unit or "").strip()
        return "{}, up to {}".format(_plural(len(joints), "joint"), text)
    return "changed"


def minimal_cause(case: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """One row per kept part of the case's minimal selection: ``{entity, part, fraction, magnitude}``."""

    rows = {r.get("entity"): r for r in _list(case.get("differences")) if isinstance(r, Mapping)}
    selection = _mapping(_mapping(case.get("minimal")).get("selection"))
    found = []
    for entity, parts in selection.items():
        for part, fraction in _mapping(parts).items():
            if part not in ("position", "rotation", "joints") or _number(fraction) is None:
                continue
            found.append({"entity": entity, "part": part, "fraction": float(fraction),
                          "magnitude": _magnitude(_mapping(rows.get(entity)), part, float(fraction))})
    return found


# --------------------------------------------------------------------------------------
# Verdicts
# --------------------------------------------------------------------------------------


def _audit_summary(case: Mapping[str, Any]) -> Tuple[str, str, bool]:
    """``(verdict, sentence, attention)`` of an audit case from its families and stop reason."""

    families = _mapping(case.get("families"))
    found = {name: _number(_mapping(info).get("threshold_severity")) for name, info in families.items()}
    hit = {name: severity for name, severity in found.items() if severity is not None}
    reason = _str(case.get("stop_reason"))
    if hit:
        lowest = min(hit, key=lambda name: (hit[name], name))
        return ("reproduces",
                "The policy fails reliably under {} of {} disturbance {}; the lowest threshold is {} at severity "
                "{:g}.".format(len(hit), len(families), "family" if len(families) == 1 else "families",
                               FAMILY_LABELS.get(lowest, lowest).lower(), hit[lowest]),
                False)
    if reason == "nominal_controls_failed":
        return "stopped", stop_text(reason) or "", True
    if case.get("complete") is False or reason not in (None, "", "no_reproducible_failure"):
        return "incomplete", stop_text(reason) or "The audit did not finish.", True
    return "no_failure", "No disturbance up to full strength made the policy fail 4 of 5 times.", False


def _scenario_summary(case: Mapping[str, Any]) -> Tuple[str, str, bool]:
    minimal = _mapping(case.get("minimal"))
    kept = len(_mapping(minimal.get("selection")))
    total = len(_list(case.get("differences")))
    reduced = bool(case.get("reduced"))
    if reduced:
        text = "Fully reduced: {} of {} differences from the passing start cause the failure.".format(kept, total)
    elif minimal.get("entity_minimal"):
        text = ("Entity-minimal: {} of {} differences from the passing start are enough; their sizes were not "
                "shrunk.".format(kept, total))
    else:
        text = "Reduced to {} of {} differences from the passing start; the reduction was cut short.".format(kept, total)
    reason = _str(case.get("stop_reason"))
    return "reproduces", text, (not reduced) and needs_attention(reason)


def _paraphrase_summary(case: Mapping[str, Any]) -> Tuple[str, str, bool]:
    minimal = _mapping(case.get("minimal"))
    edits = len(_list(minimal.get("labels")))
    reduced = bool(case.get("reduced"))
    text = "A reworded instruction makes the policy fail; {} {} enough.".format(
        _plural(edits, "word edit"), "is" if edits == 1 else "are")
    reason = _str(case.get("stop_reason"))
    return "reproduces", text, (not reduced) and needs_attention(reason)


def _run_verdict(steps_data: Mapping[str, Any]) -> Tuple[str, str, bool]:
    """Verdict of a finished run that left no case, from the run's own stop reason."""

    run = _mapping(steps_data.get("run"))
    reason = _str(run.get("reason"))
    status = run.get("status")
    if reason == "no_reproducible_failure":
        return "no_failure", stop_text(reason) or "", False
    if status == "completed":
        return "no_failure", "The run finished without a failure to report.", False
    if status == "failed":
        return "failed", "The run failed before it finished.", True
    return "stopped", stop_text(reason, _str(run.get("detail"))) or "The run stopped.", needs_attention(reason)


# --------------------------------------------------------------------------------------
# The library
# --------------------------------------------------------------------------------------


class Library:
    """The read model over one artifacts folder.

    ``runs_root`` is optional: without it (the static gallery) run-dependent parts (the audit's levels, the
    step history, replays) are simply absent. ``local`` is false for the gallery: ``run`` fields are ``None``.
    ``inspect_case`` reads the occlusion case (default: the case store, which revalidates its evidence).
    """

    def __init__(self, artifact_root: Path, *, runs_root: Optional[Path] = None,
                 diagnoses_root: Optional[Path] = None, case_workspace: Optional[Path] = None,
                 inspect_case: Optional[InspectCase] = None, local: bool = True) -> None:
        self.artifact_root = Path(artifact_root)
        self.runs_root = None if runs_root is None else Path(runs_root)
        self.diagnoses_root = Path(diagnoses_root) if diagnoses_root else self.artifact_root / "diagnoses"
        self.case_workspace = Path(case_workspace) if case_workspace else self.artifact_root / "cases"
        self._inspect = inspect_case
        self.local = local

    # -- listing --------------------------------------------------------------------------

    def list(self) -> Dict[str, Any]:
        """``{"items": [LibraryItem], "warnings": [str]}``, newest first, the occlusion case last."""

        items: List[Dict[str, Any]] = []
        keys: Dict[str, str] = {}
        warnings: List[str] = []
        registered_runs, registered_cases = set(), set()
        for entry in list_diagnoses(self.diagnoses_root):
            registered_cases.add(entry["case_id"])
            item, key = self._diagnosis_item(entry)
            items.append(item)
            keys[item["id"]] = key
            if isinstance(entry.get("run"), str):
                registered_runs.add(entry["run"])
        for item, key in self._run_items(registered_runs, registered_cases):
            items.append(item)
            keys[item["id"]] = key
        for item, key in self._occlusion_items(warnings):
            items.append(item)
            keys[item["id"]] = key
        items.sort(key=lambda i: i["id"])                       # stable sorts: newest first, the old case last
        items.sort(key=lambda i: i["created"] or "", reverse=True)
        items.sort(key=lambda i: i["kind"] == "occlusion")
        assign_fault_codes(items, keys)
        return {"items": items, "warnings": warnings}

    def _base_item(self, item_id: str, kind: str, name: str) -> Dict[str, Any]:
        return {"id": item_id, "fault_code": "", "kind": kind, "name": name, "verdict": "incomplete",
                "verdict_text": "", "attention": False, "suite": None, "task_id": None, "instruction": None,
                "created": None, "case_id": None, "run": None}

    def _run_name(self, name: Any) -> Optional[str]:
        """The run folder name for local-only fields: only when the folder is really there."""

        if not self.local or self.runs_root is None or not isinstance(name, str):
            return None
        try:
            processes.run_folder(self.runs_root, name)
        except (ValueError, FileNotFoundError):
            return None
        return name

    def _diagnosis_item(self, entry: Mapping[str, Any]) -> Tuple[Dict[str, Any], str]:
        case_id = entry["case_id"]
        case = _read_json(self.diagnoses_root / case_id / "case.json") or {}
        kind = {"scenario": "scenario", "audit": "audit", "paraphrase": "paraphrase"}.get(
            _str(entry.get("mode")) or "", None)
        if kind is None:
            kind = {"audit": "audit", "paraphrase_reduction": "paraphrase"}.get(_str(entry.get("case_kind")) or "", "scenario")
        item = self._base_item("d-" + case_id, kind, _str(entry.get("name")) or case_id[:12])
        if kind == "audit":
            verdict, text, attention = _audit_summary(case)
        elif kind == "paraphrase":
            verdict, text, attention = _paraphrase_summary(case) if case else ("incomplete", "", True)
        else:
            verdict, text, attention = _scenario_summary(case) if case else ("incomplete", "", True)
        item.update(verdict=verdict, verdict_text=text, attention=attention, suite=_str(entry.get("suite")),
                    task_id=_int(entry.get("task_id")), instruction=_str(entry.get("instruction")),
                    created=stamp_to_iso(entry.get("run")), case_id=case_id, run=self._run_name(entry.get("run")))
        return item, case_id

    def _run_items(self, registered_runs: set, registered_cases: set) -> List[Tuple[Dict[str, Any], str]]:
        """Finished runs with no registered case (and not replays), newest first."""

        found = []
        if self.runs_root is None or not self.runs_root.is_dir():
            return found
        for folder in sorted(self.runs_root.iterdir()):
            if folder.name in registered_runs or not (folder / "steps.json").is_file():
                continue
            data = _read_json(folder / "steps.json")
            if data is None or data.get("mode") not in ("scenario", "audit", "paraphrase"):
                continue
            if _mapping(data.get("run")).get("status") not in ("completed", "stopped", "failed"):
                continue
            if _mapping(_mapping(data.get("steps")).get("register")).get("case_id") in registered_cases:
                continue
            verdict, text, attention = _run_verdict(data)
            item = self._base_item("r-" + folder.name, data["mode"], _str(data.get("name")) or folder.name)
            spec = processes.spec_raw(folder)
            section = _mapping(spec.get(data["mode"]))
            task = _int(section.get("task"))
            instruction = None
            if data["mode"] == "paraphrase":
                instruction = _str((_read_json(folder / "paraphrases.json") or {}).get("original"))
            item.update(verdict=verdict, verdict_text=text, attention=attention,
                        suite=_str(_mapping(spec.get("policy")).get("suite")), task_id=task,
                        instruction=instruction, created=stamp_to_iso(folder.name),
                        run=self._run_name(folder.name))
            found.append((item, folder.name))
        return found

    def _occlusion_items(self, warnings: List[str]) -> List[Tuple[Dict[str, Any], str]]:
        found = []
        if not self.case_workspace.is_dir():
            return found
        for directory in sorted(self.case_workspace.iterdir()):
            if not _CASE_ID.fullmatch(directory.name) or not directory.is_dir() or directory.is_symlink():
                continue
            case = _read_json(directory / "case.json")
            if case is None or case.get("case_id") != directory.name:
                warnings.append("an occlusion case entry is unavailable or invalid")
                continue
            item = self._base_item("m-" + directory.name, "occlusion", "September occlusion case")
            rectangle = _mapping(_mapping(case.get("perturbation")).get("rectangle"))
            area = (_number(rectangle.get("width")) or 0) * (_number(rectangle.get("height")) or 0)
            task = _mapping(case.get("task"))
            item.update(verdict="reproduces", attention=False,
                        verdict_text="A block covering {}% of the agent camera view makes the policy fail.".format(
                            _percent(area)),
                        suite=_str(task.get("suite")), task_id=_int(task.get("task_id")), case_id=directory.name)
            found.append((item, directory.name))
        return found

    # -- one item ---------------------------------------------------------------------------

    def detail(self, item_id: str) -> Dict[str, Any]:
        """``Detail`` for one item. Raises ``KeyError`` for an id that is not in the library."""

        listing = self.list()["items"]
        item = next((i for i in listing if i["id"] == item_id), None)
        if item is None:
            raise KeyError(item_id)
        detail = dict(item)
        detail.update({"sentence": None, "stop_reason": None, "stop_text": None, "checkpoint": None, "videos": [],
                       "explanation": None, "research": None, "history": None, "replays": [],
                       "report_markdown": None, "files": [], "replayable": False})
        if item_id.startswith("d-"):
            self._diagnosis_detail(detail, item["case_id"])
        elif item_id.startswith("r-"):
            self._run_detail(detail, item_id[2:])
        else:
            self._occlusion_detail(detail, item["case_id"])
        return detail

    def file_path(self, item_id: str, name: str) -> Path:
        """The file ``name`` (one of the case's published files) of a library item; ``KeyError`` if none."""

        if name not in FILE_NAMES:
            raise KeyError(name)
        if item_id.startswith("d-") and _CASE_ID.fullmatch(item_id[2:] or ""):
            path = self.diagnoses_root / item_id[2:] / name
        elif item_id.startswith("r-") and self.runs_root is not None and name == "report.md":
            path = processes.run_folder(self.runs_root, item_id[2:]) / name
        else:
            raise KeyError(item_id)
        if not path.is_file() or path.is_symlink():
            raise KeyError(name)
        return path

    # -- diagnosis detail ----------------------------------------------------------------

    def _media_url(self, path: Path) -> Optional[str]:
        try:
            return "/media/" + path.resolve().relative_to(self.artifact_root.resolve()).as_posix()
        except (ValueError, OSError):
            return None

    def _diagnosis_detail(self, detail: Dict[str, Any], case_id: str) -> None:
        entry = read_diagnosis(self.diagnoses_root, case_id)
        case = _read_json(self.diagnoses_root / case_id / "case.json") or {}
        kind = detail["kind"]
        reason = _str(case.get("stop_reason"))
        detail["stop_reason"], detail["stop_text"] = reason, stop_text(reason)
        detail["checkpoint"] = self._checkpoint(case)
        report = _str(entry.get("report"))
        detail["report_markdown"] = None if report is None else processes.scrub_text(report)
        files = _mapping(entry.get("files"))
        detail["files"] = [{"name": name, "url": "/api/library/{}/files/{}".format(detail["id"], name)}
                           for key, name in FILE_LABELS if files.get(key)]
        for role, video in _mapping(entry.get("videos")).items():
            if role not in VIDEO_LABELS or not isinstance(video, Mapping):
                continue                           # no video was kept for this role
            url = None
            if isinstance(video, Mapping) and isinstance(video.get("file"), str):
                url = self._media_url(self.diagnoses_root / case_id / video["file"])
            detail["videos"].append({"role": role, "label": VIDEO_LABELS[role], "url": url,
                                     "outcome": _str(_mapping(video).get("outcome"))})
        detail["videos"].sort(key=lambda v: list(VIDEO_LABELS).index(v["role"]))
        explanation = entry.get("explanation")
        if isinstance(explanation, Mapping):
            detail["explanation"] = _explanation(
                _str(explanation.get("interpretation_status")), _str(explanation.get("disclaimer")),
                _str(_mapping(explanation.get("provenance")).get("model")), explanation.get("interpretation"))
        run_dir = self._run_dir(entry.get("run"))
        if kind == "scenario":
            detail["scenario"] = self._scenario_block(case)
            detail["sentence"] = _str(_mapping(case.get("minimal")).get("sentence"))
            detail["replayable"] = bool(files.get("replay_inputs")) and bool(files.get("case"))
        elif kind == "audit":
            detail["audit"] = self._audit_block(case, run_dir)
            detail["sentence"] = _audit_sentence(case)
        else:
            detail["paraphrase"] = _paraphrase_block(case)
            detail["sentence"] = _str(_mapping(case.get("minimal")).get("sentence"))
        if run_dir is not None:
            detail["history"] = self._history(run_dir)
        detail["replays"] = self._replays(case_id)

    @staticmethod
    def _checkpoint(case: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        checkpoint = _mapping(case.get("checkpoint"))
        if _str(checkpoint.get("id")) and _str(checkpoint.get("revision")):
            return {"id": checkpoint["id"], "revision": checkpoint["revision"],
                    "pinned": bool(checkpoint.get("pinned"))}
        return None

    def _run_dir(self, name: Any) -> Optional[Path]:
        """The run folder for history, even in the gallery's export step (a local read); ``None`` if absent."""

        if self.runs_root is None or not isinstance(name, str):
            return None
        try:
            return processes.run_folder(self.runs_root, name)
        except (ValueError, FileNotFoundError):
            return None

    def _scenario_block(self, case: Mapping[str, Any]) -> Dict[str, Any]:
        minimal = _mapping(case.get("minimal"))
        imported = _mapping(case.get("failing_import"))
        hypothesis = _mapping(case.get("hypothesis"))
        measurement = _mapping(hypothesis.get("measurement"))
        block: Dict[str, Any] = {
            "failing_start": _int(case.get("failing_start")),
            "imported": ({"file_sha256": imported["file_sha256"], "state_sha256": imported["state_sha256"]}
                         if _str(imported.get("file_sha256")) and _str(imported.get("state_sha256")) else None),
            "reference_start": _int(case.get("reference_start")),
            "entity_minimal": minimal.get("entity_minimal") if isinstance(minimal.get("entity_minimal"), bool) else None,
            "reduced": case.get("reduced") if isinstance(case.get("reduced"), bool) else None,
            "minimal_cause": minimal_cause(case),
            "differences_count": len(_list(case.get("differences"))),
            "hypothesis": None,
            "reruns": [],
        }
        ranking = [r for r in _list(hypothesis.get("ranking")) if isinstance(r, str)]
        if ranking:
            verdict = _str(hypothesis.get("measured_verdict"))
            block["hypothesis"] = {
                "ranked": ranking, "measured_verdict": verdict,
                "verdict_text": None if verdict is None else HYPOTHESIS_TEXT.get(verdict),
                "entities": [{"entity": e.get("entity"), "label": _str(e.get("label")) or "",
                              "necessary": e.get("necessary") if isinstance(e.get("necessary"), bool) else None,
                              "sufficient": e.get("sufficient") if isinstance(e.get("sufficient"), bool) else None}
                             for e in _list(measurement.get("entities")) if isinstance(e, Mapping)
                             and isinstance(e.get("entity"), str)]}
        for row in _list(case.get("evidence")):
            if not isinstance(row, Mapping) or _int(row.get("index")) is None:
                continue
            selection = row.get("selection")
            block["reruns"].append({
                "index": row["index"], "phase": _str(row.get("phase")) or "", "role": _str(row.get("role")) or "",
                "selection": selection if isinstance(selection, Mapping) else None,
                "outcomes": [o for o in _list(row.get("outcomes")) if isinstance(o, str)],
                "decision": _str(row.get("decision")) or ""})
        return block

    def _audit_block(self, case: Mapping[str, Any], run_dir: Optional[Path]) -> Dict[str, Any]:
        summary = None
        relative = _str(case.get("summary"))
        inside = _inside_folder(run_dir, relative) if run_dir is not None and relative else None
        if inside is not None:
            summary = _read_json(inside)
        summary_families = _mapping(_mapping(summary).get("families"))
        config = _mapping(_mapping(summary).get("config"))
        order = [f for f in _list(config.get("families")) if isinstance(f, str)]
        names = [n for n in order if n in _mapping(case.get("families"))] + sorted(
            n for n in _mapping(case.get("families")) if n not in order)
        families = []
        for name in names:
            info = _mapping(_mapping(case.get("families")).get(name))
            full = _mapping(summary_families.get(name))
            levels = []
            for level in _list(full.get("levels")):
                if isinstance(level, Mapping) and _number(level.get("severity")) is not None:
                    outcomes = _list(level.get("outcomes"))
                    failures = level.get("failures")
                    levels.append({"severity": float(level["severity"]),
                                   "failures": failures if type(failures) is int else
                                   sum(1 for o in outcomes if o == "policy_failure"),
                                   "attempts": len(outcomes)})
            families.append({"family": name, "label": FAMILY_LABELS.get(name, name),
                             "threshold_severity": _number(info.get("threshold_severity")),
                             "stop_reason": _str(info.get("stop_reason")) or "", "levels": levels})
        nominal = _mapping(_mapping(summary).get("nominal_controls"))
        outcomes = _mapping(nominal.get("outcomes"))
        attempts = _int(nominal.get("planned")) or sum(v for v in outcomes.values() if type(v) is int)
        return {"start_index": _int(case.get("start_index")),
                "nominal": None if not nominal else {"failures": _int(outcomes.get("policy_failure")) or 0,
                                                     "attempts": attempts},
                "families": families}

    # -- run detail (finished runs with no case) ----------------------------------------------

    def _run_detail(self, detail: Dict[str, Any], run: str) -> None:
        run_dir = processes.run_folder(self.runs_root, run) if self.runs_root is not None else None
        if run_dir is None:
            raise KeyError(run)
        data = _read_json(run_dir / "steps.json") or {}
        header = _mapping(data.get("run"))
        reason = _str(header.get("reason"))
        detail["stop_reason"], detail["stop_text"] = reason, stop_text(reason, _str(header.get("detail")))
        detail["sentence"] = detail["verdict_text"]
        report = _read_text(run_dir / "report.md")
        detail["report_markdown"] = None if report is None else processes.scrub_text(report)
        if detail["report_markdown"] is not None:
            detail["files"] = [{"name": "report.md", "url": "/api/library/{}/files/report.md".format(detail["id"])}]
        if detail["kind"] == "paraphrase":
            detail["paraphrase"] = _paraphrase_from_run(run_dir)
        elif detail["kind"] == "scenario":
            detail["scenario"] = {"failing_start": None, "imported": None, "reference_start": None,
                                  "entity_minimal": None, "reduced": None, "minimal_cause": [],
                                  "differences_count": 0, "hypothesis": None, "reruns": []}
        else:
            detail["audit"] = {"start_index": None, "nominal": None, "families": []}
        detail["history"] = self._history(run_dir)

    # -- the September occlusion case ------------------------------------------------------------

    def _occlusion_detail(self, detail: Dict[str, Any], case_id: str) -> None:
        inspect = self._inspect or _default_inspect
        case = inspect(self.case_workspace, case_id)
        detail["sentence"] = detail["verdict_text"]
        evidence = _mapping(case.get("evidence"))
        source_root = self._source_root(case_id)
        episodes = []
        for episode in _list(evidence.get("episodes")):
            if not isinstance(episode, Mapping) or not isinstance(episode.get("episode_id"), str):
                continue
            url = None
            video = _mapping(episode.get("video"))
            if source_root is not None and _str(video.get("path")):
                url = self._media_url(source_root / video["path"])
            episodes.append({"episode_id": episode["episode_id"], "stage": _str(episode.get("stage")) or "",
                             "role": _str(episode.get("role")) or "",
                             "outcome": _str(episode.get("gate_outcome")) or "", "url": url})
        lineage = []
        for step in _list(evidence.get("lineage")):
            rectangle = _mapping(_mapping(step).get("rectangle"))
            if (all(_number(rectangle.get(k)) is not None for k in ("x", "y", "width", "height"))
                    and _str(_mapping(step).get("edge")) and _number(_mapping(step).get("delta")) is not None):
                lineage.append({"rectangle": {k: float(rectangle[k]) for k in ("x", "y", "width", "height")},
                                "edge": step["edge"], "delta": float(step["delta"])})
        detail["occlusion"] = {"perturbation": dict(_mapping(case.get("perturbation"))), "lineage": lineage,
                               "episodes": episodes}
        for report in self._m4_reports(case_id):
            detail["explanation"] = report
        detail["research"] = self._m4_research(case_id)

    def _source_root(self, case_id: str) -> Optional[Path]:
        binding = _read_json(self.case_workspace / case_id / "local-source.json")
        root = _str(_mapping(binding).get("source_root"))
        return Path(root) if root else None

    def _m4_reports(self, case_id: str) -> List[Dict[str, Any]]:
        try:
            from robot_debug.explanation_store import read_case_reports

            reports = read_case_reports(self.case_workspace, case_id).get("reports") or []
        except Exception:                # noqa: BLE001 - stored explanations are optional
            return []
        reports = sorted((r for r in reports if isinstance(r, Mapping)),
                         key=lambda r: (_str(_mapping(r.get("provenance")).get("created_at")) or "",
                                        _str(r.get("report_id")) or ""))
        found = []
        for record in reports[-1:]:
            report = _mapping(record.get("report"))
            found.append(_explanation(_str(report.get("interpretation_status")), _str(report.get("disclaimer")),
                                      _str(_mapping(record.get("provenance")).get("model")),
                                      report.get("interpretation")))
        return found

    def _m4_research(self, case_id: str) -> Optional[Dict[str, Any]]:
        try:
            from robot_debug.research_store import read_case_research

            records = read_case_research(self.case_workspace, case_id).get("records") or []
        except Exception:                # noqa: BLE001 - stored research is optional
            return None
        if not records:
            return None
        record = _mapping(records[-1])
        sources, seen = [], set()
        for query in _list(record.get("queries")):
            for result in _list(_mapping(query).get("results")):
                url = _str(_mapping(result).get("url"))
                if url and url.startswith("https://") and url not in seen:
                    seen.add(url)
                    sources.append({"title": _str(result.get("title")) or url, "url": url})
        summary = _mapping(record.get("summary"))
        related = None
        if summary.get("status") == "interpreted":
            parts = []
            for entry in _list(summary.get("related_work")):
                text = _str(_mapping(entry).get("text"))
                if text:
                    ids = [i for i in _list(entry.get("source_ids")) if isinstance(i, str)]
                    parts.append(text + ("" if not ids else " [" + ", ".join(ids) + "]"))
            related = "\n\n".join(parts) or None
        return {"related": related, "sources": sources}

    # -- history and replays -------------------------------------------------------------------------

    def _history(self, run_dir: Path) -> Optional[Dict[str, Any]]:
        data = _read_json(run_dir / "steps.json")
        if data is None or not isinstance(data.get("steps"), Mapping):
            return None
        ledger = _read_json(run_dir / "ledger.json") or {}
        steps = data["steps"]
        mode = _str(data.get("mode")) or "scenario"
        rows = processes.step_rows(mode, steps, processes.spec_raw(run_dir), _str(_mapping(data.get("run")).get("status")))
        history = []
        for row in rows:
            record = _mapping(steps.get(row["key"]))
            if not record:
                continue
            history.append({"key": row["key"], "label": row["label"], "status": row["status"], "state": row["state"],
                            "partial": bool(record.get("partial")), "cost_usd": _number(record.get("cost_usd"))})
        jobs = sum(1 for job in _mapping(ledger.get("jobs")).values()
                   if isinstance(job, Mapping) and job.get("state") == "settled" and (_number(job.get("cost_usd")) or 0) > 0)
        return {"steps": history, "jobs": jobs, "spent_usd": _number(ledger.get("spent_usd")),
                "cap_usd": _number(ledger.get("cap_usd")), "hourly_usd": _number(ledger.get("hourly_usd")),
                "elapsed_seconds": _number(ledger.get("elapsed_seconds")),
                "max_hours": _number(ledger.get("max_hours"))}

    def _replays(self, case_id: str) -> List[Dict[str, Any]]:
        """Replay runs whose ``replay-result.json`` names this case, newest first."""

        found = []
        if self.runs_root is None or not self.runs_root.is_dir():
            return found
        from robot_debug.orchestrator import replay_text

        for folder in sorted(self.runs_root.iterdir(), reverse=True):
            result = _read_json(folder / "replay-result.json")
            if result is None or result.get("case_id") != case_id:
                continue
            verdict = _str(result.get("verdict")) or "inconclusive"
            ledger = _read_json(folder / "ledger.json") or {}
            found.append({"run": self._run_name(folder.name), "verdict": verdict, "verdict_text": replay_text(verdict),
                          "created": stamp_to_iso(folder.name), "cost_usd": _number(ledger.get("spent_usd"))})
        return found


def _default_inspect(workspace: Path, case_id: str) -> Mapping[str, Any]:
    from robot_debug.case_store import inspect_case

    return inspect_case(workspace, case_id)


def _explanation(status: Optional[str], disclaimer: Optional[str], model: Optional[str],
                 interpretation: Any) -> Dict[str, Any]:
    """The flat explanation block: hypotheses and observations with their evidence ids, and the limitations."""

    body = _mapping(interpretation)

    def entries(key: str) -> List[Dict[str, Any]]:
        return [{"text": e["text"], "evidence_ids": [i for i in _list(e.get("evidence_ids")) if isinstance(i, str)]}
                for e in _list(body.get(key)) if isinstance(e, Mapping) and isinstance(e.get("text"), str)]

    return {"status": status or "absent", "model": model, "disclaimer": disclaimer,
            "hypotheses": entries("hypotheses"), "observations": entries("observations"),
            "limitations": [t for t in _list(body.get("limitations")) if isinstance(t, str)]}


def _audit_sentence(case: Mapping[str, Any]) -> str:
    verdict, text, _attention = _audit_summary(case)
    parts = []
    for name, info in sorted(_mapping(case.get("families")).items()):
        severity = _number(_mapping(info).get("threshold_severity"))
        label = FAMILY_LABELS.get(name, name)
        parts.append("{} from severity {:g}".format(label, severity) if severity is not None
                     else "{}: no failure found".format(label))
    return text if not parts else text + " " + "; ".join(parts) + "."


def _paraphrase_block(case: Mapping[str, Any]) -> Dict[str, Any]:
    rows = [r for r in _list(case.get("screen")) if isinstance(r, Mapping)]
    control = next((r for r in rows if r.get("kind") == "original"), None)
    minimal = _mapping(case.get("minimal"))
    return {
        "original": _str(case.get("instruction")),
        "control": [o for o in _list(_mapping(control).get("outcomes")) if isinstance(o, str)],
        "paraphrases": [{"text": r["text"], "outcomes": [o for o in _list(r.get("outcomes")) if isinstance(o, str)],
                         "failures": r.get("failures") if type(r.get("failures")) is int else
                         sum(1 for o in _list(r.get("outcomes")) if o == "policy_failure"),
                         "meaning": _str(r.get("meaning_check"))}
                        for r in rows if r.get("kind") == "paraphrase" and isinstance(r.get("text"), str)],
        "minimal_edit": ({"text": minimal["text"], "edits": [e for e in _list(minimal.get("labels")) if isinstance(e, str)]}
                         if _str(minimal.get("text")) else None),
    }


def _paraphrase_from_run(run_dir: Path) -> Dict[str, Any]:
    """The paraphrase block of a run that found no failure: the wordings and the screen's outcomes."""

    stored = _read_json(run_dir / "paraphrases.json") or {}
    meanings = {c.get("text"): _str(c.get("meaning_check")) for c in _list(stored.get("meaning_checks"))
                if isinstance(c, Mapping)}
    summary = None
    jobs = run_dir / "jobs"
    if jobs.is_dir():
        for job in sorted(p for p in jobs.iterdir() if p.is_dir()):
            found = next(iter(sorted((job / "evidence").rglob("language_summary.json"))), None) \
                if (job / "evidence").is_dir() else None
            summary = _read_json(found) if found is not None else summary
            if summary is not None:
                break
    rows = [r for r in _list(_mapping(summary).get("instructions")) if isinstance(r, Mapping)]
    control = next((r for r in rows if r.get("kind") == "original"), None)
    return {
        "original": _str(stored.get("original")) or _str(_mapping(summary).get("original")),
        "control": [o for o in _list(_mapping(control).get("outcomes")) if isinstance(o, str)],
        "paraphrases": [{"text": r["text"], "outcomes": [o for o in _list(r.get("outcomes")) if isinstance(o, str)],
                         "failures": r.get("failures") if type(r.get("failures")) is int else
                         sum(1 for o in _list(r.get("outcomes")) if o == "policy_failure"),
                         "meaning": meanings.get(r["text"])}
                        for r in rows if r.get("kind") == "paraphrase" and isinstance(r.get("text"), str)],
        "minimal_edit": None,
    }
