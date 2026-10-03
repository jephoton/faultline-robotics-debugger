"""Private local binding and portable, source-free case exports."""
from __future__ import annotations

import json
import re
from pathlib import Path

from robot_debug.case_io import SanitizedCaseValidationError, _json, revalidate_case
from robot_debug.cases import CaseValidationError, normalize_case


_ID = re.compile(r"[0-9a-f]{64}\Z")


def _fail(message): raise SanitizedCaseValidationError(message)


def _id(case_id):
    if not isinstance(case_id, str) or _ID.fullmatch(case_id) is None: _fail("case ID must be a full lowercase SHA-256 digest")
    return case_id


def _workspace(workspace: Path, source_root: Path | None = None) -> Path:
    path = Path(workspace).resolve()
    if source_root is not None:
        root = Path(source_root).resolve()
        if path == root or root in path.parents: _fail("workspace must be outside source root")
    return path


def _case_dir(workspace: Path, case_id: str) -> Path:
    base = _workspace(workspace)
    path = base / _id(case_id)
    if path.is_symlink(): _fail("case directory is a symlink")
    return path


def _write(path: Path, value: dict):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _read(path: Path) -> dict:
    try:
        value = _json(path.parent, path.name)
        return normalize_case(value)
    except (CaseValidationError, SanitizedCaseValidationError): _fail("stored case metadata is invalid")


def _core(case: dict) -> dict:
    result = {key: value for key, value in case.items() if key not in {"capabilities", "measurements", "limitations"}}
    source = dict(result["source"])
    if source.get("profile") is None: source.pop("profile", None)
    result["source"] = source
    evidence = dict(result["evidence"])
    evidence.pop("media_counts", None)
    evidence.pop("media_availability", None)
    episodes = evidence.get("episodes")
    if isinstance(episodes, list):
        evidence["episodes"] = [{k: v for k, v in episode.items() if k not in {"video", "trace"}} if isinstance(episode, dict) else episode for episode in episodes]
    result["evidence"] = evidence
    return result


def register_case(case: dict, source_root: Path, workspace: Path) -> Path:
    """Persist a validated case and private source binding, exclusively."""
    base = _workspace(workspace, source_root)
    try: proposed = normalize_case(case)
    except CaseValidationError: _fail("case metadata is invalid")
    fresh = revalidate_case(proposed, source_root)
    if fresh["capabilities"]["inspection"]["status"] != "available": _fail("source evidence is unavailable or changed")
    if _core(proposed) != _core(fresh): _fail("case metadata differs from source evidence")
    base.mkdir(parents=True, exist_ok=True)
    target = _case_dir(base, proposed["case_id"])
    if target.exists():
        saved = _read(target / "case.json")
        if _core(saved) != _core(fresh): _fail("case ID collision has different payload")
        return target
    try: target.mkdir()
    except FileExistsError: _fail("case registry race")
    try:
        _write(target / "case.json", fresh)
        _write(target / "local-source.json", {"source_root": str(Path(source_root).resolve())})
    except BaseException:
        for name in ("case.json", "local-source.json"):
            (target / name).unlink(missing_ok=True)
        target.rmdir()
        raise
    return target


def _binding(target: Path) -> Path | None:
    try:
        data = _json(target, "local-source.json")
        if set(data) != {"source_root"} or not isinstance(data["source_root"], str): return None
        path = Path(data["source_root"])
        return path if path.is_absolute() else None
    except SanitizedCaseValidationError: return None


def inspect_case(workspace: Path, case_id: str) -> dict:
    target = _case_dir(workspace, case_id)
    if not target.is_dir(): _fail("case is unavailable")
    saved = _read(target / "case.json")
    if saved["case_id"] != case_id: _fail("stored case ID differs from directory")
    source = _binding(target)
    if source is None:
        saved["capabilities"] = {"inspection": {"status": "unavailable", "reasons": ["source binding is unavailable"]}, "replay_recipe": {"status": "incomplete", "missing": ["source.summary", "source.replay"]}, "exercised_replay": {"status": "unverified", "reasons": ["no fresh replay executed"]}, "historical_failure": {"status": "not-established", "reasons": ["source binding is unavailable"]}}
        return normalize_case(saved)
    return revalidate_case(saved, source)


def list_cases(workspace: Path) -> list[dict]:
    base = _workspace(workspace)
    if not base.is_dir(): return []
    result = []
    for target in sorted(base.iterdir(), key=lambda p: p.name):
        if not target.is_dir() and not target.is_symlink(): continue
        if _ID.fullmatch(target.name) is None:
            result.append({"case_id": None, "status": "unavailable", "reasons": ["malformed registry entry"]})
            continue
        try: result.append(inspect_case(base, target.name))
        except SanitizedCaseValidationError: result.append({"case_id": target.name, "status": "unavailable", "reasons": ["case entry is unavailable or invalid"]})
    return result


def export_case(workspace: Path, case_id: str, output: Path) -> Path:
    """Create a new portable metadata directory after full revalidation."""
    case = inspect_case(workspace, case_id)
    if case["capabilities"]["inspection"]["status"] != "available" and case["capabilities"]["inspection"]["reasons"] != ["optional media changed"]: _fail("core evidence is unavailable or changed")
    if case["capabilities"]["historical_failure"]["status"] == "conflicting": _fail("conflicting core evidence cannot be exported")
    out = Path(output)
    bound = _binding(_case_dir(workspace, case_id))
    if bound is not None:
        source = bound.resolve()
        destination = out.resolve()
        if destination == source or source in destination.parents: _fail("export target must be outside source root")
    if out.exists(): _fail("export target already exists")
    recipe = {key: case[key] for key in ("schema_version", "case_id", "task", "policy", "runtime", "perturbation", "protocol")}
    note = ("# Offline diagnostic case\n\n"
            "This case records saved historical evidence. No fresh replay was executed by import or export.\n\n"
            f"Historical failure: {case['capabilities']['historical_failure']['status']}\n\n"
            f"Replay recipe: {case['capabilities']['replay_recipe']['status']}\n\n"
            f"Missing inputs: {', '.join(case['capabilities']['replay_recipe']['missing']) or 'none'}\n\n"
            "Media files and private source binding are omitted. Claims are limited to the stored perturbation family and evidence.\n")
    try: out.mkdir(parents=True)
    except FileExistsError: _fail("export target already exists")
    try:
        _write(out / "case.json", case)
        (out / "README.md").write_text(note, encoding="utf-8")
        if case["capabilities"]["replay_recipe"]["status"] == "complete": _write(out / "replay_recipe.json", recipe)
    except BaseException:
        for name in ("case.json", "README.md", "replay_recipe.json"): (out / name).unlink(missing_ok=True)
        out.rmdir()
        raise
    return out


def reimport_case(index: Path, source_root: Path, workspace: Path) -> Path:
    """Rebind portable metadata to explicit local sources and rebuilt claims."""
    raw = _read(Path(index))
    fresh = revalidate_case(raw, source_root)
    if fresh["capabilities"]["inspection"]["status"] != "available" or raw["case_id"] != fresh["case_id"] or _core(raw) != _core(fresh): _fail("portable case differs from source evidence")
    return register_case(fresh, source_root, workspace)
