"""Synthetic artifact folders for the control-panel tests (library, server, export).

The shapes follow the real files the CLI writes (``case.json``, ``steps.json``, ``ledger.json``,
``m6_summary.json``, ``language_summary.json``, the diagnosis index made by ``register_run``), with obviously
fake ids, names and values: the repository is public, so nothing here comes from a real run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from robot_debug.case_register import register_run

SCENARIO_ID = "afb5" + "0123456789abcdef" * 3 + "0123456789ab"[:12]
SCENARIO_ID_TWIN = "afb5" + "fedcba9876543210" * 3 + "fedcba987654"[:12]
AUDIT_ID = "08d3" + "11" * 30
PARAPHRASE_ID = "c0de" + "22" * 30
OCCLUSION_ID = "52d8" + "33" * 30
FAKE_JOB_ID = "aijob-fakefakefake0001"
FAKE_PROJECT = "project-fakeproject0001"
FAKE_BUCKET = "faultline-fake-bucket-0001"
SCENARIO_RUN = "scenario-demo-20261016T064528Z"
TWIN_RUN = "scenario-twin-20261016T070000Z"
AUDIT_RUN = "audit-demo-20261015T155833Z"
PARAPHRASE_RUN = "paraphrase-demo-20261017T010203Z"
QUIET_RUN = "paraphrase-quiet-20261016T020108Z"
REPLAY_RUN = "replay-demo-20261016T120000Z"
LIVE_RUN = "scenario-live-20261017T020000Z"
for _id in (SCENARIO_ID, SCENARIO_ID_TWIN, AUDIT_ID, PARAPHRASE_ID, OCCLUSION_ID):
    assert len(_id) == 64 and all(c in "0123456789abcdef" for c in _id), _id

INSTRUCTION = "put both the alphabet soup and the tomato sauce in the basket"
CHECKPOINT = {"id": "example/checkpoint-libero_10", "pinned": True, "revision": "0123456789abcdef0123456789abcdef01234567"}


def write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1), encoding="utf-8")
    return path


def write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def spec_text(name: str, mode: str, suite: str = "libero_10", task: int = 0) -> str:
    section = {"scenario": "scenario: {{task: {task}, start: 14}}", "audit": "audit: {{task: {task}, start: 0, families: [darken, blur]}}",
               "paraphrase": "paraphrase: {{task: {task}, start: 7}}", "replay": ""}[mode].format(task=task)
    return ("faultline: 1\nname: {name}\nmode: {mode}\npolicy: {{suite: {suite}}}\n{section}\n"
            "budget: {{max_spend_usd: 10.0, max_hours: 5}}\nbackend:\n  kind: nebius\n  hourly_usd: 1.8\n").format(
                name=name, mode=mode, suite=suite, section=section)


def scenario_case(case_id: str = SCENARIO_ID) -> Dict[str, Any]:
    joints = [{"name": "robot0_joint{}".format(i), "offset": offset, "unit": "deg"}
              for i, offset in enumerate((-1.469, 2.129, 2.641, 2.527, 0.9, -1.1), start=1)]
    return {
        "schema_version": 1, "kind": "scenario_reduction", "case_id": case_id, "suite": "libero_10", "task_id": 0,
        "instruction": INSTRUCTION, "checkpoint": dict(CHECKPOINT), "failing_start": None,
        "failing_import": {"file_sha256": "ab" * 32, "state_sha256": "cd" * 32,
                           "source": {"init_state_index": 14, "kind": "benchmark"}},
        "reference_start": 28, "reduced": False, "stop_reason": "budget_exhausted",
        "differences": [
            {"entity": "robot", "kind": "robot", "joints": joints},
            {"entity": "soup_1", "kind": "object", "position_cm": 2.89},
            {"entity": "cheese_1", "kind": "object", "position_cm": 1.08, "rotation_deg": 12.0},
            {"entity": "sauce_1", "kind": "object", "position_cm": 0.7}],
        "minimal": {"entity_minimal": True, "parts": [],
                    "selection": {"soup_1": {"position": 1.0}, "cheese_1": {"position": 0.5, "rotation": 0.5},
                                  "robot": {"joints": 1.0}},
                    "sentence": "Moving soup_1 by 2.9 cm, cheese_1 by 0.5 cm and 6 robot joints is enough."},
        "hypothesis": {
            "ranking": ["robot", "soup_1", "sauce_1"], "source": "model", "model": "example/model",
            "measured_verdict": "necessary_not_sufficient", "verdict": None, "text": "free prose",
            "measurement": {"verdict": "necessary_not_sufficient", "entities": [
                {"entity": "robot", "label": "necessary_not_sufficient", "necessary": True, "sufficient": False, "rank": 1},
                {"entity": "soup_1", "label": "necessary_not_sufficient", "necessary": True, "sufficient": False, "rank": 2},
                {"entity": "sauce_1", "label": "not_in_final", "necessary": False, "sufficient": False, "rank": 3}]}},
        "evidence": [
            {"index": 0, "phase": "gate", "role": "failing", "selection": None, "decision": "reproduces",
             "outcomes": ["policy_failure"] * 4},
            {"index": 1, "phase": "gate", "role": "reference", "selection": None, "decision": "passes",
             "outcomes": ["success"] * 5},
            {"index": 2, "phase": "probe", "role": "hybrid", "selection": {"robot": {"joints": 1.0}},
             "decision": "does_not_reproduce", "outcomes": ["success"] * 3}],
        "measurements": {"attempts_run": 108},
        "videos": {role: {"case_id": role + "-a01", "key": "k" * 64, "outcome": outcome,
                          "video": "runs/{}-a01/episodes/{}.mp4".format(role, role)}
                   for role, outcome in (("original", "policy_failure"), ("minimal", "policy_failure"),
                                         ("reference", "success"))},
    }


def explanation_record(case_id: str) -> Dict[str, Any]:
    return {
        "case_id": case_id, "kind": "scenario_explanation", "interpretation_status": "validated-structure",
        "disclaimer": "No causal proof is established; human review is required.",
        "interpretation": {
            "hypotheses": [{"text": "The joint offsets may matter.", "evidence_ids": ["c1", "c2"]}],
            "observations": [{"text": "The robot ranked first and was necessary.", "evidence_ids": ["c2"]}],
            "limitations": ["Local minimum from limited reruns."]},
        "provenance": {"model": "example/nemotron", "source": "live", "provider": "example",
                       "endpoint": "https://example.invalid/v1/", "created_at": "2026-10-16T08:08:46Z"},
        "packet": {"differences": []},
    }


def audit_case() -> Dict[str, Any]:
    return {"schema_version": 1, "kind": "audit", "case_id": AUDIT_ID, "suite": "libero_goal", "task_id": 0,
            "start_index": 0, "complete": True, "stop_reason": None, "job_name": "audit-demo-2610151558-audit",
            "summary": "jobs/audit-demo-2610151558-audit/evidence/m6/m6_summary.json",
            "families": {"blur": {"stop_reason": "no_reproducible_failure", "threshold_severity": None},
                         "darken": {"stop_reason": "threshold_found", "threshold_severity": 0.35}}}


def audit_summary() -> Dict[str, Any]:
    def level(severity, failures):
        return {"severity": severity, "failures": failures, "complete": True,
                "outcomes": ["policy_failure"] * failures + ["success"] * (5 - failures)}

    return {"schema_version": 1, "mode": "m6-threshold", "complete": True, "stop_reason": None,
            "config": {"families": ["darken", "blur"], "sweep": [0.2, 0.4], "suite": "libero_goal", "task_id": 0},
            "nominal_controls": {"outcomes": {"success": 5}, "planned": 5},
            "families": {"darken": {"threshold_severity": 0.35, "levels": [level(0.2, 0), level(0.4, 5), level(0.35, 5)]},
                         "blur": {"threshold_severity": None, "levels": [level(0.2, 0), level(0.4, 1)]}}}


def paraphrase_case() -> Dict[str, Any]:
    return {
        "schema_version": 1, "kind": "paraphrase_reduction", "case_id": PARAPHRASE_ID, "suite": "libero_10",
        "task_id": 0, "start_index": 7, "instruction": INSTRUCTION, "checkpoint": dict(CHECKPOINT),
        "paraphrase": "Please put the soup and the tomato sauce in the basket", "stop_reason": "reduced",
        "reduced": True,
        "minimal": {"text": "put the alphabet soup and the tomato sauce in the basket", "edits": [{"id": 1}],
                    "edit_ids": [1], "labels": ["drop \"both\""], "edit_minimal": True, "meaning_check": "kept",
                    "sentence": "Dropping the word \"both\" is enough to make the policy fail."},
        "screen": [
            {"label": "orig", "kind": "original", "text": INSTRUCTION, "outcomes": ["success", "success"],
             "failures": 0, "decision": None, "edit_count": None, "meaning_check": None},
            {"label": "p01", "kind": "paraphrase", "text": "Please put the soup and the tomato sauce in the basket",
             "outcomes": ["policy_failure"] * 5, "failures": 5, "decision": "reproduces", "edit_count": 3,
             "meaning_check": "kept"},
            {"label": "p02", "kind": "paraphrase", "text": "Grab the soup.", "outcomes": ["success"],
             "failures": 0, "decision": None, "edit_count": 5, "meaning_check": "object_or_target_dropped"}],
        "videos": {}, "evidence": [], "measurements": {},
    }


def steps_document(name: str, mode: str, steps: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    return {"schema_version": 1, "name": name, "mode": mode, "steps": steps, "run": run}


def ledger_document(spent: float = 1.5) -> Dict[str, Any]:
    return {"schema_version": 1, "cap_usd": 10.0, "max_hours": 5.0, "hourly_usd": 1.8, "elapsed_seconds": 1234.5,
            "spent_usd": spent, "reserved_usd": 0.0,
            "jobs": {"job-a": {"state": "settled", "cost_usd": spent, "reserved_usd": 3.0, "container_seconds": 900},
                     "job-b": {"state": "settled", "cost_usd": 0.0, "reserved_usd": 3.0, "container_seconds": None}}}


def make_run(runs: Path, name: str, mode: str, steps: Dict[str, Any], run: Dict[str, Any], *, report: Optional[str] = None,
             case: Optional[Dict[str, Any]] = None, explanation: Optional[Dict[str, Any]] = None,
             spent: float = 1.5, videos: bool = False, spec_name: Optional[str] = None,
             suite: str = "libero_10") -> Path:
    folder = runs / name
    spec_name = spec_name or name.rsplit("-", 1)[0]
    write_text(folder / "spec.yaml", spec_text(spec_name, mode, suite))
    write_json(folder / "steps.json", steps_document(spec_name, mode, steps, run))
    write_json(folder / "ledger.json", ledger_document(spent))
    write_json(folder / "backend-state.json", {"project_id": FAKE_PROJECT, "bucket_name": FAKE_BUCKET})
    if report is not None:
        write_text(folder / "report.md", report)
    if case is not None:
        write_json(folder / "case.json", case)
    if explanation is not None:
        write_json(folder / "explanation.json", explanation)
    if videos:
        for role, entry in ((r, e) for r, e in (case or {}).get("videos", {}).items()):
            write_text(folder / "jobs" / "job-a" / "evidence" / "scenario" / entry["video"], "fake mp4 " + role)
    return folder


def build(root: Path) -> Dict[str, Path]:
    """Create ``root/artifacts`` with a registered scenario, twin scenario, audit and paraphrase diagnosis, a
    run that found nothing, a replay run, a live run folder and the occlusion case; return the paths."""

    artifacts = root / "artifacts"
    runs = artifacts / "runs"
    done = {"status": "stopped", "reason": "budget_exhausted"}
    scenario_steps = {
        "screen": {"status": "done", "state": "COMPLETED", "partial": False, "cost_usd": 0.4, "job_name": "job-a",
                   "job_id": FAKE_JOB_ID, "attempts": [{"job_name": "job-a", "job_id": FAKE_JOB_ID, "state": "settled"}]},
        "reduce": {"status": "done", "state": "FAILED", "partial": True, "cost_usd": 1.1, "job_name": "job-b",
                   "job_id": FAKE_JOB_ID, "attempts": [{"job_name": "job-b", "job_id": FAKE_JOB_ID, "state": "settled"}]},
        "report": {"status": "done"}, "case": {"status": "done", "case_id": SCENARIO_ID},
        "register": {"status": "done", "case_id": SCENARIO_ID}}
    report = "# Scenario reduction\n\nResult: see the table. Run folder C:\\Users\\someone\\artifacts\\runs\\x and /home/someone/y.\n"
    scenario_run = make_run(runs, SCENARIO_RUN, "scenario", scenario_steps, done, report=report, case=scenario_case(),
                            explanation=explanation_record(SCENARIO_ID), videos=True, spec_name="scenario-demo")
    write_json(scenario_run / "replay-inputs.json", {"layout": {"fake": True}})
    write_json(scenario_run / "minimal-candidate.json", {"state": [0.0, 1.0]})
    register_run(scenario_run, artifacts / "diagnoses")

    twin_steps = dict(scenario_steps, case={"status": "done", "case_id": SCENARIO_ID_TWIN},
                      register={"status": "done", "case_id": SCENARIO_ID_TWIN})
    twin = make_run(runs, TWIN_RUN, "scenario", twin_steps, done, report="# Twin\n", case=scenario_case(SCENARIO_ID_TWIN),
                    spec_name="scenario-twin")
    register_run(twin, artifacts / "diagnoses")

    audit_steps = {"audit": {"status": "done", "state": "COMPLETED", "partial": False, "cost_usd": 1.5,
                             "attempts": [{"job_name": "audit-demo-2610151558-audit", "state": "settled"}]},
                   "report": {"status": "done"}, "case": {"status": "done", "case_id": AUDIT_ID},
                   "register": {"status": "done", "case_id": AUDIT_ID}}
    audit = make_run(runs, AUDIT_RUN, "audit", audit_steps, {"status": "completed", "reason": None}, report="# Audit\n",
                     case=audit_case(), spec_name="audit-demo", suite="libero_goal")
    write_json(audit / "jobs" / "audit-demo-2610151558-audit" / "evidence" / "m6" / "m6_summary.json", audit_summary())
    register_run(audit, artifacts / "diagnoses")

    para_steps = {"paraphrase": {"status": "done", "count": 3}, "screen": {"status": "done", "state": "COMPLETED"},
                  "reduce": {"status": "done", "state": "COMPLETED"}, "report": {"status": "done"},
                  "case": {"status": "done", "case_id": PARAPHRASE_ID},
                  "register": {"status": "done", "case_id": PARAPHRASE_ID}}
    para = make_run(runs, PARAPHRASE_RUN, "paraphrase", para_steps, {"status": "completed", "reason": None},
                    report="# Paraphrase\n", case=paraphrase_case(), spec_name="paraphrase-demo")
    register_run(para, artifacts / "diagnoses")

    quiet_steps = {"paraphrase": {"status": "done", "count": 2}, "screen": {"status": "done", "state": "COMPLETED"}}
    quiet = make_run(runs, QUIET_RUN, "paraphrase", quiet_steps,
                     {"status": "stopped", "reason": "no_reproducible_failure", "detail": "raw detail"},
                     report="# Quiet\n", spec_name="paraphrase-quiet")
    write_json(quiet / "paraphrases.json", {
        "original": INSTRUCTION, "paraphrases": ["Place the soup and sauce in the basket.", "Drop the soup."],
        "meaning_checks": [{"text": "Place the soup and sauce in the basket.", "meaning_check": "kept"},
                           {"text": "Drop the soup.", "meaning_check": "object_or_target_dropped"}]})
    write_json(quiet / "jobs" / "paraphrase-quiet-2610160201-screen" / "evidence" / "language" / "language_summary.json", {
        "instructions": [
            {"label": "orig", "kind": "original", "text": INSTRUCTION, "outcomes": ["success", "success"], "failures": 0},
            {"label": "p01", "kind": "paraphrase", "text": "Place the soup and sauce in the basket.",
             "outcomes": ["success"], "failures": 0},
            {"label": "p02", "kind": "paraphrase", "text": "Drop the soup.", "outcomes": ["success"], "failures": 0}]})

    make_run(runs, REPLAY_RUN, "replay", {"replay": {"status": "done", "state": "COMPLETED", "cost_usd": 0.4}},
             {"status": "completed", "verdict": "still_reproduces", "reproduces": True}, spent=0.4, spec_name="replay-demo")
    write_json(runs / REPLAY_RUN / "replay-result.json", {"case_id": SCENARIO_ID, "reproduces": True,
                                                          "verdict": "still_reproduces", "job_name": "replay-job"})
    make_run(runs, LIVE_RUN, "scenario", {"screen": {"status": "running"}}, {"status": "running"}, spec_name="scenario-live")
    (runs / LIVE_RUN / "steps.json").write_text(json.dumps(
        steps_document("scenario-live", "scenario", {"screen": {"status": "running"}}, {})), encoding="utf-8")

    cases = artifacts / "cases" / OCCLUSION_ID
    source = artifacts / "m4-source"
    write_json(cases / "case.json", occlusion_case())
    write_json(cases / "local-source.json", {"source_root": str(source.resolve())})
    for episode in occlusion_case()["evidence"]["episodes"]:
        write_text(source / episode["video"]["path"], "fake mp4")
    return {"artifacts": artifacts, "runs": runs, "diagnoses": artifacts / "diagnoses", "cases": artifacts / "cases",
            "source": source}


def occlusion_case() -> Dict[str, Any]:
    rectangle = {"x": 0.625, "y": 0.0, "width": 0.375, "height": 0.375}
    return {
        "schema_version": 1, "case_id": OCCLUSION_ID, "task": {"suite": "libero-object", "task_id": 0, "seed": 7},
        "perturbation": {"family": "agentview-opaque-rectangle", "fill_value": 0, "rectangle": rectangle},
        "protocol": {"failures": 4, "max_attempts": 5},
        "policy": {"model_id": "example policy", "checkpoint_revision": None},
        "runtime": {"project_revision": "0" * 40},
        "evidence": {
            "episodes": [
                {"episode_id": "1a8513e316cce7aa", "stage": "parent-x0500", "role": "parent", "task_id": 0,
                 "reset_index": 0, "raw_outcome": "task_failure", "gate_outcome": "policy_failure",
                 "instruction": None, "video": {"path": "runs/parent/episode.mp4", "sha256": "0" * 64}},
                {"episode_id": "d02392d812d90d32", "stage": "nominal", "role": "nominal", "task_id": 0,
                 "reset_index": 0, "raw_outcome": "success", "gate_outcome": "success", "instruction": None,
                 "video": {"path": "runs/nominal/episode.mp4", "sha256": "0" * 64}}],
            "lineage": [{"rectangle": {"x": 0.625, "y": 0.0, "width": 0.375, "height": 0.5}, "edge": "left", "delta": 0.125},
                        {"rectangle": rectangle, "edge": "bottom", "delta": 0.125}],
            "media_counts": {"videos": 2, "traces": 0}, "media_availability": {"status": "available"}},
        "measurements": {"cost": None}, "capabilities": {},
    }
