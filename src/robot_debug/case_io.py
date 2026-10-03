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


class SanitizedCaseValidationError(CaseValidationError):
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
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError: _fail("source reference cannot be read")
    return digest.hexdigest()


def _ref(root: Path, relative: str) -> dict:
    try: return {"path": _relative(relative), "sha256": _hash(_path(root, relative))}
    except OSError: _fail("source reference cannot be read")


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result: _fail("JSON contains duplicate keys")
        result[key] = value
    return result


def _bad_constant(_): _fail("JSON contains nonfinite number")


def _json(root: Path, relative: str) -> dict:
    path = _path(root, relative)
    try:
        if path.stat().st_size > _MAX_JSON: _fail("JSON source exceeds size limit")
        content = path.read_bytes()
    except OSError: _fail("JSON source cannot be read")
    try:
        value = json.loads(content.decode("utf-8", "strict"), object_pairs_hook=_pairs, parse_constant=_bad_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        _fail("JSON source is malformed")
    if not isinstance(value, dict) or ("schema_version" in value and (type(value["schema_version"]) is not int or value["schema_version"] != 1)):
        _fail("JSON source schema is unsupported")
    return value


def _rect(value):
    if not isinstance(value, dict): return None
    try:
        if any(type(value[key]) not in (int, float) for key in ("x", "y", "width", "height")): return None
        nums = {key: float(value[key]) for key in ("x", "y", "width", "height")}
        if any(not math.isfinite(v) for v in nums.values()): return None
        if not (0 <= nums["x"] <= 1 and 0 <= nums["y"] <= 1 and nums["width"] > 0 and nums["height"] > 0 and nums["x"] + nums["width"] <= 1 and nums["y"] + nums["height"] <= 1): return None
        return nums
    except (KeyError, ValueError, TypeError, OverflowError): return None


def _same(a, b): return _rect(a) is not None and _rect(a) == _rect(b)


def _nonnegative_int(value): return type(value) is int and value >= 0


def _positive_finite_number(value):
    if type(value) not in (int, float): return False
    try: return math.isfinite(float(value)) and value > 0
    except (ValueError, OverflowError): return False


def _nonnegative_finite_number(value):
    if type(value) not in (int, float): return None
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, OverflowError): return None


def _evidence_core(value: dict) -> dict:
    result = dict(value)
    result.pop("media_counts", None)
    result.pop("media_availability", None)
    episodes = result.get("episodes")
    if isinstance(episodes, list):
        result["episodes"] = [{k: v for k, v in episode.items() if k not in {"video", "trace"}} if isinstance(episode, dict) else episode for episode in episodes]
    return result


def _mask(value, rect):
    if rect is None: return value == {"enabled": False} or value is None
    if not isinstance(value, dict) or value.get("enabled") is not True or not _same(value, rect): return False
    if set(value) != {"enabled", "x", "y", "width", "height", "color", "opacity"}: return False
    if value.get("opacity") != 1 or type(value.get("opacity")) not in (int, float): return False
    color = value.get("color")
    return isinstance(color, list) and len(color) == 3 and all(type(c) is int and 0 <= c <= 255 for c in color) and len(set(color)) == 1


def _media(root: Path, run: Path, benchmark: str, task_id: int, reset_index: int, suffix: str) -> tuple[dict | None, str | None]:
    pattern = f"task{task_id:04d}_ep{reset_index:04d}_*" + suffix
    paths = []
    directories = [run]
    if re.fullmatch(r"[A-Za-z0-9_.-]+", benchmark): directories.append(run / "episodes" / benchmark)
    for directory in directories:
        if directory.is_dir(): paths.extend(directory.glob(pattern))
    if not paths: return None, None
    if len(paths) != 1: return None, "optional media is ambiguous"
    try: return _ref(root, paths[0].relative_to(root).as_posix()), None
    except (SanitizedCaseValidationError, ValueError, OSError): return None, "optional media is unavailable"


