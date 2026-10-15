"""Tests for the M6 runner: manifests, the shared evaluator pool, smoke and threshold modes."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import time
import types
import unittest

from robot_debug import m6_experiment as m6
from robot_debug.job_workload import CERTIFIED_M4_RECTANGLE
from robot_debug.parallel_eval import _MASK_RECTANGLE
from tests.test_batch_experiment import World

THRESHOLD_CONFIG = {
    "families": list(m6.LEGACY_FAMILIES),
    "sweep": [0.2, 0.4, 0.6, 0.8, 1.0],
    "attempts": 5,
    "required_failures": 4,
    "bisection_steps": 4,
}
BOUNDARIES = {"darken": 0.35, "noise": 0.55, "blur": None, "contrast": 0.05}


class M6World(World):
    """The M3 fake process world with outcomes decided from each item's written config."""

    def __init__(self, decide, **kwargs):
        super().__init__(**kwargs)
        self.decide = decide
        self.by_case = {}

    def write_config(self, **kwargs):
        self.by_case[kwargs["config_path"].stem] = kwargs
        super().write_config(**kwargs)

    def load_result(self, output):
        case = Path(output).name
        return types.SimpleNamespace(
            outcome=self.decide(case, self.by_case[case]), episode_index=0, steps=9)


def boundary_decide(boundaries):
    def decide(case, kwargs):
        spec = kwargs.get("image_perturbation")
        if spec is None:
            return "success"
        boundary = boundaries[spec["kind"]]
        return "policy_failure" if boundary is not None and spec["severity"] >= boundary else "success"

    return decide


