"""Drive a whole ``faultline`` diagnosis from the user's machine (ADR 0031).

Mode 1 (``scenario``): screen -> choose the failing start -> plan (Nemotron or the
fixed order) -> reduce Job -> continuation Jobs while the result is not
entity-minimal and the cap allows -> report, case, explanation, registration.
Mode 2 (``audit``): one audit Job -> report -> case -> registration.
``replay``: one Job that re-runs a saved case.

Everything that touches the cloud goes through a *backend* (``robot_debug.backends``)
and everything that builds workloads, plans, reports or explanations goes through a
*tools* object, so tests inject fakes and no test needs a network, a GPU or a key.
:class:`DefaultTools` loads the real scripts lazily.

The run folder (``artifacts/runs/<name>-<UTC stamp>/``)::

    spec.yaml                 the spec as run
    ledger.json               reservations and measured spend
    steps.json                progress log (resume reads it)
    plans/plan*.json          planning output (and the raw Nemotron reply)
    jobs/<job_name>/          workload.json, result.json, logs-tail.txt, evidence/
    report.md  case.json  minimal-candidate.json  explanation.json   final outputs

Resume (``--resume RUN_DIR``) skips completed steps, never resubmits a Job whose
result is recorded, and re-attaches to a Job that was submitted but not finished.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from robot_debug import ledger as lg
from robot_debug.spec import Spec

STEPS_SCHEMA = 1
MAX_ATTEMPTS = 6                       # submissions of one step under capacity failures
CAPACITY_PAUSE_SECONDS = 300
MAX_CONTINUATIONS = 3
RUNNING_GRACE_SECONDS = 300            # beyond the Job's own deadline before the watchdog cancels
QUEUE_ALLOWANCE_SECONDS = 2400         # waiting for a machine, pulling the image
PRICE_TOLERANCE = 1.05
REPLAY_ATTEMPTS = 5
REPLAY_REQUIRED_FAILURES = 4
MAX_WORKLOAD_BYTES = 64 * 1024
ATTEMPT_SUFFIXES = "abcdefghijklmnopqrstuvwxyz"
_STAMP = re.compile(r"(\d{8})T(\d{6})Z\Z")
_JOB_NAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class OrchestratorError(RuntimeError):
    """An unexpected local failure; the message is fixed text."""


class StopRun(Exception):
    """An expected end of the run (no failure found, cap reached, Job failed): not a crash."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason + (": " + detail if detail else ""))
        self.reason = reason
        self.detail = detail


class JobHandleRecord(NamedTuple):
    """Stand-in for ``backends.JobHandle`` when re-attaching to a recorded Job."""

    job_name: str
    job_id: str


@dataclass
class JobOutcome:
    step: str
    job_name: str
    summary: Dict[str, Any]
    summary_path: Path
    partial: bool
    state: str
    cost_usd: float


@dataclass
class RunResult:
    status: str                        # completed | stopped
    reason: Optional[str]
    run_dir: Path
    spent_usd: float
    case_id: Optional[str] = None
    reproduces: Optional[bool] = None
    notes: List[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return 0 if self.status == "completed" else 3


# --------------------------------------------------------------------------------------
# Run folder and progress log
# --------------------------------------------------------------------------------------


def utc_stamp(moment: dt.datetime) -> str:
    return moment.strftime("%Y%m%dT%H%M%SZ")


def create_run_dir(root: Path, spec: Spec, spec_text: Optional[str], moment: dt.datetime) -> Path:
    """``<root>/<name>-<stamp>/`` with a copy of the spec; never reuses a folder."""

    run_dir = Path(root) / "{}-{}".format(spec.name, utc_stamp(moment))
    run_dir.mkdir(parents=True, exist_ok=False)
    if spec_text is None:
        import yaml

        spec_text = yaml.safe_dump(dict(spec.raw), sort_keys=False)
    (run_dir / "spec.yaml").write_text(spec_text, encoding="utf-8", newline="\n")
    return run_dir


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=1, sort_keys=True, allow_nan=False, default=str) + "\n",
                         encoding="utf-8", newline="\n")
    os.replace(str(temporary), str(path))


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class StepLog:
    """``steps.json``: one record per step, rewritten after every change."""

    def __init__(self, path: Path, header: Mapping[str, Any]) -> None:
        self.path = Path(path)
        if self.path.exists():
            data = _read_json(self.path)
            if data.get("schema_version") != STEPS_SCHEMA or type(data.get("steps")) is not dict:
                raise OrchestratorError("steps.json is not a faultline progress log")
            self.data = data
        else:
            self.data = {"schema_version": STEPS_SCHEMA, **dict(header), "steps": {}}
            self.save()

    def save(self) -> None:
        _write_json(self.path, self.data)

    def get(self, step: str) -> Dict[str, Any]:
        return self.data["steps"].get(step, {})

    def is_done(self, step: str) -> bool:
        return self.get(step).get("status") == "done"

    def update(self, step: str, **fields: Any) -> Dict[str, Any]:
        record = self.data["steps"].setdefault(step, {})
        record.update(fields)
        self.save()
        return record

    def set_run(self, **fields: Any) -> None:
        self.data["run"] = dict(self.data.get("run", {}), **fields)
        self.save()


# --------------------------------------------------------------------------------------
# Pure helpers (also used by the tests)
# --------------------------------------------------------------------------------------


def find_file(root: Path, name: str, prefer: Optional[Path] = None) -> Optional[Path]:
    """The first ``name`` under ``root`` (the Job's download), preferring ``prefer`` if it has it."""

    if prefer is not None:
        direct = Path(prefer)
        for candidate in (direct, direct / name, direct / "scenario" / name, direct / "m6" / name):
            if candidate.is_file() and candidate.name == name:
                return candidate
    matches = sorted(Path(root).rglob(name))
    return matches[0] if matches else None


def _start_record(summary: Mapping[str, Any], task: int, start: int) -> Optional[Mapping[str, Any]]:
    task_entry = None
    for key in (str(task), task):
        if key in summary.get("tasks", {}):
            task_entry = summary["tasks"][key]
    if not isinstance(task_entry, Mapping):
        return None
    for key in (str(start), start):
        if key in task_entry.get("starts", {}):
            return task_entry["starts"][key]
    return None