def _profile(root: Path, relative: str | None, summary: dict, replay: dict) -> tuple[dict, dict, dict | None]:
    model = summary.get("model_identity") if isinstance(summary.get("model_identity"), str) and summary["model_identity"] else None
    revision = summary.get("repository_revision") if isinstance(summary.get("repository_revision"), str) and summary["repository_revision"] not in ("", "unknown") else None
    policy = {"model_id": model, "checkpoint_revision": None, "provenance": {"model_id": "source.summary.model_identity"} if model else {}}
    runtime = {"project_revision": revision, "upstream_harness_revision": None, "simulator_image_digest": None, "provenance": {"project_revision": "source.summary.repository_revision"} if revision else {}}
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
    task_id, reset_index, seed = (manifest.get(key) for key in ("task_id", "episode_index", "seed"))
    if any(type(value) is not int or value < 0 for value in (task_id, reset_index, seed)):
        _fail("replay task, episode, or seed is invalid")
    completed = src.get("completed") if isinstance(src.get("completed"), dict) else {}
    stages = completed.get("stages") if isinstance(completed.get("stages"), list) else []
    final = _rect(src.get("geometry", {}).get("final") if isinstance(src.get("geometry"), dict) else None)
    parent_rect = _rect(src.get("geometry", {}).get("parent") if isinstance(src.get("geometry"), dict) else None)
    if final is None: _fail("final rectangle is invalid")
    if not _same(final, manifest.get("rectangle")) or not _same(final, src.get("certified_rectangle")): conflicting.append("final rectangle differs")
    if manifest.get("acceptance_rule") != {"failures": 4, "attempts": 5}: conflicting.append("replay acceptance rule differs")
    if manifest.get("expected_outcome") != "policy_failure": conflicting.append("replay expected outcome differs")
    if manifest.get("source_summary") not in (None, summary.rsplit("/", 1)[-1]): conflicting.append("replay source summary differs")
    planned = src.get("planned")
    if isinstance(planned, dict) and planned.get("model_identity") != src.get("model_identity"): conflicting.append("planned policy identity differs")
    try: structural = ArtifactCatalog._validate_reduction(src, manifest)
    except (ValueError, TypeError, OverflowError, KeyError): structural = None
    if structural is None: reasons.append("reduction structure is incomplete")
    episodes, refs, selected, seed_values, fill_values, media_counts = [], [], [], set(), set(), {"videos": 0, "traces": 0}
    media_problems, episode_ids = [], set()
    session_rel = summary.rpartition("/")[0]
    seen = set()
    for stage in stages:
        if not isinstance(stage, dict) or not isinstance(stage.get("stage"), str) or not _STAGE.fullmatch(stage["stage"]): conflicting.append("stage name is invalid"); continue
        name = stage["stage"]
        if name in seen: conflicting.append("duplicate stage"); continue
        seen.add(name)
        if stage.get("status") != "completed": continue
        stage_rect = _rect(stage.get("rectangle")) if stage.get("rectangle") is not None else None
        if stage.get("rectangle") is not None and stage_rect is None:
            conflicting.append("stage rectangle is invalid"); continue
        if name.startswith("parent-") and not _same(stage_rect, parent_rect):
            conflicting.append("parent stage rectangle differs from declared parent")
        if stage.get("planned_episode_indices") is not None and stage["planned_episode_indices"] != [reset_index]:
            conflicting.append("stage planned reset differs"); continue
        run = root.joinpath(*session_rel.split("/")) / "runs" / name
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
        if config.get("benchmark") != "robot_debug.libero:DiagnosticLIBEROBenchmark" or params.get("suite") != "libero_object" or type(params.get("task_id", task_id)) is not int or params.get("task_id", task_id) != task_id or not isinstance(raw, list) or len(raw) != 1:
            conflicting.append("stage benchmark or episode count differs"); continue
        episode = raw[0]
        if not isinstance(episode, dict) or type(episode.get("task_id")) is not int or episode.get("task_id") != task_id or type(episode.get("episode_idx", episode.get("episode_id"))) is not int or episode.get("episode_idx", episode.get("episode_id")) != reset_index or not _mask(params.get("agentview_occlusion"), stage_rect):
            conflicting.append("stage task, episode, or mask differs"); continue
        if stage_rect is not None:
            fill_values.add(params["agentview_occlusion"]["color"][0])
        if not _nonnegative_int(params.get("seed")) or params["seed"] != seed or not _nonnegative_int(params.get("env_seed")):
            conflicting.append("stage seed differs"); continue
        seed_values.add(params["env_seed"])
        try: result = classify_aggregate({"tasks": [{"episodes": [episode]}]})
        except ValueError: conflicting.append("raw episode is invalid"); continue
        reported = stage.get("results")
        if not isinstance(reported, list) or len(reported) != 1 or not isinstance(reported[0], dict) or reported[0].get("outcome") != result.outcome or not _nonnegative_int(reported[0].get("episode_index")) or reported[0]["episode_index"] != reset_index or not _nonnegative_int(stage.get("physical_episode_count")) or stage["physical_episode_count"] != 1:
            conflicting.append("summary result differs from raw episode"); continue
        role = "nominal" if stage_rect is None else "reduced" if _same(stage_rect, final) and name.startswith("delta-") else "parent" if name.startswith("parent-") else "other"
        server = aggregate.get("server_info") if isinstance(aggregate.get("server_info"), dict) else {}
        if role in ("parent", "reduced", "nominal"):
            if "model_identity" not in server: reasons.append("historical policy identity is not linked to aggregate")
            elif server["model_identity"] != src.get("model_identity"): conflicting.append("aggregate policy identity differs")
        reason = episode.get("failure_reason")
        raw_outcome = "infrastructure_error" if result.outcome == "infrastructure_error" else "success" if result.outcome == "success" else "episode_timeout" if reason == "timeout" else "task_failure"
        identity = f"{aggregate.get('eval_id') or rel}:{task_id}:{reset_index}"
        episode_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        if episode_id in episode_ids: conflicting.append("stable episode identity repeats")
        episode_ids.add(episode_id)
        entry = {"episode_id": episode_id, "stage": name, "role": role, "aggregate": refs[-1], "task_id": task_id, "reset_index": reset_index, "raw_outcome": raw_outcome, "gate_outcome": result.outcome, "instruction": None}
        for key, suffix, count in (("video", ".mp4", "videos"), ("trace", ".jsonl", "traces")):
            media, media_problem = _media(root, run, aggregate.get("benchmark") if isinstance(aggregate.get("benchmark"), str) else "", task_id, reset_index, suffix)
            if media_problem: media_problems.append(media_problem)
            if media is not None:
                entry[key] = media
                media_counts[count] += 1
        episodes.append(entry)
        selected.append((name, role, result.outcome, stage_rect))
    if len(seed_values) > 1: conflicting.append("stage environment seeds differ")
    if len(fill_values) > 1: conflicting.append("stage fill colors differ")
    env_seed = next(iter(seed_values)) if len(seed_values) == 1 else None
    if not stages or len(episodes) != len([s for s in stages if isinstance(s, dict) and s.get("status") == "completed"]): reasons.append("completed stage evidence is incomplete")
    evidence_complete = len(episodes) == len([s for s in stages if isinstance(s, dict) and s.get("status") == "completed"])
    reported_valid = src.get("valid_episode_count")
    reported_physical = src.get("physical_episode_count")
    if not _nonnegative_int(reported_valid) or not _nonnegative_int(reported_physical): conflicting.append("summary episode counts are invalid")
    elif evidence_complete and (reported_valid != len(episodes) or reported_physical != len(episodes)): conflicting.append("summary episode counts differ")
    if completed.get("sentinel_outcome") != "success":
        conflicting.append("nominal control outcomes differ")
    if evidence_complete:
        if [outcome for name, role, outcome, rect in selected if name == "nominal-sentinel"] != ["success"] or [outcome for name, role, outcome, rect in selected if role == "nominal" and name.startswith("nominal-control-")] != completed.get("control_outcomes"):
            conflicting.append("nominal control outcomes differ")
    else:
        reasons.append("nominal control evidence is incomplete")
    parent = [d for d in completed.get("decisions", []) if isinstance(d, dict) and d.get("label") == "parent" and d.get("decision") == "pass" and _same(d.get("rectangle"), src.get("geometry", {}).get("parent"))] if isinstance(completed.get("decisions"), list) else []
    parent_raw = [outcome for name, role, outcome, rect in selected if role == "parent"]
    if evidence_complete and parent and parent[-1].get("outcomes") != parent_raw: conflicting.append("parent outcomes differ from raw episodes")
    if not parent or parent_raw.count("policy_failure") < 4 or len(parent_raw) > 5: reasons.append("parent reproducibility is not established")
    accepted = [d for d in completed.get("decisions", []) if isinstance(d, dict) and d.get("label") == "candidate" and d.get("decision") == "pass" and _same(d.get("rectangle"), final)] if isinstance(completed.get("decisions"), list) else []
    reduced_raw = [o for _, role, o, rect in selected if role == "reduced" and _same(rect, final)]
    if evidence_complete and accepted and accepted[-1].get("outcomes") != reduced_raw: conflicting.append("accepted outcomes differ from raw episodes")
    if reduced_raw.count("policy_failure") < 4 or len(reduced_raw) > 5: reasons.append("reduced failure count is not established")
    if not any(role == "parent" and outcome == "policy_failure" for _, role, outcome, _ in selected): reasons.append("parent failure evidence is missing")
    if src.get("stop_reason") != "reduced_failure_with_nominal_controls": reasons.append("nominal controls did not certify the reduction")
    if conflicting: history = "conflicting"; history_reasons = sorted(set(conflicting))
    elif reasons: history = "not-established"; history_reasons = sorted(set(reasons))
    else: history = "confirmed"; history_reasons = []
    lineage = []
    if not isinstance(src.get("lineage"), list): conflicting.append("lineage is invalid")
    else:
        for item in src["lineage"]:
            edge = item.get("edge") if isinstance(item, dict) else None
            delta = item.get("delta") if isinstance(item, dict) else None
            if not isinstance(item, dict) or _rect(item.get("rectangle")) is None or not isinstance(edge, str) or edge not in {"left", "right", "top", "bottom"} or not _positive_finite_number(delta):
                conflicting.append("lineage entry is invalid")
                continue
            lineage.append({"rectangle": _rect(item["rectangle"]), "edge": item["edge"], "delta": float(item["delta"])})
    if conflicting: history = "conflicting"; history_reasons = sorted(set(conflicting))
    media_availability = {"status": "available" if sum(media_counts.values()) else "unavailable", "reasons": sorted(set(media_problems)) if media_problems else ([] if sum(media_counts.values()) else ["media absent"])}
    case = {"schema_version": 1, "source": source, "task": {"suite": "libero-object", "task_id": task_id, "reset_index": reset_index, "seed": seed, "env_seed": env_seed, "reset_strategy": "libero-init-state-index"}, "policy": policy, "runtime": runtime, "perturbation": {"family": "agentview-opaque-rectangle", "rectangle": final, "fill_value": next(iter(fill_values)) if len(fill_values) == 1 else None}, "protocol": {"failures": 4, "max_attempts": 5, "reject_successes": 2, "nominal_controls": 5}, "evidence": {"episodes": episodes, "aggregate_refs": refs, "lineage": lineage, "media_counts": media_counts, "media_availability": media_availability}, "measurements": {"source_reported_elapsed_seconds": _nonnegative_finite_number(src.get("elapsed_seconds")), "physical_episode_count": reported_physical if _nonnegative_int(reported_physical) else None, "valid_episode_count": reported_valid if _nonnegative_int(reported_valid) and not conflicting and evidence_complete else None, "cost": None}, "capabilities": {}, "limitations": ["Historical evidence does not establish fresh replay or billing cost."]}
    try: case = normalize_case(case)
    except (CaseValidationError, RecursionError, OverflowError, TypeError): _fail("normalized case is invalid")
    missing = recipe_missing(case)
    case["capabilities"] = {"inspection": {"status": "available" if episodes else "unavailable", "reasons": [] if episodes else ["no validated episodes"]}, "replay_recipe": {"status": "complete" if not missing else "incomplete", "missing": missing}, "exercised_replay": {"status": "unverified", "reasons": ["no fresh replay executed"]}, "historical_failure": {"status": history, "reasons": history_reasons}}
    try: return normalize_case(case)
    except (CaseValidationError, RecursionError, OverflowError, TypeError): _fail("normalized case is invalid")


