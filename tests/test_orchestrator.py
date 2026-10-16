"""The orchestrator: fake backend, fake Nemotron, summaries modelled on the October 13 runs."""

from __future__ import annotations

import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional

from robot_debug import ledger as lg
from robot_debug import orchestrator as orch
from robot_debug import scenario_state as ss
from robot_debug import spec as sp
from robot_debug.scenario_import import build_candidate
from tests.scenario_fakes import base_state, synthetic_layout, with_object_pose

RATE = 1.8
SECONDS = 1000                       # container seconds of every fake Job
INSTRUCTION = "put the soup in the basket"
MOMENT = dt.datetime(2026, 10, 14, 10, 15, 30, tzinfo=dt.timezone.utc)
SOUP, BOWL = 3, 11                   # free-joint addresses in the synthetic layout


class Handle(NamedTuple):
    job_name: str
    job_id: str


class Result(NamedTuple):
    job_name: str
    job_id: str
    state: str
    reason: Optional[str]
    started_at: Any
    finished_at: Any
    container_seconds: Optional[float]


class Crash(BaseException):
    """Stands in for a killed process: not caught by any `except Exception`."""


class BackendFailure(Exception):
    pass


def spec_for(mode="scenario", cap=10.0, hours=5.0, **overrides) -> sp.Spec:
    backend = {"kind": "nebius", "image": "cr.example.invalid/REGISTRY_ID/faultline@sha256:IMAGE_DIGEST",
               "hf_token_secret": "faultline-hf-token", "hourly_usd": RATE}
    data = {"faultline": 1, "name": "soup-start", "mode": mode, "policy": {"suite": "libero_10"},
            "budget": {"max_spend_usd": cap, "max_hours": hours, "max_candidates": 36},
            "nemotron": {"hypothesis": True, "explain": True}, "backend": backend}
    if mode == "scenario":
        data["scenario"] = overrides.pop("scenario", {"task": 3, "start": 0})
    elif mode == "audit":
        data["audit"] = {"task": 0, "start": 0, "families": ["blur", "noise"]}
    else:
        del data["policy"]
    data.update(overrides)
    return sp.parse_spec(data)


# --- summaries --------------------------------------------------------------------------------


def screen_summary(failing=True, extra_failing=None) -> Dict[str, Any]:
    layout = synthetic_layout()
    base = base_state(layout)
    fail = with_object_pose(with_object_pose(base, SOUP, dxyz=(0.05, 0, 0)), BOWL, dxyz=(0, 0.04, 0))
    near = with_object_pose(base, SOUP, dxyz=(0.04, 0, 0))              # soup differs by 1 cm only
    starts = {
        "0": {"outcomes": ["policy_failure"] * 5 if failing else ["success"], "state": fail.tolist(),
              "decision": "reproduces" if failing else None},
        "1": {"outcomes": ["success"], "state": near.tolist()},
        "2": {"outcomes": ["success"], "state": base.tolist()},
        "3": {"outcomes": ["policy_failure", "success", "policy_failure", "success", "success"],
              "state": near.tolist(), "decision": "does_not_reproduce"},
    }
    if extra_failing is not None:
        starts["7"] = {"outcomes": extra_failing, "state": fail.tolist(), "decision": "reproduces"}
    return {"schema_version": 1, "mode": "scenario-screen", "suite": "libero_10", "stop_reason": None,
            "complete": True, "total_seconds": 900, "checkpoint": None,
            "tasks": {"3": {"instruction": INSTRUCTION, "layout": layout, "starts": starts}},
            "reproducible_failures": [], "confirm": {"skipped_attempts": 2}, "topup": {"episodes": 0}}


def reduce_summary(workload: Dict[str, Any], *, stop_reason: str, selection: Dict[str, Any],
                   entity_minimal: bool, reduced: bool = False, verified: bool = True) -> Dict[str, Any]:
    layout = workload["layout"]
    reference = workload["references"][0]
    plan = {"suite": workload["suite"], "task_id": workload["task_id"], "instruction": workload["instruction"],
            "failing_start": workload["failing"]["start_index"],
            "references": [r["start_index"] for r in workload["references"]],
            "order": list(workload["order"]), "order_source": workload["order_source"],
            "hypothesis": copy.deepcopy(workload["hypothesis"])}
    candidate = None
    if selection:
        state = ss.hybrid(reference["state"], workload["failing"]["state"], selection, layout)
        candidate = build_candidate(workload["suite"], workload["task_id"], state, {
            "kind": "hybrid", "reference": reference["start_index"],
            "failing": workload["failing"]["start_index"],
            "applied": [{"entity": e, "component": c, "t": t} for e, parts in selection.items()
                        for c, t in parts.items()]})
    reduction = {
        "stop_reason": stop_reason, "reduced": reduced, "error": None, "note": None, "attempts": 5,
        "required_failures": 4, "bisection_steps": 4, "max_candidates": 36, "concurrency": 3,
        "speculative_bisection": True, "reference": reference["start_index"],
        "references_tried": [{"id": reference["start_index"], "decision": "passes", "outcomes": ["success"] * 5}],
        "order": list(workload["order"]), "entities": list(workload["order"]), "entity_minimal": entity_minimal,
        "surviving_entities": list(selection), "final_selection": selection or None,
        "final_candidate": 7 if (selection and verified) else None, "parts": [], "ranked_probe": None,
        "candidates": [], "candidates_tested": 12, "attempts_run": 60, "attempts_run_gates": 15,
        "attempts_run_hybrid": 45, "attempts_skipped": 20, "attempts_stop_withdrawn": 0, "invalid_scenes": []}
    return {"schema_version": 1, "mode": "scenario-reduce", "suite": workload["suite"], "plan": plan,
            "reduction": reduction, "differences": reference["differences"], "videos": {},
            "minimal_candidate": candidate, "checkpoint": None, "total_seconds": 600, "startup_seconds": 100,
            "stop_reason": stop_reason, "complete": reduced, "hypothesis_verdict": None,
            "hypothesis_measurement": None}


# --- the fake backend ----------------------------------------------------------------------------


def capacity() -> Dict[str, Any]:
    return {"state": "FAILED", "reason": "NotEnoughResources", "container_seconds": None}


def finished(summary: Callable[[Dict[str, Any]], Dict[str, Any]], name="scenario_summary.json",
             state="COMPLETED", reason=None, seconds=SECONDS) -> Dict[str, Any]:
    return {"state": state, "reason": reason, "container_seconds": seconds, "summary": summary,
            "summary_name": name}


class FakeBackend:
    kind = "fake"

    def __init__(self, behaviours: List[Dict[str, Any]], price=None) -> None:
        self.behaviours = list(behaviours)
        self.assigned: Dict[str, Dict[str, Any]] = {}
        self.workloads: Dict[str, Dict[str, Any]] = {}
        self.submitted: List[str] = []
        self.waited: List[str] = []
        self.cancelled: List[str] = []
        self.finished = 0
        self.prepared = 0
        self.price = price
        self.fail_prepare = False
        self.fail_submit_at: Optional[int] = None
        self.kills_at_wait: Optional[int] = None
        self.interrupt_at_wait: Optional[int] = None
        self.kill_class = Crash
        self.on_wait: Optional[Callable[[], None]] = None
        self.created: set = set()                    # Jobs that exist in the (fake) cloud
        self.submit_error: Optional[BaseException] = None
        self.error_after_create = True               # the injected submit error comes after the Job exists
        self.error_at_submit: Optional[int] = None
        self.interrupt_at_download = False
        self.cancel_error: Optional[Exception] = None
        self.lookup_error: Optional[Exception] = None
        # What a user stop does to the Job: (final state, container seconds or None); None = the hook is ignored.
        self.stop_outcome: Optional[tuple] = None
        self.stop_cancels: List[str] = []
        self.stop_hooks: List[bool] = []

    def prepare(self, run_dir, spec):
        self.prepared += 1
        if self.fail_prepare:
            raise BackendFailure("prepare")

    def price_per_hour(self):
        if self.price is None:
            raise BackendFailure("no price")
        return self.price

    def submit(self, job_name, workload):
        if self.fail_submit_at is not None and len(self.submitted) == self.fail_submit_at:
            raise BackendFailure("submit")
        failing = self.submit_error is not None and (
            self.error_at_submit is None or len(self.submitted) == self.error_at_submit)
        if failing and not self.error_after_create:
            raise self.submit_error
        self.submitted.append(job_name)
        self.created.add(job_name)
        self.workloads[job_name] = copy.deepcopy(workload)
        self.assigned[job_name] = self.behaviours.pop(0)
        if failing:
            raise self.submit_error
        return Handle(job_name, "id-" + job_name)

    def lookup(self, job_name):
        if self.lookup_error is not None:
            raise self.lookup_error
        return Handle(job_name, "id-" + job_name) if job_name in self.created else None

    def wait(self, handle, *, running_max_seconds, total_max_seconds, poll_seconds=60, should_stop=None):
        self.waited.append(handle.job_name)
        self.stop_hooks.append(should_stop is not None)
        if self.on_wait is not None:
            self.on_wait()
        if should_stop is not None and self.stop_outcome is not None and should_stop():
            self.stop_cancels.append(handle.job_name)
            state, seconds, *times = self.stop_outcome
            if times:                                  # (started_at, finished_at) when the test sets them
                return Result(handle.job_name, handle.job_id, state, "stopped_by_user", times[0][0], times[0][1], seconds)
            return Result(handle.job_name, handle.job_id, state, "stopped_by_user",
                          None if seconds is None else MOMENT, None if seconds is None else MOMENT, seconds)
        if self.kills_at_wait is not None and len(self.waited) == self.kills_at_wait:
            raise Crash()
        if self.interrupt_at_wait is not None and len(self.waited) == self.interrupt_at_wait:
            raise KeyboardInterrupt()
        behaviour = self.assigned.get(handle.job_name) or self.assigned.setdefault(
            handle.job_name, self.behaviours.pop(0))
        seconds = behaviour["container_seconds"]
        return Result(handle.job_name, handle.job_id, behaviour["state"], behaviour["reason"],
                      None if seconds is None else MOMENT, None if seconds is None else MOMENT, seconds)

    def download(self, handle, dest):
        if self.interrupt_at_download:
            self.interrupt_at_download = False
            raise KeyboardInterrupt()
        behaviour = self.assigned[handle.job_name]
        tree = Path(dest) / "faultline-runs" / handle.job_name
        if behaviour.get("summary") is not None:
            summary = behaviour["summary"](self.workloads.get(handle.job_name, {}))
            target = tree / "scenario" / behaviour["summary_name"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(summary), encoding="utf-8")
        else:
            tree.mkdir(parents=True, exist_ok=True)
        return tree

    def logs_tail(self, handle, lines):
        return "log of " + handle.job_name

    def cancel(self, handle):
        self.cancelled.append(handle.job_name)
        if self.cancel_error is not None:
            raise self.cancel_error
        return "cancelled" if handle.job_name in self.created else "not_found"

    def finish(self):
        self.finished += 1