def failures_of(record: Optional[Mapping[str, Any]]) -> int:
    """Policy failures among the first five attempts of a start that meets the 4-of-5 gate, else 0."""

    if not isinstance(record, Mapping) or record.get("validity") == "invalid_scene":
        return 0
    outcomes = record.get("outcomes")
    if not isinstance(outcomes, list) or len(outcomes) < 5:
        return 0
    count = outcomes[:5].count("policy_failure")
    return count if count >= 4 else 0


def choose_start(summary: Mapping[str, Any], task: int, given: Optional[int]) -> Optional[int]:
    """The failing start to reduce: the given one if it meets the gate, else the start with the most
    failures that meets it (ties: lowest index); ``None`` when nothing qualifies."""

    if given is not None:
        return given if failures_of(_start_record(summary, task, given)) else None
    best = None
    for key in (str(task), task):
        entry = summary.get("tasks", {}).get(key)
        if isinstance(entry, Mapping):
            for index, record in entry.get("starts", {}).items():
                count = failures_of(record)
                if count and (best is None or (count, -int(index)) > (best[0], -best[1])):
                    best = (count, int(index))
    return None if best is None else best[1]


def screen_table(summary: Mapping[str, Any], task: int) -> List[str]:
    """Starts that failed at least once, as ``start N: F S F F F (decision)`` lines."""

    letters = {"success": "S", "policy_failure": "F", "invalid_scene": "I"}
    lines = []
    entry = summary.get("tasks", {}).get(str(task)) or summary.get("tasks", {}).get(task) or {}
    for index, record in sorted(entry.get("starts", {}).items(), key=lambda item: int(item[0])):
        outcomes = record.get("outcomes") or []
        if any(item != "success" for item in outcomes):
            lines.append("start {}: {} ({})".format(
                index, " ".join(letters.get(item, "?") for item in outcomes), record.get("decision") or "-"))
    return lines or ["every screened start passed"]


def continuation_plan(plan: Mapping[str, Any], reduction: Mapping[str, Any]) -> Dict[str, Any]:
    """The plan for the follow-up reduction from the best reproducing selection (October 13, as code).

    The failing state becomes the reference with only the surviving selection applied; the
    reference is the one that reproduced; the order and ranking keep the surviving entities.
    """

    from robot_debug import scenario_state as ss

    selection, reference_id = reduction.get("final_selection"), reduction.get("reference")
    if not selection or reference_id is None:
        raise StopRun("no_continuation", "the reduction left no reproducing selection")
    layout = plan["layout"]
    entry = next((r for r in plan["references"] if r["start_index"] == reference_id), None)
    if entry is None:
        raise StopRun("no_continuation", "the chosen reference is not in the plan")
    reference_state = ss.validate_state(entry["state"], layout)
    failing_state = ss.validate_state(plan["failing"]["state"], layout)
    state = ss.hybrid(reference_state, failing_state, ss.normalise_selection(copy.deepcopy(selection), layout), layout)
    table = json.loads(json.dumps(ss.differences(state, reference_state, layout)))
    survivors = [row["entity"] for row in table]
    if not survivors:
        raise StopRun("no_continuation", "the surviving scene no longer differs from the reference")
    result = copy.deepcopy(dict(plan))
    result["failing"] = {"start_index": plan["failing"]["start_index"], "outcomes": ["policy_failure"] * 4,
                         "state": state.tolist()}
    result["references"] = [{
        "start_index": reference_id, "distance": float(ss.scenario_distance(state, reference_state, layout)),
        "outcomes": list(entry["outcomes"]), "state": reference_state.tolist(), "differences": table}]
    result["order"] = [name for name in plan["order"] if name in survivors]
    result["hypothesis"]["ranking"] = [name for name in plan["hypothesis"]["ranking"] if name in survivors]
    return result


def verified_selection(reduction: Mapping[str, Any]) -> bool:
    """The reduction ended on a selection that itself passed the failure gate."""

    return bool(reduction.get("final_selection")) and reduction.get("final_candidate") is not None


REPLAY_INPUTS = "replay-inputs.json"


def replay_verdict(summary: Mapping[str, Any]) -> Optional[bool]:
    """Whether a ``scenario-replay`` summary says the saved failure still reproduces.

    Expected shape: ``summary["replay"]["reproduces"]`` (bool). Otherwise the minimal scene's
    outcomes are read from ``summary["replay"]["minimal"]["outcomes"]`` against the 4-of-5 gate.
    ``None`` when the summary has neither.
    """

    verdict = summary.get("verdict")
    if verdict == "still_reproduces":
        return True
    if verdict == "no_longer_reproduces":
        return False
    replay = summary.get("replay")
    if not isinstance(replay, Mapping):
        return None
    if type(replay.get("reproduces")) is bool:
        return replay["reproduces"]
    minimal = replay.get("minimal")
    outcomes = minimal.get("outcomes") if isinstance(minimal, Mapping) else None
    if isinstance(outcomes, list) and outcomes:
        return outcomes.count("policy_failure") >= REPLAY_REQUIRED_FAILURES
    return None


# --------------------------------------------------------------------------------------
# Tools: workloads, planning, reports, explanation, registration (lazy, replaceable)
# --------------------------------------------------------------------------------------


