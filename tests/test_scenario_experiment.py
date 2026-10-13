"""Tests for the scenario Job modes: configuration, deadlines, the pool, classification and the runs."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import types
import unittest

from robot_debug import scenario_experiment as se
from robot_debug import scenario_state as ss
from robot_debug.job_runtime import SCENARIO_MODES, JobRuntimeError, validate_workload_config
from robot_debug.scenario_import import load_scenario_candidate
from scripts import plan_scenario_reduction as planner
from tests.scenario_world import FAIL_X, FakeSimulation, ScenarioWorld

SMOKE = {"schema_version": 1, "mode": "scenario-smoke", "run_id": "scn-smoke-1", "deadline_seconds": 1500}
SCREEN = {"schema_version": 1, "mode": "scenario-screen", "run_id": "scn-screen-1", "deadline_seconds": 2700,
          "task_ids": [0], "start_indices": list(range(10))}


def quiet_screen(**changes):
    return dict(SCREEN, **changes)


class ConfigTests(unittest.TestCase):
    def test_modes_are_registered_in_both_places(self):
        self.assertEqual(set(se.SCENARIO_MODES), SCENARIO_MODES)

    def test_smoke_defaults(self):
        config = validate_workload_config(dict(SMOKE))
        self.assertEqual(("libero_10", 0), (config["suite"], config["task_id"]))
        config = validate_workload_config(dict(SMOKE, suite="libero_object", task_id=3))
        self.assertEqual(("libero_object", 3), (config["suite"], config["task_id"]))

    def test_screen_defaults_and_bounds(self):
        config = validate_workload_config(dict(SCREEN))
        self.assertEqual((1, 4, 4), (config["attempts"], config["confirm_attempts"], config["required_failures"]))
        for changes in (
            {"task_ids": []}, {"task_ids": [0, 0]}, {"task_ids": [-1]}, {"task_ids": [True]},
            {"task_ids": list(range(11))}, {"start_indices": []}, {"start_indices": [50]},
            {"start_indices": list(range(51))}, {"attempts": 2}, {"attempts": 0},
            {"confirm_attempts": 9}, {"confirm_attempts": -1}, {"required_failures": 6},
            {"required_failures": 1}, {"suite": "libero_goal"},
            {"task_ids": list(range(10)), "start_indices": list(range(50))},
        ):
            with self.subTest(changes=changes), self.assertRaises(JobRuntimeError):
                validate_workload_config(dict(SCREEN, **changes))

    def test_unknown_missing_and_extra_fields_are_rejected(self):
        with self.assertRaises(JobRuntimeError):
            validate_workload_config(dict(SMOKE, surprise=1))
        with self.assertRaises(JobRuntimeError):
            validate_workload_config({key: value for key, value in SCREEN.items() if key != "task_ids"})
        with self.assertRaises(JobRuntimeError):
            validate_workload_config(dict(SMOKE, task_ids=[0]))

    def test_deadline_is_still_capped_by_the_runtime(self):
        with self.assertRaises(JobRuntimeError):
            validate_workload_config(dict(SMOKE, deadline_seconds=3001))


def make_plan():
    """A real plan from a fake screen of task 0 (failing start 9)."""

    summary = {
        "suite": "libero_10",
        "tasks": {"0": {"instruction": "put the soup in the basket",
                        "layout": FakeSimulation().layout(0),
                        "starts": {str(i): {"outcomes": ["success"] if i < 5 else ["policy_failure"] * 5,
                                            "state": FakeSimulation().state_for(i)} for i in range(10)}}},
    }
    return planner.build_plan(summary, 0, 9, use_llm=False)


class ReduceConfigTests(unittest.TestCase):
    def setUp(self):
        self.plan = make_plan()

    def workload(self, **options):
        return se.build_reduce_workload(self.plan, run_id="scn-reduce-1", **options)

    def test_a_plan_becomes_a_valid_workload_with_the_recommended_deadline(self):
        workload = self.workload()
        config = validate_workload_config(workload)
        self.assertEqual("scenario-reduce", config["mode"])
        self.assertEqual(se.recommended_deadline_seconds("scenario-reduce", {}), config["deadline_seconds"])
        self.assertEqual((3, 30, 5, 4), (config["concurrency"], config["max_candidates"],
                                         config["attempts"], config["required_failures"]))
        self.assertIs(True, config["speculative_bisection"])
        self.assertLessEqual(len(json.dumps(workload)), 64 * 1024)

    def test_options_override_the_defaults(self):
        config = validate_workload_config(self.workload(
            max_candidates=12, concurrency=2, bisection_steps=2, speculative_bisection=False))
        self.assertEqual((12, 2, 2, False), (config["max_candidates"], config["concurrency"],
                                             config["bisection_steps"], config["speculative_bisection"]))
        for bad in (1, "yes", None, 0):
            with self.assertRaises((JobRuntimeError, ValueError)):
                validate_workload_config(self.workload(speculative_bisection=bad))
        with self.assertRaises(ValueError):
            self.workload(surprise=1)

    def test_every_plan_field_is_checked_fail_closed(self):
        def mutate(path, value):
            workload = self.workload()
            target = workload
            for step in path[:-1]:
                target = target[step]
            if value is KeyError:
                del target[path[-1]]
            else:
                target[path[-1]] = value
            return workload

        bad = [
            (("task_id",), -1), (("task_id",), True), (("instruction",), ""), (("instruction",), "x" * 600),
            (("layout", "task_id"), 5), (("layout", "suite"), "libero_object"), (("layout", "joints"), []),
            (("failing", "state"), [0.0]), (("failing", "outcomes"), ["maybe"]),
            (("failing", "extra"), 1), (("failing", "start_index"), 99),
            (("references",), []), (("references",), "x"), (("references", 0, "state"), [1.0, 2.0]),
            (("references", 0, "start_index"), 9), (("references", 0, "distance"), float("nan")),
            (("references", 0, "differences"), "x"), (("references", 0, "extra"), 1),
            (("order",), "robot"), (("order",), [1]), (("order_source",), "oracle"),
            (("hypothesis", "extra"), 1), (("hypothesis", "ranking"), "robot"),
            (("hypothesis", "raw_content"), "x" * 9000), (("hypothesis", "text"), "x" * 5000),
            (("hypothesis",), []), (("attempts",), 9), (("required_failures",), 6),
            (("concurrency",), 4), (("max_candidates",), 31), (("max_references",), 4),
            (("bisection_steps",), 7), (("hypothesis", "text"), "bad\x00text"),
        ]
        for path, value in bad:
            with self.subTest(path=path, value=str(value)[:20]), self.assertRaises((JobRuntimeError, ValueError)):
                validate_workload_config(mutate(path, value))
        for key in ("layout", "failing", "references", "order", "hypothesis", "instruction"):
            with self.subTest(missing=key), self.assertRaises(JobRuntimeError):
                validate_workload_config(mutate((key,), KeyError))


class DeadlineTests(unittest.TestCase):
    def test_documented_assumptions(self):
        self.assertEqual(130.0, se.ASSUMED_FAILING_EPISODE_SECONDS)
        self.assertEqual(80.0, se.ASSUMED_SUCCESS_EPISODE_SECONDS)
        self.assertGreater(se.ASSUMED_FAILING_EPISODE_SECONDS, se.ASSUMED_SUCCESS_EPISODE_SECONDS)

    def test_planned_deadlines(self):
        everything = {"task_ids": list(range(10)), "start_indices": list(range(10))}
        self.assertEqual(1380, se.recommended_deadline_seconds("scenario-smoke", {"task_id": 0}))
        self.assertEqual(2940, se.recommended_deadline_seconds("scenario-screen", everything))
        self.assertEqual(2640, se.recommended_deadline_seconds("scenario-reduce", {}))

    def test_deadlines_respect_the_floor_and_the_cap(self):
        tiny = {"task_ids": [0], "start_indices": [0]}
        self.assertGreaterEqual(se.recommended_deadline_seconds("scenario-screen", tiny), se.MIN_DEADLINE_SECONDS)
        self.assertEqual(0, se.recommended_deadline_seconds("scenario-smoke", {}) % se.DEADLINE_ROUNDING_SECONDS)
        with self.assertRaises(ValueError):
            se.recommended_deadline_seconds(
                "scenario-screen", {"task_ids": list(range(10)), "start_indices": list(range(30))})
        with self.assertRaises(ValueError):
            se.recommended_deadline_seconds("other", {})

    def test_a_larger_workload_never_gets_a_shorter_deadline(self):
        base = {"task_ids": [0, 1], "start_indices": list(range(10))}
        bigger = {"task_ids": [0, 1, 2], "start_indices": list(range(10))}
        self.assertGreaterEqual(se.recommended_deadline_seconds("scenario-screen", bigger),
                                se.recommended_deadline_seconds("scenario-screen", base))
        self.assertGreaterEqual(se.recommended_deadline_seconds("scenario-reduce", {"max_candidates": 30}),
                                se.recommended_deadline_seconds("scenario-reduce", {"max_candidates": 8}))

    def test_the_planned_workloads_stay_within_the_runtime_cap(self):
        for mode, config in (("scenario-smoke", {}), ("scenario-reduce", {}),
                             ("scenario-screen", {"task_ids": list(range(10)), "start_indices": list(range(10))})):
            self.assertLessEqual(se.recommended_deadline_seconds(mode, config), se.MAX_DEADLINE_SECONDS)


class PoolTests(unittest.TestCase):
    def pool(self, evaluate, *, workers=2, remaining=lambda: 1000.0, cancel=None, item_timeout=300.0):
        pool = se.ScenarioPool(workers=workers, evaluate=evaluate, remaining=remaining,
                               item_timeout=item_timeout, cancel=cancel or threading.Event())
        self.addCleanup(pool.shutdown)
        return pool

    @staticmethod
    def record(item, status="valid", outcome="success"):
        return {"case_id": item["case_id"], "kind": item["kind"], "status": status, "outcome": outcome,
                "started_seconds": 0.0, "ended_seconds": 1.0}

    def test_a_queued_ticket_can_be_withdrawn_once(self):
        pool = self.pool(lambda item: self.record(item))        # workers not started: everything queues
        ticket = pool.submit({"case_id": "a", "kind": "k", "meta": {"x": 1}})
        self.assertFalse(ticket.done())
        self.assertTrue(ticket.withdraw())
        self.assertTrue(ticket.done())
        self.assertEqual(("decided_skipped", False, 1), (
            ticket.record["status"], ticket.record["started"], ticket.record["x"]))
        self.assertFalse(ticket.withdraw())
        self.assertEqual({"decided_skipped": 1}, pool.not_started_counts())

    def test_a_ticket_withdrawn_because_the_batch_stopped_says_so(self):
        pool = self.pool(lambda item: self.record(item))
        ticket = pool.submit({"case_id": "a", "kind": "k"})
        self.assertTrue(ticket.withdraw("stop_withdrawn"))
        self.assertEqual("stop_withdrawn", ticket.record["status"])
        self.assertEqual({"stop_withdrawn": 1}, pool.not_started_counts())

    def test_a_withdrawn_ticket_is_never_evaluated(self):
        seen = []
        pool = self.pool(lambda item: seen.append(item["case_id"]) or self.record(item), workers=1)
        keep = pool.submit({"case_id": "keep", "kind": "k"})
        drop = pool.submit({"case_id": "drop", "kind": "k"})
        self.assertTrue(drop.withdraw())
        pool.start()
        pool.wait([keep])
        pool.shutdown()
        self.assertEqual(["keep"], seen)
        self.assertEqual(["keep"], [r["case_id"] for r in pool.results])
        self.assertFalse(pool.cancel.is_set(), "a withdrawal is not a failure")

    def test_a_started_ticket_cannot_be_withdrawn(self):
        started, release = threading.Event(), threading.Event()

        def evaluate(item):
            started.set()
            release.wait(5)
            return self.record(item)

        pool = self.pool(evaluate, workers=1)
        pool.start()
        ticket = pool.submit({"case_id": "a", "kind": "k"})
        self.assertTrue(started.wait(5))
        self.assertFalse(ticket.withdraw())
        release.set()
        pool.wait([ticket])
        self.assertEqual("valid", ticket.record["status"])

    def test_wait_any_returns_when_one_ticket_finishes_or_after_the_timeout(self):
        release = threading.Event()
        pool = self.pool(lambda item: (release.wait(5), self.record(item))[1], workers=2)
        pool.start()
        slow = pool.submit({"case_id": "slow", "kind": "k"})
        started = time.monotonic()
        pool.wait_any([slow], 0.15)
        self.assertGreaterEqual(time.monotonic() - started, 0.1)
        self.assertFalse(slow.done())
        quick = pool.submit({"case_id": "quick", "kind": "k"})
        pool.wait_any([slow, quick], 5.0)
        release.set()
        pool.wait([slow, quick])

    def test_wait_any_wakes_on_withdrawal(self):
        pool = self.pool(lambda item: self.record(item))
        ticket = pool.submit({"case_id": "a", "kind": "k"})
        threading.Timer(0.1, ticket.withdraw).start()
        started = time.monotonic()
        pool.wait_any([ticket], 5.0)
        self.assertLess(time.monotonic() - started, 3.0)
        self.assertTrue(ticket.done())

    def test_it_satisfies_the_gate_executor_protocol(self):
        from robot_debug.decided_gate import run_gates

        pool = self.pool(lambda item: self.record(item, outcome="policy_failure"), workers=3)
        pool.start()
        executor = se.PoolExecutor(pool, lambda spec: {"case_id": "c{}".format(spec["attempt"]), "kind": "k"})
        run = run_gates(executor, [{"key": "a", "item": {}, "kind": "failure"}], attempts=5,
                        required_failures=4, max_in_flight=3, drain=True)
        self.assertEqual("reproduces", run.decisions["a"])
        self.assertIsNone(run.stop)

    def test_a_non_valid_record_still_cancels_the_pool(self):
        pool = self.pool(lambda item: self.record(item, status="infrastructure_error", outcome=None), workers=1)
        pool.start()
        first = pool.submit({"case_id": "a", "kind": "k"})
        pool.wait([first])
        self.assertTrue(pool.cancel.is_set())


class EvaluateTests(unittest.TestCase):
    """Classification: an invalid scene is a valid record that is not a policy failure."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "configs").mkdir()
        (self.root / "runs").mkdir()
        self.world = ScenarioWorld(item_seconds=0.0)
        self.cancel = threading.Event()

    def evaluator(self, **overrides):
        kwargs = dict(
            suite="libero_10", project_root=self.root, write_config=self.world.write_config,
            load_result=self.world.load_result, run_item=self.world.run_item, cancel=self.cancel,
            item_timeout=300.0, clock=time.monotonic, ready_at=time.monotonic(),
            configs_dir=self.root / "configs", runs_dir=self.root / "runs", batch_root=self.root)
        kwargs.update(overrides)
        return se.make_scenario_evaluate(**kwargs)

    def candidate(self, state, name="c.json"):
        from robot_debug.scenario_import import build_candidate, write_scenario_candidate

        path = self.root / name
        write_scenario_candidate(path, build_candidate(
            "libero_10", 0, state, {"kind": "benchmark", "init_state_index": 0}))
        return path

    def overlapping(self):
        state = self.world.simulation.state_for(2)
        state[10 + 1:10 + 4] = state[3 + 1:3 + 4]
        return state

    def item(self, case, **config):
        return {"case_id": case, "kind": "k", "config": dict({"task_id": 0}, **config),
                "exports": {}, "meta": {"role": "x"}}

    def test_start_items_classify_success_and_policy_failure(self):
        evaluate = self.evaluator()
        good = evaluate(self.item("a", init_state_index=1))
        bad = evaluate(self.item("b", init_state_index=9))
        self.assertEqual(("valid", "success", 100), (good["status"], good["outcome"], good["steps"]))
        self.assertEqual(("valid", "policy_failure", 520), (bad["status"], bad["outcome"], bad["steps"]))
        self.assertEqual("x", good["role"])
        self.assertTrue(good["artifacts"]["video"].endswith(".mp4"))
        self.assertEqual("put the alphabet soup in the basket", good["instruction"])
        self.assertNotIn("restore", good)

    def test_an_invalid_scene_is_a_valid_record_with_its_own_outcome(self):
        evaluate = self.evaluator()
        record = evaluate(self.item("inv", scenario_start=self.candidate(self.overlapping())))
        self.assertEqual(("valid", "invalid_scene"), (record["status"], record["outcome"]))
        self.assertEqual(1, record["steps"])
        self.assertEqual("invalid_scene", record["restore"]["validity"])
        self.assertEqual(["alphabet_soup_1", "basket_1"], record["restore"]["deepest_pair"])
        self.assertIsNone(record["restore"]["post_settle_state_sha256"])

    def test_scenario_starts_record_their_restore_hashes(self):
        evaluate = self.evaluator()
        state = self.world.simulation.state_for(3)
        record = evaluate(self.item("ok", scenario_start=self.candidate(state)))
        self.assertEqual("success", record["outcome"])
        restore = record["restore"]
        self.assertEqual(restore["candidate_state_sha256"], restore["pre_settle_state_sha256"])
        self.assertEqual("valid", restore["validity"])

    def test_an_invalid_scene_neither_cancels_the_pool_nor_counts_as_a_failure(self):
        pool = se.ScenarioPool(workers=2, evaluate=self.evaluator(), remaining=lambda: 1000.0,
                               item_timeout=300.0, cancel=self.cancel)
        self.addCleanup(pool.shutdown)
        pool.start()
        invalid = self.candidate(self.overlapping(), "inv.json")
        later = [pool.submit(self.item("later-{}".format(i), init_state_index=1)) for i in range(4)]
        first = pool.submit(self.item("inv", scenario_start=invalid))
        pool.wait([first] + later)
        self.assertEqual("invalid_scene", first.record["outcome"])
        self.assertFalse(self.cancel.is_set(), "the pool must keep running")
        self.assertEqual(["valid"] * 4, [t.record["status"] for t in later])
        self.assertEqual(["success"] * 4, [t.record["outcome"] for t in later])
        from robot_debug.decided_gate import decide

        outcomes = [first.record["outcome"]]
        self.assertEqual("invalid_scene", decide(outcomes), "the gate reports it, never as a failure")
        self.assertEqual({"invalid_scene": 1, "success": 4}, se._count_outcomes(pool.results))
        self.assertEqual(0, [r["outcome"] for r in pool.results].count("policy_failure"))

    def test_the_metrics_flag_and_the_sidecar_must_agree(self):
        class Disagree(ScenarioWorld):
            def run_item(self_, command, *, item_timeout, cancel):
                ScenarioWorld.run_item(self_, command, item_timeout=item_timeout, cancel=cancel)
                case = Path(command[-1]).stem
                sidecar = Path(command[-1]).parent.parent / "runs" / case / "scenario_start.json"
                records = json.loads(sidecar.read_text(encoding="utf-8"))
                records[0]["validity"] = "valid" if records[0]["validity"] == "invalid_scene" else "invalid_scene"
                sidecar.write_text(json.dumps(records), encoding="utf-8")

        self.world = Disagree(item_seconds=0.0)
        evaluate = self.evaluator(write_config=self.world.write_config, load_result=self.world.load_result,
                                  run_item=self.world.run_item)
        for name, state in (("a", self.overlapping()), ("b", self.world.simulation.state_for(2))):
            record = evaluate(self.item(name, scenario_start=self.candidate(state, name + ".json")))
            self.assertEqual("invalid_evidence", record["status"], name)

    def test_a_scenario_stage_without_a_sidecar_is_invalid_evidence(self):
        class NoSidecar(ScenarioWorld):
            def run_item(self_, command, *, item_timeout, cancel):
                ScenarioWorld.run_item(self_, command, item_timeout=item_timeout, cancel=cancel)
                case = Path(command[-1]).stem
                (Path(command[-1]).parent.parent / "runs" / case / "scenario_start.json").unlink()

        self.world = NoSidecar(item_seconds=0.0)
        evaluate = self.evaluator(write_config=self.world.write_config, load_result=self.world.load_result,
                                  run_item=self.world.run_item)
        record = evaluate(self.item("a", scenario_start=self.candidate(self.world.simulation.state_for(1))))
        self.assertEqual("invalid_evidence", record["status"])

    def test_a_start_stage_that_claims_an_invalid_scene_is_invalid_evidence(self):
        record = self.evaluator(read=lambda output, root: dict(
            se.read_evidence(output, root), metric_invalid_scene=True))(self.item("a", init_state_index=1))
        self.assertEqual("invalid_evidence", record["status"])

    def test_an_exported_start_carries_its_contact_scan(self):
        evaluate = self.evaluator()
        item = dict(self.item("a", init_state_index=2), exports={"state_out": True})
        record = evaluate(item)
        self.assertEqual({"validity": "valid", "deepest_penetration_m": 0.0, "deepest_pair": None,
                          "invalid_contacts": 0}, record["start_validity"])
        self.world.simulation.invalid_starts = {3}
        bad = evaluate(dict(self.item("b", init_state_index=3), exports={"state_out": True}))
        self.assertEqual(("valid", "invalid_scene"), (bad["status"], bad["start_validity"]["validity"]))
        self.assertEqual(["alphabet_soup_1", "basket_1"], bad["start_validity"]["deepest_pair"])

    def test_an_exported_start_without_its_scan_is_invalid_evidence(self):
        class NoScan(ScenarioWorld):
            def run_item(self_, command, *, item_timeout, cancel):
                ScenarioWorld.run_item(self_, command, item_timeout=item_timeout, cancel=cancel)
                case = Path(command[-1]).stem
                (Path(command[-1]).parent.parent / "runs" / case / "start_state.validity.json").unlink()

        self.world = NoScan(item_seconds=0.0)
        evaluate = self.evaluator(write_config=self.world.write_config, load_result=self.world.load_result,
                                  run_item=self.world.run_item)
        record = evaluate(dict(self.item("a", init_state_index=2), exports={"state_out": True}))
        self.assertEqual(("invalid_evidence", None), (record["status"], record["outcome"]))

    def test_exports_are_requested_as_files_in_the_stage_output(self):
        evaluate = self.evaluator()
        item = dict(self.item("a", init_state_index=2), exports={"state_out": True, "layout_out": True})
        record = evaluate(item)
        kwargs = self.world.by_case["a"]
        self.assertEqual(self.root / "runs" / "a" / "start_state.json", Path(kwargs["state_out"]))
        self.assertEqual(self.root / "runs" / "a" / "layout.json", Path(kwargs["layout_out"]))
        self.assertEqual("runs/a/start_state.json", record["artifacts"]["state"])
        self.assertEqual("runs/a/layout.json", record["artifacts"]["layout"])
        self.assertEqual("libero_10", kwargs["suite"])
        self.assertEqual(self.world.simulation.state_for(2), load_scenario_candidate(
            self.root / "runs" / "a" / "start_state.json")["state"])

    def test_runner_failures_keep_their_status(self):
        from robot_debug.job_process import InfrastructureError, RunCancelled

        def raising(error):
            def run_item(command, *, item_timeout, cancel):
                raise error
            return run_item

        for error, status in ((RunCancelled("c"), "cancelled"), (InfrastructureError("x"), "infrastructure_error")):
            record = self.evaluator(run_item=raising(error))(self.item("e", init_state_index=0))
            self.assertEqual(status, record["status"])
        timeout = InfrastructureError("t")
        timeout.__cause__ = __import__("subprocess").TimeoutExpired("c", 1)
        self.assertEqual("timed_out", self.evaluator(run_item=raising(timeout))(
            self.item("t", init_state_index=0))["status"])


class RunTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.remaining_value = [10000.0]
        self.events = []

    def run_mode(self, world, mode, config, **overrides):
        kwargs = dict(
            mode=mode, config=validate_workload_config(config), batch_root=self.root / "scenario",
            log_root=self.root / "logs", project_root=self.root, model_factory=world.model_factory,
            set_model=world.set_model, run_item=world.run_item, failure=lambda: world.latched,
            remaining=lambda: self.remaining_value[0], launch_deadline=50000.0,
            progress=lambda event, **fields: self.events.append((event, fields)),
            server_clock=lambda: 0.5, write_config=world.write_config, load_result=world.load_result,
            snapshot=lambda: {"mem_available_mb": 1.0, "gpu_used_mb": 2.0, "gpu_total_mb": 3.0},
        )
        kwargs.update(overrides)
        return se.run_scenario(**kwargs)

    def saved(self):
        return json.loads((self.root / "scenario" / se.SUMMARY_NAME).read_text(encoding="utf-8"))


class SmokeRunTests(RunTestCase):
    def test_every_check_passes_in_a_healthy_world(self):
        world = ScenarioWorld(item_seconds=0.0)
        summary = self.run_mode(world, "scenario-smoke", SMOKE)
        self.assertIsNone(summary["stop_reason"])
        self.assertTrue(summary["complete"], summary["checks"])
        self.assertEqual({True}, set(summary["checks"].values()))
        self.assertEqual({"state_export_repeatable", "state_length_matches_layout", "restore_hash_matches",
                          "hybrid_restored_and_valid", "overlap_marked_invalid_scene",
                          "invalid_scene_not_a_policy_failure", "nominal_success_seen",
                          "benchmark_start_at_rest"}, set(summary["checks"]))
        self.assertEqual(35, summary["state_length"])
        self.assertEqual(world.simulation.layout(0), summary["layout"])
        self.assertEqual(["alphabet_soup_1", "basket_1"], summary["overlap_pair"])
        self.assertEqual(1, len(world.models))
        self.assertEqual(("faultline", 12), (world.models[0].kwargs["server"], world.models[0].kwargs["max_batch_size"]))
        self.assertEqual(7, len(world.ran), "six items and the warm-up")
        by_case = {scene["case_id"]: scene for scene in summary["scenes"]}
        self.assertEqual("invalid_scene", by_case["overlap-s0"]["outcome"])
        self.assertEqual("valid", by_case["hybrid-objects-s1"]["restore"]["validity"])
        self.assertEqual(summary, self.saved())

    def test_init_runs_export_layout_and_states_and_use_the_suite_and_task(self):
        world = ScenarioWorld(item_seconds=0.0)
        self.run_mode(world, "scenario-smoke", dict(SMOKE, task_id=2))
        first = world.by_case["init0-a"]
        self.assertEqual((2, 0, "libero_10"), (first["task_id"], first["init_state_index"], first["suite"]))
        self.assertIn("layout_out", first)
        self.assertNotIn("layout_out", world.by_case["init0-b"])
        self.assertIn("state_out", world.by_case["init1"])
        self.assertEqual(1, world.by_case["init1"]["init_state_index"])

    def test_the_hybrid_takes_objects_from_start_one_and_the_robot_from_start_zero(self):
        world = ScenarioWorld(item_seconds=0.0)
        self.run_mode(world, "scenario-smoke", SMOKE)
        sim = world.simulation
        candidate = load_scenario_candidate(self.root / "scenario" / "candidates" / "hybrid-objects-s1.json")
        s0, s1 = sim.state_for(0), sim.state_for(1)
        self.assertEqual({"kind": "hybrid", "reference": 0, "failing": 1}, {
            key: candidate["source"][key] for key in ("kind", "reference", "failing")})
        self.assertEqual(s0[1], candidate["state"][1], "robot joint from start 0")
        self.assertEqual(s1[4], candidate["state"][4], "soup x from start 1")

    def test_the_overlap_candidate_puts_one_object_on_another(self):
        world = ScenarioWorld(item_seconds=0.0)
        self.run_mode(world, "scenario-smoke", SMOKE)
        state = load_scenario_candidate(self.root / "scenario" / "candidates" / "overlap-s0.json")["state"]
        self.assertEqual(state[4:7], state[11:14])

    def test_a_world_that_misses_the_overlap_is_reported_not_hidden(self):
        world = ScenarioWorld(FakeSimulation(detect_overlap=False), item_seconds=0.0)
        summary = self.run_mode(world, "scenario-smoke", SMOKE)
        self.assertIsNone(summary["stop_reason"])
        self.assertFalse(summary["checks"]["overlap_marked_invalid_scene"])
        self.assertFalse(summary["complete"], "the smoke only passes when validity detection works")

    def test_a_broken_checkpoint_is_caught_by_the_unperturbed_start_zero_attempts(self):
        # Every unperturbed attempt of start 0 fails: the policy cannot do the task at all.
        sim = FakeSimulation(flaky=lambda state, params, count: "policy_failure"
                             if "scenario_start" not in params and params.get("init_state_index") == 0 else None)
        summary = self.run_mode(ScenarioWorld(sim, item_seconds=0.0), "scenario-smoke", SMOKE)
        self.assertFalse(summary["checks"]["nominal_success_seen"])
        self.assertFalse(summary["complete"])
        self.assertIsNone(summary["stop_reason"])

    def test_one_success_among_the_start_zero_attempts_is_enough(self):
        sim = FakeSimulation(flaky=lambda state, params, count: "policy_failure"
                             if "scenario_start" not in params and params.get("init_state_index") == 0
                             and count == 2 else None)
        summary = self.run_mode(ScenarioWorld(sim, item_seconds=0.0), "scenario-smoke", SMOKE)
        self.assertTrue(summary["checks"]["nominal_success_seen"])

    def test_benchmark_starts_that_are_moving_fail_the_at_rest_check(self):
        for index, label in ((1 + 18, "velocity"), (0, "time")):
            with self.subTest(label):
                sim = FakeSimulation()
                original = sim.state_for

                def moving(start, original=original, index=index):
                    state = original(start)
                    state[index] = 0.25
                    return state

                sim.state_for = moving
                summary = self.run_mode(ScenarioWorld(sim, item_seconds=0.0), "scenario-smoke", SMOKE)
                self.assertFalse(summary["checks"]["benchmark_start_at_rest"])
                self.assertFalse(summary["complete"])

    def test_a_failed_item_stops_with_a_reason_and_still_writes_a_summary(self):
        world = ScenarioWorld(item_seconds=0.0, fail_case="init1")
        summary = self.run_mode(world, "scenario-smoke", SMOKE)
        self.assertEqual("evaluator_failed", summary["stop_reason"])
        self.assertFalse(summary["complete"])
        self.assertEqual(summary, self.saved())

    def test_nothing_runs_when_the_warmup_does_not_complete(self):
        world = ScenarioWorld(item_seconds=0.0, fail_case="warmup-init0-a")
        summary = self.run_mode(world, "scenario-smoke", SMOKE)
        self.assertEqual("evaluator_failed", summary["stop_reason"])
        self.assertEqual(["warmup-init0-a"], world.ran)