class FakeTools(orch.DefaultTools):
    """Real planning, workloads, reports and cases; fake time, explanation and registration."""

    def __init__(self, explain_error=None) -> None:
        def request(instruction, differences, api_key, **kwargs):
            names = [row["entity"] for row in differences]
            ranking = list(reversed(names))                        # the model ranks the bowl first
            return {"source": "model", "ranking": ranking, "hypothesis": "The bowl matters.", "completed": [],
                    "model": "fake/nemotron", "tier": "ultra", "fallback_reason": None,
                    "provenance": {"model": "fake/nemotron"}, "raw_content": "raw reply"}

        super().__init__(request=request, load_key=lambda env: "FAKE-KEY")
        self.clock = MOMENT
        self.slept: List[float] = []
        self.explained: List[tuple] = []
        self.registered: List[Path] = []
        self.explain_error = explain_error
        self.on_sleep: Optional[Callable[[], None]] = None

    def now(self):
        return self.clock

    def sleep(self, seconds):
        self.slept.append(seconds)
        if self.on_sleep is not None:
            self.on_sleep()

    def explain(self, case_path, out_path, env_file, label):
        if self.explain_error is not None:
            raise self.explain_error
        self.explained.append((Path(case_path), Path(out_path), env_file, label))
        Path(out_path).write_text(json.dumps({"kind": "scenario_explanation"}), encoding="utf-8")
        return {"interpretation_status": "validated-structure"}

    def register(self, run_dir):
        self.registered.append(Path(run_dir))
        return "registered-case-id"


def make_world(spec: sp.Spec, behaviours, *, tools=None, backend=None, run_dir=None, **options):
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    tools = tools or FakeTools()
    backend = backend or FakeBackend(behaviours)
    if run_dir is None:
        run_dir = orch.create_run_dir(root / "runs", spec, None, MOMENT)
    clock = [1000.0]
    ledger = lg.Ledger.load(run_dir / "ledger.json", cap_usd=spec.budget.max_spend_usd,
                            max_hours=spec.budget.max_hours, hourly_usd=spec.backend.hourly_usd,
                            clock=lambda: clock[0])
    lines: List[str] = []
    options.setdefault("poll_seconds", 0.0)
    runner = orch.Orchestrator(spec, run_dir, backend, tools, ledger, out=lines.append, **options)
    runner.test_clock = clock
    return temp, runner, backend, tools, ledger, lines


def reduce_one(**kwargs):
    return lambda workload: reduce_summary(workload, **kwargs)


SOUP_ONLY = {"soup_1": {"position": 1.0}}
BOTH = {"soup_1": {"position": 1.0}, "bowl_1": {"position": 1.0}}


def full_script():
    """Screen, a partial reduce that needs a continuation, then an entity-minimal continuation."""

    return [
        finished(lambda workload: screen_summary()),
        finished(reduce_one(stop_reason="budget_exhausted", selection=BOTH, entity_minimal=False),
                 state="FAILED", reason="ContainerFailed"),
        finished(reduce_one(stop_reason="budget_exhausted", selection=SOUP_ONLY, entity_minimal=True)),
    ]


def cost(seconds=SECONDS):
    return (seconds + 240) / 3600.0 * RATE


class Base(unittest.TestCase):
    def world(self, behaviours, spec=None, **options):
        temp, runner, backend, tools, ledger, lines = make_world(spec or spec_for(), behaviours, **options)
        self.addCleanup(temp.cleanup)
        return runner, backend, tools, ledger, lines


class PureHelperTests(unittest.TestCase):
    def test_choose_start_prefers_most_failures_then_lowest_index(self):
        summary = screen_summary(extra_failing=["policy_failure"] * 5)
        self.assertEqual(orch.choose_start(summary, 3, None), 0)           # 5 failures, lowest of the ties
        summary = screen_summary(failing=False, extra_failing=["policy_failure", "success", "policy_failure",
                                                              "policy_failure", "policy_failure"])
        self.assertEqual(orch.choose_start(summary, 3, None), 7)           # 4 of 5 meets the gate
        self.assertIsNone(orch.choose_start(screen_summary(failing=False), 3, None))

    def test_choose_start_respects_a_given_start_and_the_gate(self):
        summary = screen_summary(extra_failing=["policy_failure"] * 5)
        self.assertEqual(orch.choose_start(summary, 3, 7), 7)
        self.assertIsNone(orch.choose_start(summary, 3, 3))                # flaky: 2 of 5
        self.assertIsNone(orch.choose_start(summary, 3, 99))

    def test_invalid_scene_never_counts_as_a_failure(self):
        summary = screen_summary()
        summary["tasks"]["3"]["starts"]["0"]["validity"] = "invalid_scene"
        self.assertIsNone(orch.choose_start(summary, 3, None))

    def test_screen_table_lists_only_starts_that_failed(self):
        lines = orch.screen_table(screen_summary(), 3)
        self.assertEqual(lines, ["start 0: F F F F F (reproduces)", "start 3: F S F S S (does_not_reproduce)"])

    def test_continuation_plan_follows_the_october_13_step(self):
        tools = FakeTools()
        config, _raw = tools.plan(screen_summary(), 3, 0, use_llm=True, env_file=None, references=3)
        self.assertEqual(config["order"], ["bowl_1", "soup_1"])
        reduction = {"final_selection": {"soup_1": {"position": 0.5}}, "reference": config["references"][0]["start_index"]}
        nxt = orch.continuation_plan(config, reduction)
        layout = config["layout"]
        reference = config["references"][0]
        expected = ss.hybrid(reference["state"], config["failing"]["state"], reduction["final_selection"], layout)
        self.assertEqual(nxt["failing"]["state"], expected.tolist())
        self.assertEqual(nxt["failing"]["outcomes"], ["policy_failure"] * 4)
        self.assertEqual(nxt["failing"]["start_index"], 0)
        self.assertEqual([r["start_index"] for r in nxt["references"]], [reference["start_index"]])
        self.assertEqual([row["entity"] for row in nxt["references"][0]["differences"]], ["soup_1"])
        self.assertEqual(nxt["order"], ["soup_1"])
        self.assertEqual(nxt["hypothesis"]["ranking"], ["soup_1"])
        self.assertEqual(config["order"], ["bowl_1", "soup_1"], "the input plan is not modified")
        self.assertEqual(tools.reduce_workload("x" * 3, _write(config), 36)["mode"], "scenario-reduce")

    def test_continuation_without_a_selection_stops(self):
        with self.assertRaises(orch.StopRun):
            orch.continuation_plan({"references": []}, {"final_selection": None, "reference": None})

    def test_replay_verdict(self):
        self.assertTrue(orch.replay_verdict({"replay": {"reproduces": True}}))
        self.assertFalse(orch.replay_verdict({"replay": {"reproduces": False}}))
        self.assertTrue(orch.replay_verdict({"replay": {"minimal": {"outcomes": ["policy_failure"] * 4 + ["success"]}}}))
        self.assertFalse(orch.replay_verdict({"replay": {"minimal": {"outcomes": ["success"] * 5}}}))
        self.assertIsNone(orch.replay_verdict({}))
        self.assertTrue(orch.replay_verdict({"verdict": "still_reproduces"}))
        self.assertFalse(orch.replay_verdict({"verdict": "no_longer_reproduces"}))
        self.assertIsNone(orch.replay_verdict({"verdict": "reference_fails"}))

    def test_replay_verdict_key_keeps_the_provider_verdict(self):
        self.assertEqual(orch.replay_verdict_key({"verdict": "reference_fails"}), "reference_fails")
        self.assertEqual(orch.replay_verdict_key({"verdict": "invalid_scene"}), "invalid_scene")
        self.assertEqual(orch.replay_verdict_key({"verdict": "still_reproduces"}), "still_reproduces")
        self.assertEqual(orch.replay_verdict_key({"replay": {"reproduces": False}}), "no_longer_reproduces")
        self.assertIsNone(orch.replay_verdict_key({}))
        self.assertIn("reference failed", orch.replay_text("reference_fails"))
        self.assertIn("invalid", orch.replay_text("invalid_scene"))
        self.assertIn("does not say", orch.replay_text(None))