def _load_script(name: str):
    key = "faultline_script_" + name
    if key in sys.modules:
        return sys.modules[key]
    path = REPOSITORY_ROOT / "scripts" / (name + ".py")
    if not path.is_file():
        raise OrchestratorError("this step needs a source checkout of Faultline (scripts/{}.py)".format(name))
    spec = importlib.util.spec_from_file_location(key, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(key, None)
        raise
    return module


class DefaultTools:
    """The real implementations. ``request`` and ``load_key`` let a test fake Nemotron."""

    def __init__(self, request: Optional[Callable[..., Any]] = None,
                 load_key: Optional[Callable[..., Any]] = None) -> None:
        self.request, self.load_key = request, load_key

    # time
    def now(self) -> dt.datetime:
        return dt.datetime.now(dt.timezone.utc)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    # workloads
    def screen_workload(self, run_id: str, suite: str, task: int, starts: str, confirm: int) -> Dict[str, Any]:
        import argparse

        module = _load_script("make_scenario_workload")
        args = argparse.Namespace(mode="screen", run_id=run_id, out=None, deadline=None, force=False,
                                  suite=suite, tasks=str(task), starts=starts, confirm_attempts=confirm)
        return self._checked(module.build(args))

    def reduce_workload(self, run_id: str, plan_path: Path, max_candidates: int) -> Dict[str, Any]:
        import argparse

        module = _load_script("make_scenario_workload")
        deadline = self.reduce_deadline(max_candidates)
        args = argparse.Namespace(mode="reduce", run_id=run_id, out=None, deadline=deadline, force=False,
                                  plan=Path(plan_path), max_candidates=max_candidates, concurrency=None,
                                  bisection_steps=None, no_speculative_bisection=False)
        return self._checked(module.build(args))

    def reduce_deadline(self, max_candidates: int) -> int:
        from robot_debug import scenario_experiment as se

        try:
            return se.recommended_deadline_seconds("scenario-reduce", {"max_candidates": max_candidates})
        except ValueError as error:
            raise StopRun("candidates_too_large", "budget.max_candidates {}: {}".format(max_candidates, error)) from None

    def audit_workload(self, spec: Spec, run_id: str) -> Dict[str, Any]:
        from robot_debug.workloads import audit_workload

        return self._checked(audit_workload(spec.raw if isinstance(spec, Spec) else spec, run_id))

    def replay_workload(self, case: Mapping[str, Any], run_id: str, attempts: int,
                        inputs: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        from robot_debug.workloads import replay_workload

        return self._checked(replay_workload(case, run_id, attempts=attempts, **dict(inputs or {})))

    def replay_inputs(self, case_dir: Path, case: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        """The layout and reference start a replay needs beyond ``case.json``.

        Read from ``replay-inputs.json`` beside the case (written when a diagnosis finishes and
        copied into the diagnoses index), else derived from the newest ``scenario-reduce``
        workload under ``jobs/``. ``None`` when neither exists.
        """

        stored = case_dir / REPLAY_INPUTS
        if stored.is_file():
            return _read_json(stored)
        from robot_debug.workloads import reference_inputs

        jobs = case_dir / "jobs"
        if not jobs.is_dir():
            return None
        for job in sorted((p for p in jobs.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
            path = job / "workload.json"
            if not path.is_file():
                continue
            workload = _read_json(path)
            if isinstance(workload, Mapping) and workload.get("mode") == "scenario-reduce":
                return reference_inputs(workload, case)
        return None

    @staticmethod
    def _checked(workload: Dict[str, Any]) -> Dict[str, Any]:
        if len(json.dumps(workload, sort_keys=True).encode("utf-8")) > MAX_WORKLOAD_BYTES:
            raise StopRun("workload_too_large", "the workload exceeds 64 KiB")
        return workload

    # planning
    def plan(self, summary: Mapping[str, Any], task: int, start: int, *, use_llm: bool,
             env_file: Optional[Path], references: int):
        module = _load_script("plan_scenario_reduction")
        kwargs: Dict[str, Any] = {}
        if self.request is not None:
            kwargs["request"] = self.request
        if self.load_key is not None:
            kwargs["load_key"] = self.load_key
        try:
            return module.build_plan_with_reply(summary, task, start, use_llm=use_llm, env_file=env_file,
                                                references=references, **kwargs)
        except module.PlanError as error:
            raise StopRun("plan_failed", str(error)) from None

    # reports and cases
    def scenario_report(self, summary: Mapping[str, Any], screen: Optional[Mapping[str, Any]],
                        hourly_usd: Optional[float]) -> str:
        module = _load_script("report_scenario_reduction")
        try:
            return module.build_report(summary, screen, hourly_usd)
        except (module.ReportError, KeyError, TypeError) as error:
            raise StopRun("report_failed", str(error)) from None

    def audit_report(self, summary: Mapping[str, Any]) -> str:
        module = _load_script("report_m6_experiment")
        try:
            return module.render_report([summary])
        except (module.ReportError, KeyError, TypeError) as error:
            raise StopRun("report_failed", str(error)) from None

    def build_case(self, summary: Mapping[str, Any]) -> Dict[str, Any]:
        from robot_debug import scenario_experiment as se

        try:
            return se.build_case(summary)
        except (ValueError, KeyError, TypeError):
            raise StopRun("case_failed", "the summary cannot be turned into a case") from None

    def write_candidate(self, path: Path, candidate: Mapping[str, Any]) -> None:
        from robot_debug.scenario_import import validate_scenario_candidate, write_scenario_candidate

        write_scenario_candidate(Path(path), validate_scenario_candidate(dict(candidate)))

    def explain(self, case_path: Path, out_path: Path, env_file: Optional[Path], label: str) -> Dict[str, Any]:
        module = _load_script("explain_case")
        return module.run_scenario_live(Path(case_path), Path(out_path), env_file, label)

    def register(self, run_dir: Path) -> str:
        from robot_debug.case_register import register_run

        return register_run(Path(run_dir))


# --------------------------------------------------------------------------------------
# The orchestrator
# --------------------------------------------------------------------------------------


def dry_run_lines(spec: Spec, tools: Any, *, rate: Optional[float] = None) -> Tuple[List[str], float]:
    """The planned Jobs and their worst-case spend, built from the spec alone (no backend call)."""

    rate = spec.backend.hourly_usd if rate is None else rate
    ledger_allowance = lg.DEFAULT_START_ALLOWANCE_SECONDS

    def worst(deadline: float) -> float:
        return (deadline + ledger_allowance) / 3600.0 * rate

    jobs: List[Tuple[str, str, int]] = []
    if spec.mode == "scenario":
        sc = spec.scenario
        if sc.import_path:
            raise StopRun("import_unsupported", "scenario.import is not supported yet; use start or screen")
        starts = _screen_starts(spec)
        screen = tools.screen_workload("dry-run", spec.suite, sc.task, starts, sc.confirm)
        reduce_deadline = tools.reduce_deadline(spec.budget.max_candidates)
        jobs.append(("screen", "screen task {} starts {}".format(sc.task, starts), int(screen["deadline_seconds"])))
        jobs.append(("reduce", "reduce the chosen failing start ({} candidates)".format(spec.budget.max_candidates),
                     reduce_deadline))
        for number in range(1, MAX_CONTINUATIONS + 1):
            jobs.append(("reduce{}".format(number + 1), "continuation {} (only if not entity-minimal)".format(number),
                         reduce_deadline))
    elif spec.mode == "audit":
        workload = tools.audit_workload(spec, "dry-run")
        jobs.append(("audit", "audit task {} start {}: {}".format(
            spec.audit.task, spec.audit.start, ", ".join(spec.audit.families)), int(workload["deadline_seconds"])))
    else:
        raise StopRun("dry_run_unsupported", "replay builds its Job from a case; there is nothing to plan")
    lines = ["Planned Jobs ({} backend, US${:.4f}/h, cap US${:.2f}, {:g} h):".format(
        spec.backend.kind, rate, spec.budget.max_spend_usd, spec.budget.max_hours)]
    required = 0.0
    for index, (step, text, deadline) in enumerate(jobs):
        cost = worst(deadline)
        optional = step.startswith("reduce") and step != "reduce" and spec.mode == "scenario"
        lines.append("  {:<8} {:<56} deadline {:>4d} s  worst case US${:.2f}{}".format(
            step, text, deadline, cost, "" if not optional else " (optional)"))
        if not optional:
            required += cost
    lines.append("Worst case of the required Jobs: US${:.2f}.".format(required))
    if required > spec.budget.max_spend_usd:
        lines.append("WARNING: that exceeds the cap; the spend ledger will refuse a Job and the run will stop early.")
    lines.append("Each Job is reserved at its worst case before submission and settled at measured container time.")
    return lines, required


def _screen_starts(spec: Spec) -> str:
    sc = spec.scenario
    if sc.screen_text is not None:
        return sc.screen_text.replace(" ", "")
    if sc.reference != "auto":
        return ",".join(str(i) for i in sorted({sc.start, sc.reference}))
    # The failing start plus a pool of benchmark starts to choose the nearest passing
    # reference from (scenario.pool, default 0-19; October 13's reference came from 10-49).
    from robot_debug.spec import parse_starts

    starts = set(parse_starts(sc.pool_text, "scenario.pool")) | {sc.start}
    return ",".join(str(i) for i in sorted(starts))


class Orchestrator:
    def __init__(self, spec: Spec, run_dir: Path, backend: Any, tools: Any, ledger: lg.Ledger, *,
                 env_file: Optional[Path] = None, no_llm: bool = False,
                 out: Callable[[str], None] = print, poll_seconds: float = 60.0,
                 pause_seconds: float = CAPACITY_PAUSE_SECONDS, max_attempts: int = MAX_ATTEMPTS) -> None:
        self.spec, self.run_dir, self.backend, self.tools, self.ledger = spec, Path(run_dir), backend, tools, ledger
        self.env_file, self.no_llm, self.out = env_file, no_llm, out
        self.poll_seconds, self.pause_seconds, self.max_attempts = poll_seconds, pause_seconds, max_attempts
        self.steps = StepLog(self.run_dir / "steps.json", {"name": spec.name, "mode": spec.mode})
        self._inflight: Optional[Tuple[Any, str]] = None
        self.cancel_outcome: Optional[Tuple[str, str]] = None
        match = _STAMP.search(self.run_dir.name)
        self.tag = (match.group(1)[2:] + match.group(2)[:4]) if match else "000000" + "0000"
        self.notes: List[str] = []

    # -- output -------------------------------------------------------------------------

    def say(self, step: str, message: str) -> None:
        self.out("{} {} … {}  {}".format(self.tools.now().strftime("%H:%M"), step, message, self.ledger.status_text()))

    def _warn(self, step: str, message: str) -> None:
        self.notes.append("{}: {}".format(step, message))
        self.say(step, "WARNING " + message)

    # -- entry points ----------------------------------------------------------------------

    def diagnose(self) -> RunResult:
        return self._guarded(self._diagnose)

    def replay(self, case_dir: Path) -> RunResult:
        return self._guarded(lambda: self._replay(Path(case_dir)))

    def _guarded(self, body: Callable[[], RunResult]) -> RunResult:
        try:
            try:
                self._start()
                result = body()
            except StopRun as stop:
                result = self._stopped(stop)
            return result
        except KeyboardInterrupt:
            self._cancel_inflight()
            self.steps.set_run(status="interrupted")
            raise
        except Exception:
            self._cancel_inflight()              # best effort: never leave a paid Job running behind a crash
            self.steps.set_run(status="failed")
            raise
        finally:
            try:
                self.backend.finish()
            except Exception as error:      # noqa: BLE001 - cleanup must not mask the result
                self.notes.append("backend cleanup failed: {}".format(type(error).__name__))
                self.out("WARNING backend cleanup failed ({}); check for leftover cloud resources".format(
                    type(error).__name__))

    def _start(self) -> None:
        self.backend.prepare(self.run_dir, self.spec.raw)       # backends read the raw YAML mapping
        try:
            live = self.backend.price_per_hour()
        except Exception:                   # noqa: BLE001 - a live price is optional
            live = None
        rate = self.spec.backend.hourly_usd
        if type(live) in (int, float) and live > rate * PRICE_TOLERANCE > 0:
            raise StopRun("price_above_spec", "the live price US${:.4f}/h is above backend.hourly_usd US${:.4f}/h; "
                          "update the spec so the cap arithmetic is right".format(live, rate))

    def _stopped(self, stop: StopRun) -> RunResult:
        self.steps.set_run(status="stopped", reason=stop.reason, detail=stop.detail)
        self.say("stop", "{}{}".format(stop.reason, " – " + stop.detail if stop.detail else ""))
        return RunResult("stopped", stop.reason, self.run_dir, self.ledger.spent, notes=list(self.notes))

    def _diagnose(self) -> RunResult:
        if self.spec.mode == "scenario":
            return self._scenario()
        if self.spec.mode == "audit":
            return self._audit()
        raise StopRun("wrong_mode", "a replay spec is used with `faultline replay`")

    # -- Jobs --------------------------------------------------------------------------------

    def job_name(self, step: str, number: int) -> str:
        name = "{}-{}-{}".format(self.spec.name, self.tag, step)
        if number:
            name += "-" + ATTEMPT_SUFFIXES[number - 1]
        if _JOB_NAME.fullmatch(name) is None:
            raise OrchestratorError("the Job name is not valid")
        return name

    def _handle(self, job_name: str, job_id: Any) -> Any:
        try:
            from robot_debug.backends import JobHandle

            return JobHandle(job_name, job_id)
        except Exception:                    # noqa: BLE001 - the backends package may be absent in tests
            return JobHandleRecord(job_name, job_id)

    def _cancel(self, handle: Any) -> str:
        """Ask the backend to cancel a Job. ``cancelled`` (the request was sent and accepted), ``finished``,
        ``not_found`` (no such Job: proven never created) or ``unconfirmed`` (the cancel itself failed)."""

        try:
            outcome = self.backend.cancel(handle)
        except Exception:                    # noqa: BLE001 - best effort
            return "unconfirmed"
        return outcome if outcome in ("cancelled", "finished", "not_found") else "cancelled"

    def _cancel_inflight(self) -> None:
        if self._inflight is None:
            return
        handle, job_name = self._inflight
        outcome = self._cancel(handle)
        try:
            if outcome == "not_found":
                self.ledger.settle(job_name, None)           # provably never created
            else:
                self.ledger.settle_worst_case(job_name)
        except lg.LedgerError:
            pass
        for record in self.steps.data["steps"].values():
            for attempt in record.get("attempts", []):
                if attempt.get("job_name") == job_name and attempt.get("state") in ("submitting", "submitted"):
                    attempt["state"] = "cancelled"
        self.steps.save()
        self.cancel_outcome = (job_name, outcome)
        self._inflight = None

    def interrupt_report(self) -> str:
        """What the interrupt did about the Job in flight; never claims a cancel that was not acknowledged."""

        if self.cancel_outcome is None:
            return "no Job was in flight, so nothing needed cancelling."
        name, outcome = self.cancel_outcome
        if outcome == "cancelled":
            return "the cancel request for Job {} was sent and acknowledged by the backend.".format(name)
        if outcome == "finished":
            return "Job {} had already finished; its spend is charged at the worst case.".format(name)
        if outcome == "not_found":
            return "Job {} did not exist, so nothing was cancelled and nothing is charged.".format(name)
        return ("WARNING: the cancel of Job {} could not be confirmed; check the cloud console and cancel it "
                "by hand. The ledger charges its worst case.".format(name))

    def run_job(self, step: str, workload: Mapping[str, Any], deadline: int, summary_name: str) -> JobOutcome:
        """Submit (resubmitting under capacity failures), wait, download and read one Job's summary."""

        record = self.steps.get(step)
        if record.get("status") == "done":
            return self._stored_outcome(step, record)
        attempts: List[Dict[str, Any]] = self.steps.update(step, status="running").setdefault("attempts", [])
        for number in range(self.max_attempts):
            job_name = self.job_name(step, number)
            prior = next((a for a in attempts if a["job_name"] == job_name), None)
            if prior is not None and prior["state"] in ("capacity", "cancelled", "failed"):
                continue
            job_dir = self.run_dir / "jobs" / job_name
            if prior is not None and prior["state"] == "submitted":
                handle = self._handle(job_name, prior["job_id"])
                self.say(step, "re-attaching to {}".format(job_name))
                self._inflight = (handle, job_name)
            elif prior is not None and prior["state"] == "submitting":
                handle = self._reattach_submitting(step, job_name, prior, deadline)
                if handle is None:                 # the interrupted submission never created the Job
                    continue
            else:
                handle = self._submit(step, job_name, workload, deadline, job_dir, attempts)
            outcome = self._await(step, handle, job_name, deadline, job_dir, attempts, summary_name)
            if outcome is not None:
                return outcome
            if number + 1 >= self.max_attempts:
                break
            try:
                self.ledger.check_time(extra_seconds=self.pause_seconds + deadline)
            except lg.TimeExhausted as error:
                raise StopRun("max_hours", str(error)) from None
            self.say(step, "no capacity; pausing {:g} s before resubmitting".format(self.pause_seconds))
            self.tools.sleep(self.pause_seconds)
        self.steps.update(step, status="stopped")
        raise StopRun("capacity_unavailable", "no GPU capacity after {} submissions".format(self.max_attempts))

    def _submit(self, step: str, job_name: str, workload: Mapping[str, Any], deadline: int, job_dir: Path,
                attempts: List[Dict[str, Any]]) -> Any:
        try:
            self.ledger.check_time(extra_seconds=deadline)
        except lg.TimeExhausted as error:
            self.steps.update(step, status="stopped")
            raise StopRun("max_hours", str(error)) from None
        payload = dict(workload, run_id=job_name)
        _write_json(job_dir / "workload.json", payload)
        # Record the attempt before reserving and before the real create, so a crash at any point leaves
        # a trail that --resume can follow (look the Job up by name; never reserve the same name twice).
        attempt: Dict[str, Any] = {"job_name": job_name, "job_id": None, "state": "submitting"}
        attempts.append(attempt)
        self.steps.save()
        try:
            self.ledger.reserve(job_name, self.ledger.worst_case_usd(deadline))
        except lg.BudgetExceeded as error:
            attempts.remove(attempt)
            self.steps.update(step, status="stopped")
            raise StopRun("spend_cap", str(error)) from None
        # In flight from here on: a Ctrl-C inside backend.submit cancels the Job by name.
        self._inflight = (self._handle(job_name, None), job_name)
        try:
            handle = self.backend.submit(job_name, payload)
        except Exception as error:
            # The real create may have run. Find the Job by name and cancel it; only a Job that provably
            # does not exist is free, anything else is charged the whole reservation.
            self._inflight = None
            outcome = self._cancel(self._handle(job_name, None))
            if outcome == "not_found":
                self.ledger.settle(job_name, None)
            else:
                self.ledger.settle_worst_case(job_name)
            attempt["state"] = "failed"
            self.steps.update(step, status="stopped")
            raise StopRun("backend_error", "submit failed ({}); {}".format(
                type(error).__name__, "no Job was created" if outcome == "not_found" else
                "the Job may exist and was {}; its worst case is charged".format(
                    "cancelled" if outcome == "cancelled" else "not confirmed cancelled"))) from None
        attempt.update(job_id=getattr(handle, "job_id", None), state="submitted")
        self._inflight = (handle, job_name)
        self.steps.update(step, job_name=job_name)
        self.say(step, "submitted {} (deadline {} s, reserved US${:.2f})".format(
            job_name, deadline, self.ledger.jobs[job_name]["reserved_usd"]))
        return handle

    def _reattach_submitting(self, step: str, job_name: str, attempt: Dict[str, Any], deadline: int) -> Any:
        """Resume an attempt that was interrupted inside ``backend.submit``: find the Job by name.

        Returns its handle (the existing reservation is kept), or ``None`` after settling the
        reservation at zero when the Job was provably never created.
        """

        try:
            found = self.backend.lookup(job_name)
        except Exception as error:               # noqa: BLE001 - the cloud cannot say; keep the reservation
            self.steps.update(step, status="stopped")
            raise StopRun("backend_error", "could not look up {} after an interrupted submission ({}); the "
                          "reservation is kept, resume again when the cloud API answers".format(
                              job_name, type(error).__name__)) from None
        if found is None:
            if job_name in self.ledger.jobs:
                self.ledger.settle(job_name, None)
            attempt["state"] = "failed"
            self.steps.save()
            self.say(step, "{} was never created; submitting under a new name".format(job_name))
            return None
        if job_name not in self.ledger.jobs:
            try:
                self.ledger.reserve(job_name, self.ledger.worst_case_usd(deadline))
            except lg.BudgetExceeded as error:
                self._cancel(found)
                attempt["state"] = "cancelled"
                self.steps.update(step, status="stopped")
                raise StopRun("spend_cap", str(error)) from None
        attempt.update(job_id=getattr(found, "job_id", None), state="submitted")
        self._inflight = (found, job_name)
        self.steps.update(step, job_name=job_name)
        self.say(step, "re-attaching to {} (found by name)".format(job_name))
        return found

    def _await(self, step: str, handle: Any, job_name: str, deadline: int, job_dir: Path,
               attempts: List[Dict[str, Any]], summary_name: str) -> Optional[JobOutcome]:
        attempt = next(a for a in attempts if a["job_name"] == job_name)
        running_max = deadline + RUNNING_GRACE_SECONDS
        total_max = max(60.0, min(running_max + QUEUE_ALLOWANCE_SECONDS, self.ledger.remaining_seconds()))
        try:
            result = self.backend.wait(handle, running_max_seconds=running_max, total_max_seconds=total_max,
                                       poll_seconds=self.poll_seconds)
        except Exception as error:               # noqa: BLE001 - polling failed after the backend's retries
            self._best_effort_cancel(handle)
            self.ledger.settle_worst_case(job_name)
            self._inflight = None
            attempt["state"] = "failed"
            self.steps.update(step, status="stopped")
            raise StopRun("backend_error", "waiting failed ({})".format(type(error).__name__)) from None
        state = str(getattr(result, "state", "UNKNOWN"))
        reason = getattr(result, "reason", None)
        seconds = getattr(result, "container_seconds", None)
        started = getattr(result, "started_at", None)
        if seconds is None and started is not None and getattr(result, "finished_at", None) is not None:
            try:
                seconds = (result.finished_at - started).total_seconds()
            except (TypeError, AttributeError):
                seconds = None
        capacity = "notenoughresources" in str(reason or "").lower() and not seconds
        if capacity:
            self.ledger.settle(job_name, None)
            self._inflight = None
            attempt["state"] = "capacity"
            self.steps.save()
            self.say(step, "{} found no capacity ({})".format(job_name, reason))
            return None
        if state in ("TIMEOUT", "UNKNOWN"):
            self._best_effort_cancel(handle)
        if seconds is None:                      # no measured time: assume the whole reservation was used
            cost = self.ledger.settle_worst_case(job_name)
        else:
            cost = self.ledger.settle(job_name, seconds)
        self._inflight = None                    # terminal and settled: a later Ctrl-C must not cancel or recharge it
        job_dir.mkdir(parents=True, exist_ok=True)
        _write_json(job_dir / "result.json", {
            "job_name": job_name, "job_id": getattr(handle, "job_id", None), "state": state, "reason": reason,
            "started_at": started, "finished_at": getattr(result, "finished_at", None),
            "container_seconds": seconds, "cost_usd": cost})
        self._save_logs(handle, job_dir)
        evidence = job_dir / "evidence"
        returned = None
        try:
            returned = self.backend.download(handle, evidence)
        except Exception as error:               # noqa: BLE001 - a missing download is reported below
            self.say(step, "download failed ({})".format(type(error).__name__))
        path = find_file(evidence, summary_name, returned) if evidence.exists() or returned else None
        summary = None
        if path is not None:
            try:
                summary = _read_json(path)
            except (OSError, ValueError):
                summary = None
        complete = isinstance(summary, dict) and summary.get("complete") is not False
        known_stop = isinstance(summary, dict) and isinstance(summary.get("stop_reason"), str)
        usable = isinstance(summary, dict) and ((state == "COMPLETED") or (not complete and known_stop))
        if not usable:
            attempt["state"] = "failed"
            self.steps.update(step, status="stopped")
            raise StopRun("job_failed", "{} ended {}{} without a usable summary".format(
                job_name, state, "" if not reason else " (" + str(reason) + ")"))
        partial = state != "COMPLETED" or not complete
        attempt["state"] = "settled"
        self.steps.update(step, status="done", job_name=job_name, job_id=getattr(handle, "job_id", None),
                          summary=path.relative_to(self.run_dir).as_posix(), partial=partial, state=state,
                          cost_usd=cost)
        self.say(step, "{} {}{}".format(job_name, state.lower(), " (partial summary: {})".format(
            summary.get("stop_reason")) if partial else ""))
        return JobOutcome(step, job_name, summary, path, partial, state, cost)

    def _stored_outcome(self, step: str, record: Mapping[str, Any]) -> JobOutcome:
        path = self.run_dir / record["summary"]
        self.say(step, "already done ({}); not resubmitting".format(record["job_name"]))
        return JobOutcome(step, record["job_name"], _read_json(path), path, bool(record.get("partial")),
                          str(record.get("state")), float(record.get("cost_usd", 0.0)))

    def _best_effort_cancel(self, handle: Any) -> None:
        try:
            self.backend.cancel(handle)
        except Exception:                        # noqa: BLE001
            pass

    def _save_logs(self, handle: Any, job_dir: Path) -> None:
        try:
            text = self.backend.logs_tail(handle, 200)
        except Exception as error:               # noqa: BLE001 - logs are a convenience
            text = "(log tail unavailable: {})".format(type(error).__name__)
        (job_dir / "logs-tail.txt").write_text(str(text), encoding="utf-8", newline="\n")

    # -- mode 1 --------------------------------------------------------------------------------

    def _scenario(self) -> RunResult:
        spec, sc = self.spec, self.spec.scenario
        if sc.import_path:
            raise StopRun("import_unsupported", "scenario.import is not supported yet; use start or screen")
        screen_workload = self.tools.screen_workload(
            self.job_name("screen", 0), spec.suite, sc.task, _screen_starts(spec), sc.confirm)
        screen = self.run_job("screen", screen_workload, int(screen_workload["deadline_seconds"]),
                              "scenario_summary.json")
        screen_summary = screen.summary
        start = choose_start(screen_summary, sc.task, sc.start)
        if start is None:
            self._write_screen_only_report(screen_summary, sc.task)
            raise StopRun("no_reproducible_failure",
                          "no start failed 4 of 5 attempts. " + "; ".join(screen_table(screen_summary, sc.task)))
        plan = self._plan(screen_summary, sc.task, start)
        best, last, reason = self._reduce_loop(plan)
        return self._finish_scenario(best, last, reason, screen_summary)

    def _write_screen_only_report(self, screen_summary: Mapping[str, Any], task: int) -> None:
        try:
            text = self.tools.scenario_report(screen_summary, None, self.spec.backend.hourly_usd)
            (self.run_dir / "report.md").write_text(text, encoding="utf-8", newline="\n")
        except (StopRun, OrchestratorError):
            pass
        for line in screen_table(screen_summary, task):
            self.out("  " + line)

    def _plan(self, screen_summary: Mapping[str, Any], task: int, start: int) -> Dict[str, Any]:
        path = self.run_dir / "plans" / "plan.json"
        if self.steps.is_done("plan"):
            return _read_json(path)
        sc = self.spec.scenario
        summary = screen_summary
        references = 3
        if sc.reference != "auto":
            summary = self._restricted(screen_summary, task, start, sc.reference)
            references = 1
        use_llm = self.spec.nemotron.hypothesis and not self.no_llm
        self.say("plan", "asking Nemotron for a hypothesis" if use_llm else "using the fixed order")
        try:
            config, raw = self.tools.plan(summary, task, start, use_llm=use_llm, env_file=self.env_file,
                                          references=references)
        except StopRun:
            raise
        except ValueError as error:
            raise StopRun("plan_failed", str(error)) from None
        _write_json(path, config)
        if raw:
            path.with_name("plan.json.hypothesis-raw.txt").write_text(raw, encoding="utf-8", newline="")
        hypothesis = config.get("hypothesis") or {}
        self.steps.update("plan", status="done", task=task, start=start, order_source=config.get("order_source"),
                          references=[r["start_index"] for r in config["references"]],
                          fallback_reason=hypothesis.get("fallback_reason"))
        self.say("plan", "start {} against reference {} ({} order{})".format(
            start, ",".join(str(r["start_index"]) for r in config["references"]), config.get("order_source"),
            "" if not hypothesis.get("fallback_reason") else ": " + str(hypothesis["fallback_reason"])))
        return config

    @staticmethod
    def _restricted(summary: Mapping[str, Any], task: int, start: int, reference: int) -> Dict[str, Any]:
        """The screen summary with only the failing start and the pinned reference, which must have passed."""

        result = copy.deepcopy(dict(summary))
        key = str(task) if str(task) in result["tasks"] else task
        starts = result["tasks"][key]["starts"]
        keep = {str(start), str(reference)}
        result["tasks"][key]["starts"] = {k: v for k, v in starts.items() if str(k) in keep}
        record = result["tasks"][key]["starts"].get(str(reference))
        outcomes = (record or {}).get("outcomes") or []
        if not outcomes or any(item != "success" for item in outcomes):
            raise StopRun("reference_not_passing", "the pinned reference start {} did not pass the screen".format(reference))
        return result

    def _reduce_loop(self, plan: Dict[str, Any]):
        """Reduce, then continue while not entity-minimal. Returns ``(best summary, last summary, reason)``."""

        best: Optional[Dict[str, Any]] = None
        last: Optional[Dict[str, Any]] = None
        reason: Optional[str] = None
        previous_selection = None
        for index in range(1 + MAX_CONTINUATIONS):
            step = "reduce" if index == 0 else "reduce{}".format(index + 1)
            path = self.run_dir / "plans" / ("plan.json" if index == 0 else "plan-{}.json".format(step))
            if index:
                _write_json(path, plan)
            elif not path.exists():
                _write_json(path, plan)
            try:
                workload = self.tools.reduce_workload(self.job_name(step, 0), path, self.spec.budget.max_candidates)
                outcome = self.run_job(step, workload, int(workload["deadline_seconds"]), "scenario_summary.json")
            except StopRun as stop:
                if best is None and last is None:
                    raise
                return best, last, stop.reason
            last = outcome.summary
            reduction = last.get("reduction") or {}
            if verified_selection(reduction):
                best = last
            reason = reduction.get("stop_reason") or last.get("stop_reason")
            self.say(step, "stop reason {}; entity-minimal {}; {} entities".format(
                reason, bool(reduction.get("entity_minimal")), len(reduction.get("surviving_entities") or [])))
            if reduction.get("reduced") or reduction.get("entity_minimal"):
                break
            if reason not in ("budget_exhausted", "deadline_exhausted") or not verified_selection(reduction):
                break
            if index == MAX_CONTINUATIONS:
                break
            if previous_selection is not None and reduction.get("final_selection") == previous_selection:
                reason = "no_progress"
                break
            previous_selection = reduction.get("final_selection")
            try:
                plan = continuation_plan(plan, reduction)
            except StopRun as stop:
                reason = stop.reason
                break
            self.say(step, "continuing from {} surviving entities".format(len(reduction["final_selection"])))
        return best, last, reason

    def _finish_scenario(self, best: Optional[Dict[str, Any]], last: Optional[Dict[str, Any]],
                         reason: Optional[str], screen_summary: Mapping[str, Any]) -> RunResult:
        summary = best or last
        reduction = (summary or {}).get("reduction") or {}
        if self.steps.is_done("report"):
            pass
        else:
            text = self.tools.scenario_report(summary, screen_summary, self.spec.backend.hourly_usd)
            (self.run_dir / "report.md").write_text(text, encoding="utf-8", newline="\n")
            self.steps.update("report", status="done")
            self.say("report", "report.md")
        case_id = None
        if best is not None:
            case_id = self._case_and_after(best)
        finished = bool(reduction.get("reduced") or reduction.get("entity_minimal")) and case_id is not None
        stop_reason = None if finished else (reason or "incomplete")
        self.steps.set_run(status="completed" if finished else "stopped", reason=stop_reason)
        self.say("done", "completed" if finished else "stopped: {}".format(stop_reason))
        return RunResult("completed" if finished else "stopped", stop_reason, self.run_dir, self.ledger.spent,
                         case_id=case_id, notes=list(self.notes))

    def _case_and_after(self, summary: Mapping[str, Any]) -> Optional[str]:
        case_path = self.run_dir / "case.json"
        if not self.steps.is_done("case"):
            case = self.tools.build_case(summary)
            _write_json(case_path, case)
            candidate = (case.get("replay") or {}).get("candidate")
            if candidate:
                self.tools.write_candidate(self.run_dir / "minimal-candidate.json", candidate)
            try:
                inputs = self.tools.replay_inputs(self.run_dir, case)
            except Exception as error:   # replay is optional; a missing input must not fail the run
                inputs = None
                self.notes.append("replay inputs not saved: {}".format(type(error).__name__))
            if inputs is not None:
                _write_json(self.run_dir / REPLAY_INPUTS, inputs)
            self.steps.update("case", status="done", case_id=case["case_id"])
            self.say("case", "case.json {}".format(case["case_id"][:12]))
        case_id = self.steps.get("case").get("case_id")
        self._explain(case_path, case_id)
        self._register("case")
        return case_id

    def _explain(self, case_path: Path, case_id: str) -> None:
        if not self.spec.nemotron.explain or self.no_llm or self.steps.is_done("explain"):
            return
        label = "d" + hashlib.sha256((self.run_dir.name + case_id).encode("utf-8")).hexdigest()[:20]
        self.say("explain", "asking Nemotron Ultra for an explanation (Token Factory; not on the GPU ledger)")
        try:
            self.tools.explain(case_path, self.run_dir / "explanation.json", self.env_file, label)
        except Exception as error:              # noqa: BLE001 - the explanation is optional
            self._warn("explain", "no explanation written ({}: {})".format(type(error).__name__, error))
            self.steps.update("explain", status="skipped")
            return
        self.steps.update("explain", status="done")
        self.say("explain", "explanation.json")

    def _register(self, after: str) -> None:
        if self.steps.is_done("register"):
            return
        try:
            case_id = self.tools.register(self.run_dir)
        except Exception as error:              # noqa: BLE001 - registration is a convenience
            self._warn("register", "the case was not registered in the viewer ({})".format(type(error).__name__))
            return
        self.steps.update("register", status="done", case_id=case_id)
        self.say("register", "viewer case {}".format(str(case_id)[:12]))

    # -- mode 2 --------------------------------------------------------------------------------

    def _audit(self) -> RunResult:
        workload = self.tools.audit_workload(self.spec, self.job_name("audit", 0))
        outcome = self.run_job("audit", workload, int(workload["deadline_seconds"]), "m6_summary.json")
        summary = outcome.summary
        if not self.steps.is_done("report"):
            text = self.tools.audit_report(summary)
            (self.run_dir / "report.md").write_text(text, encoding="utf-8", newline="\n")
            self.steps.update("report", status="done")
            self.say("report", "report.md")
        case = self._audit_case(summary, outcome)
        _write_json(self.run_dir / "case.json", case)
        self.steps.update("case", status="done", case_id=case["case_id"])
        self._register("case")
        finished = bool(summary.get("complete")) and not outcome.partial
        reason = None if finished else str(summary.get("stop_reason") or "incomplete")
        self.steps.set_run(status="completed" if finished else "stopped", reason=reason)
        self.say("done", "completed" if finished else "stopped: {}".format(reason))
        return RunResult("completed" if finished else "stopped", reason, self.run_dir, self.ledger.spent,
                         case_id=case["case_id"], notes=list(self.notes))

    def _audit_case(self, summary: Mapping[str, Any], outcome: JobOutcome) -> Dict[str, Any]:
        audit = self.spec.audit
        families = {}
        for name, item in sorted((summary.get("families") or {}).items()):
            if isinstance(item, Mapping):
                families[name] = {"threshold_severity": item.get("threshold_severity"),
                                  "stop_reason": item.get("stop_reason")}
        identity = json.dumps({"suite": self.spec.suite, "task": audit.task, "start": audit.start,
                               "families": list(audit.families), "run": self.run_dir.name},
                              sort_keys=True, separators=(",", ":"))
        return {
            "schema_version": 1, "kind": "audit",
            "case_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
            "suite": self.spec.suite, "task_id": audit.task, "start_index": audit.start,
            "families": families, "stop_reason": summary.get("stop_reason"),
            "complete": bool(summary.get("complete")) and not outcome.partial,
            "job_name": outcome.job_name,
            "summary": outcome.summary_path.relative_to(self.run_dir).as_posix(),
        }

    # -- replay --------------------------------------------------------------------------------

    def _replay(self, case_dir: Path) -> RunResult:
        case_path = case_dir if case_dir.is_file() else case_dir / "case.json"
        try:
            case = _read_json(case_path)
        except (OSError, ValueError):
            raise StopRun("case_unreadable", "case.json could not be read") from None
        if not isinstance(case, dict) or case.get("kind") != "scenario_reduction":
            raise StopRun("case_unsupported", "only scenario reduction cases can be replayed")
        if self.spec.suite is not None and self.spec.suite != case.get("suite"):
            raise StopRun("suite_mismatch", "the spec's suite differs from the case's")
        case_root = case_path.parent
        inputs = self.tools.replay_inputs(case_root, case)
        if inputs is None:
            raise StopRun("replay_inputs_missing",
                          "no replay-inputs.json and no scenario-reduce workload beside the case")
        workload = self.tools.replay_workload(case, self.job_name("replay", 0), REPLAY_ATTEMPTS, inputs)
        outcome = self.run_job("replay", workload, int(workload["deadline_seconds"]), "scenario_summary.json")
        verdict = replay_verdict(outcome.summary)
        _write_json(self.run_dir / "replay-result.json", {
            "case_id": case.get("case_id"), "reproduces": verdict,
            "verdict": (outcome.summary or {}).get("verdict"), "job_name": outcome.job_name,
            "summary": outcome.summary_path.relative_to(self.run_dir).as_posix()})
        text = {True: "the failure still reproduces", False: "the failure no longer reproduces",
                None: "the replay summary does not say"}[verdict]
        self.steps.set_run(status="completed" if verdict is not None else "stopped", reproduces=verdict)
        self.say("replay", text)
        return RunResult("completed" if verdict is not None else "stopped",
                         None if verdict is not None else "replay_inconclusive", self.run_dir, self.ledger.spent,
                         case_id=case.get("case_id"), reproduces=verdict, notes=list(self.notes))


__all__ = [
    "DefaultTools", "JobOutcome", "Orchestrator", "OrchestratorError", "RunResult", "StepLog", "StopRun",
    "choose_start", "continuation_plan", "create_run_dir", "dry_run_lines", "failures_of", "find_file",
    "replay_verdict", "screen_table", "utc_stamp", "verified_selection",
]
