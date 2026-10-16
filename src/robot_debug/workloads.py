"""Job workloads for ``faultline diagnose`` and ``faultline replay`` (runs on the workstation).

Pure functions that turn a user spec or a saved case into a workload JSON for one
Serverless Job. Every result goes through :func:`robot_debug.job_runtime.validate_workload_config`,
the same validator the Job applies, and must fit the 64 KiB inject limit, so a bad workload is
refused here before anything is submitted.

``audit_workload``
    The ``m6-threshold`` Job (mode 2): threshold searches for the chosen perturbation families
    on one suite, task and benchmark start.

``replay_workload``
    The ``scenario-replay`` Job: the case's minimal scene (expected to fail) and, when given, its
    reference scene (expected to pass), each run ``attempts`` times.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, Mapping, Optional, Sequence

from robot_debug import checkpoint_override, m6_experiment, scenario_experiment
from robot_debug.job_runtime import JobRuntimeError, validate_workload_config
from robot_debug.scenario_import import ScenarioImportError, validate_scenario_candidate

MAX_WORKLOAD_BYTES = 64 * 1024
# The recorded M6 search, used when the spec does not narrow it.
DEFAULT_AUDIT_SEARCH = {
    "sweep": [0.2, 0.4, 0.6, 0.8, 1.0], "attempts": 5, "required_failures": 4, "bisection_steps": 4,
}
_AUDIT_OVERRIDES = ("sweep", "attempts", "required_failures", "bisection_steps")
DEFAULT_REPLAY_ATTEMPTS = 5


class WorkloadError(ValueError):
    """The spec or case cannot become a valid workload; the message says why."""


def _finish(workload: Dict[str, Any], mode: str, run_id: str) -> Dict[str, Any]:
    try:
        validate_workload_config(workload)
    except JobRuntimeError as error:
        raise WorkloadError("the {} workload is invalid: {}".format(mode, error)) from error
    size = len(json.dumps(workload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    if size > MAX_WORKLOAD_BYTES:
        raise WorkloadError("the {} workload is {} bytes; the Job accepts at most {}".format(
            mode, size, MAX_WORKLOAD_BYTES))
    return workload


def _section(spec: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    section = spec.get(name) if isinstance(spec, Mapping) else None
    if not isinstance(section, Mapping):
        raise WorkloadError("the spec has no {} section".format(name))
    return section


def spec_checkpoint_fields(policy: Mapping[str, Any]) -> Dict[str, str]:
    """The workload fields for a spec's ``policy.checkpoint`` (``{id, revision}``); empty without one."""

    checkpoint = policy.get("checkpoint") if isinstance(policy, Mapping) else None
    if checkpoint is None:
        return {}
    if not isinstance(checkpoint, Mapping):
        raise WorkloadError("policy.checkpoint must be a mapping with id and revision")
    try:
        return checkpoint_override.as_fields((checkpoint.get("id"), checkpoint.get("revision")))
    except checkpoint_override.CheckpointOverrideError as error:
        raise WorkloadError("policy.checkpoint is invalid: {}".format(error)) from error


def audit_workload(spec: Mapping[str, Any], run_id: str) -> Dict[str, Any]:
    """The ``m6-threshold`` workload for a spec's ``audit`` section and ``policy.suite``.

    ``audit`` holds ``task`` (default 0), ``start`` (omitted: the upstream start behaviour) and
    ``families`` (a non-empty subset of ``m6_experiment.FAMILIES``: the image families darken, noise,
    blur, contrast, jpeg, colour_cast, motion_blur, dead_pixels and the scene families viewpoint and
    lighting; default the four recorded ones, which a LIBERO-10 audit cannot afford, see the deadline
    cap). ``policy.suite`` is any of the four LIBERO suites. It may also narrow the search with
    ``sweep``, ``attempts``, ``required_failures`` and ``bisection_steps``. The deadline is the
    recommended one for the search, and ``WorkloadError`` says so when it exceeds the cap.
    """

    audit = _section(spec, "audit")
    policy = spec.get("policy") if isinstance(spec.get("policy"), Mapping) else {}
    suite = policy.get("suite", "libero_object")
    if suite not in m6_experiment.SUITES:
        raise WorkloadError("policy.suite must be one of {}".format(", ".join(m6_experiment.SUITES)))
    families = audit.get("families", list(m6_experiment.LEGACY_FAMILIES))
    if (not isinstance(families, (list, tuple)) or not families
            or any(name not in m6_experiment.FAMILIES for name in families)
            or len(set(families)) != len(families)):
        raise WorkloadError("audit.families must be a non-empty subset of {}".format(
            ", ".join(m6_experiment.FAMILIES)))
    config = {
        "schema_version": 1, "mode": "m6-threshold", "run_id": run_id,
        "families": [name for name in m6_experiment.FAMILIES if name in families],
        "suite": suite, "task_id": audit.get("task", 0),
    }  # type: Dict[str, Any]
    if audit.get("start") is not None:
        config["init_state_index"] = audit["start"]
    config.update(spec_checkpoint_fields(policy))
    for key in _AUDIT_OVERRIDES:
        config[key] = copy.deepcopy(audit.get(key, DEFAULT_AUDIT_SEARCH[key]))
    if "required_failures" not in audit and type(config["attempts"]) is int:
        config["required_failures"] = min(config["required_failures"], config["attempts"])
    try:
        validate_workload_config(dict(config, deadline_seconds=3000))   # fields first, deadline next
        config["deadline_seconds"] = m6_experiment.recommended_deadline_seconds("m6-threshold", config)
    except JobRuntimeError as error:
        raise WorkloadError("the audit workload is invalid: {}".format(error)) from error
    except ValueError as error:
        raise WorkloadError(str(error)) from error
    return _finish(config, "audit", run_id)