def _write(config):
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(config, handle)
    handle.close()
    return Path(handle.name)


class JobNaming(Base):
    def test_job_tag_includes_the_seconds_so_runs_in_one_minute_do_not_collide(self):
        first, _b, _t, _l, _o = self.world([], run_dir=None)
        later = MOMENT + dt.timedelta(seconds=7)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        spec = spec_for()
        other_dir = orch.create_run_dir(Path(temp.name), spec, None, later)
        other, *_rest = self.world([], run_dir=other_dir)
        self.assertEqual(first.tag, "261014101530")
        self.assertEqual(other.tag, "261014101537")
        self.assertNotEqual(first.job_name("screen", 0), other.job_name("screen", 0))

    def test_the_longest_job_name_still_fits_the_provider_limit(self):
        spec = spec_for(name="a" * 40)
        runner, *_rest = self.world([], spec=spec)
        longest = runner.job_name("reduce4", 5)
        self.assertLessEqual(len(longest), 63)


class Mode1EndToEnd(Base):
    def test_screen_reduce_one_continuation_report_case_explanation_register(self):
        runner, backend, tools, ledger, lines = self.world(full_script())
        result = runner.diagnose()
        run_dir = runner.run_dir

        self.assertEqual((result.status, result.reason, result.exit_code), ("completed", None, 0))
        tag = runner.tag
        self.assertEqual(backend.submitted, ["soup-start-{}-{}".format(tag, s) for s in ("screen", "reduce", "reduce2")])
        for name in backend.submitted:
            self.assertEqual(backend.workloads[name]["run_id"], name)
            self.assertTrue((run_dir / "jobs" / name / "workload.json").is_file())
            self.assertTrue((run_dir / "jobs" / name / "result.json").is_file())
            self.assertEqual((run_dir / "jobs" / name / "logs-tail.txt").read_text(), "log of " + name)
        self.assertAlmostEqual(ledger.spent, 3 * cost())
        self.assertEqual(result.spent_usd, ledger.spent)

        first, second = (backend.workloads[n] for n in backend.submitted[1:])
        self.assertEqual(first["mode"], "scenario-reduce")
        self.assertEqual(first["failing"]["start_index"], 0)
        self.assertEqual(first["order"], ["bowl_1", "soup_1"])            # Nemotron's ranking
        self.assertEqual(first["order_source"], "model")
        self.assertEqual(first["max_candidates"], 36)
        # The continuation: the 2-entity scene, outcomes F F F F, one reference, same ranking minus nothing lost.
        self.assertEqual(second["failing"]["outcomes"], ["policy_failure"] * 4)
        self.assertEqual(len(second["references"]), 1)
        self.assertEqual(second["max_candidates"], 36)

        for name in ("report.md", "case.json", "minimal-candidate.json", "explanation.json", "spec.yaml",
                     "ledger.json", "steps.json"):
            self.assertTrue((run_dir / name).is_file(), name)
        case = json.loads((run_dir / "case.json").read_text())
        self.assertEqual(case["kind"], "scenario_reduction")
        self.assertEqual(case["minimal"]["selection"], SOUP_ONLY)           # from the last continuation
        self.assertEqual(result.case_id, case["case_id"])
        self.assertEqual(len(tools.explained), 1)
        self.assertEqual(tools.explained[0][1], run_dir / "explanation.json")
        self.assertRegex(tools.explained[0][3], r"^[a-z0-9][a-z0-9\-]{0,31}$")
        self.assertEqual(tools.registered, [run_dir])
        self.assertEqual(backend.finished, 1)
        self.assertEqual(backend.prepared, 1)

        steps = json.loads((run_dir / "steps.json").read_text())["steps"]
        for step in ("screen", "plan", "reduce", "reduce2", "report", "case", "explain", "register"):
            self.assertEqual(steps[step]["status"], "done", step)
        self.assertTrue(steps["reduce"]["partial"])
        self.assertTrue(steps["reduce2"]["partial"], "entity-minimal but the budget ran out")
        self.assertTrue(all("spent US$" in line for line in lines))
        self.assertTrue(any(" screen … " in line for line in lines))
        self.assertTrue(lines[0].startswith("10:15 "))
        self.assertIn("raw reply", (run_dir / "plans" / "plan.json.hypothesis-raw.txt").read_text())

    def test_no_llm_uses_the_fixed_order_and_skips_the_explanation(self):
        runner, backend, tools, ledger, lines = self.world(full_script(), no_llm=True)
        runner.diagnose()
        self.assertEqual(backend.workloads[backend.submitted[1]]["order_source"], "fixed_order")
        self.assertEqual(tools.explained, [])
        self.assertNotIn("explanation.json", [p.name for p in runner.run_dir.iterdir()])

    def test_reduced_first_time_needs_no_continuation(self):
        script = [finished(lambda w: screen_summary()),
                  finished(reduce_one(stop_reason="reduced", selection=SOUP_ONLY, entity_minimal=True, reduced=True))]
        runner, backend, tools, ledger, lines = self.world(script)
        result = runner.diagnose()
        self.assertEqual(result.status, "completed")
        self.assertEqual(len(backend.submitted), 2)

    def test_screen_mode_picks_the_best_start(self):
        spec = spec_for(scenario={"task": 3, "screen": {"starts": "0-3", "confirm": 4}})
        summary = screen_summary(extra_failing=["policy_failure"] * 5)
        script = [finished(lambda w: summary),
                  finished(reduce_one(stop_reason="reduced", selection=SOUP_ONLY, entity_minimal=True, reduced=True))]
        runner, backend, *_ = self.world(script, spec=spec)
        runner.diagnose()
        self.assertEqual(backend.workloads[backend.submitted[0]]["start_indices"], [0, 1, 2, 3])
        self.assertEqual(backend.workloads[backend.submitted[1]]["failing"]["start_index"], 0)

    def test_a_pinned_reference_screens_only_two_starts_and_plans_one_reference(self):
        spec = spec_for(scenario={"task": 3, "start": 0, "reference": 2})
        script = [finished(lambda w: screen_summary()),
                  finished(reduce_one(stop_reason="reduced", selection=SOUP_ONLY, entity_minimal=True, reduced=True))]
        runner, backend, *_ = self.world(script, spec=spec)
        runner.diagnose()
        self.assertEqual(backend.workloads[backend.submitted[0]]["start_indices"], [0, 2])
        self.assertEqual([r["start_index"] for r in backend.workloads[backend.submitted[1]]["references"]], [2])

    def test_a_pinned_reference_that_failed_stops(self):
        spec = spec_for(scenario={"task": 3, "start": 0, "reference": 3})
        runner, backend, *_ = self.world([finished(lambda w: screen_summary())], spec=spec)
        result = runner.diagnose()
        self.assertEqual(result.reason, "reference_not_passing")
        self.assertEqual(len(backend.submitted), 1)

    def test_no_reproducible_failure_stops_with_the_screen_table(self):
        runner, backend, tools, ledger, lines = self.world([finished(lambda w: screen_summary(failing=False))])
        result = runner.diagnose()
        self.assertEqual((result.status, result.reason, result.exit_code), ("stopped", "no_reproducible_failure", 3))
        self.assertEqual(len(backend.submitted), 1)
        self.assertTrue((runner.run_dir / "report.md").is_file())
        self.assertTrue(any("start 3:" in line for line in lines))
        self.assertEqual(backend.finished, 1)

    def test_a_missing_import_file_is_refused_before_any_job(self):
        spec = spec_for(scenario={"task": 3, "import": "candidate.json"})
        runner, backend, *_ = self.world([], spec=spec)
        result = runner.diagnose()
        self.assertEqual(result.reason, "import_invalid")
        self.assertEqual(backend.submitted, [])

    def test_a_failed_explanation_does_not_fail_the_run(self):
        runner, backend, tools, ledger, lines = self.world(full_script(), tools=FakeTools(explain_error=RuntimeError("boom")))
        result = runner.diagnose()
        self.assertEqual(result.status, "completed")
        self.assertTrue(any("WARNING" in line and "explain" in line for line in lines))
        self.assertEqual(runner.steps.get("explain")["status"], "skipped")

    def test_failing_not_reproducible_ends_with_a_report_but_no_case(self):
        script = [finished(lambda w: screen_summary()),
                  finished(reduce_one(stop_reason="failing_not_reproducible", selection={}, entity_minimal=False),
                           state="FAILED", reason="ContainerFailed")]
        runner, backend, tools, ledger, lines = self.world(script)
        result = runner.diagnose()
        self.assertEqual((result.status, result.reason), ("stopped", "failing_not_reproducible"))
        self.assertTrue((runner.run_dir / "report.md").is_file())
        self.assertFalse((runner.run_dir / "case.json").exists())
        self.assertEqual(tools.registered, [])