class ScreenRunTests(RunTestCase):
    def test_phase_one_runs_every_start_once_and_confirms_only_the_failures(self):
        world = ScenarioWorld(item_seconds=0.0)
        summary = self.run_mode(world, "scenario-screen", SCREEN)
        self.assertIsNone(summary["stop_reason"])
        self.assertTrue(summary["complete"])
        firsts = [case for case in world.ran if case.endswith("-a01") and not case.startswith("warmup")]
        self.assertEqual(10, len(firsts))
        starts = summary["tasks"]["0"]["starts"]
        for index in range(5):
            self.assertEqual(["success"], starts[str(index)]["outcomes"])
        for index in range(5, 10):
            self.assertEqual(["policy_failure"] * 5, starts[str(index)]["outcomes"])
            self.assertEqual("reproduces", starts[str(index)]["decision"])
        self.assertEqual([[0, i] for i in range(5, 10)], [[f["task_id"], f["start_index"]]
                                                          for f in summary["reproducible_failures"]])

    def test_the_summary_has_the_planner_schema(self):
        world = ScenarioWorld(item_seconds=0.0)
        summary = self.run_mode(world, "scenario-screen", SCREEN)
        self.assertEqual("libero_10", summary["suite"])
        task = summary["tasks"]["0"]
        self.assertEqual("put the alphabet soup in the basket", task["instruction"])
        self.assertEqual(world.simulation.layout(0), task["layout"])
        for index in range(10):
            start = task["starts"][str(index)]
            self.assertEqual(world.simulation.state_for(index), start["state"])
            self.assertEqual(len(start["outcomes"]), len(start["steps"]))
        plan = planner.build_plan(summary, 0, 9, use_llm=False)
        self.assertEqual([4, 3, 2], [r["start_index"] for r in plan["references"]])
        self.assertEqual(9, plan["failing"]["start_index"])
        self.assertEqual("put the alphabet soup in the basket", plan["instruction"])

    def test_confirmation_stops_early_and_skipped_attempts_are_counted(self):
        world = ScenarioWorld(item_seconds=0.0)
        summary = self.run_mode(world, "scenario-screen", SCREEN)
        confirm = summary["confirm"]
        self.assertEqual(5, confirm["starts"])
        self.assertEqual({"t00-s0{}".format(i): "reproduces" for i in range(5, 10)}, confirm["decisions"])
        self.assertEqual(confirm["skipped_attempts"], summary["topup"]["episodes"],
                         "every attempt the gate skipped is topped up for a reproducible start")
        total_attempts = sum(len(start["outcomes"]) for start in summary["tasks"]["0"]["starts"].values())
        self.assertEqual(5 + 25, total_attempts, "five passes, five failing starts with five attempts each")

    def test_with_fewer_workers_than_attempts_early_decisions_skip_attempts(self):
        world = ScenarioWorld(item_seconds=0.01)
        summary = self.run_mode(world, "scenario-screen", dict(SCREEN, start_indices=[5, 6, 7, 8]), workers=3)
        self.assertGreater(summary["confirm"]["skipped_attempts"], 0)
        self.assertGreater(summary["topup"]["episodes"], 0)
        self.assertLessEqual(world.max_running, 3)

    def test_a_flaky_start_that_does_not_reproduce_is_not_a_candidate(self):
        def flaky(state, params, count):
            # The warm-up is the first run of start 6, so the screen attempt is run 2; later runs pass.
            if abs(state[4] - 0.6) < 1e-9 and count > 2:
                return "success"
            return None

        world = ScenarioWorld(FakeSimulation(flaky=flaky), item_seconds=0.0)
        summary = self.run_mode(world, "scenario-screen", dict(SCREEN, start_indices=[6, 9]))
        starts = summary["tasks"]["0"]["starts"]
        self.assertEqual("does_not_reproduce", starts["6"]["decision"])
        self.assertEqual("reproduces", starts["9"]["decision"])
        self.assertEqual([[0, 9]], [[f["task_id"], f["start_index"]] for f in summary["reproducible_failures"]])
        self.assertEqual("policy_failure", starts["6"]["outcomes"][0])
        # three confirmation attempts in flight; two non-failures fix the gate, the fourth is held back
        self.assertEqual(["policy_failure"] + ["success"] * 3, starts["6"]["outcomes"])

    def test_the_summary_records_each_starts_validity(self):
        world = ScenarioWorld(FakeSimulation(invalid_starts={2, 9}), item_seconds=0.0)
        summary = self.run_mode(world, "scenario-screen", SCREEN)
        starts = summary["tasks"]["0"]["starts"]
        self.assertEqual("valid", starts["1"]["validity"])
        self.assertEqual(("invalid_scene", 0.012, ["alphabet_soup_1", "basket_1"]), (
            starts["2"]["validity"], starts["2"]["deepest_penetration_m"], starts["2"]["deepest_pair"]))
        self.assertEqual("invalid_scene", starts["9"]["validity"])
        self.assertTrue(all(start["validity"] is not None for start in starts.values()))

    def test_layout_is_exported_once_per_task_and_states_for_every_start(self):
        world = ScenarioWorld(item_seconds=0.0)
        self.run_mode(world, "scenario-screen", dict(SCREEN, task_ids=[0, 3], start_indices=[1, 2]))
        with_layout = sorted(case for case, params in world.by_case.items()
                             if "layout_out" in params and not case.startswith("warmup"))
        self.assertEqual(["t00-s01-a01", "t03-s01-a01"], with_layout)
        with_state = sorted(case for case, params in world.by_case.items()
                            if "state_out" in params and not case.startswith("warmup"))
        self.assertEqual(["t00-s01-a01", "t00-s02-a01", "t03-s01-a01", "t03-s02-a01"], with_state)
        self.assertEqual({0, 3}, {world.by_case[c]["task_id"] for c in world.by_case})

    def test_a_failed_first_phase_item_stops_and_writes_a_partial_summary(self):
        world = ScenarioWorld(item_seconds=0.0, fail_case="t00-s03-a01")
        summary = self.run_mode(world, "scenario-screen", SCREEN)
        self.assertEqual("evaluator_failed", summary["stop_reason"])
        self.assertFalse(summary["complete"])
        self.assertEqual(summary, self.saved())

    def test_confirmation_can_be_switched_off(self):
        world = ScenarioWorld(item_seconds=0.0)
        summary = self.run_mode(world, "scenario-screen", dict(SCREEN, confirm_attempts=0, required_failures=1))
        self.assertIsNone(summary["confirm"])
        self.assertEqual([], summary["reproducible_failures"])
        self.assertEqual(["policy_failure"], summary["tasks"]["0"]["starts"]["9"]["outcomes"])