def reference_inputs(reduce_workload: Mapping[str, Any], case: Mapping[str, Any]) -> Dict[str, Any]:
    """What :func:`replay_workload` needs beyond the case record, read from the diagnosis's
    ``scenario-reduce`` workload (which holds the layout and every reference start's state).

    Returns ``{"layout": ..., "reference_candidate": ...}`` for the case's reference start
    (the candidate is ``None`` when the case has no reference start).
    """

    layout = reduce_workload.get("layout")
    if not isinstance(layout, Mapping):
        raise WorkloadError("the reduce workload has no layout")
    candidate = None
    start = case.get("reference_start")
    if start is not None:
        entry = next((ref for ref in reduce_workload.get("references") or ()
                      if isinstance(ref, Mapping) and ref.get("start_index") == start), None)
        if entry is None:
            raise WorkloadError("the reduce workload has no reference start {}".format(start))
        from robot_debug.scenario_import import candidate_from_benchmark

        try:
            candidate = candidate_from_benchmark(case["suite"], case["task_id"], start, entry["state"])
        except (ScenarioImportError, KeyError) as error:
            raise WorkloadError("the reference start state is invalid") from error
    return {"layout": copy.deepcopy(dict(layout)), "reference_candidate": candidate}


def replay_workload(
    case: Mapping[str, Any],
    run_id: str,
    attempts: int = DEFAULT_REPLAY_ATTEMPTS,
    *,
    layout: Mapping[str, Any],
    reference_candidate: Optional[Mapping[str, Any]] = None,
    required_failures: Optional[int] = None,
    checkpoint: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """The ``scenario-replay`` workload for a scenario case record.

    ``case`` is the record written by ``scripts/report_scenario_reduction.py``: its
    ``replay.candidate`` is the minimal scene. The case record carries neither the scene layout
    nor the reference scene, so the caller supplies them (see :func:`reference_inputs`):

    * ``layout``: the task layout the case was reduced on (the ``layout`` of the diagnosis's
      ``scenario-reduce`` workload); the Job needs it to validate the scene states.
    * ``reference_candidate``: a scenario candidate (``build_candidate``) for the reference
      start state. Without it only the minimal scene is replayed and the verdict cannot be
      ``reference_fails``.

    ``required_failures`` defaults to the case's own gate, else ``min(4, attempts)``. ``checkpoint`` is an
    ``(id, revision)`` pair to serve instead of the suite's pinned checkpoint (replay a case against a
    changed policy); without it the workload is the same as before.
    """

    if not isinstance(case, Mapping) or not isinstance(case.get("replay"), Mapping):
        raise WorkloadError("the case record has no replay block")
    candidate = case["replay"].get("candidate")
    if candidate is None:
        raise WorkloadError("the case has no minimal candidate to replay")
    try:
        minimal = validate_scenario_candidate(candidate)
        reference = None if reference_candidate is None else validate_scenario_candidate(reference_candidate)
    except ScenarioImportError as error:
        raise WorkloadError("a scene candidate is invalid") from error
    for scene in (minimal, reference):
        if scene is not None and (scene["suite"] != case.get("suite") or scene["task_id"] != case.get("task_id")):
            raise WorkloadError("a scene candidate does not belong to the case's suite and task")
    if required_failures is None:
        gate = case["replay"].get("gate") if isinstance(case["replay"].get("gate"), Mapping) else {}
        wanted = gate.get("required_failures")
        required_failures = min(wanted if type(wanted) is int else 4, attempts) if type(attempts) is int else 4
    scenes = [{"name": "minimal", "role": "minimal", "state": minimal["state"], "source": minimal["source"]}]
    if reference is not None:
        scenes.append({"name": "reference", "role": "reference", "state": reference["state"],
                       "source": reference["source"]})
    config = {
        "schema_version": 1, "mode": "scenario-replay", "run_id": run_id, "suite": case["suite"],
        "task_id": case["task_id"], "layout": copy.deepcopy(dict(layout)), "scenes": scenes,
        "attempts": attempts, "required_failures": required_failures,
    }  # type: Dict[str, Any]
    if checkpoint is not None:
        try:
            config.update(checkpoint_override.as_fields(tuple(checkpoint)))
        except checkpoint_override.CheckpointOverrideError as error:
            raise WorkloadError("the checkpoint is invalid: {}".format(error)) from error
    try:
        validate_workload_config(dict(config, deadline_seconds=3000))
        config["deadline_seconds"] = scenario_experiment.recommended_deadline_seconds(
            "scenario-replay", {"scenes": scenes, "attempts": attempts})
    except JobRuntimeError as error:
        raise WorkloadError("the replay workload is invalid: {}".format(error)) from error
    return _finish(config, "replay", run_id)


__all__ = [
    "WorkloadError",
    "audit_workload",
    "reference_inputs",
    "replay_workload",
    "spec_checkpoint_fields",
]