class CapacityAndCap(Base):
    def test_capacity_failures_are_resubmitted_under_new_names_at_no_cost(self):
        script = [capacity(), capacity(), finished(lambda w: screen_summary(failing=False))]
        runner, backend, tools, ledger, lines = self.world(script)
        runner.diagnose()
        tag = runner.tag
        base = "soup-start-{}-screen".format(tag)
        self.assertEqual(backend.submitted, [base, base + "-a", base + "-b"])
        self.assertEqual(sum(tools.slept), 600, "two pauses of 300 s, slept in short slices")
        self.assertAlmostEqual(ledger.spent, cost())
        self.assertEqual(ledger.jobs[base]["cost_usd"], 0.0)
        for name in backend.submitted:
            self.assertEqual(backend.workloads[name]["run_id"], name)
        self.assertEqual(backend.workloads[base + "-b"]["mode"], backend.workloads[base]["mode"])

    def test_six_capacity_failures_stop_the_run(self):
        runner, backend, tools, ledger, lines = self.world([capacity() for _ in range(6)] + [capacity()])
        result = runner.diagnose()
        self.assertEqual(result.reason, "capacity_unavailable")
        self.assertEqual(len(backend.submitted), 6)
        self.assertTrue(backend.submitted[-1].endswith("-screen-e"))
        self.assertEqual(sum(tools.slept), 5 * 300)
        self.assertEqual(ledger.spent, 0.0)

    def test_capacity_retries_respect_the_wall_clock(self):
        spec = spec_for(hours=1.0)
        runner, backend, tools, ledger, lines = self.world([capacity(), capacity()], spec=spec)
        backend.on_wait = lambda: runner.test_clock.__setitem__(0, runner.test_clock[0] + 2000)
        result = runner.diagnose()
        self.assertIn(result.reason, ("max_hours",))
        self.assertEqual(len(backend.submitted), 1)

    def test_a_job_that_would_pass_the_cap_is_refused_before_submission(self):
        probe = FakeTools().screen_workload("x", "libero_10", 3, "0-49", 4)["deadline_seconds"]
        reduce_deadline = FakeTools().reduce_deadline(36)
        worst = lambda d: lg.worst_case_seconds(d) / 3600.0 * RATE            # noqa: E731
        spec = spec_for(cap=worst(probe) + worst(reduce_deadline) + 0.01)
        script = [finished(lambda w: screen_summary(), seconds=probe),
                  finished(reduce_one(stop_reason="budget_exhausted", selection=BOTH, entity_minimal=False),
                           state="FAILED", reason="ContainerFailed", seconds=reduce_deadline),
                  finished(reduce_one(stop_reason="reduced", selection=SOUP_ONLY, entity_minimal=True, reduced=True))]
        runner, backend, tools, ledger, lines = self.world(script, spec=spec)
        result = runner.diagnose()
        self.assertEqual(len(backend.submitted), 2, "the continuation was never submitted")
        self.assertEqual((result.status, result.reason), ("stopped", "spend_cap"))
        self.assertTrue((runner.run_dir / "report.md").is_file())
        self.assertTrue((runner.run_dir / "case.json").is_file(), "the best result so far is still reported")
        self.assertLessEqual(ledger.spent, spec.budget.max_spend_usd)

    def test_first_job_over_the_cap_is_refused(self):
        runner, backend, *_ = self.world([], spec=spec_for(cap=0.05))
        result = runner.diagnose()
        self.assertEqual(result.reason, "spend_cap")
        self.assertEqual(backend.submitted, [])

    def test_the_wall_clock_cap_refuses_a_job_that_cannot_finish(self):
        runner, backend, *_ = self.world([], spec=spec_for(hours=0.1))
        self.assertEqual(runner.diagnose().reason, "max_hours")
        self.assertEqual(backend.submitted, [])

    def test_failed_job_without_a_summary_is_a_stop_and_is_charged(self):
        script = [{"state": "FAILED", "reason": "ContainerFailed", "container_seconds": 500, "summary": None,
                   "summary_name": "scenario_summary.json"}]
        runner, backend, tools, ledger, lines = self.world(script)
        result = runner.diagnose()
        self.assertEqual(result.reason, "job_failed")
        self.assertAlmostEqual(ledger.spent, cost(500))

    def test_price_above_the_spec_is_refused(self):
        backend = FakeBackend([], price=RATE * 1.5)
        temp, runner, backend, *_ = make_world(spec_for(), [], backend=backend)
        self.addCleanup(temp.cleanup)
        self.assertEqual(runner.diagnose().reason, "price_above_spec")
        self.assertEqual(backend.submitted, [])
        self.assertEqual(backend.finished, 1)

    def test_a_cheaper_or_unknown_live_price_is_fine(self):
        for price in (None, RATE * 0.5, RATE):
            backend = FakeBackend([finished(lambda w: screen_summary(failing=False))], price=price)
            temp, runner, backend, *_ = make_world(spec_for(), [], backend=backend)
            self.addCleanup(temp.cleanup)
            self.assertEqual(runner.diagnose().reason, "no_reproducible_failure")


class Cleanup(Base):
    def test_finish_runs_when_prepare_fails(self):
        backend = FakeBackend([])
        backend.fail_prepare = True
        temp, runner, backend, *_ = make_world(spec_for(), [], backend=backend)
        self.addCleanup(temp.cleanup)
        with self.assertRaises(BackendFailure):
            runner.diagnose()
        self.assertEqual(backend.finished, 1)

    def test_a_submit_error_is_a_stop_and_finish_runs(self):
        backend = FakeBackend([])
        backend.fail_submit_at = 0
        temp, runner, backend, tools, ledger, lines = make_world(spec_for(), [], backend=backend)
        self.addCleanup(temp.cleanup)
        result = runner.diagnose()
        self.assertEqual(result.reason, "backend_error")
        self.assertEqual(ledger.spent, 0.0)
        self.assertEqual(backend.finished, 1)

    def test_keyboard_interrupt_cancels_the_job_finishes_and_charges_the_worst_case(self):
        backend = FakeBackend([finished(lambda w: screen_summary())])
        backend.interrupt_at_wait = 1
        temp, runner, backend, tools, ledger, lines = make_world(spec_for(), [], backend=backend)
        self.addCleanup(temp.cleanup)
        with self.assertRaises(KeyboardInterrupt):
            runner.diagnose()
        self.assertEqual(backend.cancelled, backend.submitted)
        self.assertEqual(backend.finished, 1)
        name = backend.submitted[0]
        self.assertEqual(ledger.jobs[name]["state"], "settled")
        self.assertEqual(ledger.jobs[name]["cost_usd"], ledger.jobs[name]["reserved_usd"])
        attempts = json.loads((runner.run_dir / "steps.json").read_text())["steps"]["screen"]["attempts"]
        self.assertEqual(attempts[0]["state"], "cancelled")

    def test_finish_failure_does_not_mask_the_result(self):
        backend = FakeBackend([finished(lambda w: screen_summary(failing=False))])

        def broken():
            backend.finished += 1
            raise BackendFailure("finish")

        backend.finish = broken
        temp, runner, backend, tools, ledger, lines = make_world(spec_for(), [], backend=backend)
        self.addCleanup(temp.cleanup)
        self.assertEqual(runner.diagnose().reason, "no_reproducible_failure")
        self.assertTrue(any("cleanup failed" in line for line in lines))