def revalidate_case(case: dict, source_root: Path) -> dict:
    """Rebuild claims from source bytes; never trust saved capability flags."""
    try: saved = normalize_case(case)
    except (CaseValidationError, RecursionError, OverflowError, TypeError): _fail("stored case is invalid")
    def unavailable():
        degraded = dict(saved)
        degraded["capabilities"] = {"inspection": {"status": "unavailable", "reasons": ["source binding is unavailable or changed"]}, "replay_recipe": {"status": "incomplete", "missing": sorted(set(recipe_missing(saved) + ["source.summary", "source.replay"]))}, "exercised_replay": {"status": "unverified", "reasons": ["no fresh replay executed"]}, "historical_failure": {"status": "not-established", "reasons": ["source binding is unavailable or changed"]}}
        return normalize_case(degraded)
    source = saved["source"]
    for key in ("summary", "replay"):
        ref = source[key]
        path = _path(Path(source_root), ref["path"], required=False)
        if path is None or _hash(path) != ref["sha256"]: return unavailable()
    profile = source.get("profile")
    profile_available = True
    if isinstance(profile, dict):
        path = _path(Path(source_root), profile["path"], required=False)
        profile_available = path is not None and _hash(path) == profile["sha256"]
    try:
        fresh = import_m4(Path(source_root), source["summary"]["path"], source["replay"]["path"], profile["path"] if isinstance(profile, dict) and profile_available else None)
    except SanitizedCaseValidationError:
        if not isinstance(profile, dict) or not profile_available: raise
        profile_available = False
        fresh = import_m4(Path(source_root), source["summary"]["path"], source["replay"]["path"])
    if profile_available and fresh["case_id"] != saved["case_id"]: _fail("case identity differs from source")
    core_keys = {"task", "policy", "runtime", "perturbation", "protocol"}
    def source_core(value):
        result = dict(value)
        if result.get("profile") is None: result.pop("profile", None)
        return result
    saved_source = source_core(saved["source"])
    fresh_source = source_core(fresh["source"])
    if not profile_available: saved_source.pop("profile", None)
    if not profile_available and (saved["task"] != fresh["task"] or saved["perturbation"] != fresh["perturbation"] or saved["protocol"] != fresh["protocol"]):
        return unavailable()
    if saved_source != fresh_source or (profile_available and any(saved[key] != fresh[key] for key in core_keys)):
        fresh["capabilities"]["inspection"] = {"status": "unavailable", "reasons": ["core evidence changed"]}
        fresh["capabilities"]["historical_failure"] = {"status": "not-established", "reasons": ["core evidence changed"]}
    else:
        if _evidence_core(saved["evidence"]) != _evidence_core(fresh["evidence"]):
            fresh["capabilities"]["inspection"] = {"status": "unavailable", "reasons": ["core evidence changed"]}
            fresh["capabilities"]["historical_failure"] = {"status": "not-established", "reasons": ["core evidence changed"]}
        elif saved["evidence"] != fresh["evidence"]:
            fresh["evidence"]["media_availability"] = {"status": "changed", "reasons": ["optional media changed"]}
    if not profile_available:
        rebound = dict(saved)
        rebound["evidence"] = fresh["evidence"]
        rebound["capabilities"] = fresh["capabilities"]
        missing = sorted(set(recipe_missing(fresh)))
        rebound["capabilities"]["replay_recipe"] = {"status": "incomplete", "missing": missing}
        return normalize_case(rebound)
    return fresh
