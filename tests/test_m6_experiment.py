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
from robot_debug.job_runtime import M6_FAMILIES
from robot_debug.job_workload import CERTIFIED_M4_RECTANGLE
from robot_debug.parallel_eval import _MASK_RECTANGLE
from tests.test_batch_experiment import World

THRESHOLD_CONFIG = {
    "families": list(M6_FAMILIES),
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
        for family in M6_FAMILIES:
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
        self.assertEqual(1080, m6.recommended_deadline_seconds("m6-smoke"))
        self.assertEqual(185, m6.planned_episodes("m6-threshold", THRESHOLD_CONFIG))
        self.assertEqual(1740, m6.recommended_deadline_seconds("m6-threshold", THRESHOLD_CONFIG))
        small = dict(THRESHOLD_CONFIG, families=["darken"], sweep=[1.0], attempts=1,
                     required_failures=1, bisection_steps=0)
        self.assertEqual(1020, m6.recommended_deadline_seconds("m6-threshold", small))
        self.assertGreaterEqual(m6.recommended_deadline_seconds("m6-smoke"), 1000)


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
        self.assertEqual(list(M6_FAMILIES), sorted(families, key=list(M6_FAMILIES).index))
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
        self.assertEqual(set(M6_FAMILIES), set(summary["families"]))
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


if __name__ == "__main__":
    unittest.main()