class Resume(Base):
    def test_resume_skips_finished_steps_and_never_resubmits_a_recorded_job(self):
        spec = spec_for()
        # First run: the screen finishes, then submitting the reduce Job fails.
        backend1 = FakeBackend([finished(lambda w: screen_summary())])
        backend1.fail_submit_at = 1
        temp, runner1, backend1, tools1, ledger1, lines1 = make_world(spec, [], backend=backend1)
        self.addCleanup(temp.cleanup)
        first = runner1.diagnose()
        self.assertEqual(first.reason, "backend_error")
        run_dir = runner1.run_dir
        spent_before = ledger1.spent
        self.assertAlmostEqual(spent_before, cost())

        # Second run over the same folder: only the reduce Jobs are submitted.
        script = [finished(reduce_one(stop_reason="reduced", selection=SOUP_ONLY, entity_minimal=True, reduced=True))]
        backend2 = FakeBackend(script)
        _t, runner2, backend2, tools2, ledger2, lines2 = make_world(spec, [], backend=backend2, run_dir=run_dir)
        self.addCleanup(_t.cleanup)
        second = runner2.diagnose()
        self.assertEqual(second.status, "completed")
        self.assertEqual(len(backend2.submitted), 1)
        self.assertTrue(backend2.submitted[0].endswith("-reduce-a"), "a failed submission is not reused")
        self.assertAlmostEqual(ledger2.spent, spent_before + cost())
        self.assertTrue(any("already done" in line and "screen" in line for line in lines2))

    def test_resume_after_capacity_exhaustion_starts_a_fresh_round_on_new_names(self):
        spec = spec_for()
        runner1, backend1, tools1, ledger1, _l = self.world([capacity() for _ in range(6)], spec=spec)
        self.assertEqual(runner1.diagnose().reason, "capacity_unavailable")
        base = "soup-start-{}-screen".format(runner1.tag)
        self.assertEqual(backend1.submitted, [base] + [base + "-" + c for c in "abcde"])
        backend2 = FakeBackend([capacity(), capacity(), finished(lambda w: screen_summary(failing=False))])
        _t, runner2, backend2, tools2, ledger2, lines2 = make_world(
            spec, [], backend=backend2, run_dir=runner1.run_dir)
        self.addCleanup(_t.cleanup)
        result = runner2.diagnose()
        self.assertEqual(result.reason, "no_reproducible_failure", "it got past the screen")
        self.assertEqual(backend2.submitted, [base + "-f", base + "-g", base + "-h"],
                         "the letter sequence continues; no name is reused")
        self.assertEqual(sum(tools2.slept), 600)
        self.assertAlmostEqual(ledger2.spent, cost())

    def test_a_second_exhausted_round_can_be_resumed_again_and_names_stay_unique(self):
        spec = spec_for()
        runner1, backend1, *_ = self.world([capacity() for _ in range(6)], spec=spec)
        runner1.diagnose()
        run_dir, seen = runner1.run_dir, list(backend1.submitted)
        for expected_suffixes in ("fghijk", "lmnopq"):
            backend = FakeBackend([capacity() for _ in range(6)])
            _t, runner, backend, *_rest = make_world(spec, [], backend=backend, run_dir=run_dir)
            self.addCleanup(_t.cleanup)
            self.assertEqual(runner.diagnose().reason, "capacity_unavailable")
            self.assertEqual([name.rsplit("-", 1)[1] for name in backend.submitted], list(expected_suffixes))
            seen += backend.submitted
        self.assertEqual(len(seen), len(set(seen)))

    def test_resume_after_a_partly_used_round_does_not_get_a_whole_new_one(self):
        """Three capacity failures then a failed submission: two names are left in the round, not six."""

        spec = spec_for()
        backend1 = FakeBackend([capacity(), capacity(), capacity()])
        backend1.fail_submit_at = 3
        _t, runner1, backend1, *_rest = make_world(spec, [], backend=backend1)
        self.addCleanup(_t.cleanup)
        runner1.diagnose()
        backend2 = FakeBackend([capacity() for _ in range(6)])
        _t2, runner2, backend2, *_rest2 = make_world(spec, [], backend=backend2, run_dir=runner1.run_dir)
        self.addCleanup(_t2.cleanup)
        runner2.diagnose()
        self.assertEqual(len(backend2.submitted), 2)

    def test_resume_after_exhaustion_still_respects_the_time_cap(self):
        spec = spec_for(hours=1.0)
        runner1, backend1, *_ = self.world([capacity() for _ in range(6)], spec=spec)
        runner1.diagnose()
        backend2 = FakeBackend([capacity() for _ in range(6)])
        _t, runner2, backend2, *_rest = make_world(spec, [], backend=backend2, run_dir=runner1.run_dir)
        self.addCleanup(_t.cleanup)
        backend2.on_wait = lambda: runner2.test_clock.__setitem__(0, runner2.test_clock[0] + 2000)
        self.assertEqual(runner2.diagnose().reason, "max_hours")
        self.assertEqual(len(backend2.submitted), 1)

    def test_resume_of_a_finished_run_submits_nothing(self):
        runner, backend, tools, ledger, lines = self.world(full_script())
        runner.diagnose()
        run_dir = runner.run_dir
        backend2 = FakeBackend([])
        _t, runner2, backend2, tools2, ledger2, lines2 = make_world(spec_for(), [], backend=backend2, run_dir=run_dir)
        self.addCleanup(_t.cleanup)
        result = runner2.diagnose()
        self.assertEqual(result.status, "completed")
        self.assertEqual(backend2.submitted, [])
        self.assertEqual(tools2.explained, [], "the explanation (which reserves a paid attempt) is not repeated")
        self.assertEqual(backend2.finished, 1)

    def test_resume_reattaches_to_a_job_that_was_in_flight(self):
        spec = spec_for()
        backend1 = FakeBackend([finished(lambda w: screen_summary(failing=False))])
        backend1.kills_at_wait = 1
        temp, runner1, backend1, tools1, ledger1, lines1 = make_world(spec, [], backend=backend1)
        self.addCleanup(temp.cleanup)
        with self.assertRaises(Crash):
            runner1.diagnose()
        name = backend1.submitted[0]
        self.assertEqual(backend1.finished, 1)
        backend2 = FakeBackend([finished(lambda w: screen_summary(failing=False))])
        _t, runner2, backend2, tools2, ledger2, lines2 = make_world(spec, [], backend=backend2, run_dir=runner1.run_dir)
        self.addCleanup(_t.cleanup)
        result = runner2.diagnose()
        self.assertEqual(backend2.submitted, [], "no second submission")
        self.assertEqual(backend2.waited, [name])
        self.assertEqual(result.reason, "no_reproducible_failure")
        self.assertAlmostEqual(ledger2.spent, cost(), msg="settled once, not twice")


