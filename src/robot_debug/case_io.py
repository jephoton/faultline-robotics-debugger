"""Bounded, offline import and revalidation of existing M4 reduction artifacts."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from robot_debug.cases import CaseValidationError, normalize_case, recipe_missing
from robot_debug.session import classify_aggregate
from robot_debug.viewer.catalog import ArtifactCatalog


class SanitizedCaseValidationError(ValueError):
    """Invalid source evidence; messages contain no source values or paths."""


_MAX_JSON = 8 * 1024 * 1024
_STAGE = re.compile(r"[a-z0-9][a-z0-9-]{0,150}\Z")


def _fail(message: str):
    raise SanitizedCaseValidationError(message)


def _relative(path: str) -> str:
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path or ":" in path or "\x00" in path or any(p in ("", ".", "..") for p in path.split("/")):
        _fail("source reference is not a portable relative path")
    return path


def _path(root: Path, relative: str, *, required=True) -> Path | None:
    relative = _relative(relative)
    base = root.resolve()
    candidate = root.joinpath(*relative.split("/"))
    try:
        candidate = candidate.resolve(strict=True)
        candidate.relative_to(base)
        if not candidate.is_file(): _fail("source reference is not a regular file")
    except (FileNotFoundError, OSError):
        if not required: return None
        _fail("source reference is unavailable")
    except (RuntimeError, ValueError):
        _fail("source reference escapes source root")
    return candidate


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ref(root: Path, relative: str) -> dict:
    return {"path": _relative(relative), "sha256": _hash(_path(root, relative))}


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result: _fail("JSON contains duplicate keys")
        result[key] = value
    return result


def _bad_constant(_): _fail("JSON contains nonfinite number")


def _json(root: Path, relative: str) -> dict:
    path = _path(root, relative)
    if path.stat().st_size > _MAX_JSON: _fail("JSON source exceeds size limit")
    try:
        value = json.loads(path.read_bytes().decode("utf-8", "strict"), object_pairs_hook=_pairs, parse_constant=_bad_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        _fail("JSON source is malformed")
    if not isinstance(value, dict) or value.get("schema_version", 1) != 1:
        _fail("JSON source schema is unsupported")
    return value


def _rect(value):
    if not isinstance(value, dict): return None
    try:
        nums = {key: float(value[key]) for key in ("x", "y", "width", "height")}
        if any(not math.isfinite(v) for v in nums.values()): return None
        if not (0 <= nums["x"] <= 1 and 0 <= nums["y"] <= 1 and nums["width"] > 0 and nums["height"] > 0 and nums["x"] + nums["width"] <= 1 and nums["y"] + nums["height"] <= 1): return None
        return nums
    except (KeyError, ValueError, TypeError, OverflowError): return None


def _same(a, b): return _rect(a) is not None and _rect(a) == _rect(b)


def _mask(value, rect):
    if rect is None: return value == {"enabled": False} or value is None
    if not isinstance(value, dict) or value.get("enabled") is not True or not _same(value, rect): return False
    if value.get("opacity") != 1 or type(value.get("opacity")) not in (int, float): return False
    color = value.get("color")
    return isinstance(color, list) and len(color) == 3 and all(type(c) is int and 0 <= c <= 255 for c in color) and len(set(color)) == 1


def _profile(root: Path, relative: str | None, summary: dict, replay: dict) -> tuple[dict, dict, dict | None]:
    policy = {"model_id": None, "checkpoint_revision": None, "provenance": {}}
    runtime = {"project_revision": None, "upstream_harness_revision": None, "simulator_image_digest": None, "provenance": {}}
    if relative is None: return policy, runtime, None
    data = _json(root, relative)
    if data.get("schema_version") != 1 or set(data) != {"schema_version", "policy", "runtime", "provenance"}: _fail("profile schema is unsupported")
    if not isinstance(data["policy"], dict) or not isinstance(data["runtime"], dict) or not isinstance(data["provenance"], dict): _fail("profile schema is malformed")
    allowed = {"policy.model_id", "policy.checkpoint_revision", "runtime.project_revision", "runtime.upstream_harness_revision", "runtime.simulator_image_digest"}
    for group, keys in (("policy", ("model_id", "checkpoint_revision")), ("runtime", ("project_revision", "upstream_harness_revision", "simulator_image_digest"))):
        if set(data[group]) - set(keys): _fail("profile field is unsupported")
        for key in keys:
            value = data[group].get(key)
            if value is None: continue
            dotted = f"{group}.{key}"
            if not isinstance(value, str) or not value or dotted not in data["provenance"]: _fail("profile pin lacks provenance")
            proof = data["provenance"][dotted]
            if not isinstance(proof, dict) or set(proof) != {"path", "sha256"}: _fail("profile proof is malformed")
            if _ref(root, proof["path"]) != proof: _fail("profile proof hash differs")
            source = summary.get("model_identity") if dotted == "policy.model_id" else summary.get("repository_revision") if dotted == "runtime.project_revision" else None
            if source is not None and source != value: _fail("profile pin conflicts with source")
            target = policy if group == "policy" else runtime
            target[key] = value
            target["provenance"][key] = proof
    if set(data["provenance"]) - allowed: _fail("profile provenance is unsupported")
    return policy, runtime, _ref(root, relative)


def import_m4(source_root: Path, summary: str = "failure-reduction/session_summary.json", replay: str = "failure-reduction/replay_case.json", profile: str | None = None) -> dict:
    """Import only allowlisted evidence, without running or copying source artifacts."""
    root = Path(source_root)
    if not root.is_dir(): _fail("source root is unavailable")
    src, manifest = _json(root, summary), _json(root, replay)
    if src.get("schema_version") != 1 or manifest.get("schema_version") != 1: _fail("M4 source version is unsupported")
    source = {"adapter": "existing-m4-v1", "summary": _ref(root, summary), "replay": _ref(root, replay)}
    policy, runtime, pref = _profile(root, profile, src, manifest)
    if pref: source["profile"] = pref
    reasons = []
    conflicting = []
    if src.get("model_identity") != manifest.get("model_identity") or src.get("repository_revision") != manifest.get("repository_revision"):
        conflicting.append("summary and replay identity differ")
    if manifest.get("task_id") != 0 or manifest.get("episode_index") != 0 or type(manifest.get("seed")) is not int: conflicting.append("replay task, episode, or seed is inconsistent")
    completed = src.get("completed") if isinstance(src.get("completed"), dict) else {}
    stages = completed.get("stages") if isinstance(completed.get("stages"), list) else []
    final = _rect(src.get("geometry", {}).get("final") if isinstance(src.get("geometry"), dict) else None)
    if final is None or not _same(final, manifest.get("rectangle")) or not _same(final, src.get("certified_rectangle")): conflicting.append("final rectangle differs")
    if manifest.get("acceptance_rule") != {"failures": 4, "attempts": 5}: conflicting.append("replay acceptance rule differs")
    structural = ArtifactCatalog._validate_reduction(src, manifest)
    if structural is None: reasons.append("reduction structure is incomplete")
    episodes, refs, selected, seed_values, media_counts = [], [], [], set(), {"videos": 0, "traces": 0}
    seen = set()
    for stage in stages:
        if not isinstance(stage, dict) or not isinstance(stage.get("stage"), str) or not _STAGE.fullmatch(stage["stage"]): conflicting.append("stage name is invalid"); continue
        name = stage["stage"]
        if name in seen: conflicting.append("duplicate stage"); continue
        seen.add(name)
        if stage.get("status") != "completed": continue
        stage_rect = _rect(stage.get("rectangle")) if stage.get("rectangle") is not None else None
        run = root / "failure-reduction" / "runs" / name
        if not run.is_dir(): reasons.append("stage aggregate is unavailable"); continue
        matches = sorted(run.rglob("*_aggregate.json"))
        if len(matches) == 0: reasons.append("stage aggregate is unavailable"); continue
        if len(matches) != 1: conflicting.append("stage aggregate is ambiguous"); continue
        try: rel = matches[0].relative_to(root).as_posix()
        except ValueError: conflicting.append("stage aggregate escapes source root"); continue
        aggregate = _json(root, rel)
        refs.append(_ref(root, rel))
        config = aggregate.get("config") if isinstance(aggregate.get("config"), dict) else {}
        params = config.get("params") if isinstance(config.get("params"), dict) else {}
        groups = aggregate.get("tasks")
        raw = groups[0].get("episodes") if isinstance(groups, list) and len(groups) == 1 and isinstance(groups[0], dict) else None
        if config.get("benchmark") != "robot_debug.libero:DiagnosticLIBEROBenchmark" or params.get("suite") != "libero_object" or params.get("task_id", 0) != 0 or not isinstance(raw, list) or len(raw) != 1:
            conflicting.append("stage benchmark or episode count differs"); continue
        episode = raw[0]
        if not isinstance(episode, dict) or episode.get("task_id") != 0 or episode.get("episode_idx", episode.get("episode_id")) != 0 or not _mask(params.get("agentview_occlusion"), stage_rect):
            conflicting.append("stage task, episode, or mask differs"); continue
        if params.get("seed") != manifest.get("seed") or type(params.get("env_seed")) is not int:
            conflicting.append("stage seed differs"); continue
        seed_values.add(params["env_seed"])
        try: result = classify_aggregate({"tasks": [{"episodes": [episode]}]})
        except ValueError: conflicting.append("raw episode is invalid"); continue
        reported = stage.get("results")
        if not isinstance(reported, list) or len(reported) != 1 or reported[0].get("outcome") != result.outcome:
            conflicting.append("summary result differs from raw episode"); continue
        role = "nominal" if stage_rect is None else "reduced" if _same(stage_rect, final) and name.startswith("delta-") else "parent" if name.startswith("parent-") else "other"
        server = aggregate.get("server_info") if isinstance(aggregate.get("server_info"), dict) else {}
        if role in ("parent", "reduced", "nominal") and server.get("model_identity") != src.get("model_identity"):
            reasons.append("historical policy identity is not linked to aggregate")
        entry = {"episode_id": f"{name}:0", "stage": name, "role": role, "aggregate": refs[-1], "task_id": 0, "reset_index": 0, "raw_outcome": result.outcome, "instruction": episode.get("name") if isinstance(episode.get("name"), str) and len(episode["name"]) < 300 else None}
        episodes.append(entry)
        selected.append((name, role, result.outcome, stage_rect))
    if len(seed_values) > 1: conflicting.append("stage environment seeds differ")
    env_seed = next(iter(seed_values)) if len(seed_values) == 1 else None
    if not stages or len(episodes) != len([s for s in stages if isinstance(s, dict) and s.get("status") == "completed"]): reasons.append("completed stage evidence is incomplete")
    evidence_complete = len(episodes) == len([s for s in stages if isinstance(s, dict) and s.get("status") == "completed"])
    if evidence_complete and (src.get("valid_episode_count") != len(episodes) or src.get("physical_episode_count") != len(episodes)): conflicting.append("summary episode counts differ")
    if completed.get("sentinel_outcome") != "success" or [outcome for name, role, outcome, rect in selected if role == "nominal" and name.startswith("nominal-control-")] != completed.get("control_outcomes"):
        conflicting.append("nominal control outcomes differ")
    accepted = [d for d in completed.get("decisions", []) if isinstance(d, dict) and d.get("label") == "candidate" and d.get("decision") == "pass" and _same(d.get("rectangle"), final)] if isinstance(completed.get("decisions"), list) else []
    if evidence_complete and accepted and accepted[-1].get("outcomes") != [o for _, role, o, rect in selected if role == "reduced" and _same(rect, final)]: conflicting.append("accepted outcomes differ from raw episodes")
    if not any(role == "parent" and outcome == "policy_failure" for _, role, outcome, _ in selected): reasons.append("parent failure evidence is missing")
    if src.get("stop_reason") != "reduced_failure_with_nominal_controls": reasons.append("nominal controls did not certify the reduction")
    if conflicting: history = "conflicting"; history_reasons = sorted(set(conflicting))
    elif reasons: history = "not-established"; history_reasons = sorted(set(reasons))
    else: history = "confirmed"; history_reasons = []
    case = {"schema_version": 1, "source": source, "task": {"suite": "libero-object", "task_id": 0, "reset_index": 0, "seed": manifest.get("seed") if type(manifest.get("seed")) is int else None, "env_seed": env_seed, "reset_strategy": "libero-init-state-index"}, "policy": policy, "runtime": runtime, "perturbation": {"family": "agentview-opaque-rectangle", "rectangle": final or {"x": .5, "y": 0, "width": .5, "height": .375}, "fill_value": 0}, "protocol": {"failures": 4, "max_attempts": 5, "reject_successes": 2, "nominal_controls": 5}, "evidence": {"episodes": episodes, "aggregate_refs": refs, "lineage": [{"rectangle": _rect(x.get("rectangle")), "edge": x.get("edge"), "delta": x.get("delta")} for x in src.get("lineage", []) if isinstance(x, dict) and _rect(x.get("rectangle"))], "media_counts": media_counts}, "measurements": {"source_reported_elapsed_seconds": src.get("elapsed_seconds") if type(src.get("elapsed_seconds")) in (int, float) and math.isfinite(src["elapsed_seconds"]) else None, "physical_episode_count": src.get("physical_episode_count"), "valid_episode_count": len(episodes) if not conflicting else None, "cost": None}, "capabilities": {}, "limitations": ["Historical evidence does not establish fresh replay or billing cost."]}
    try: case = normalize_case(case)
    except CaseValidationError: _fail("normalized case is invalid")
    missing = recipe_missing(case)
    case["capabilities"] = {"inspection": {"status": "available", "reasons": []}, "replay_recipe": {"status": "complete" if not missing else "incomplete", "missing": missing}, "exercised_replay": {"status": "unverified", "reasons": ["no fresh replay executed"]}, "historical_failure": {"status": history, "reasons": history_reasons}}
    return normalize_case(case)


def revalidate_case(case: dict, source_root: Path) -> dict:
    """Rebuild claims from source bytes; never trust saved capability flags."""
    try: saved = normalize_case(case)
    except CaseValidationError: _fail("stored case is invalid")
    source = saved["source"]
    for key in ("summary", "replay", "profile"):
        ref = source.get(key)
        if ref is not None:
            path = _path(Path(source_root), ref["path"], required=False)
            if path is None:
                degraded = dict(saved)
                degraded["capabilities"] = {"inspection": {"status": "unavailable", "reasons": ["source binding is unavailable"]}, "replay_recipe": {"status": "incomplete", "missing": recipe_missing(saved)}, "exercised_replay": {"status": "unverified", "reasons": ["no fresh replay executed"]}, "historical_failure": {"status": "not-established", "reasons": ["source binding is unavailable"]}}
                return normalize_case(degraded)
            if _hash(path) != ref["sha256"]: _fail("core source hash differs")
    fresh = import_m4(Path(source_root), source["summary"]["path"], source["replay"]["path"], source.get("profile", {}).get("path"))
    if fresh["case_id"] != saved["case_id"]: _fail("case identity differs from source")
    return fresh