class ManifestTests(unittest.TestCase):
    def test_smoke_manifest_has_the_planned_conditions(self):
        items = m6.smoke_manifest()
        kinds = {}
        for item in items:
            kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
        self.assertEqual(38, len(items))
        self.assertEqual({
            "nominal": 6, "agentview_mask_wrist_black": 12, "wrist_mask_only": 12,
            "darken_0.6": 2, "noise_0.6": 2, "blur_0.6": 2, "contrast_0.6": 2,
        }, kinds)
        self.assertEqual(len(items), len({item["case_id"] for item in items}))
        self.assertEqual("nominal", items[0]["kind"], "the warm-up is a nominal item")

    def test_reduced_mask_is_the_certified_rectangle(self):
        self.assertEqual(CERTIFIED_M4_RECTANGLE, m6.REDUCED_MASK)
        self.assertEqual(_MASK_RECTANGLE, m6.REDUCED_MASK)

    def test_smoke_conditions_map_to_the_adr_configurations(self):
        by_kind = {}
        for item in m6.smoke_manifest():
            by_kind.setdefault(item["kind"], item["config"])
        self.assertEqual({}, by_kind["nominal"])
        self.assertEqual(
            dict(m6.REDUCED_MASK, wrist_occlusion={"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}),
            by_kind["agentview_mask_wrist_black"])
        self.assertEqual({"wrist_occlusion": dict(m6.REDUCED_MASK)}, by_kind["wrist_mask_only"])
        self.assertNotIn("x", by_kind["wrist_mask_only"], "agent view stays clean")
        for family in m6.LEGACY_FAMILIES:
            self.assertEqual({"image_perturbation": {"kind": family, "severity": 0.6}},
                             by_kind["{}_0.6".format(family)])

    def test_level_items_are_unique_attempts_of_one_family_level(self):
        items = m6.level_items("noise", 0.0125, 5, phase="bisect")
        self.assertEqual(5, len(items))
        self.assertEqual(5, len({item["case_id"] for item in items}))
        self.assertEqual("noise-s012500-a01", items[0]["case_id"])
        self.assertEqual({"image_perturbation": {"kind": "noise", "severity": 0.0125}}, items[0]["config"])
        self.assertEqual({"family": "noise", "severity": 0.0125, "attempt": 1, "phase": "bisect",
                          "condition": "noise"}, items[0]["meta"])

    def test_case_ids_are_safe_file_stems(self):
        for item in m6.smoke_manifest() + m6.level_items("blur", 0.3, 5) + m6.nominal_controls():
            self.assertRegex(item["case_id"], r"^[a-z0-9][a-z0-9-]*$")

    def test_recommended_deadlines_follow_the_documented_assumptions(self):
        self.assertEqual(185, m6.planned_episodes("m6-threshold", THRESHOLD_CONFIG))
        self.assertEqual(1200, m6.recommended_deadline_seconds("m6-smoke"))
        self.assertEqual(1920, m6.recommended_deadline_seconds("m6-threshold", THRESHOLD_CONFIG))
        small = dict(THRESHOLD_CONFIG, families=["darken"], sweep=[1.0], attempts=1,
                     required_failures=1, bisection_steps=0)
        self.assertEqual(1200, m6.recommended_deadline_seconds("m6-threshold", small))

    def test_the_planned_workloads_stay_within_the_2400_second_cap(self):
        self.assertLessEqual(m6.recommended_deadline_seconds("m6-smoke"), 2400)
        self.assertLessEqual(m6.recommended_deadline_seconds("m6-threshold", THRESHOLD_CONFIG), 2400)
        huge = dict(THRESHOLD_CONFIG, sweep=[0.1 * i for i in range(1, 9)], attempts=12,
                    required_failures=10, bisection_steps=6)
        with self.assertRaises(ValueError):
            m6.recommended_deadline_seconds("m6-threshold", huge)

    def test_the_estimate_includes_the_no_start_guard_and_one_episode_wall_time(self):
        overhead = sum(m6.ASSUMED_OVERHEAD_SECONDS.values())
        guard = m6.be.ITEM_TIMEOUT_SECONDS + m6.ASSUMED_EPISODE_WALL_SECONDS
        smoke_work = 4 * m6.ASSUMED_EPISODE_WALL_SECONDS  # 38 items over 12 workers: four waves
        needed = overhead + smoke_work + guard
        self.assertGreaterEqual(m6.recommended_deadline_seconds("m6-smoke"), needed)
        self.assertLess(m6.recommended_deadline_seconds("m6-smoke"), needed + m6.DEADLINE_ROUNDING_SECONDS)
        self.assertEqual(300.0, m6.be.ITEM_TIMEOUT_SECONDS)

    def test_a_level_is_assumed_to_take_at_least_two_waves(self):
        self.assertGreaterEqual(m6.ASSUMED_LEVEL_SECONDS, 2 * m6.ASSUMED_EPISODE_WALL_SECONDS)

    def test_fifo_waves_quantise_the_threshold_work(self):
        # One family: five attempts fit one wave, so the nine levels are nine waves.
        self.assertEqual(9, m6.threshold_waves(1, 9, 5, 12))
        # Two families: ten attempts per round still fit one wave.
        self.assertEqual(9, m6.threshold_waves(2, 9, 5, 12))
        # Four families compete: 20 first-level attempts need two waves, and the slack is reused.
        waves = m6.threshold_waves(4, 9, 5, 12)
        self.assertEqual(15, waves)
        self.assertGreaterEqual(waves, -(-4 * 9 * 5 // 12))
        self.assertGreaterEqual(waves, 9)
        # Single-attempt levels with one worker are strictly sequential.
        self.assertEqual(4, m6.threshold_waves(2, 2, 1, 1))

    def test_a_libero_10_audit_uses_the_longer_episode_time(self):
        small = dict(THRESHOLD_CONFIG, families=["darken"], sweep=[0.5, 1.0], attempts=3,
                     required_failures=2, bisection_steps=2)
        base = m6.recommended_deadline_seconds("m6-threshold", small)
        self.assertEqual(base, m6.recommended_deadline_seconds(
            "m6-threshold", dict(small, suite="libero_object", task_id=4, init_state_index=1)))
        long_ = m6.recommended_deadline_seconds("m6-threshold", dict(small, suite="libero_10"))
        self.assertGreater(long_, base)
        self.assertLessEqual(long_, m6.MAX_LIBERO_10_DEADLINE_SECONDS)
        with self.assertRaises(ValueError):
            m6.recommended_deadline_seconds("m6-threshold", dict(THRESHOLD_CONFIG, suite="libero_10"))

    def test_a_libero_10_level_takes_one_wave_per_twelve_attempts(self):
        two = dict(THRESHOLD_CONFIG, families=["darken", "noise"], suite="libero_10")
        self.assertLessEqual(m6.recommended_deadline_seconds("m6-threshold", two), 2400)
        three = dict(THRESHOLD_CONFIG, families=["darken", "noise", "blur"], suite="libero_10")
        with self.assertRaises(ValueError):
            m6.recommended_deadline_seconds("m6-threshold", three)

    def test_suite_step_limits_mirror_the_pinned_upstream_harness(self):
        self.assertEqual({"libero_object": 280, "libero_10": 520, "libero_spatial": 220, "libero_goal": 300},
                         m6.SUITE_MAX_STEPS)
        self.assertEqual(("libero_object", "libero_10", "libero_spatial", "libero_goal"), m6.SUITES)

    def test_spatial_and_goal_audits_get_step_scaled_deadlines(self):
        small = dict(THRESHOLD_CONFIG, families=["darken", "noise"], sweep=[0.5, 1.0], attempts=3,
                     required_failures=2, bisection_steps=2)
        base = m6.recommended_deadline_seconds("m6-threshold", dict(small, suite="libero_object"))
        # Spatial episodes (220 steps) are no longer than Object's (280): the recorded timing holds.
        self.assertEqual(base, m6.recommended_deadline_seconds("m6-threshold", dict(small, suite="libero_spatial")))
        goal = m6.recommended_deadline_seconds("m6-threshold", dict(small, suite="libero_goal"))
        self.assertGreaterEqual(goal, base)
        self.assertLess(goal, m6.recommended_deadline_seconds("m6-threshold", dict(small, suite="libero_10")))
        for suite in ("libero_spatial", "libero_goal"):
            self.assertLessEqual(
                m6.recommended_deadline_seconds("m6-threshold", dict(THRESHOLD_CONFIG, suite=suite)),
                m6.MAX_RECOMMENDED_DEADLINE_SECONDS)
        self.assertEqual(m6.recommended_deadline_seconds("m6-threshold", THRESHOLD_CONFIG),
                         m6.recommended_deadline_seconds("m6-threshold", dict(THRESHOLD_CONFIG, suite="libero_object")))

    def test_a_larger_search_never_gets_a_shorter_deadline(self):
        base = m6.recommended_deadline_seconds("m6-threshold", THRESHOLD_CONFIG)
        for changes in (dict(attempts=6), dict(bisection_steps=5), dict(sweep=[0.2, 0.4, 0.6, 0.8, 0.9, 1.0])):
            with self.subTest(changes=changes):
                self.assertGreaterEqual(
                    m6.recommended_deadline_seconds("m6-threshold", dict(THRESHOLD_CONFIG, **changes)), base)


class PoolTests(unittest.TestCase):
    def pool(self, evaluate, *, workers=3, remaining=lambda: 1000.0, cancel=None, item_timeout=300.0):
        cancel = cancel or threading.Event()
        pool = m6.EvaluatorPool(workers=workers, evaluate=evaluate, remaining=remaining,
                                item_timeout=item_timeout, cancel=cancel)
        self.addCleanup(pool.shutdown)
        return pool

    @staticmethod
    def record(item, status="valid", outcome="success"):
        return {"case_id": item["case_id"], "kind": item["kind"], "status": status, "outcome": outcome,
                "started_seconds": 0.0, "ended_seconds": 1.0}

    def test_every_ticket_resolves_with_a_record(self):
        pool = self.pool(lambda item: self.record(item))
        pool.start()
        tickets = [pool.submit({"case_id": "a{}".format(i), "kind": "nominal"}) for i in range(10)]
        pool.wait(tickets)
        self.assertEqual({"a{}".format(i) for i in range(10)}, {t.record["case_id"] for t in tickets})
        self.assertEqual(10, len(pool.results))
        self.assertFalse(pool.cancel.is_set())

    def test_worker_count_bounds_concurrency(self):
        live = {"now": 0, "max": 0}
        lock = threading.Lock()

        def evaluate(item):
            with lock:
                live["now"] += 1
                live["max"] = max(live["max"], live["now"])
            time.sleep(0.03)
            with lock:
                live["now"] -= 1
            return self.record(item)

        pool = self.pool(evaluate, workers=4)
        pool.start()
        pool.wait([pool.submit({"case_id": "c{}".format(i), "kind": "k"}) for i in range(16)])
        self.assertEqual(4, live["max"])

    def test_a_non_valid_item_cancels_everything_queued_behind_it(self):
        gate = threading.Event()

        def evaluate(item):
            if item["case_id"] == "bad":
                return self.record(item, status="infrastructure_error", outcome=None)
            gate.wait(5)
            return self.record(item)

        pool = self.pool(evaluate, workers=1)
        pool.start()
        tickets = [pool.submit({"case_id": name, "kind": "k"}) for name in ("bad", "later-1", "later-2")]
        gate.set()
        pool.wait(tickets)
        self.assertTrue(pool.cancel.is_set())
        self.assertEqual(["infrastructure_error", "cancelled", "cancelled"],
                         [t.record["status"] for t in tickets])
        self.assertEqual(1, len(pool.results), "skipped items are not results")
        self.assertEqual({"cancelled": 2}, pool.not_started_counts())

    def test_items_are_skipped_when_the_deadline_could_cut_them_short(self):
        pool = self.pool(lambda item: self.record(item), remaining=lambda: 299.0)
        pool.start()
        tickets = [pool.submit({"case_id": "x", "kind": "k"})]
        pool.wait(tickets)
        self.assertEqual("deadline_skipped", tickets[0].record["status"])
        self.assertTrue(pool.deadline_stop.is_set())
        self.assertFalse(pool.cancel.is_set())
        self.assertEqual([], pool.results)

    def test_exactly_the_item_timeout_remaining_still_starts(self):
        pool = self.pool(lambda item: self.record(item), remaining=lambda: 300.0)
        pool.start()
        ticket = pool.submit({"case_id": "x", "kind": "k"})
        pool.wait([ticket])
        self.assertEqual("valid", ticket.record["status"])

    def test_an_evaluator_crash_resolves_the_ticket_and_cancels(self):
        def evaluate(item):
            raise SystemExit("boom")

        pool = self.pool(evaluate, workers=1)
        pool.start()
        ticket = pool.submit({"case_id": "x", "kind": "k"})
        pool.wait([ticket])
        self.assertEqual("infrastructure_error", ticket.record["status"])
        self.assertTrue(pool.cancel.is_set())

    def test_meta_is_copied_into_skipped_records(self):
        cancel = threading.Event()
        cancel.set()
        pool = self.pool(lambda item: self.record(item), cancel=cancel)
        pool.start()
        ticket = pool.submit({"case_id": "x", "kind": "noise", "meta": {"family": "noise", "severity": 0.2}})
        pool.wait([ticket])
        self.assertEqual(("cancelled", "noise", 0.2), (
            ticket.record["status"], ticket.record["family"], ticket.record["severity"]))


class SummaryHelperTests(unittest.TestCase):
    def test_condition_stats_count_valid_items_only(self):
        records = [
            {"case_id": "a", "kind": "k", "status": "valid", "outcome": "policy_failure",
             "started_seconds": 1.0, "ended_seconds": 15.0, "steps": 280},
            {"case_id": "b", "kind": "k", "status": "valid", "outcome": "success",
             "started_seconds": 2.0, "ended_seconds": 10.0, "steps": 140},
            {"case_id": "c", "kind": "k", "status": "timed_out", "outcome": None,
             "started_seconds": 2.0, "ended_seconds": 302.0},
        ]
        table = m6.condition_stats(records, {"k": 4, "other": 2})
        self.assertEqual(4, table["k"]["planned"])
        self.assertEqual((3, 2), (table["k"]["attempted"], table["k"]["valid"]))
        self.assertEqual({"policy_failure": 1, "success": 1}, table["k"]["outcomes"])
        self.assertEqual([8.0, 14.0], table["k"]["durations_seconds"])
        self.assertEqual(11.0, table["k"]["median_duration_seconds"])
        self.assertEqual(210.0, table["k"]["median_steps"])
        self.assertEqual((0, 0, None), (table["other"]["valid"], table["other"]["attempted"],
                                        table["other"]["median_duration_seconds"]))

    def test_nominal_summary_requires_every_control_to_succeed(self):
        def nominal(outcome, status="valid"):
            return {"kind": "nominal", "status": status, "outcome": outcome}

        self.assertTrue(m6.nominal_summary([nominal("success")] * 5, 5)["passed"])
        self.assertFalse(m6.nominal_summary([nominal("success")] * 4 + [nominal("policy_failure")], 5)["passed"])
        self.assertFalse(m6.nominal_summary([nominal("success")] * 4, 5)["passed"])
        self.assertFalse(m6.nominal_summary([nominal("success")] * 4 + [nominal(None, "timed_out")], 5)["passed"])


class RunTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.remaining_value = [1000.0]
        self.events = []

    def run_m6(self, world, mode, config=None, **overrides):
        kwargs = dict(
            mode=mode, config=config, batch_root=self.root / "m6", log_root=self.root / "logs",
            project_root=self.root, model_factory=world.model_factory, set_model=world.set_model,
            run_item=world.run_item, failure=lambda: world.latched,
            remaining=lambda: self.remaining_value[0], launch_deadline=5000.0,
            progress=lambda event, **fields: self.events.append((event, fields)),
            server_clock=lambda: 0.5, write_config=world.write_config, load_result=world.load_result,
            snapshot=lambda: {"mem_available_mb": 1.0, "gpu_used_mb": 2.0, "gpu_total_mb": 3.0},
        )
        kwargs.update(overrides)
        return m6.run_m6(**kwargs)

    def saved(self):
        return json.loads((self.root / "m6" / m6.SUMMARY_NAME).read_text(encoding="utf-8"))


def smoke_decide(case, kwargs):
    if "image_perturbation" in kwargs:
        return "policy_failure" if kwargs["image_perturbation"]["kind"] in ("darken", "noise") else "success"
    if "wrist_occlusion" in kwargs and "x" in kwargs:
        return "policy_failure"
    return "success"


class SmokeRunTests(RunTestCase):
    def test_one_server_one_wave_and_a_complete_summary(self):
        world = M6World(smoke_decide, item_seconds=0.02)
        summary = self.run_m6(world, "m6-smoke")

        self.assertIsNone(summary["stop_reason"])
        self.assertTrue(summary["complete"])
        self.assertEqual(38, summary["valid_count"])
        self.assertEqual(39, len(world.ran), "38 items and the untimed warm-up")
        self.assertEqual(1, len(world.models))
        self.assertEqual(("faultline", 12), (world.models[0].kwargs["server"],
                                             world.models[0].kwargs["max_batch_size"]))
        self.assertEqual(self.root / "m6" / "server-timing.jsonl", world.models[0].kwargs["timing_log"])
        self.assertEqual(self.root / "logs", world.models[0].kwargs["log_root"])
        self.assertLessEqual(world.max_running, 12)
        self.assertGreater(world.max_running, 1)
        self.assertTrue(all(live == 1 for live in world.models_at_run))
        self.assertEqual([("start", 12), ("ready", 5000.0), ("close", 12)], world.events)
        self.assertEqual([world.models[0], None], world.set_calls)

    def test_condition_table_and_nominal_gate(self):
        summary = self.run_m6(M6World(smoke_decide), "m6-smoke")
        conditions = summary["conditions"]

        self.assertEqual({"success": 6}, conditions["nominal"]["outcomes"])
        self.assertEqual({"policy_failure": 12}, conditions["agentview_mask_wrist_black"]["outcomes"])
        self.assertEqual({"success": 12}, conditions["wrist_mask_only"]["outcomes"])
        self.assertEqual({"policy_failure": 2}, conditions["darken_0.6"]["outcomes"])
        self.assertEqual({"success": 2}, conditions["blur_0.6"]["outcomes"])
        self.assertEqual(12, conditions["wrist_mask_only"]["planned"])
        self.assertEqual({"planned": 6, "valid": 6, "outcomes": {"success": 6}, "passed": True},
                         summary["nominal_controls"])
        self.assertTrue(summary["all_nominal_succeeded"])
        self.assertEqual({}, summary["families"])

    def test_summary_file_is_json_clean_and_complete(self):
        summary = self.run_m6(M6World(smoke_decide), "m6-smoke")
        saved = self.saved()
        self.assertEqual(json.loads(json.dumps(summary, sort_keys=True)), saved)
        self.assertEqual(("m6-smoke", 12, 12), (saved["mode"], saved["workers"], saved["max_batch_size"]))
        self.assertEqual("complete", "complete" if saved["complete"] else "partial")
        self.assertEqual(38, len(saved["items"]))
        self.assertIn("duration_seconds", saved["warmup"])
        self.assertEqual("warmup-nominal-01", saved["warmup"]["case_id"])
        self.assertEqual(3, saved["timing"]["calls"], "the warm-up call is excluded from the timing")
        self.assertEqual({"mem_available_mb": 1.0, "gpu_used_mb": 2.0, "gpu_total_mb": 3.0},
                         saved["memory_start"])
        self.assertEqual(saved["memory_start"], saved["memory_end"])
        self.assertIsNotNone(saved["startup_seconds"])
        self.assertFalse(list((self.root / "m6").glob(".*.tmp")))
        self.assertTrue((self.root / "m6" / "server-timing.jsonl").is_file())

    def test_items_carry_their_condition_and_the_written_configs(self):
        world = M6World(smoke_decide)
        summary = self.run_m6(world, "m6-smoke")
        by_case = {item["case_id"]: item for item in summary["items"]}
        self.assertEqual("wrist_mask_only", by_case["wrist-mask-only-01"]["condition"])
        self.assertEqual("noise", by_case["noise-s600000-02"]["family"])
        config = world.by_case["wrist-mask-only-01"]
        self.assertEqual("m6-wrist-mask-only-01", config["stage_name"])
        self.assertEqual((0,), config["episode_indices"])
        self.assertEqual(m6.REDUCED_MASK, config["wrist_occlusion"])
        self.assertNotIn("x", config)

    def test_a_failed_nominal_is_reported_not_hidden(self):
        def decide(case, kwargs):
            return "policy_failure" if case == "nominal-03" else smoke_decide(case, kwargs)

        summary = self.run_m6(M6World(decide), "m6-smoke")
        self.assertFalse(summary["all_nominal_succeeded"])
        self.assertEqual({"policy_failure": 1, "success": 5}, summary["conditions"]["nominal"]["outcomes"])
        self.assertTrue(summary["complete"], "all items still ran; the gate is reported separately")

    def test_an_invalid_item_cancels_the_wave_and_names_the_cause(self):
        world = M6World(smoke_decide, fail_case="wrist-mask-only-03", item_seconds=0.05)
        summary = self.run_m6(world, "m6-smoke")

        self.assertEqual("evaluator_failed", summary["stop_reason"])
        self.assertFalse(summary["complete"])
        self.assertLess(summary["valid_count"], 38)
        self.assertIn("infrastructure_error", {item["status"] for item in summary["items"]})
        self.assertIn(("close", 12), world.events)
        self.assertGreater(sum(summary["not_started"].values()), 0)

    def test_warmup_failure_stops_before_any_item(self):
        world = M6World(smoke_decide, fail_case="warmup-nominal-01")
        summary = self.run_m6(world, "m6-smoke")
        self.assertEqual("evaluator_failed", summary["stop_reason"])
        self.assertEqual(["warmup-nominal-01"], world.ran)
        self.assertEqual([("start", 12), ("ready", 5000.0), ("close", 12)], world.events)
        self.assertEqual(0, summary["valid_count"])

    def test_a_short_deadline_skips_the_whole_run_cleanly(self):
        self.remaining_value[0] = 100.0
        world = M6World(smoke_decide)
        summary = self.run_m6(world, "m6-smoke")
        self.assertEqual("deadline_exhausted", summary["stop_reason"])
        self.assertEqual("skipped_deadline", summary["warmup"]["status"])
        self.assertEqual([], world.ran)
        self.assertIn(("close", 12), world.events)

    def test_deadline_mid_wave_leaves_an_honest_partial(self):
        world = M6World(smoke_decide, item_seconds=0.02)
        summary = self.run_m6(world, "m6-smoke", remaining=lambda: 1000.0 if len(world.ran) < 15 else 10.0)
        self.assertEqual("deadline_exhausted", summary["stop_reason"])
        self.assertFalse(summary["complete"])
        self.assertGreater(summary["not_started"]["deadline_skipped"], 0)
        self.assertGreaterEqual(summary["valid_count"], 14)


class StartupFailureTests(RunTestCase):
    def test_server_start_failures_have_safe_codes_and_run_nothing(self):
        for fail, code in (("start", "model_start_failed"), ("ready", "readiness_failed"), ("dead", "model_died")):
            with self.subTest(fail=fail):
                world = M6World(smoke_decide, model_fail=fail)
                summary = self.run_m6(world, "m6-smoke")
                self.assertEqual(code, summary["stop_reason"])
                self.assertEqual([], world.ran)
                self.assertIn(("close", 12), world.events)
                self.assertEqual(code, self.saved()["stop_reason"])

    def test_a_failing_model_factory_is_a_start_failure(self):
        def broken(**_kwargs):
            raise ValueError("bad options")

        summary = self.run_m6(M6World(smoke_decide), "m6-smoke", model_factory=broken)
        self.assertEqual("model_start_failed", summary["stop_reason"])

    def test_prefetch_failure_starts_no_server(self):
        def prefetch():
            raise RuntimeError("download failed")

        world = M6World(smoke_decide)
        summary = self.run_m6(world, "m6-smoke", prefetch=prefetch)
        self.assertEqual("prefetch_failed", summary["stop_reason"])
        self.assertEqual([], world.models)
        self.assertIsNotNone(summary["prefetch_seconds"])
        self.assertIn("batch_prefetch_failed", [event for event, _ in self.events])

    def test_prefetch_runs_once_before_the_server(self):
        order = []
        world = M6World(smoke_decide)
        factory = world.model_factory
        summary = self.run_m6(
            world, "m6-smoke", prefetch=lambda: order.append("prefetch"),
            model_factory=lambda **kwargs: (order.append("model"), factory(**kwargs))[1])
        self.assertEqual(["prefetch", "model"], order)
        self.assertIsNone(summary["stop_reason"])

    def test_close_failure_propagates_and_keeps_the_model_registered(self):
        from robot_debug.job_process import InfrastructureError

        world = M6World(smoke_decide, model_fail="close")
        with self.assertRaises(InfrastructureError):
            self.run_m6(world, "m6-smoke")
        self.assertEqual([world.models[0]], world.set_calls)
        self.assertTrue((self.root / "m6" / m6.SUMMARY_NAME).is_file(), "the summary is still written")

    def test_invalid_modes_and_missing_configuration_are_rejected(self):
        with self.assertRaises(ValueError):
            self.run_m6(M6World(smoke_decide), "m3-batch")
        with self.assertRaises(ValueError):
            self.run_m6(M6World(smoke_decide), "m6-threshold", config=None)


class ThresholdRunTests(RunTestCase):
    def run_threshold(self, world=None, config=None, **overrides):
        world = world or M6World(boundary_decide(BOUNDARIES), item_seconds=0.02)
        return world, self.run_m6(world, "m6-threshold", config or dict(THRESHOLD_CONFIG), **overrides)

    def test_each_family_finds_its_own_threshold(self):
        _world, summary = self.run_threshold()
        families = summary["families"]

        self.assertIsNone(summary["stop_reason"])
        self.assertTrue(summary["complete"])
        self.assertEqual(list(m6.LEGACY_FAMILIES), sorted(families, key=list(m6.LEGACY_FAMILIES).index))
        self.assertEqual("threshold_found", families["darken"]["stop_reason"])
        self.assertEqual(0.35, families["darken"]["threshold_severity"])
        self.assertEqual(0.3375, families["darken"]["lower_bound"])
        self.assertEqual([0.2, 0.4, 0.3, 0.35, 0.325, 0.3375], families["darken"]["levels_tried"])
        self.assertEqual((0.55, 0.5375), (families["noise"]["threshold_severity"], families["noise"]["lower_bound"]))
        self.assertEqual([0.2, 0.4, 0.6, 0.5, 0.55, 0.525, 0.5375], families["noise"]["levels_tried"])
        self.assertEqual("no_reproducible_failure", families["blur"]["stop_reason"])
        self.assertIsNone(families["blur"]["threshold_severity"])
        self.assertEqual([0.2, 0.4, 0.6, 0.8, 1.0], families["blur"]["levels_tried"])
        self.assertEqual((0.05, 0.0375), (families["contrast"]["threshold_severity"],
                                          families["contrast"]["lower_bound"]))
        self.assertEqual({"name": "brightness_factor", "value": round(1 - 0.95 * 0.35, 6)},
                         families["darken"]["threshold_physical"])
        self.assertEqual("noise", families["noise"]["family"])

    def test_episode_budget_and_conditions(self):
        world, summary = self.run_threshold()
        self.assertEqual(5 + 30 + 35 + 25 + 25, summary["valid_count"])
        self.assertEqual(summary["valid_count"] + 1, len(world.ran), "plus the untimed warm-up")
        self.assertEqual({"success": 5}, summary["conditions"]["nominal"]["outcomes"])
        self.assertEqual({"passed": True, "planned": 5, "valid": 5, "outcomes": {"success": 5}},
                         summary["nominal_controls"])
        self.assertEqual(30, summary["conditions"]["darken"]["valid"])
        self.assertEqual(
            sum(item["attempts_used"] for item in summary["families"].values()), summary["valid_count"] - 5)

    def test_without_an_audit_target_the_configs_are_the_recorded_ones(self):
        world, summary = self.run_threshold()
        for kwargs in world.by_case.values():
            self.assertFalse({"suite", "task_id", "init_state_index"} & set(kwargs), kwargs)
        self.assertEqual(set(THRESHOLD_CONFIG), set(summary["config"]))

    def test_an_audit_target_reaches_every_episode_and_the_summary(self):
        target = dict(THRESHOLD_CONFIG, families=["darken"], suite="libero_10", task_id=3,
                      init_state_index=14)
        world, summary = self.run_threshold(config=target)
        self.assertGreater(len(world.by_case), 6)
        for case, kwargs in world.by_case.items():
            with self.subTest(case=case):
                self.assertEqual(("libero_10", 3, 14), (
                    kwargs["suite"], kwargs["task_id"], kwargs["init_state_index"]))
        controls = [kwargs for case, kwargs in world.by_case.items() if "nominal" in case]
        self.assertTrue(controls and all("image_perturbation" not in kwargs for kwargs in controls))
        self.assertEqual(("libero_10", 3, 14), (
            summary["config"]["suite"], summary["config"]["task_id"], summary["config"]["init_state_index"]))
        self.assertEqual(0.35, summary["families"]["darken"]["threshold_severity"])

    def test_a_partial_target_passes_only_what_was_given(self):
        world, _summary = self.run_threshold(config=dict(
            THRESHOLD_CONFIG, families=["darken"], task_id=2))
        for kwargs in world.by_case.values():
            self.assertEqual(2, kwargs["task_id"])
            self.assertFalse({"suite", "init_state_index"} & set(kwargs))

    def test_the_four_families_share_one_pool_of_twelve_workers_and_one_server(self):
        world, _summary = self.run_threshold(M6World(boundary_decide(BOUNDARIES), item_seconds=0.06))
        self.assertEqual(12, world.max_running, "20 first-level attempts compete for 12 workers")
        self.assertEqual(1, len(world.models))
        self.assertEqual(("faultline", 12), (world.models[0].kwargs["server"],
                                             world.models[0].kwargs["max_batch_size"]))
        self.assertTrue(all(live == 1 for live in world.models_at_run))

    def test_controls_finish_before_any_family_starts(self):
        world, _summary = self.run_threshold()
        first_family = min(i for i, case in enumerate(world.ran) if not case.startswith(("nominal", "warmup")))
        self.assertEqual(5, len([c for c in world.ran[:first_family] if c.startswith("nominal-control")]))

    def test_a_failed_nominal_control_stops_before_any_family_runs(self):
        world = M6World(lambda case, kwargs: "policy_failure" if case == "nominal-control-02" else "success")
        summary = self.run_m6(world, "m6-threshold", dict(THRESHOLD_CONFIG))

        self.assertEqual("nominal_controls_failed", summary["stop_reason"])
        self.assertFalse(summary["complete"])
        self.assertFalse(summary["nominal_controls"]["passed"])
        self.assertEqual({"policy_failure": 1, "success": 4}, summary["nominal_controls"]["outcomes"])
        self.assertEqual(set(m6.LEGACY_FAMILIES), set(summary["families"]))
        for family in summary["families"].values():
            self.assertEqual("nominal_failed", family["stop_reason"])
            self.assertIsNone(family["threshold_severity"])
            self.assertEqual([], family["levels"])
        self.assertEqual(6, len(world.ran), "the warm-up and the five controls only")

    def test_an_invalid_attempt_never_counts_as_a_policy_failure(self):
        world = M6World(boundary_decide(BOUNDARIES), fail_case="noise-s400000-a02", item_seconds=0.03)
        summary = self.run_m6(world, "m6-threshold", dict(THRESHOLD_CONFIG))

        self.assertEqual("evaluator_failed", summary["stop_reason"])
        self.assertFalse(summary["complete"])
        noise = summary["families"]["noise"]
        self.assertEqual("infrastructure_error", noise["stop_reason"])
        self.assertIsNone(noise["threshold_severity"])
        for level in noise["levels"]:
            if not level["complete"]:
                self.assertIsNone(level["reproducible"])
        self.assertIn(("close", 12), world.events)
        self.assertTrue(all(item["stop_reason"] in ("infrastructure_error", "threshold_found",
                                                    "no_reproducible_failure")
                            for item in summary["families"].values()))

    def test_a_deadline_during_the_search_marks_families_deadline_exhausted(self):
        world = M6World(boundary_decide(BOUNDARIES), item_seconds=0.02)
        summary = self.run_m6(
            world, "m6-threshold", dict(THRESHOLD_CONFIG),
            remaining=lambda: 1000.0 if len(world.ran) < 40 else 10.0)

        self.assertEqual("deadline_exhausted", summary["stop_reason"])
        self.assertFalse(summary["complete"])
        stops = {item["stop_reason"] for item in summary["families"].values()}
        self.assertIn("deadline_exhausted", stops)
        self.assertLessEqual(len(world.ran), 41 + 12, "nothing starts once the deadline guard trips")
        for item in summary["families"].values():
            for level in item["levels"]:
                if not level["complete"]:
                    self.assertIsNone(level["reproducible"])
        self.assertIn(("close", 12), world.events)

    def test_a_family_that_cannot_start_is_deadline_exhausted_without_levels(self):
        # Controls pass, then the guard trips before any level is submitted.
        world = M6World(boundary_decide(BOUNDARIES), item_seconds=0.01)
        summary = self.run_m6(
            world, "m6-threshold", dict(THRESHOLD_CONFIG),
            remaining=lambda: 1000.0 if len(world.ran) < 6 else 10.0)
        self.assertEqual("deadline_exhausted", summary["stop_reason"])
        for item in summary["families"].values():
            self.assertEqual("deadline_exhausted", item["stop_reason"])
            self.assertEqual([], item["levels"])

    def test_a_subset_of_families_and_a_custom_gate(self):
        config = dict(THRESHOLD_CONFIG, families=["blur", "darken"], sweep=[0.5, 1.0], attempts=3,
                      required_failures=2, bisection_steps=1)
        world, summary = self.run_threshold(
            M6World(boundary_decide({"blur": 0.5, "darken": None}), item_seconds=0.01), config)
        self.assertEqual({"blur", "darken"}, set(summary["families"]))
        self.assertEqual([0.5, 0.25], summary["families"]["blur"]["levels_tried"])
        self.assertEqual(0.5, summary["families"]["blur"]["threshold_severity"])
        self.assertEqual("no_reproducible_failure", summary["families"]["darken"]["stop_reason"])
        self.assertEqual(5 + 6 + 6, summary["valid_count"])

    def test_the_family_result_and_item_records_agree(self):
        _world, summary = self.run_threshold()
        failures = {}
        for item in summary["items"]:
            if item.get("family") and item["status"] == "valid":
                key = (item["family"], item["severity"])
                failures.setdefault(key, []).append(item["outcome"])
        for family, result in summary["families"].items():
            for level in result["levels"]:
                self.assertEqual(sorted(level["outcomes"]), sorted(failures[(family, level["severity"])]))

    def test_summary_file_matches_the_returned_summary_and_progress_reports_thresholds(self):
        _world, summary = self.run_threshold()
        self.assertEqual(json.loads(json.dumps(summary, sort_keys=True)), self.saved())
        names = [event for event, _ in self.events]
        self.assertEqual(1, names.count("m6_controls_done"))
        self.assertEqual(4, names.count("m6_family_done"))
        final = dict(self.events)["m6_summary"]
        self.assertEqual(0.35, final["thresholds"]["darken"])
        self.assertIsNone(final["thresholds"]["blur"])

    def test_no_threads_outlive_the_run(self):
        before = {t.name for t in threading.enumerate()}
        self.run_threshold()
        time.sleep(0.05)
        leftover = {t.name for t in threading.enumerate()} - before
        self.assertEqual(set(), {name for name in leftover if name.startswith("m6-")})

    def test_cancelled_run_directories_are_removed(self):
        world = M6World(boundary_decide(BOUNDARIES), item_seconds=0.05, fail_case="darken-s200000-a01",
                        leave_companions=True)
        summary = self.run_m6(world, "m6-threshold", dict(THRESHOLD_CONFIG))
        self.assertEqual("evaluator_failed", summary["stop_reason"])
        self.assertFalse(list((self.root / "m6").rglob("*.sqlite-*")))


def fake_probe(kwargs):
    """What the benchmark probe would write for a config (two samples)."""

    def camera(unperturbed_mean, unperturbed_std, mean_ratio, std_ratio):
        return {"unperturbed_mean": unperturbed_mean, "unperturbed_std": unperturbed_std,
                "perturbed_mean": round(unperturbed_mean * mean_ratio, 4),
                "perturbed_std": round(unperturbed_std * std_ratio, 4)}

    agent, wrist = (1.0, 1.0), (1.0, 1.0)
    if "x" in kwargs:  # the agent-view rectangle
        agent = (0.9, 0.8)
    spec = kwargs.get("image_perturbation")
    if spec is not None:
        both = (1.0 - 0.5 * spec["severity"], 1.0 - 0.25 * spec["severity"])
        agent, wrist = both, both
    if "wrist_occlusion" in kwargs:
        wrist = (0.5, 0.75)
    samples = [
        {"step": step, "agentview": camera(100.0, 40.0, *agent), "wrist": camera(80.0, 20.0, *wrist)}
        for step in (0, 40)
    ]
    return {"schema_version": 1, "perturbation": {"seed": 7},
            "episodes": [{"episode_index": 0, "samples": samples}]}


class ProbingWorld(M6World):
    """Writes the benchmark's probe sidecar beside each perturbed config, like the real image."""

    def write_config(self, **kwargs):
        super().write_config(**kwargs)
        if "wrist_occlusion" in kwargs or "image_perturbation" in kwargs:
            path = kwargs["config_path"]
            path.with_name(path.stem + m6.PROBE_SUFFIX).write_text(
                json.dumps(fake_probe(kwargs)), encoding="utf-8")


class CameraEffectTests(unittest.TestCase):
    def test_median_ratios_per_camera(self):
        def doc(rows):
            return {"schema_version": 1, "episodes": [{"episode_index": 0, "samples": [
                {"step": 40 * i, "agentview": {"unperturbed_mean": um, "unperturbed_std": us,
                                               "perturbed_mean": pm, "perturbed_std": ps}}
                for i, (um, us, pm, ps) in enumerate(rows)]}]}

        effect = m6.camera_effect([doc([(100, 10, 50, 20), (100, 10, 60, 30), (100, 10, 90, 40)])])
        self.assertEqual({"items": 1, "agentview": {"mean_ratio": 0.6, "std_ratio": 3.0, "samples": 3}}, effect)

    def test_pools_samples_across_items_and_skips_zero_denominators(self):
        def doc(um, us, pm, ps):
            return {"schema_version": 1, "episodes": [{"episode_index": 0, "samples": [
                {"step": 0, "wrist": {"unperturbed_mean": um, "unperturbed_std": us,
                                      "perturbed_mean": pm, "perturbed_std": ps}}]}]}

        effect = m6.camera_effect([doc(100, 10, 50, 5), doc(100, 0, 70, 3), doc(0, 10, 9, 20)])
        self.assertEqual(3, effect["items"])
        # mean ratios 0.5 and 0.7 (the zero-mean image is skipped); std ratios 0.5 and 2.0 (zero std skipped)
        self.assertEqual({"mean_ratio": 0.6, "std_ratio": 1.25, "samples": 3}, effect["wrist"])

    def test_no_probes_means_no_effect(self):
        self.assertIsNone(m6.camera_effect([]))
        self.assertIsNone(m6.camera_effect([{"schema_version": 1, "episodes": []}]))

    def test_load_probe_rejects_missing_malformed_and_foreign_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(m6.load_probe(root / "missing.json"))
            for name, text in (("garbage.json", "{no"), ("list.json", "[]"), ("schema.json", '{"schema_version": 2}'),
                               ("episodes.json", '{"schema_version": 1, "episodes": 3}'),
                               ("nan.json", '{"schema_version": 1, "episodes": [], "x": NaN}')):
                (root / name).write_text(text, encoding="utf-8")
                with self.subTest(name=name):
                    self.assertIsNone(m6.load_probe(root / name))
            (root / "ok.json").write_text(json.dumps(fake_probe({"image_perturbation": {"severity": 0.2}})),
                                          encoding="utf-8")
            self.assertEqual(1, m6.load_probe(root / "ok.json")["schema_version"])

    def test_oversized_probe_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "big.json"
            path.write_text(json.dumps({"schema_version": 1, "episodes": [], "pad": "x" * 40000}),
                            encoding="utf-8")
            self.assertIsNone(m6.load_probe(path))


class CameraEffectRunTests(RunTestCase):
    def test_smoke_conditions_carry_the_camera_effect(self):
        summary = self.run_m6(ProbingWorld(smoke_decide), "m6-smoke")
        conditions = summary["conditions"]

        self.assertIsNone(conditions["nominal"]["camera_effect"])
        wrist_only = conditions["wrist_mask_only"]["camera_effect"]
        self.assertEqual(12, wrist_only["items"])
        self.assertEqual({"mean_ratio": 1.0, "std_ratio": 1.0, "samples": 24}, wrist_only["agentview"])
        self.assertEqual({"mean_ratio": 0.5, "std_ratio": 0.75, "samples": 24}, wrist_only["wrist"])
        darken = conditions["darken_0.6"]["camera_effect"]
        self.assertEqual(2, darken["items"])
        self.assertEqual(darken["agentview"], darken["wrist"])
        self.assertEqual(0.7, darken["agentview"]["mean_ratio"])
        self.assertEqual(0.85, darken["agentview"]["std_ratio"])

    def test_threshold_levels_and_thresholds_carry_the_camera_effect(self):
        world = ProbingWorld(boundary_decide(BOUNDARIES))
        summary = self.run_m6(world, "m6-threshold", dict(THRESHOLD_CONFIG))
        darken = summary["families"]["darken"]

        by_severity = {level["severity"]: level for level in darken["levels"]}
        self.assertEqual(0.8, by_severity[0.4]["camera_effect"]["wrist"]["mean_ratio"])
        self.assertEqual(5, by_severity[0.4]["camera_effect"]["items"])
        self.assertEqual(by_severity[0.35]["camera_effect"], darken["threshold_camera_effect"])
        self.assertEqual(0.825, darken["threshold_camera_effect"]["agentview"]["mean_ratio"])
        self.assertIsNone(summary["families"]["blur"]["threshold_camera_effect"])
        self.assertIsNotNone(summary["families"]["blur"]["levels"][0]["camera_effect"])
        self.assertIsNone(summary["conditions"]["nominal"]["camera_effect"])

    def test_missing_or_broken_probes_leave_the_effect_empty_without_failing_the_run(self):
        world = ProbingWorld(smoke_decide)
        original = world.write_config

        def write_config(**kwargs):
            original(**kwargs)
            path = kwargs["config_path"]
            probe = path.with_name(path.stem + m6.PROBE_SUFFIX)
            if path.stem.startswith("darken"):
                probe.unlink()
            elif path.stem.startswith("noise"):
                probe.write_text("{broken", encoding="utf-8")

        world.write_config = write_config
        summary = self.run_m6(world, "m6-smoke")
        self.assertTrue(summary["complete"])
        self.assertIsNone(summary["conditions"]["darken_0.6"]["camera_effect"])
        self.assertIsNone(summary["conditions"]["noise_0.6"]["camera_effect"])
        self.assertIsNotNone(summary["conditions"]["blur_0.6"]["camera_effect"])

    def test_the_warmup_probe_is_not_counted(self):
        world = ProbingWorld(smoke_decide)
        summary = self.run_m6(world, "m6-smoke")
        self.assertIsNone(summary["conditions"]["nominal"]["camera_effect"])
        self.assertEqual("warmup-nominal-01", summary["warmup"]["case_id"])

    def test_summary_json_round_trips_with_the_camera_effect(self):
        summary = self.run_m6(ProbingWorld(smoke_decide), "m6-smoke")
        self.assertEqual(json.loads(json.dumps(summary, sort_keys=True)), self.saved())


class InterruptTests(RunTestCase):
    """An interrupt must cancel and join every evaluator before the server is closed."""

    def interrupted_run(self, mode, config):
        from unittest import mock

        seen = []
        world = M6World(smoke_decide, block_until_cancel=False, leave_companions=True)
        world.on_run = lambda case: setattr(world, "block_until_cancel", not case.startswith("warmup"))
        pools = []
        original_init = m6.EvaluatorPool.__init__

        def recording_init(pool, **kwargs):
            original_init(pool, **kwargs)
            pools.append(pool)

        def interrupt(tickets):
            deadline = time.monotonic() + 5
            while world.running < 5 and time.monotonic() < deadline:
                time.sleep(0.01)
            raise KeyboardInterrupt

        factory = world.model_factory

        def watching_factory(**kwargs):
            model = factory(**kwargs)
            original_close = model.close

            def close():
                seen.append({"cancel": pools[0].cancel.is_set(), "running": world.running})
                original_close()

            model.close = close
            return model

        started = time.monotonic()
        with mock.patch.object(m6.EvaluatorPool, "__init__", recording_init), \
                mock.patch.object(m6.EvaluatorPool, "wait", staticmethod(interrupt)):
            with self.assertRaises(KeyboardInterrupt):
                self.run_m6(world, mode, config, model_factory=watching_factory)
        return world, seen, time.monotonic() - started

    def check(self, world, seen, elapsed):
        self.assertEqual([{"cancel": True, "running": 0}], seen,
                         "the server closed only after the evaluators were cancelled and gone")
        self.assertLess(elapsed, 10.0)
        self.assertEqual([None], world.set_calls[-1:], "the model was unregistered after closing")
        summary = self.saved()
        self.assertFalse(summary["complete"])
        self.assertFalse(list((self.root / "m6").rglob("*.sqlite-*")), "no SQLite companions remain")
        killed = [item for item in summary["items"] if item["status"] == "cancelled"]
        self.assertTrue(killed)
        self.assertTrue(all(item["run_dir_removed"] for item in killed))
        self.assertFalse(any((self.root / "m6" / "runs" / item["case_id"]).exists() for item in killed))

    def test_interrupt_during_the_smoke_wave(self):
        self.check(*self.interrupted_run("m6-smoke", None))

    def test_interrupt_during_the_threshold_controls(self):
        self.check(*self.interrupted_run("m6-threshold", dict(THRESHOLD_CONFIG)))

    def test_shutdown_waits_for_all_workers_under_one_shared_deadline(self):
        gate = threading.Event()
        self.addCleanup(gate.set)

        def evaluate(item):
            gate.wait(30)
            return {"case_id": item["case_id"], "kind": "k", "status": "valid", "outcome": "success",
                    "started_seconds": 0.0, "ended_seconds": 1.0}

        pool = m6.EvaluatorPool(workers=12, evaluate=evaluate, remaining=lambda: 1000.0,
                                item_timeout=300.0, cancel=threading.Event())
        pool.start()
        for index in range(12):
            pool.submit({"case_id": "c{}".format(index), "kind": "k"})
        time.sleep(0.1)
        started = time.monotonic()
        pool.shutdown(0.5)
        self.assertLess(time.monotonic() - started, 2.0, "12 stuck workers cost one deadline, not twelve")

    def test_family_threads_are_joined_under_one_deadline_too(self):
        source = (Path(m6.__file__)).read_text(encoding="utf-8")
        self.assertNotIn("thread.join(30)", source)


class FamilySnapshotTests(unittest.TestCase):
    def test_the_summary_copies_the_families_under_their_lock(self):
        events = []

        class Lock:
            def __enter__(self):
                events.append("enter")

            def __exit__(self, *exc):
                events.append("exit")

        state = {"families": {"darken": {"stop_reason": "threshold_found"}}}
        snapshot = m6.snapshot_families(state, Lock())
        state["families"]["noise"] = {}
        self.assertEqual(["enter", "exit"], events)
        self.assertEqual({"darken"}, set(snapshot))

    def test_a_family_thread_writing_during_summaries_never_breaks_them(self):
        state = {"families": {}}
        lock = threading.Lock()
        stop = threading.Event()

        def writer():
            index = 0
            while not stop.is_set():
                with lock:
                    state["families"]["f{}".format(index)] = {"stop_reason": "threshold_found"}
                index += 1

        thread = threading.Thread(target=writer)
        thread.start()
        try:
            for _ in range(300):
                self.assertIsInstance(m6.snapshot_families(state, lock), dict)
        finally:
            stop.set()
            thread.join()


class PythonCompatibilityTests(unittest.TestCase):
    """The simulator image runs the workload and the benchmark adapter on Python 3.8."""

    MODULES = ("image_perturbation", "occlusion", "libero", "threshold_search", "m6_experiment",
               "batch_experiment", "job_workload", "job_runtime")

    def test_modules_parse_as_python_38(self):
        import ast

        source = Path(__file__).parents[1] / "src" / "robot_debug"
        for name in self.MODULES:
            with self.subTest(module=name):
                path = source / (name + ".py")
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 8))



class BreadthFamiliesTests(unittest.TestCase):
    """ADR 0032: the audit accepts the new image families and the two scene families."""

    ALL = ("darken", "noise", "blur", "contrast", "jpeg", "colour_cast", "motion_blur", "dead_pixels",
           "viewpoint", "lighting")

    def test_the_family_registry_lists_every_family_in_canonical_order(self):
        self.assertEqual(self.ALL, m6.FAMILIES)
        self.assertEqual(("darken", "noise", "blur", "contrast"), m6.LEGACY_FAMILIES)
        self.assertEqual(("viewpoint", "lighting"), m6.SCENE_FAMILIES)
        self.assertEqual(self.ALL[:8], m6.IMAGE_FAMILIES)

    def test_scene_families_use_the_scene_option_and_image_families_the_image_option(self):
        self.assertEqual({"image_perturbation": {"kind": "jpeg", "severity": 0.4}}, m6.scalar_config("jpeg", 0.4))
        self.assertEqual({"scene_perturbation": {"kind": "viewpoint", "severity": 0.4}},
                         m6.scalar_config("viewpoint", 0.4))
        self.assertEqual({"scene_perturbation": {"kind": "lighting", "severity": 0.0125}},
                         m6.scalar_config("lighting", 0.0125))

    def test_level_items_carry_the_scene_option(self):
        (first, *_rest) = m6.level_items("viewpoint", 0.6, 3)
        self.assertEqual("viewpoint-s600000-a01", first["case_id"])
        self.assertEqual({"scene_perturbation": {"kind": "viewpoint", "severity": 0.6}}, first["config"])
        self.assertEqual("viewpoint", first["meta"]["family"])

    def test_the_smoke_manifest_is_frozen_on_the_four_recorded_families(self):
        families = {item["meta"]["family"] for item in m6.smoke_manifest() if "family" in item["meta"]}
        self.assertEqual(set(m6.LEGACY_FAMILIES), families)

    def test_a_new_family_never_shortens_the_deadline_and_jpeg_costs_the_most(self):
        base = dict(THRESHOLD_CONFIG, sweep=[0.5, 1.0], attempts=3, required_failures=2, bisection_steps=2)
        legacy = m6.recommended_deadline_seconds("m6-threshold", dict(base, families=["blur"]))
        deadlines = {family: m6.recommended_deadline_seconds("m6-threshold", dict(base, families=[family]))
                     for family in m6.FAMILIES}
        for family, seconds in deadlines.items():
            with self.subTest(family=family):
                self.assertGreaterEqual(seconds, legacy)
        self.assertEqual(max(deadlines.values()), deadlines["jpeg"])
        self.assertEqual(deadlines["viewpoint"], deadlines["lighting"], "scene families add no per-step cost")
        self.assertEqual(legacy, deadlines["darken"], "the recorded families keep their recorded estimates")

    def test_the_per_step_overhead_of_the_worst_family_in_the_mix_sets_the_estimate(self):
        base = dict(THRESHOLD_CONFIG, sweep=[0.5, 1.0], attempts=3, required_failures=2, bisection_steps=2)
        mixed = m6.recommended_deadline_seconds("m6-threshold", dict(base, families=["blur", "jpeg"]))
        alone = m6.recommended_deadline_seconds("m6-threshold", dict(base, families=["jpeg"]))
        self.assertGreaterEqual(mixed, alone)

    def test_a_family_costs_more_on_a_longer_suite(self):
        config = dict(THRESHOLD_CONFIG, families=["jpeg"], sweep=[0.5, 1.0], attempts=3, required_failures=2,
                      bisection_steps=2)
        wall_object = m6.episode_wall_seconds(config)
        wall_ten = m6.episode_wall_seconds(dict(config, suite="libero_10"))
        self.assertGreater(wall_ten, wall_object)
        self.assertEqual(m6.ASSUMED_EPISODE_WALL_SECONDS, m6.episode_wall_seconds(dict(config, families=["darken"])))
        self.assertGreater(wall_object, m6.ASSUMED_EPISODE_WALL_SECONDS)

    def test_step_overheads_cover_exactly_the_costly_new_families(self):
        self.assertEqual({"jpeg", "motion_blur", "colour_cast", "dead_pixels"}, set(m6.FAMILY_STEP_OVERHEAD_SECONDS))
        self.assertTrue(all(0 < seconds < 0.1 for seconds in m6.FAMILY_STEP_OVERHEAD_SECONDS.values()))


class StageConfigWriterTests(unittest.TestCase):
    """``write_stage_config`` adds the breadth-pack benchmark options to the generated YAML."""

    def write(self, **options):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "configs" / "viewpoint-s400000-a01.yaml"
            config_path.parent.mkdir()
            m6.write_stage_config(
                config_path=config_path, output_dir=root / "runs" / "x", project_root=root / "project",
                stage_name="m6-x", episode_indices=(0,), **options)
            return config_path.read_text(encoding="utf-8")

    def params(self, text):
        import yaml

        return yaml.safe_load(text)["benchmarks"][0]["params"]

    def test_without_the_new_options_the_file_is_the_recorded_one(self):
        from scripts import run_failure_search

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "case.yaml"
            options = dict(config_path=path, output_dir=root / "o", project_root=root / "p", stage_name="s",
                           episode_indices=(0,), image_perturbation={"kind": "blur", "severity": 0.4})
            run_failure_search._write_config(**options)
            plain = path.read_text(encoding="utf-8")
            m6.write_stage_config(**options)
            self.assertEqual(plain, path.read_text(encoding="utf-8"))
            m6.write_stage_config(scene_perturbation=None, instruction=None, instruction_out=False, **options)
            self.assertEqual(plain, path.read_text(encoding="utf-8"))

    def test_a_scene_family_is_written_with_its_probe_sidecar(self):
        params = self.params(self.write(scene_perturbation={"kind": "viewpoint", "severity": 0.4}, task_id=2))
        self.assertEqual({"kind": "viewpoint", "severity": 0.4}, params["scene_perturbation"])
        self.assertTrue(params["camera_probe"].endswith("viewpoint-s400000-a01.camera_probe.json"))
        self.assertEqual(2, params["task_id"])

    def test_an_image_family_keeps_its_single_probe_line(self):
        text = self.write(image_perturbation={"kind": "jpeg", "severity": 0.4}, scene_perturbation=None)
        self.assertEqual(1, text.count("camera_probe:"))
        self.assertNotIn("scene_perturbation", text)

    def test_a_scene_family_with_an_image_family_writes_one_probe_line(self):
        text = self.write(image_perturbation={"kind": "blur", "severity": 0.4},
                          scene_perturbation={"kind": "lighting", "severity": 0.3})
        self.assertEqual(1, text.count("camera_probe:"))
        params = self.params(text)
        self.assertEqual("lighting", params["scene_perturbation"]["kind"])
        self.assertEqual("blur", params["image_perturbation"]["kind"])

    def test_an_instruction_and_its_sidecar_are_written(self):
        params = self.params(self.write(instruction='move the "soup" tin: now', instruction_out=True))
        self.assertEqual('move the "soup" tin: now', params["instruction"])
        self.assertTrue(params["instruction_out"].endswith("viewpoint-s400000-a01.instruction.json"))

    def test_a_non_ascii_instruction_survives_the_yaml_round_trip(self):
        params = self.params(self.write(instruction="déplace la boîte"))
        self.assertEqual("déplace la boîte", params["instruction"])
        self.assertNotIn("instruction_out", params)

    def test_bad_values_are_refused_before_a_file_is_written(self):
        for options in ({"scene_perturbation": {"kind": "viewpoint"}}, {"scene_perturbation": "x"},
                        {"scene_perturbation": {"kind": "blur", "severity": 0.5}},
                        {"scene_perturbation": {"kind": "lighting", "severity": 0.1234567}},
                        {"instruction": ""}, {"instruction": "a\nb"}, {"instruction": 5},
                        {"instruction": "x" * 201}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.write(**options)

    def test_the_written_options_are_accepted_by_the_benchmark_constructor(self):
        from robot_debug.scene_perturbation import ScenePerturbation

        params = self.params(self.write(scene_perturbation={"kind": "lighting", "severity": 0.25},
                                        instruction="open the drawer", instruction_out=True))
        self.assertEqual("lighting", ScenePerturbation.from_mapping(params["scene_perturbation"]).kind)


class SceneThresholdRunTests(RunTestCase):
    """A threshold run over mixed families: image families and scene families share the pool."""

    @staticmethod
    def decide(case, kwargs):
        spec = kwargs.get("image_perturbation") or kwargs.get("scene_perturbation")
        if spec is None:
            return "success"
        boundary = {"jpeg": 0.7, "dead_pixels": None, "viewpoint": 0.35, "lighting": 0.05}[spec["kind"]]
        return "policy_failure" if boundary is not None and spec["severity"] >= boundary else "success"

    def test_scene_and_image_families_find_their_thresholds_on_one_pool(self):
        config = dict(THRESHOLD_CONFIG, families=["jpeg", "dead_pixels", "viewpoint", "lighting"])
        world = M6World(self.decide, item_seconds=0.02)
        summary = self.run_m6(world, "m6-threshold", config)
        families = summary["families"]

        self.assertIsNone(summary["stop_reason"])
        self.assertTrue(summary["complete"])
        self.assertEqual((0.7, 0.6875), (families["jpeg"]["threshold_severity"], families["jpeg"]["lower_bound"]))
        self.assertEqual("no_reproducible_failure", families["dead_pixels"]["stop_reason"])
        self.assertEqual(0.35, families["viewpoint"]["threshold_severity"])
        self.assertEqual(0.05, families["lighting"]["threshold_severity"])
        self.assertEqual({"name": "jpeg_quality", "value": round(95 - 90 * 0.7, 6)},
                         families["jpeg"]["threshold_physical"])
        self.assertEqual({"name": "camera_shift_m", "value": 0.035}, families["viewpoint"]["threshold_physical"])
        self.assertEqual({"name": "light_scale", "value": round(1 - 0.9 * 0.05, 6)},
                         families["lighting"]["threshold_physical"])
        scene_cases = [kwargs for kwargs in world.by_case.values() if "scene_perturbation" in kwargs]
        self.assertTrue(scene_cases)
        self.assertTrue(all("image_perturbation" not in kwargs for kwargs in scene_cases))

    def test_the_applied_scene_values_reach_the_level_entries_of_scene_families_only(self):
        class SceneProbingWorld(M6World):
            def write_config(self, **kwargs):
                super().write_config(**kwargs)
                spec = kwargs.get("scene_perturbation")
                if spec is not None:
                    path = kwargs["config_path"]
                    path.with_name(path.stem + m6.PROBE_SUFFIX).write_text(json.dumps({
                        "schema_version": 1, "perturbation": {"seed": 7}, "episodes": [],
                        "scene_applied": [{"episode_index": 0, "kind": spec["kind"], "severity": spec["severity"],
                                           "shift_m": round(0.1 * spec["severity"], 6)}]}), encoding="utf-8")

        config = dict(THRESHOLD_CONFIG, families=["viewpoint", "jpeg"], sweep=[0.4, 1.0], bisection_steps=0)
        summary = self.run_m6(SceneProbingWorld(self.decide, item_seconds=0.01), "m6-threshold", config)
        viewpoint = summary["families"]["viewpoint"]
        self.assertEqual({"kind": "viewpoint", "severity": 0.4, "shift_m": 0.04},
                         viewpoint["levels"][0]["scene_applied"])
        self.assertIsNone(viewpoint["levels"][0]["camera_effect"], "a scene family has no image statistics")
        for level in summary["families"]["jpeg"]["levels"]:
            self.assertNotIn("scene_applied", level)

    def test_nominal_controls_carry_no_scene_option(self):
        config = dict(THRESHOLD_CONFIG, families=["viewpoint"])
        world = M6World(self.decide, item_seconds=0.01)
        self.run_m6(world, "m6-threshold", config)
        controls = [kwargs for case, kwargs in world.by_case.items() if "nominal" in case]
        self.assertTrue(controls)
        self.assertTrue(all("scene_perturbation" not in kwargs and "image_perturbation" not in kwargs
                            for kwargs in controls))


if __name__ == "__main__":
    unittest.main()