class InFlight(Base):
    """A Job is tracked from before it is submitted until its result is settled."""

    def attempts(self, runner, step="screen"):
        return json.loads((runner.run_dir / "steps.json").read_text())["steps"][step]["attempts"]

    def test_ctrl_c_during_submit_cancels_the_job_by_name_and_charges_the_worst_case(self):
        backend = FakeBackend([finished(lambda w: screen_summary())])
        backend.submit_error = KeyboardInterrupt()
        temp, runner, backend, tools, ledger, lines = make_world(spec_for(), [], backend=backend)
        self.addCleanup(temp.cleanup)
        with self.assertRaises(KeyboardInterrupt):
            runner.diagnose()
        name = backend.submitted[0]
        self.assertEqual(backend.cancelled, [name])
        self.assertEqual(ledger.jobs[name]["cost_usd"], ledger.jobs[name]["reserved_usd"])
        self.assertEqual(self.attempts(runner)[0]["state"], "cancelled")
        self.assertIn("acknowledged", runner.interrupt_report())

    def test_ctrl_c_before_the_job_exists_costs_nothing(self):
        backend = FakeBackend([])
        backend.submit_error = KeyboardInterrupt()
        backend.error_after_create = False
        temp, runner, backend, tools, ledger, lines = make_world(spec_for(), [], backend=backend)
        self.addCleanup(temp.cleanup)
        with self.assertRaises(KeyboardInterrupt):
            runner.diagnose()
        self.assertEqual(ledger.spent, 0.0)
        self.assertIn("did not exist", runner.interrupt_report())

    def test_interrupt_report_admits_an_unconfirmed_cancel(self):
        backend = FakeBackend([finished(lambda w: screen_summary())])
        backend.submit_error = KeyboardInterrupt()
        backend.cancel_error = BackendFailure("api down")
        temp, runner, backend, tools, ledger, lines = make_world(spec_for(), [], backend=backend)
        self.addCleanup(temp.cleanup)
        with self.assertRaises(KeyboardInterrupt):
            runner.diagnose()
        report = runner.interrupt_report()
        self.assertIn("could not be confirmed", report)
        self.assertNotIn("acknowledged", report)
        name = backend.submitted[0]
        self.assertEqual(ledger.jobs[name]["cost_usd"], ledger.jobs[name]["reserved_usd"])

    def test_a_failed_submit_of_a_job_that_exists_is_cancelled_and_charged(self):
        backend = FakeBackend([finished(lambda w: screen_summary())])
        backend.submit_error = BackendFailure("create response lost")
        temp, runner, backend, tools, ledger, lines = make_world(spec_for(), [], backend=backend)
        self.addCleanup(temp.cleanup)
        result = runner.diagnose()
        name = backend.submitted[0]
        self.assertEqual((result.reason, backend.cancelled), ("backend_error", [name]))
        self.assertEqual(ledger.jobs[name]["cost_usd"], ledger.jobs[name]["reserved_usd"])

    def test_a_failed_submit_with_an_unreachable_api_is_charged_the_worst_case(self):
        backend = FakeBackend([])
        backend.submit_error = BackendFailure("create failed")
        backend.error_after_create = False
        backend.cancel_error = BackendFailure("api down")
        temp, runner, backend, tools, ledger, lines = make_world(spec_for(), [], backend=backend)
        self.addCleanup(temp.cleanup)
        self.assertEqual(runner.diagnose().reason, "backend_error")
        self.assertGreater(ledger.spent, 0.0, "it cannot be proven that nothing was created")

    def test_any_exception_cancels_the_job_in_flight(self):
        backend = FakeBackend([finished(lambda w: screen_summary())])
        temp, runner, backend, tools, ledger, lines = make_world(spec_for(), [], backend=backend)
        self.addCleanup(temp.cleanup)

        def broken():
            raise RuntimeError("boom")

        tools.now = broken                      # first called after the Job was submitted
        with self.assertRaises(RuntimeError):
            runner.diagnose()
        self.assertEqual(backend.cancelled, backend.submitted)
        name = backend.submitted[0]
        self.assertEqual(ledger.jobs[name]["state"], "settled")
        self.assertEqual(backend.finished, 1)

    def test_resume_after_a_crash_during_submit_reattaches_to_the_job_by_name(self):
        spec = spec_for()
        backend1 = FakeBackend([finished(lambda w: screen_summary(failing=False))])
        backend1.submit_error = Crash()
        temp, runner1, backend1, tools1, ledger1, lines1 = make_world(spec, [], backend=backend1)
        self.addCleanup(temp.cleanup)
        with self.assertRaises(Crash):
            runner1.diagnose()
        name = backend1.submitted[0]
        self.assertEqual(self.attempts(runner1)[0]["state"], "submitting")
        self.assertEqual(ledger1.jobs[name]["state"], "reserved")
        backend2 = FakeBackend([])
        backend2.created.add(name)
        backend2.assigned[name] = finished(lambda w: screen_summary(failing=False))
        _t, runner2, backend2, tools2, ledger2, lines2 = make_world(spec, [], backend=backend2, run_dir=runner1.run_dir)
        self.addCleanup(_t.cleanup)
        result = runner2.diagnose()
        self.assertEqual(backend2.submitted, [], "no second create, no second reservation")
        self.assertEqual(backend2.waited, [name])
        self.assertEqual(result.reason, "no_reproducible_failure")
        self.assertAlmostEqual(ledger2.spent, cost())

    def test_resume_after_a_crash_before_the_job_was_created_settles_zero_and_moves_on(self):
        spec = spec_for()
        backend1 = FakeBackend([])
        backend1.submit_error = Crash()
        backend1.error_after_create = False
        temp, runner1, backend1, tools1, ledger1, lines1 = make_world(spec, [], backend=backend1)
        self.addCleanup(temp.cleanup)
        with self.assertRaises(Crash):
            runner1.diagnose()
        first = "soup-start-{}-screen".format(runner1.tag)
        backend2 = FakeBackend([finished(lambda w: screen_summary(failing=False))])
        _t, runner2, backend2, tools2, ledger2, lines2 = make_world(spec, [], backend=backend2, run_dir=runner1.run_dir)
        self.addCleanup(_t.cleanup)
        runner2.diagnose()
        self.assertEqual(backend2.submitted, [first + "-a"])
        self.assertEqual(ledger2.jobs[first]["cost_usd"], 0.0)
        self.assertAlmostEqual(ledger2.spent, cost())

    def test_resume_with_an_unreachable_lookup_stops_and_keeps_the_reservation(self):
        spec = spec_for()
        backend1 = FakeBackend([finished(lambda w: screen_summary())])
        backend1.submit_error = Crash()
        temp, runner1, backend1, tools1, ledger1, lines1 = make_world(spec, [], backend=backend1)
        self.addCleanup(temp.cleanup)
        with self.assertRaises(Crash):
            runner1.diagnose()
        backend2 = FakeBackend([])
        backend2.lookup_error = BackendFailure("api down")
        _t, runner2, backend2, tools2, ledger2, lines2 = make_world(spec, [], backend=backend2, run_dir=runner1.run_dir)
        self.addCleanup(_t.cleanup)
        self.assertEqual(runner2.diagnose().reason, "backend_error")
        self.assertEqual(backend2.submitted, [])
        self.assertEqual(ledger2.jobs[backend1.submitted[0]]["state"], "reserved")

    def test_ctrl_c_during_download_keeps_the_settled_job_and_resume_downloads_it_again(self):
        spec = spec_for()
        backend1 = FakeBackend([finished(lambda w: screen_summary(failing=False))])
        backend1.interrupt_at_download = True
        temp, runner1, backend1, tools1, ledger1, lines1 = make_world(spec, [], backend=backend1)
        self.addCleanup(temp.cleanup)
        with self.assertRaises(KeyboardInterrupt):
            runner1.diagnose()
        name = backend1.submitted[0]
        self.assertEqual(backend1.cancelled, [], "a finished Job is not cancelled")
        self.assertAlmostEqual(ledger1.jobs[name]["cost_usd"], cost())
        self.assertEqual(self.attempts(runner1)[0]["state"], "submitted")
        self.assertIn("no Job was in flight", runner1.interrupt_report())
        backend2 = FakeBackend([])
        backend2.created.add(name)
        backend2.assigned[name] = finished(lambda w: screen_summary(failing=False))
        _t, runner2, backend2, tools2, ledger2, lines2 = make_world(spec, [], backend=backend2, run_dir=runner1.run_dir)
        self.addCleanup(_t.cleanup)
        result = runner2.diagnose()
        self.assertEqual((backend2.submitted, backend2.waited), ([], [name]))
        self.assertEqual(result.reason, "no_reproducible_failure")
        self.assertAlmostEqual(ledger2.spent, cost(), msg="paid once")


class Mode2AndReplay(Base):
    class AuditTools(FakeTools):
        def audit_workload(self, spec, run_id):
            return {"schema_version": 1, "mode": "m6-threshold", "run_id": run_id, "deadline_seconds": 1500}

        def audit_report(self, summary):
            return "# audit report\n"

        def replay_workload(self, case, run_id, attempts, inputs=None):
            self.replayed = (case["case_id"], run_id, attempts, inputs)
            return {"schema_version": 1, "mode": "scenario-replay", "run_id": run_id, "deadline_seconds": 1000}

        def replay_inputs(self, case_dir, case):
            return {"layout": {"fake": True}, "reference_candidate": None}

    def audit_summary(self, complete=True):
        return {"mode": "m6-threshold", "complete": complete, "stop_reason": None if complete else "deadline_exhausted",
                "families": {"blur": {"threshold_severity": 0.4, "stop_reason": "threshold_found"},
                             "noise": {"threshold_severity": None, "stop_reason": "budget_exhausted"}}}

    def test_audit_runs_one_job_then_report_case_and_register(self):
        spec = spec_for(mode="audit")
        script = [finished(lambda w: self.audit_summary(), name="m6_summary.json")]
        tools = self.AuditTools()
        runner, backend, tools, ledger, lines = self.world(script, spec=spec, tools=tools)
        result = runner.diagnose()
        self.assertEqual((result.status, backend.submitted), ("completed", ["soup-start-{}-audit".format(runner.tag)]))
        self.assertEqual((runner.run_dir / "report.md").read_text(), "# audit report\n")
        case = json.loads((runner.run_dir / "case.json").read_text())
        self.assertEqual((case["kind"], case["task_id"], case["start_index"]), ("audit", 0, 0))
        self.assertEqual(case["families"]["blur"]["threshold_severity"], 0.4)
        self.assertEqual(tools.registered, [runner.run_dir])
        self.assertEqual(tools.explained, [])
        self.assertAlmostEqual(ledger.spent, cost())

    def test_partial_audit_summary_is_a_result_but_the_run_is_stopped(self):
        spec = spec_for(mode="audit")
        script = [finished(lambda w: self.audit_summary(False), name="m6_summary.json", state="FAILED",
                           reason="ContainerFailed")]
        runner, backend, tools, ledger, lines = self.world(script, spec=spec, tools=self.AuditTools())
        result = runner.diagnose()
        self.assertEqual((result.status, result.reason), ("stopped", "deadline_exhausted"))
        self.assertTrue((runner.run_dir / "case.json").is_file())

    def replay_case(self):
        case = {"kind": "scenario_reduction", "case_id": "ab" * 32, "suite": "libero_10",
                "replay": {"candidate": {"x": 1}}}
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        (Path(directory.name) / "case.json").write_text(json.dumps(case), encoding="utf-8")
        return Path(directory.name)

    def test_replay_reports_whether_the_failure_reproduces(self):
        for reproduces in (True, False):
            with self.subTest(reproduces=reproduces):
                tools = self.AuditTools()
                script = [finished(lambda w: {"verdict": "still_reproduces" if reproduces else "no_longer_reproduces", "complete": True})]
                runner, backend, tools, ledger, lines = self.world(script, spec=spec_for(mode="replay"), tools=tools)
                result = runner.replay(self.replay_case())
                self.assertEqual(result.reproduces, reproduces)
                self.assertEqual(result.status, "completed")
                self.assertEqual(tools.replayed[2], 5)
                self.assertIn("still reproduces" if reproduces else "no longer reproduces", " ".join(lines))
                saved = json.loads((runner.run_dir / "replay-result.json").read_text())
                self.assertEqual(saved["reproduces"], reproduces)

    def test_replay_keeps_an_inconclusive_verdict_and_says_it_plainly(self):
        for verdict, words in (("reference_fails", "reference failed"), ("invalid_scene", "invalid")):
            with self.subTest(verdict=verdict):
                script = [finished(lambda w, v=verdict: {"verdict": v, "complete": True})]
                runner, backend, tools, ledger, lines = self.world(
                    script, spec=spec_for(mode="replay"), tools=self.AuditTools())
                result = runner.replay(self.replay_case())
                self.assertEqual((result.status, result.reason, result.verdict, result.reproduces),
                                 ("stopped", "replay_inconclusive", verdict, None))
                saved = json.loads((runner.run_dir / "replay-result.json").read_text())
                self.assertEqual((saved["verdict"], saved["reproduces"]), (verdict, None))
                self.assertIn(words, orch.replay_text(verdict))
                self.assertIn(orch.replay_text(verdict), " ".join(lines))

    def test_replay_refuses_a_case_of_another_suite_or_kind(self):
        runner, backend, *_ = self.world([], spec=spec_for(mode="replay", policy={"suite": "libero_object"}),
                                         tools=self.AuditTools())
        self.assertEqual(runner.replay(self.replay_case()).reason, "suite_mismatch")
        self.assertEqual(backend.submitted, [])