class ReduceRunTests(RunTestCase):
    def setUp(self):
        super().setUp()
        self.plan = make_plan()

    def workload(self, **options):
        return se.build_reduce_workload(self.plan, run_id="scn-reduce-1", **options)

    def test_the_reduction_finds_the_soup_position_and_shrinks_it(self):
        world = ScenarioWorld(item_seconds=0.0)
        summary = self.run_mode(world, "scenario-reduce", self.workload())
        reduction = summary["reduction"]
        self.assertEqual("reduced", reduction["stop_reason"])
        self.assertTrue(summary["complete"])
        self.assertEqual(4, reduction["reference"])
        self.assertEqual(["alphabet_soup_1"], reduction["surviving_entities"])
        self.assertEqual({"alphabet_soup_1": {"position": 0.125}}, reduction["final_selection"])
        self.assertTrue(reduction["entity_minimal"])
        self.assertIn(reduction["final_candidate"], [c["index"] for c in reduction["candidates"]])

    def test_case_ids_point_at_the_three_videos(self):
        world = ScenarioWorld(item_seconds=0.0)
        summary = self.run_mode(world, "scenario-reduce", self.workload())
        videos = summary["videos"]
        self.assertEqual({"original", "minimal", "reference"}, set(videos))
        self.assertEqual("policy_failure", videos["original"]["outcome"])
        self.assertEqual("policy_failure", videos["minimal"]["outcome"])
        self.assertEqual("success", videos["reference"]["outcome"])
        for video in videos.values():
            self.assertTrue((self.root / "scenario" / video["video"]).is_file(), video)
        self.assertTrue(videos["original"]["case_id"].startswith("fail-"))
        self.assertTrue(videos["minimal"]["case_id"].startswith("hyb-"))
        self.assertTrue(videos["reference"]["case_id"].startswith("ref04-"))

    def test_the_summary_carries_the_replay_recipe_and_the_hypothesis_verdict(self):
        world = ScenarioWorld(item_seconds=0.0)
        summary = self.run_mode(world, "scenario-reduce", self.workload())
        candidate = summary["minimal_candidate"]
        self.assertEqual("hybrid", candidate["source"]["kind"])
        self.assertEqual((4, 9), (candidate["source"]["reference"], candidate["source"]["failing"]))
        self.assertEqual({"entity": "alphabet_soup_1", "component": "position", "t": 0.125},
                         candidate["source"]["applied"][0])
        expected_x = 0.4 + 0.125 * (0.9 - 0.4)
        self.assertAlmostEqual(expected_x, candidate["state"][4])
        self.assertIsNone(summary["hypothesis_verdict"], "a fixed order is not a hypothesis")
        self.assertEqual(self.plan["order"], summary["plan"]["order"])
        self.assertEqual("fixed_order", summary["plan"]["order_source"])
        self.assertEqual(["robot", "alphabet_soup_1"], [row["entity"] for row in summary["differences"]])
        self.assertTrue(summary["differences_match_plan"])

    def test_a_model_order_gets_a_mechanical_verdict(self):
        for ranking, expected in ((["alphabet_soup_1", "robot"], "confirmed"), (["robot", "alphabet_soup_1"], "refuted")):
            with self.subTest(ranking=ranking):
                plan = make_plan()
                plan["order_source"] = "model"
                plan["order"] = list(ranking)
                plan["hypothesis"].update(source="model", model="test/model", tier="ultra", ranking=list(ranking),
                                          text="The soup matters.", fallback_reason=None)
                world = ScenarioWorld(item_seconds=0.0)
                summary = self.run_mode(world, "scenario-reduce", se.build_reduce_workload(plan, run_id="scn-reduce-1"))
                self.assertEqual(expected, summary["hypothesis_verdict"])
                self.assertEqual(expected, se.build_case(summary)["hypothesis"]["verdict"])

    def test_the_held_fifth_attempt_saves_episodes_even_with_twelve_workers(self):
        # Before the hold, 12 workers started all five attempts of every candidate at once: 40
        # episodes and no saving for this fake world. Now every reproducing candidate stops at four.
        world = ScenarioWorld(item_seconds=0.02)
        summary = self.run_mode(world, "scenario-reduce", self.workload())
        reduction = summary["reduction"]
        reproducing = [c for c in reduction["candidates"] if c["decision"] == "reproduces"]
        self.assertGreaterEqual(len(reproducing), 4)
        for candidate in reproducing:
            self.assertEqual(4, len(candidate["outcomes"]) + len(candidate["late_outcomes"]), candidate["index"])
        self.assertGreaterEqual(reduction["attempts_skipped"], len(reproducing))
        real = [case for case in world.ran if not case.startswith("warmup")]
        self.assertLessEqual(len(real), 40 - len(reproducing))
        self.assertLessEqual(world.max_running, 12)

    def test_early_decisions_skip_attempts_when_attempts_outnumber_workers(self):
        world = ScenarioWorld(item_seconds=0.01)
        summary = self.run_mode(world, "scenario-reduce", self.workload(), workers=3)
        reduction = summary["reduction"]
        self.assertEqual("reduced", reduction["stop_reason"])
        self.assertGreater(reduction["attempts_skipped"], 0)
        self.assertGreater(sum(summary["not_started"].values()) + reduction["attempts_skipped"], 0)
        self.assertLessEqual(world.max_running, 3)
        self.assertEqual(reduction["attempts_run"], sum(
            len(c["outcomes"]) + len(c["late_outcomes"]) for c in reduction["candidates"]))
        by_role = {role: [c for c in reduction["candidates"] if c["role"] == role]
                   for role in ("failing", "reference", "hybrid")}
        self.assertEqual("reproduces", by_role["failing"][0]["decision"])
        self.assertEqual("passes", by_role["reference"][0]["decision"])
        self.assertEqual(5, len(by_role["reference"][0]["outcomes"]), "a pass gate runs all five")
        self.assertEqual(reduction["attempts_run"], sum(
            len(c["outcomes"]) + len(c["late_outcomes"]) for c in reduction["candidates"]))

    def test_candidate_files_are_validated_scenario_candidates(self):
        world = ScenarioWorld(item_seconds=0.0)
        self.run_mode(world, "scenario-reduce", self.workload())
        files = sorted((self.root / "scenario" / "candidates").glob("*.json"))
        self.assertGreaterEqual(len(files), 4)
        for path in files:
            candidate = load_scenario_candidate(path)
            self.assertEqual(("libero_10", 0), (candidate["suite"], candidate["task_id"]))
            self.assertEqual(35, len(candidate["state"]))
            self.assertEqual(0.0, max(abs(v) for v in candidate["state"][1 + 18:]), "velocities are zero")
        self.assertIn("failing", {p.name.split("-")[0] for p in files})

    def test_every_attempt_runs_through_scenario_start_with_unique_case_ids(self):
        world = ScenarioWorld(item_seconds=0.0)
        self.run_mode(world, "scenario-reduce", self.workload())
        real = [case for case in world.ran if not case.startswith("warmup")]
        self.assertEqual(len(real), len(set(real)))
        for case in real:
            self.assertIn("scenario_start", world.by_case[case])
            self.assertNotIn("init_state_index", world.by_case[case])
            self.assertEqual(0, world.by_case[case]["task_id"])
            self.assertEqual("libero_10", world.by_case[case]["suite"])

    def test_a_failing_start_that_stops_failing_ends_the_run_with_a_reason(self):
        sim = FakeSimulation(flaky=lambda state, params, count: "success" if abs(state[4] - 0.9) < 1e-9 else None)
        world = ScenarioWorld(sim, item_seconds=0.0)
        summary = self.run_mode(world, "scenario-reduce", self.workload())
        self.assertEqual("failing_not_reproducible", summary["stop_reason"])
        self.assertFalse(summary["complete"])
        self.assertIsNone(summary["minimal_candidate"])
        self.assertEqual({}, {k: v for k, v in summary["videos"].items() if k == "minimal"})

    def test_an_invalid_reference_is_skipped_and_never_counted_as_a_failure(self):
        sim = FakeSimulation(invalid_rule=lambda state: abs(state[4] - 0.4) < 1e-9 and abs(state[1]) < 0.045)
        world = ScenarioWorld(sim, item_seconds=0.0)
        summary = self.run_mode(world, "scenario-reduce", self.workload())
        reduction = summary["reduction"]
        self.assertEqual("reduced", reduction["stop_reason"])
        self.assertEqual("invalid_scene", reduction["references_tried"][0]["decision"])
        self.assertEqual(3, reduction["reference"], "the next nearest passing start is used")
        invalid = [c for c in reduction["candidates"] if c["decision"] == "invalid_scene"]
        self.assertTrue(invalid)
        self.assertTrue(all("policy_failure" not in c["outcomes"] for c in invalid))
        self.assertEqual(reduction["invalid_scenes"], [c["index"] for c in invalid])
        self.assertFalse(world.latched, "an invalid scene is not an infrastructure failure")


if __name__ == "__main__":
    unittest.main()