class DryRun(unittest.TestCase):
    def test_dry_run_lists_jobs_and_worst_case_without_touching_anything(self):
        tools = FakeTools()
        lines, required = orch.dry_run_lines(spec_for(cap=3.0), tools)
        text = "\n".join(lines)
        self.assertIn("screen", text)
        self.assertIn("reduce", text)
        self.assertIn("optional", text)
        self.assertGreater(required, 0)
        self.assertIn("cap US$3.00", text)

    def test_dry_run_warns_when_the_required_jobs_exceed_the_cap(self):
        lines, _ = orch.dry_run_lines(spec_for(cap=0.5), FakeTools())
        self.assertIn("WARNING", "\n".join(lines))

    def test_too_many_candidates_for_one_job_is_a_clear_stop(self):
        spec = spec_for()
        spec = sp.parse_spec(dict(spec.raw, budget={"max_spend_usd": 10.0, "max_hours": 5, "max_candidates": 60}))
        with self.assertRaises(orch.StopRun) as caught:
            orch.dry_run_lines(spec, FakeTools())
        self.assertEqual(caught.exception.reason, "candidates_too_large")

    def test_dry_run_of_a_missing_import_file_is_refused(self):
        with self.assertRaises(orch.StopRun):
            orch.dry_run_lines(spec_for(scenario={"task": 3, "import": "x.json"}), FakeTools())


class StopTests(Base):
    """``faultline stop``: a request file, a backend stop hook, and a ledger that stays honest."""

    def steps_of(self, runner):
        return json.loads((runner.run_dir / "steps.json").read_text(encoding="utf-8"))

    def stopping_world(self, script, outcome=("CANCELLED", 300), **options):
        runner, backend, tools, ledger, lines = self.world(script, **options)
        backend.stop_outcome = outcome
        backend.on_wait = lambda: orch.request_stop(runner.run_dir)
        return runner, backend, tools, ledger, lines

    def resume_world(self, runner, script, **options):
        """A second orchestrator over the same run folder, as `faultline diagnose --resume` builds it."""

        orch.clear_stop_request(runner.run_dir)
        backend2 = FakeBackend(script)
        temp, runner2, backend2, tools2, ledger2, lines2 = make_world(
            runner.spec, [], backend=backend2, run_dir=runner.run_dir, **options)
        self.addCleanup(temp.cleanup)
        return runner2, backend2, tools2, ledger2, lines2

    def test_the_request_file_helpers(self):
        runner, *_rest = self.world([])
        self.assertFalse(orch.stop_requested(runner.run_dir))
        path = orch.request_stop(runner.run_dir)
        self.assertEqual(path.name, "stop-request.json")
        self.assertTrue(orch.stop_requested(runner.run_dir))
        self.assertRegex(json.loads(path.read_text(encoding="utf-8"))["requested_at"], r"^\d{4}-\d\d-\d\dT")
        orch.clear_stop_request(runner.run_dir)
        orch.clear_stop_request(runner.run_dir)                      # idempotent
        self.assertFalse(orch.stop_requested(runner.run_dir))

    def test_every_wait_gets_the_stop_hook(self):
        runner, backend, *_rest = self.world(full_script())
        runner.diagnose()
        self.assertEqual(backend.stop_hooks, [True, True, True])

    def test_a_stop_while_waiting_settles_at_measured_time_and_leaves_the_run_resumable(self):
        runner, backend, tools, ledger, lines = self.stopping_world([finished(lambda w: screen_summary())])
        result = runner.diagnose()

        self.assertEqual((result.status, result.reason, result.exit_code), ("stopped", "stopped_by_user", 3))
        name = backend.submitted[0]
        self.assertEqual((backend.submitted, backend.stop_cancels), ([name], [name]))
        self.assertAlmostEqual(ledger.jobs[name]["cost_usd"], cost(300))
        self.assertNotIn("worst_case", ledger.jobs[name], "the container time was measured")
        self.assertEqual((ledger.reserved, ledger.spent), (0.0, ledger.jobs[name]["cost_usd"]))
        self.assertIsNone(runner._inflight)
        self.assertEqual(backend.finished, 1)
        data = self.steps_of(runner)
        self.assertEqual(data["steps"]["screen"]["status"], "stopped")
        self.assertEqual(data["steps"]["screen"]["attempts"][0]["state"], "cancelled")
        self.assertEqual((data["run"]["status"], data["run"]["reason"]), ("stopped", "stopped_by_user"))
        job_dir = runner.run_dir / "jobs" / name
        self.assertEqual(json.loads((job_dir / "result.json").read_text(encoding="utf-8"))["reason"], "stopped_by_user")
        self.assertFalse((job_dir / "evidence").exists(), "a cancelled Job's partial export is not downloaded")
        self.assertTrue(any("stopped_by_user" in line for line in lines))

    def test_stopping_a_job_that_never_started_charges_nothing(self):
        # A queued Job cancelled before it started: serverless does not bill queued time (the capacity path too).
        runner, backend, tools, ledger, lines = self.stopping_world(
            [finished(lambda w: screen_summary())], outcome=("CANCELLED", None))
        result = runner.diagnose()
        name = backend.submitted[0]
        self.assertEqual(result.reason, "stopped_by_user")
        job = ledger.jobs[name]
        self.assertEqual(job["cost_usd"], 0.0)
        self.assertNotIn("worst_case", job)
        self.assertEqual((ledger.reserved, ledger.spent), (0.0, 0.0))
        self.assertEqual(self.steps_of(runner)["steps"]["screen"]["attempts"][0]["state"], "cancelled")
        self.assertTrue(any("charged US$0.00" in line for line in lines))

    def test_stopping_a_job_that_started_charges_the_time_it_ran(self):
        started, ended = MOMENT, MOMENT + dt.timedelta(seconds=120)
        runner, backend, tools, ledger, lines = self.stopping_world(
            [finished(lambda w: screen_summary())], outcome=("CANCELLED", None, (started, ended)))
        runner.diagnose()
        job = ledger.jobs[backend.submitted[0]]
        self.assertAlmostEqual(job["cost_usd"], cost(120), msg="the start and end times give the container seconds")
        self.assertNotIn("worst_case", job)

    def test_stopping_a_job_that_started_but_whose_time_is_unknown_charges_the_worst_case(self):
        runner, backend, tools, ledger, lines = self.stopping_world(
            [finished(lambda w: screen_summary())], outcome=("CANCELLED", None, (MOMENT, None)))
        runner.diagnose()
        job = ledger.jobs[backend.submitted[0]]
        self.assertEqual(job["cost_usd"], job["reserved_usd"])
        self.assertTrue(job["worst_case"])

    def test_a_cancel_the_provider_never_confirmed_stays_re_attachable(self):
        runner, backend, tools, ledger, lines = self.stopping_world(
            [finished(lambda w: screen_summary())], outcome=("TIMEOUT", None))
        result = runner.diagnose()
        name = backend.submitted[0]
        self.assertEqual(result.reason, "stopped_by_user")
        self.assertTrue(ledger.jobs[name]["worst_case"])
        self.assertEqual(self.steps_of(runner)["steps"]["screen"]["attempts"][0]["state"], "unconfirmed")
        self.assertIsNone(runner._inflight)

        runner2, backend2, tools2, ledger2, lines2 = self.resume_world(
            runner, [finished(lambda w: screen_summary(failing=False), seconds=900)])
        second = runner2.diagnose()
        self.assertEqual(second.reason, "no_reproducible_failure", "the screen finished after re-attaching")
        self.assertEqual(backend2.submitted, [], "nothing was resubmitted")
        self.assertEqual(backend2.waited, [name])
        self.assertAlmostEqual(ledger2.spent, cost(900), msg="the measured cost replaced the worst case")
        self.assertNotIn("worst_case", ledger2.jobs[name])

    def stop_again(self, runner, outcome=("CANCELLED", 300)):
        """Resume the run and stop it again while its Job waits: one more cancelled attempt."""

        runner2, backend2, tools2, ledger2, lines2 = self.resume_world(runner, [finished(lambda w: screen_summary())])
        backend2.stop_outcome = outcome
        backend2.on_wait = lambda: orch.request_stop(runner2.run_dir)
        self.assertEqual(runner2.diagnose().reason, "stopped_by_user")
        return runner2, backend2

    def test_repeated_stops_do_not_strand_the_step_after_a_whole_round_of_names(self):
        runner, backend, *_rest = self.stopping_world([finished(lambda w: screen_summary())])
        runner.diagnose()
        base = backend.submitted[0]
        names = list(backend.submitted)
        for _ in range(orch.MAX_ATTEMPTS - 1):                      # six stopped attempts in all
            _runner, again = self.stop_again(runner)
            names += again.submitted
        self.assertEqual([n.rsplit("-", 1)[-1] for n in names[1:]], list("abcde"))
        attempts = self.steps_of(runner)["steps"]["screen"]["attempts"]
        self.assertEqual([a["state"] for a in attempts], ["cancelled"] * 6)

        runner2, backend2, tools2, ledger2, _l = self.resume_world(
            runner, [finished(lambda w: screen_summary(failing=False))])
        result = runner2.diagnose()
        self.assertEqual(result.reason, "no_reproducible_failure", "it got past the screen instead of capacity_unavailable")
        self.assertEqual(backend2.submitted, [base + "-f"], "a fresh round on an unused suffix")
        self.assertNotIn(backend2.submitted[0], names)

    def test_a_round_of_capacity_waits_and_stops_starts_a_fresh_round_too(self):
        runner, backend, *_rest = self.stopping_world(
            [capacity(), capacity(), capacity(), finished(lambda w: screen_summary())])
        orch.clear_stop_request(runner.run_dir)
        backend.on_wait = lambda: len(backend.waited) == 4 and orch.request_stop(runner.run_dir)
        self.assertEqual(runner.diagnose().reason, "stopped_by_user")
        for _ in range(2):
            runner, _backend = self.stop_again(runner)
        states = [a["state"] for a in self.steps_of(runner)["steps"]["screen"]["attempts"]]
        self.assertEqual(states, ["capacity"] * 3 + ["cancelled"] * 3)
        runner2, backend2, *_rest2 = self.resume_world(runner, [finished(lambda w: screen_summary(failing=False))])
        self.assertEqual(runner2.diagnose().reason, "no_reproducible_failure")
        self.assertTrue(backend2.submitted[0].endswith("-screen-f"))

    def test_a_round_with_a_failed_attempt_is_not_restarted_by_the_fresh_round_rule(self):
        runner, *_rest = self.world([])
        attempts = [{"job_name": "j", "state": "cancelled", "stopped_by_user": True}] * 5 + [
            {"job_name": "k", "state": "failed"}]
        self.assertEqual(runner._first_attempt_number(attempts), 0)
        attempts[-1] = {"job_name": "k", "state": "cancelled"}          # cancelled for another reason (the spend cap)
        self.assertEqual(runner._first_attempt_number(attempts), 0)

    def test_a_stop_before_a_submit_creates_nothing(self):
        runner, backend, tools, ledger, lines = self.world([finished(lambda w: screen_summary())])
        orch.request_stop(runner.run_dir)
        result = runner.diagnose()
        self.assertEqual((result.status, result.reason), ("stopped", "stopped_by_user"))
        self.assertEqual((backend.submitted, backend.waited), ([], []))
        self.assertEqual(ledger.jobs, {})
        self.assertEqual(self.steps_of(runner)["steps"]["screen"]["status"], "stopped")
        self.assertEqual(backend.finished, 1)

    def test_a_stop_during_a_capacity_pause_ends_the_pause_and_submits_nothing_more(self):
        runner, backend, tools, ledger, lines = self.world(
            [capacity(), finished(lambda w: screen_summary(failing=False))])
        tools.on_sleep = lambda: orch.request_stop(runner.run_dir)
        result = runner.diagnose()
        self.assertEqual(result.reason, "stopped_by_user")
        self.assertEqual(len(backend.submitted), 1)
        self.assertLessEqual(sum(tools.slept), 10, "the 300 s pause is slept in short slices and abandoned")
        self.assertEqual(ledger.spent, 0.0)
        data = self.steps_of(runner)
        self.assertEqual(data["steps"]["screen"]["attempts"][0]["state"], "capacity")
        self.assertEqual(data["steps"]["screen"]["status"], "stopped")

        runner2, backend2, tools2, ledger2, _l = self.resume_world(
            runner, [finished(lambda w: screen_summary(failing=False))])
        self.assertEqual(runner2.diagnose().reason, "no_reproducible_failure")
        self.assertEqual(len(backend2.submitted), 1)
        self.assertTrue(backend2.submitted[0].endswith("-screen-a"))

    def test_resume_after_a_stop_submits_under_a_fresh_name_and_the_ledger_adds_up(self):
        runner, backend, tools, ledger, lines = self.stopping_world([finished(lambda w: screen_summary())])
        runner.diagnose()
        stopped = backend.submitted[0]

        runner2, backend2, tools2, ledger2, lines2 = self.resume_world(
            runner, [finished(lambda w: screen_summary(failing=False), seconds=1000)])
        second = runner2.diagnose()
        self.assertEqual(second.reason, "no_reproducible_failure")
        self.assertEqual(backend2.submitted, [stopped + "-a"], "the cancelled attempt is skipped, never re-attached")
        self.assertEqual(backend2.waited, [stopped + "-a"])
        self.assertAlmostEqual(ledger2.spent, cost(300) + cost(1000))
        self.assertEqual(ledger2.reserved, 0.0)
        attempts = self.steps_of(runner)["steps"]["screen"]["attempts"]
        self.assertEqual([a["state"] for a in attempts], ["cancelled", "settled"])

    def test_a_stop_during_a_continuation_does_not_finish_the_scenario_and_resume_does(self):
        runner, backend, tools, ledger, lines = self.stopping_world(full_script(), outcome=("CANCELLED", 200))
        backend.on_wait = lambda: len(backend.waited) == 3 and orch.request_stop(runner.run_dir)
        result = runner.diagnose()
        self.assertEqual(result.reason, "stopped_by_user")
        self.assertEqual(len(backend.submitted), 3)
        for name in ("report.md", "case.json", "explanation.json"):
            self.assertFalse((runner.run_dir / name).exists(), name)
        self.assertEqual(tools.registered, [])
        self.assertEqual(tools.explained, [])

        runner2, backend2, tools2, ledger2, _l = self.resume_world(
            runner, [finished(reduce_one(stop_reason="budget_exhausted", selection=SOUP_ONLY, entity_minimal=True))])
        second = runner2.diagnose()
        self.assertEqual((second.status, second.reason), ("completed", None))
        self.assertTrue(backend2.submitted[0].endswith("-reduce2-a"))
        self.assertTrue((runner.run_dir / "case.json").is_file())
        self.assertAlmostEqual(ledger2.spent, 2 * cost() + cost(200) + cost())

    def test_a_job_that_ends_on_its_own_wins_and_the_run_stops_before_the_next_job(self):
        runner, backend, tools, ledger, lines = self.world([finished(lambda w: screen_summary())])
        backend.on_wait = lambda: orch.request_stop(runner.run_dir)         # backend ignores the hook
        result = runner.diagnose()
        self.assertEqual(result.reason, "stopped_by_user")
        self.assertEqual(len(backend.submitted), 1, "no reduce Job was submitted")
        data = self.steps_of(runner)
        self.assertEqual(data["steps"]["screen"]["status"], "done")
        self.assertEqual(data["steps"]["reduce"]["status"], "stopped")
        self.assertAlmostEqual(ledger.spent, cost())


class RunFolder(unittest.TestCase):
    def test_create_run_dir_copies_the_spec_and_never_reuses_a_folder(self):
        with tempfile.TemporaryDirectory() as root:
            spec = spec_for()
            path = orch.create_run_dir(Path(root), spec, "faultline: 1\n", MOMENT)
            self.assertEqual(path.name, "soup-start-20261014T101530Z")
            self.assertEqual((path / "spec.yaml").read_text(), "faultline: 1\n")
            with self.assertRaises(FileExistsError):
                orch.create_run_dir(Path(root), spec, None, MOMENT)

    def test_find_file_prefers_the_returned_tree(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / "a" / "scenario").mkdir(parents=True)
            (root / "b" / "scenario").mkdir(parents=True)
            (root / "a" / "scenario" / "x.json").write_text("{}")
            (root / "b" / "scenario" / "x.json").write_text("{}")
            self.assertEqual(orch.find_file(root, "x.json", root / "b"), root / "b" / "scenario" / "x.json")
            self.assertEqual(orch.find_file(root, "x.json"), root / "a" / "scenario" / "x.json")
            self.assertIsNone(orch.find_file(root, "missing.json"))


if __name__ == "__main__":
    unittest.main()
