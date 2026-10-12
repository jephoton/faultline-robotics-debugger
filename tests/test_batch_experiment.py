"""Tests for the M3 batched-inference phase runner, statistics and verdict."""

from __future__ import annotations

import _thread
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

from robot_debug import batch_experiment as be
from robot_debug.job_process import CleanupUnconfirmed, InfrastructureError, RunCancelled
from robot_debug.job_runtime import JobRuntimeError, export_closed_evidence
from robot_debug.parallel_eval import build_manifest, manifest_hash


def phase(workers, size, epm, *, status="complete", valid=24, drift=(), total=300.0, timing=None):
    return {
        "workers": workers, "max_batch_size": size, "status": status, "valid_count": valid,
        "episodes_per_minute": epm, "drift_ids": list(drift), "total_seconds": total, "timing": timing,
    }


class StatisticsTests(unittest.TestCase):
    def test_percentile_interpolates_and_handles_edges(self) -> None:
        self.assertIsNone(be.percentile([], 50))
        self.assertEqual(7.0, be.percentile([7], 95))
        self.assertEqual(2.5, be.percentile([1, 2, 3, 4], 50))
        self.assertAlmostEqual(3.85, be.percentile([1, 2, 3, 4], 95))
        self.assertEqual(4.0, be.percentile([4, 1, 3, 2], 100))

    def write_log(self, directory, lines):
        path = Path(directory) / "t.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_timing_stats_from_a_server_log(self) -> None:
        records = [
            {"t": 1.0, "batch_size": 1, "inference_ms": 100.0, "wait_ms": [0.0]},
            {"t": 2.0, "batch_size": 3, "inference_ms": 200.0, "wait_ms": [10.0, 20.0, 30.0]},
            {"t": 3.0, "batch_size": 2, "inference_ms": 300.0, "wait_ms": [5.0, 15.0]},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_log(directory, [json.dumps(r) for r in records])
            stats = be.timing_stats(path, 4.0)
        self.assertEqual(3, stats["calls"])
        self.assertEqual(6, stats["items_served"])
        self.assertEqual(2.0, stats["mean_batch_size"])
        self.assertEqual(3, stats["max_batch_size_observed"])
        self.assertEqual(200.0, stats["inference_ms_p50"])
        self.assertEqual(290.0, stats["inference_ms_p95"])
        self.assertEqual(12.5, stats["wait_ms_p50"])
        self.assertEqual(0.6, stats["busy_seconds"])
        self.assertEqual(0.15, stats["model_call_busy_share"])
        self.assertEqual(0, stats["malformed_lines"])

    def test_malformed_and_implausible_lines_are_counted_not_trusted(self) -> None:
        good = json.dumps({"t": 1, "batch_size": 1, "inference_ms": 5.0, "wait_ms": [0.0]})
        bad = [
            "not json",
            json.dumps({"batch_size": 2, "inference_ms": 1.0, "wait_ms": [0.0]}),
            json.dumps({"t": 1, "batch_size": 2, "inference_ms": 1.0, "wait_ms": [0.0]}),
            json.dumps({"t": 1, "batch_size": 1, "inference_ms": -1.0, "wait_ms": [0.0]}),
            json.dumps({"t": 1, "batch_size": True, "inference_ms": 1.0, "wait_ms": [0.0]}),
            "{}",
        ]
        with tempfile.TemporaryDirectory() as directory:
            stats = be.timing_stats(self.write_log(directory, [good] + bad), 1.0)
        self.assertEqual(1, stats["calls"])
        self.assertEqual(len(bad), stats["malformed_lines"])

    def test_missing_or_empty_log_means_no_stats(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(be.timing_stats(Path(directory) / "none.jsonl", 1.0))
            self.assertIsNone(be.timing_stats(self.write_log(directory, []), 1.0))

    def test_drift_flags_nominal_failures_and_mask_successes_only(self) -> None:
        results = [
            {"case_id": "nominal-01", "kind": "nominal", "status": "valid", "outcome": "success"},
            {"case_id": "nominal-02", "kind": "nominal", "status": "valid", "outcome": "policy_failure"},
            {"case_id": "mask-01", "kind": "mask", "status": "valid", "outcome": "policy_failure"},
            {"case_id": "mask-02", "kind": "mask", "status": "valid", "outcome": "success"},
            {"case_id": "mask-03", "kind": "mask", "status": "cancelled", "outcome": None},
        ]
        self.assertEqual(["mask-02", "nominal-02"], be.drift_ids(results))
        self.assertEqual(
            {"nominal": {"success": 1, "policy_failure": 1}, "mask": {"policy_failure": 1, "success": 1}},
            be.outcomes_by_kind(results),
        )

    def test_estimate_scales_down_worker_counts_conservatively(self) -> None:
        done = [{"workers": 8, "total_seconds": 200.0}, {"workers": 12, "total_seconds": 150.0}]
        self.assertIsNone(be.estimate_phase_seconds([], 8))
        self.assertEqual(225.0, be.estimate_phase_seconds(done, 8))  # 12 workers: 150 s * 12/8
        self.assertEqual(200.0, be.estimate_phase_seconds(done, 12))  # never shrinks below a longer phase
        self.assertEqual(450.0, be.estimate_phase_seconds(done, 4))
        self.assertEqual(be.phase_label(1, 8, 8), "phase-02-w08-b08")


class VerdictTests(unittest.TestCase):
    def test_bar_is_inclusive_at_fifteen_percent(self) -> None:
        comparisons = be.compare_phases([phase(8, 1, 10.0), phase(8, 8, 11.5)])
        self.assertEqual(1.15, comparisons[0]["speedup"])
        self.assertEqual("works", comparisons[0]["verdict"])
        below = be.compare_phases([phase(8, 1, 10.0), phase(8, 8, 11.49)])
        self.assertEqual("no_measurable_gain", below[0]["verdict"])

    def test_comparison_needs_both_phases_complete_with_equal_work(self) -> None:
        cases = (
            [phase(8, 1, 10.0), phase(8, 8, 12.0, status="incomplete", valid=20)],
            [phase(8, 1, 10.0), phase(8, 8, 12.0, valid=23)],
            [phase(8, 1, None, status="incomplete"), phase(8, 8, 12.0)],
        )
        for phases in cases:
            comparisons = be.compare_phases(phases)
            self.assertEqual("incomplete", comparisons[0]["status"])
            self.assertIsNone(comparisons[0]["speedup"])

    def test_only_matching_pairs_are_compared(self) -> None:
        comparisons = be.compare_phases([phase(8, 1, 10.0), phase(12, 12, 9.0), phase(4, 1, 5.0)])
        self.assertEqual([], comparisons)

    def test_verdict_precedence(self) -> None:
        good = [phase(8, 1, 10.0), phase(8, 8, 13.0)]
        comparisons = be.compare_phases(good)
        self.assertEqual("works", be.overall_verdict(good, comparisons, None))
        self.assertEqual("works", be.overall_verdict(good, comparisons, {"passed": True}))
        self.assertEqual("parity_failed", be.overall_verdict(good, comparisons, {"passed": False}))
        drifted = [phase(8, 1, 10.0), phase(8, 8, 13.0, drift=["mask-02"])]
        self.assertEqual("outcome_drift", be.overall_verdict(drifted, be.compare_phases(drifted), None))
        self.assertEqual(
            "parity_failed", be.overall_verdict(drifted, be.compare_phases(drifted), {"passed": False})
        )
        flat = [phase(8, 1, 10.0), phase(8, 8, 10.4), phase(12, 1, 10.0), phase(12, 12, 10.1)]
        self.assertEqual("no_measurable_gain", be.overall_verdict(flat, be.compare_phases(flat), None))
        self.assertEqual("incomplete", be.overall_verdict([phase(8, 1, 10.0)], [], None))

    def test_one_working_worker_count_is_enough_for_works(self) -> None:
        phases = [phase(8, 1, 10.0), phase(8, 8, 10.2), phase(12, 1, 10.0), phase(12, 12, 12.0)]
        self.assertEqual("works", be.overall_verdict(phases, be.compare_phases(phases), None))

    def test_summary_records_manifest_and_smoke_assessment(self) -> None:
        batched = phase(4, 4, 6.0, valid=4, timing={"max_batch_size_observed": 3})
        summary = be.build_summary(
            mode="m3-batch-smoke", repeats_per_kind=2, planned=[[4, 4]], phases=[batched],
            parity={"passed": True}, stop_reason=None,
        )
        self.assertEqual(manifest_hash(build_manifest(2)), summary["manifest_hash"])
        self.assertEqual(4, summary["items_per_phase"])
        self.assertTrue(summary["smoke"]["passed"])
        self.assertTrue(summary["smoke"]["batching_engaged"])
        self.assertTrue(summary["all_phases_complete"])
        self.assertEqual("incomplete", summary["verdict"])
        json.dumps(summary, allow_nan=False)

    def test_smoke_does_not_pass_without_parity_or_with_drift(self) -> None:
        for parity, drift in (({"passed": False}, ()), (None, ()), ({"passed": True}, ("mask-01",))):
            summary = be.build_summary(
                mode="m3-batch-smoke", repeats_per_kind=2, planned=[[4, 4]],
                phases=[phase(4, 4, 6.0, valid=4, drift=drift)], parity=parity, stop_reason=None,
            )
            self.assertFalse(summary["smoke"]["passed"])

    def test_measurement_summary_notes_parity_lives_in_the_smoke_job(self) -> None:
        summary = be.build_summary(
            mode="m3-batch", repeats_per_kind=12, planned=[[8, 1]], phases=[], parity=None, stop_reason=None
        )
        self.assertIn("smoke", summary["parity_note"])
        self.assertNotIn("smoke", summary)
        self.assertFalse(summary["all_phases_complete"])


# ---------------------------------------------------------------------------
# Phase execution with fakes
# ---------------------------------------------------------------------------


class FakeModel:
    def __init__(self, world, kwargs, *, fail=None):
        self.world = world
        self.kwargs = kwargs
        self.fail = fail

    def start(self):
        self.world.events.append(("start", self.kwargs["max_batch_size"]))
        if self.fail == "start":
            raise InfrastructureError("hidden")
        self.world.live += 1
        self.world.max_live = max(self.world.max_live, self.world.live)
        log = Path(self.kwargs["timing_log"])
        log.parent.mkdir(parents=True, exist_ok=True)
        size = self.kwargs["max_batch_size"]
        lines = [
            {"t": 1.0 + i, "batch_size": size, "inference_ms": 50.0, "wait_ms": [1.0] * size}
            for i in range(3)
        ]
        log.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")

    def wait_ready(self, *, deadline):
        self.world.events.append(("ready", deadline))
        if self.fail == "ready":
            raise InfrastructureError("hidden")

    @property
    def argv(self):
        return ["/py", "server.py", "--args.max_batch_size={}".format(self.kwargs["max_batch_size"])]

    def check_alive(self):
        if self.fail == "dead":
            raise InfrastructureError("hidden")
        if self.world.on_check_alive is not None and self.world.live:
            self.world.on_check_alive()

    def close(self):
        self.world.events.append(("close", self.kwargs["max_batch_size"]))
        self.world.live -= 1
        if self.fail == "close":
            raise InfrastructureError("cleanup")


class World:
    """Shared fake process world: model factory, bounded runner, results."""

    def __init__(self, *, workers_hint=4, item_seconds=0.01, fail_case=None, model_fail=None,
                 outcome_for=None, block_until_cancel=False, timeout_case=None, leave_companions=False,
                 on_check_alive=None):
        self.timeout_case = timeout_case
        self.leave_companions = leave_companions
        self.on_check_alive = on_check_alive
        self.events = []
        self.live = 0
        self.max_live = 0
        self.models = []
        self.running = 0
        self.max_running = 0
        self.lock = threading.Lock()
        self.item_seconds = item_seconds
        self.fail_case = fail_case
        self.model_fail = model_fail
        self.block_until_cancel = block_until_cancel
        self.ran = []
        self.latched = None
        self.models_at_run = []
        self.outcome_for = outcome_for or (
            lambda case: "success" if case.startswith("nominal") else "policy_failure"
        )
        self.set_calls = []
        self.configs = []

    def model_factory(self, **kwargs):
        model = FakeModel(self, kwargs, fail=self.model_fail)
        self.models.append(model)
        return model

    def set_model(self, model):
        self.set_calls.append(model)

    def write_config(self, **kwargs):
        self.configs.append(kwargs)
        kwargs["config_path"].write_text("config", encoding="utf-8")

    def run_item(self, command, *, item_timeout, cancel):
        case = Path(command[-1]).stem
        output = Path(command[-1]).parent.parent / "runs" / case
        with self.lock:
            self.running += 1
            self.max_running = max(self.max_running, self.running)
            self.ran.append(case)
            self.models_at_run.append(self.live)
        companions = []
        if self.leave_companions:
            output.mkdir(parents=True, exist_ok=True)
            for name in ("recording.sqlite", "recording.sqlite-wal", "recording.sqlite-shm"):
                (output / name).write_bytes(b"x")
            companions = [output / "recording.sqlite-wal", output / "recording.sqlite-shm"]
        try:
            if self.block_until_cancel:
                cancel.wait(30)
                raise RunCancelled("cancelled")
            time.sleep(self.item_seconds)
            if cancel.is_set():
                raise RunCancelled("cancelled")
            if case == self.timeout_case:
                self.latched = "evaluator_failed"
                try:
                    raise subprocess.TimeoutExpired(command, 1)
                except subprocess.TimeoutExpired as expired:
                    raise InfrastructureError("evaluator timed out") from expired
            if case == self.fail_case:
                self.latched = "evaluator_failed"
                raise InfrastructureError("evaluator returned nonzero")
            for companion in companions:  # a normal exit checkpoints and removes them
                companion.unlink()
        finally:
            with self.lock:
                self.running -= 1

    def load_result(self, output):
        case = Path(output).name
        return types.SimpleNamespace(outcome=self.outcome_for(case), episode_index=0, steps=9)


class RunPhasesTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.clock_value = [0.0]
        self.remaining_value = [1000.0]

    def run_phases(self, world, phases, *, mode="m3-batch", repeats=2, parity_runner=None, failure=None,
                   progress=None, **overrides):
        kwargs = dict(
            mode=mode, phases=phases, repeats_per_kind=repeats,
            batch_root=self.root / "m3-batch", log_root=self.root / "logs", project_root=self.root,
            model_factory=world.model_factory, set_model=world.set_model, run_item=world.run_item,
            failure=failure or (lambda: world.latched), remaining=lambda: self.remaining_value[0],
            launch_deadline=5000.0, progress=progress or (lambda *_a, **_k: None),
            parity_runner=parity_runner, write_config=world.write_config, load_result=world.load_result,
        )
        kwargs.update(overrides)
        return be.run_phases(**kwargs)

    def test_each_phase_runs_the_whole_manifest_on_a_fresh_server(self) -> None:
        world = World()
        summary = self.run_phases(world, [[4, 1], [4, 4]])
        self.assertTrue(summary["all_phases_complete"])
        self.assertIsNone(summary["stop_reason"])
        self.assertEqual([("start", 1), ("ready", 5000.0), ("close", 1), ("start", 4), ("ready", 5000.0),
                          ("close", 4)], world.events)
        self.assertEqual(1, world.max_live, "the previous server must be gone before the next starts")
        self.assertEqual(8, len(world.ran))
        self.assertEqual({"nominal-01", "nominal-02", "mask-01", "mask-02"}, set(world.ran))
        self.assertTrue(all(live == 1 for live in world.models_at_run), "evaluators ran against a live server")
        self.assertEqual([world.models[0], None, world.models[1], None], world.set_calls)
        first, second = summary["phases"]
        for record, size in ((first, 1), (second, 4)):
            self.assertEqual("complete", record["status"])
            self.assertEqual(4, record["valid_count"])
            self.assertEqual(size, record["max_batch_size"])
            self.assertEqual({"nominal": {"success": 2}, "mask": {"policy_failure": 2}},
                             record["outcomes_by_kind"])
            self.assertEqual([], record["drift_ids"])
            self.assertEqual(manifest_hash(build_manifest(2)), record["manifest_hash"])
            self.assertEqual(3, record["timing"]["calls"])
            self.assertGreater(record["episodes_per_minute"], 0)
        self.assertEqual("compared", summary["comparisons"][0]["status"])

    def test_model_factory_gets_the_phase_options_and_a_per_phase_timing_path(self) -> None:
        world = World()
        self.run_phases(world, [[4, 1], [4, 4]])
        first, second = (m.kwargs for m in world.models)
        self.assertEqual(("faultline", 1), (first["server"], first["max_batch_size"]))
        self.assertEqual(("faultline", 4), (second["server"], second["max_batch_size"]))
        self.assertEqual(self.root / "logs", first["log_root"])
        self.assertEqual(self.root / "m3-batch" / "phase-01-w04-b01" / "server-timing.jsonl",
                         first["timing_log"])
        self.assertEqual(self.root / "m3-batch" / "phase-02-w04-b04" / "server-timing.jsonl",
                         second["timing_log"])

    def test_items_use_the_frozen_manifest_configs(self) -> None:
        world = World()
        self.run_phases(world, [[4, 4]])
        by_case = {c["stage_name"]: c for c in world.configs}
        self.assertEqual({"m3-nominal-01", "m3-nominal-02", "m3-mask-01", "m3-mask-02"}, set(by_case))
        self.assertNotIn("x", by_case["m3-nominal-01"])
        mask = by_case["m3-mask-01"]
        self.assertEqual((0.625, 0.0, 0.375, 0.375), (mask["x"], mask["y"], mask["width"], mask["height"]))
        self.assertEqual((0,), mask["episode_indices"])
        self.assertEqual(self.root, mask["project_root"])

    def test_workers_steal_from_one_queue_and_never_exceed_the_worker_count(self) -> None:
        world = World(item_seconds=0.05)
        self.run_phases(world, [[4, 1]], repeats=6)  # 12 items, 4 workers
        self.assertEqual(12, len(world.ran))
        self.assertEqual(12, len(set(world.ran)))
        self.assertEqual(4, world.max_running)

    def test_summary_file_is_written_and_json_clean(self) -> None:
        world = World()
        self.run_phases(world, [[4, 4]])
        path = self.root / "m3-batch" / be.SUMMARY_NAME
        loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual("m3-batch", loaded["mode"])
        self.assertEqual("complete", loaded["phases"][0]["status"])
        self.assertTrue((self.root / "m3-batch" / "phase-01-w04-b04" / "server-timing.jsonl").is_file())
        self.assertFalse(list((self.root / "m3-batch").glob(".*.tmp")))

    def test_outcome_drift_is_reported_but_the_phase_still_completes(self) -> None:
        world = World(outcome_for=lambda case: "success")
        summary = self.run_phases(world, [[4, 1], [4, 4]])
        self.assertEqual("complete", summary["phases"][0]["status"])
        self.assertEqual(["mask-01", "mask-02"], summary["phases"][0]["drift_ids"])
        self.assertEqual("outcome_drift", summary["verdict"])

    def test_an_item_failure_cancels_the_phase_and_skips_the_rest(self) -> None:
        world = World(fail_case="nominal-02", item_seconds=0.05)
        summary = self.run_phases(world, [[4, 1], [4, 4]])
        first, second = summary["phases"]
        self.assertEqual("incomplete", first["status"])
        self.assertLess(first["valid_count"], 4)
        self.assertEqual("not_run", second["status"])
        self.assertEqual("evaluator_failed", summary["stop_reason"])
        self.assertEqual([("start", 1), ("ready", 5000.0), ("close", 1)], world.events)
        self.assertEqual(1, len(world.models))
        statuses = {item["status"] for item in first["items"]}
        self.assertIn("infrastructure_error", statuses)
        self.assertEqual("incomplete", summary["verdict"])

    def test_invalid_evidence_is_never_counted_as_valid(self) -> None:
        world = World(outcome_for=lambda case: "infrastructure_error")
        summary = self.run_phases(world, [[4, 1]])
        record = summary["phases"][0]
        self.assertEqual(0, record["valid_count"])
        self.assertEqual("incomplete", record["status"])
        self.assertIn("invalid_evidence", {item["status"] for item in record["items"]})
        self.assertEqual("phase_incomplete", summary["stop_reason"])

    def test_server_start_failures_stop_the_experiment_with_safe_codes(self) -> None:
        for fail, code in (("start", "model_start_failed"), ("ready", "readiness_failed"), ("dead", "model_died")):
            with self.subTest(fail=fail):
                world = World(model_fail=fail)
                summary = self.run_phases(world, [[4, 1], [4, 4]])
                self.assertEqual(code, summary["stop_reason"])
                self.assertEqual(["start_failed", "not_run"], [p["status"] for p in summary["phases"]])
                self.assertEqual(code, summary["phases"][0]["stop_reason"])
                self.assertEqual([], world.ran)
                self.assertIn(("close", 1), world.events, "a half-started server must still be closed")
                self.root_cleanup()

    def root_cleanup(self) -> None:
        import shutil

        shutil.rmtree(self.root / "m3-batch", ignore_errors=True)

    def test_model_factory_exception_is_a_start_failure(self) -> None:
        world = World()

        def broken(**_kwargs):
            raise ValueError("bad options")

        summary = self.run_phases(world, [[4, 1]], model_factory=broken)
        self.assertEqual("model_start_failed", summary["stop_reason"])

    def test_close_failure_propagates_and_keeps_the_model_registered(self) -> None:
        world = World(model_fail="close")
        with self.assertRaises(InfrastructureError):
            self.run_phases(world, [[4, 1], [4, 4]])
        self.assertEqual([world.models[0]], world.set_calls)
        self.assertEqual(1, len(world.models), "no further server starts after an unconfirmed cleanup")

    def test_first_phase_needs_the_minimum_window_then_estimates_gate_later_phases(self) -> None:
        world = World()
        self.remaining_value[0] = be.FIRST_PHASE_MINIMUM_SECONDS - 1
        summary = self.run_phases(world, [[4, 1]])
        self.assertEqual("deadline_skipped", summary["phases"][0]["status"])
        self.assertEqual("deadline_exhausted", summary["stop_reason"])
        self.assertEqual([], world.events)

    def test_later_phase_is_skipped_when_the_estimate_does_not_fit(self) -> None:
        def remaining():
            return 400.0 if world.ran else 1000.0

        world = World()
        events = []
        with mock.patch.object(be, "estimate_phase_seconds", side_effect=lambda done, w: 900.0 if done else None):
            summary = self.run_phases(
                world, [[4, 1], [4, 4]], remaining=remaining,
                progress=lambda event, **fields: events.append(event),
            )
        self.assertEqual(["complete", "deadline_skipped"], [p["status"] for p in summary["phases"]])
        self.assertEqual("deadline_exhausted", summary["stop_reason"])
        self.assertEqual([("start", 1), ("ready", 5000.0), ("close", 1)], world.events)
        self.assertIn("batch_phase_skipped", events)
        self.assertFalse(summary["all_phases_complete"])

    def test_a_skipped_phase_does_not_block_a_later_one_that_fits(self) -> None:
        world = World()
        estimates = {4: 900.0, 12: 100.0}
        with mock.patch.object(
            be, "estimate_phase_seconds", side_effect=lambda done, w: estimates[w] if done else None
        ):
            summary = self.run_phases(
                world, [[12, 1], [4, 1], [12, 12]], remaining=lambda: 500.0 if world.ran else 1000.0
            )
        self.assertEqual(["complete", "deadline_skipped", "complete"], [p["status"] for p in summary["phases"]])
        self.assertEqual("deadline_exhausted", summary["stop_reason"])
        self.assertEqual(8, len(world.ran))

    def test_smoke_parity_failure_starts_no_server(self) -> None:
        world = World()
        calls = []

        def parity(**kwargs):
            calls.append(kwargs)
            return {"passed": False, "max_abs_diff": 0.4, "error": None}

        summary = self.run_phases(world, [[4, 4]], mode="m3-batch-smoke", parity_runner=parity)
        self.assertEqual([], world.events)
        self.assertEqual("parity_failed", summary["stop_reason"])
        self.assertEqual("parity_failed", summary["verdict"])
        self.assertEqual(["not_run"], [p["status"] for p in summary["phases"]])
        self.assertEqual(4, calls[0]["max_batch_size"])
        self.assertEqual(self.root / "m3-batch" / "parity.json", calls[0]["output"])
        self.assertLessEqual(calls[0]["timeout_seconds"], be.PARITY_CAP_SECONDS)

    def test_smoke_parity_pass_then_runs_the_batched_phase(self) -> None:
        world = World()
        summary = self.run_phases(
            world, [[4, 4]], mode="m3-batch-smoke",
            parity_runner=lambda **_kwargs: {"passed": True, "max_abs_diff": 0.01},
        )
        self.assertEqual({"passed": True, "max_abs_diff": 0.01}, summary["parity"])
        self.assertTrue(summary["smoke"]["passed"])
        self.assertEqual([("start", 4), ("ready", 5000.0), ("close", 4)], world.events)

    def test_smoke_parity_infrastructure_error_is_distinct_from_a_failed_check(self) -> None:
        world = World()

        def crashed(**_kwargs):
            raise InfrastructureError("parity check crashed")

        summary = self.run_phases(world, [[4, 4]], mode="m3-batch-smoke", parity_runner=crashed)
        self.assertEqual("parity_error", summary["stop_reason"])
        self.assertEqual([], world.events)

    def test_smoke_without_a_parity_runner_fails_closed(self) -> None:
        world = World()
        summary = self.run_phases(world, [[4, 4]], mode="m3-batch-smoke")
        self.assertEqual("parity_error", summary["stop_reason"])
        self.assertEqual([], world.events)

    def test_measurement_mode_never_runs_parity(self) -> None:
        world = World()
        calls = []
        self.run_phases(world, [[4, 1]], parity_runner=lambda **k: calls.append(k) or {"passed": True})
        self.assertEqual([], calls)

    def test_keyboard_interrupt_cancels_workers_and_closes_the_server(self) -> None:
        world = World(block_until_cancel=True)
        timer = threading.Timer(0.3, _thread.interrupt_main)
        timer.start()
        try:
            with self.assertRaises(KeyboardInterrupt):
                self.run_phases(world, [[4, 1], [4, 4]])
        finally:
            timer.cancel()
        self.assertEqual(0, world.running, "every worker must have stopped")
        self.assertEqual(0, world.live)
        self.assertEqual([("start", 1), ("ready", 5000.0), ("close", 1)], world.events)

    # -- killed evaluators must not poison the export -------------------------------

    def export_batch_tree(self):
        destination = self.root / "export" / "batch"
        destination.parent.mkdir(exist_ok=True)
        return export_closed_evidence(
            self.root / "m3-batch", destination, status="partial", cleanup_confirmed=True
        )

    def test_exporter_rejects_leftover_sqlite_companions(self) -> None:
        batch = self.root / "m3-batch" / "phase-01-w04-b01" / "runs" / "mask-01"
        batch.mkdir(parents=True)
        (batch / "recording.sqlite-wal").write_bytes(b"x")
        with self.assertRaisesRegex(JobRuntimeError, "SQLite companion"):
            self.export_batch_tree()
        self.assertEqual(1, be.purge_sqlite_companions(self.root / "m3-batch"))
        self.export_batch_tree()

    def test_timed_out_and_cancelled_items_lose_their_run_dirs_and_the_export_succeeds(self) -> None:
        world = World(timeout_case="nominal-01", leave_companions=True, item_seconds=0.05)
        summary = self.run_phases(world, [[4, 1]])
        record = summary["phases"][0]
        by_status = {}
        for item in record["items"]:
            by_status.setdefault(item["status"], []).append(item)
        self.assertEqual(["nominal-01"], [i["case_id"] for i in by_status["timed_out"]])
        self.assertTrue(by_status["timed_out"][0]["run_dir_removed"])
        for item in by_status.get("cancelled", []):
            self.assertTrue(item["run_dir_removed"])
        runs = self.root / "m3-batch" / "phase-01-w04-b01" / "runs"
        self.assertFalse((runs / "nominal-01").exists())
        self.assertFalse(list((self.root / "m3-batch").rglob("*.sqlite-*")))
        self.export_batch_tree()
        self.assertEqual("evaluator_failed", summary["stop_reason"])

    def test_stray_companions_in_kept_items_are_purged_and_counted(self) -> None:
        world = World(fail_case="mask-02", leave_companions=True, item_seconds=0.02)

        original = world.run_item

        def leaky(command, *, item_timeout, cancel):
            case = Path(command[-1]).stem
            try:
                return original(command, item_timeout=item_timeout, cancel=cancel)
            finally:
                # a failed (not killed) item keeps its directory, with a stray companion
                output = Path(command[-1]).parent.parent / "runs" / case
                if case == "mask-02":
                    (output / "left.sqlite-wal").write_bytes(b"x")

        world.run_item = leaky
        summary = self.run_phases(world, [[4, 1]])
        self.assertGreaterEqual(summary["sqlite_companions_removed"], 1)
        self.assertFalse(list((self.root / "m3-batch").rglob("*.sqlite-*")))
        self.export_batch_tree()

    def test_interrupt_also_scrubs_before_anything_can_be_exported(self) -> None:
        world = World(block_until_cancel=True, leave_companions=True)
        timer = threading.Timer(0.3, _thread.interrupt_main)
        timer.start()
        try:
            with self.assertRaises(KeyboardInterrupt):
                self.run_phases(world, [[4, 1]])
        finally:
            timer.cancel()
        self.assertFalse(list((self.root / "m3-batch").rglob("*.sqlite-*")))
        self.export_batch_tree()

    def test_remove_tree_within_refuses_paths_outside_the_root_and_links(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        inside = self.root / "tree"
        inside.mkdir()
        self.assertFalse(be.remove_tree_within(outside, inside))
        self.assertTrue(outside.exists())
        self.assertTrue(be.remove_tree_within(inside / "missing", inside))
        (inside / "gone").mkdir()
        (inside / "gone" / "f").write_text("x", encoding="utf-8")
        self.assertTrue(be.remove_tree_within(inside / "gone", inside))
        self.assertFalse((inside / "gone").exists())

    # -- item starts respect the Job deadline ----------------------------------------

    def test_no_item_starts_when_less_than_one_item_timeout_remains(self) -> None:
        world = World()
        self.remaining_value[0] = be.ITEM_TIMEOUT_SECONDS - 1  # above the first-phase minimum
        self.assertGreaterEqual(self.remaining_value[0], be.FIRST_PHASE_MINIMUM_SECONDS)
        summary = self.run_phases(world, [[4, 1]])
        self.assertEqual([], world.ran)
        self.assertTrue(summary["phases"][0]["deadline_stopped"])
        self.assertEqual("deadline_exhausted", summary["stop_reason"])
        self.assertEqual("incomplete", summary["phases"][0]["status"])

    def test_item_started_with_enough_time_but_timed_out_is_timed_out_not_deadline(self) -> None:
        world = World(timeout_case="mask-01")
        summary = self.run_phases(world, [[4, 1]])
        statuses = {i["case_id"]: i["status"] for i in summary["phases"][0]["items"]}
        self.assertEqual("timed_out", statuses["mask-01"])

    # -- prefetch is separate from the phases -----------------------------------------

    def test_prefetch_runs_once_before_parity_and_phases_and_is_timed_separately(self) -> None:
        world = World()
        order = []
        state = {"t": 0.0}

        def prefetch():
            order.append("prefetch")
            state["t"] += 900.0

        def parity(**kwargs):
            order.append("parity")
            kwargs_seen.append(kwargs)
            return {"passed": True}

        kwargs_seen = []
        summary = self.run_phases(
            world, [[4, 4]], mode="m3-batch-smoke", parity_runner=parity, prefetch=prefetch,
            clock=lambda: state["t"], remaining=lambda: 1000.0 - state["t"],
        )
        self.assertEqual(["prefetch", "parity"], order)
        self.assertEqual(900.0, summary["prefetch_seconds"])
        self.assertEqual(100.0, kwargs_seen[0]["timeout_seconds"], "parity budget is taken after prefetch")

    def test_a_long_prefetch_no_longer_makes_the_last_phase_skip(self) -> None:
        world = World()
        state = {"t": 0.0}

        def prefetch():
            state["t"] += 800.0

        def tick():
            state["t"] += 20.0  # every phase reads the clock a few times: ~100 s per phase
            return state["t"]

        summary = self.run_phases(
            world, [[4, 1], [4, 4]], prefetch=prefetch, clock=tick,
            remaining=lambda: 1500.0 - state["t"],
        )
        self.assertGreaterEqual(summary["prefetch_seconds"], 800.0)
        self.assertEqual(["complete", "complete"], [p["status"] for p in summary["phases"]])
        for phase in summary["phases"]:
            self.assertLess(phase["total_seconds"], 400.0)

    def test_prefetch_failure_is_not_a_model_start_failure(self) -> None:
        world = World()
        calls = []

        def broken():
            raise subprocess.TimeoutExpired("prefetch", 1)

        summary = self.run_phases(
            world, [[4, 4]], mode="m3-batch-smoke", prefetch=broken,
            parity_runner=lambda **k: calls.append(k) or {"passed": True},
        )
        self.assertEqual("prefetch_failed", summary["stop_reason"])
        self.assertEqual([], world.models)
        self.assertEqual([], calls)
        self.assertEqual(["not_run"], [p["status"] for p in summary["phases"]])

    # -- parity always leaves a verdict -----------------------------------------------

    def test_parity_crash_timeout_and_unconfirmed_cleanup_still_write_both_files(self) -> None:
        for error, code, cleanup in (
            (subprocess.TimeoutExpired("parity", 1), "exception", False),
            (InfrastructureError("parity check timed out"), "infrastructure_error", False),
            (CleanupUnconfirmed("group"), "cleanup_unconfirmed", True),
        ):
            with self.subTest(error=type(error).__name__):
                self.root_cleanup()

                def crashed(**_kwargs):
                    raise error

                world = World()
                summary = self.run_phases(world, [[4, 4]], mode="m3-batch-smoke", parity_runner=crashed)
                verdict = json.loads((self.root / "m3-batch" / "parity.json").read_text(encoding="utf-8"))
                self.assertFalse(verdict["passed"])
                self.assertEqual(code, verdict["error_code"])
                self.assertTrue((self.root / "m3-batch" / be.SUMMARY_NAME).is_file())
                self.assertEqual(cleanup, summary["cleanup_unconfirmed"])
                self.assertEqual("cleanup_unconfirmed" if cleanup else "parity_error", summary["stop_reason"])
                self.assertEqual([], world.models)

    def test_a_runner_that_wrote_no_file_still_gets_a_verdict_file(self) -> None:
        world = World()
        self.run_phases(world, [[4, 4]], mode="m3-batch-smoke", parity_runner=lambda **k: {"passed": True})
        self.assertTrue((self.root / "m3-batch" / "parity.json").is_file())

    # -- memory and per-phase argv ------------------------------------------------------

    def test_phase_records_memory_snapshots_argv_and_progress_carries_them(self) -> None:
        world = World()
        events = []
        summary = self.run_phases(
            world, [[4, 1], [4, 4]],
            snapshot=lambda: {"mem_available_mb": 512.0, "gpu_used_mb": 7.0},
            progress=lambda event, **fields: events.append((event, fields)),
        )
        first, second = summary["phases"]
        self.assertEqual({"mem_available_mb": 512.0, "gpu_used_mb": 7.0}, first["memory_start"])
        self.assertEqual({"mem_available_mb": 512.0, "gpu_used_mb": 7.0}, first["memory_end"])
        self.assertEqual(["server.py", "--args.max_batch_size=1"], first["server_argv"])
        self.assertEqual(["server.py", "--args.max_batch_size=4"], second["server_argv"])
        starts = [fields for event, fields in events if event == "batch_phase_start"]
        self.assertTrue(all("mem_available_mb" in fields for fields in starts))
        done = [fields for event, fields in events if event == "batch_phase_done"]
        self.assertTrue(all("gpu_used_mb" in fields for fields in done))

    def test_memory_snapshot_parses_meminfo_and_tolerates_missing_sources(self) -> None:
        meminfo = self.root / "meminfo"
        meminfo.write_text("MemTotal: 100 kB\nMemAvailable:   2097152 kB\n", encoding="utf-8")

        def smi(argv, **kwargs):
            return types.SimpleNamespace(returncode=0, stdout="1234, 46068\n")

        snap = be.memory_snapshot(str(meminfo), smi)
        self.assertEqual({"mem_available_mb": 2048.0, "gpu_used_mb": 1234.0, "gpu_total_mb": 46068.0}, snap)

        def absent(argv, **kwargs):
            raise FileNotFoundError("nvidia-smi")

        none = be.memory_snapshot(str(self.root / "missing"), absent)
        self.assertEqual({"mem_available_mb": None, "gpu_used_mb": None, "gpu_total_mb": None}, none)

        def failing(argv, **kwargs):
            return types.SimpleNamespace(returncode=9, stdout="")

        self.assertIsNone(be.memory_snapshot(str(meminfo), failing)["gpu_used_mb"])

        def garbled(argv, **kwargs):
            return types.SimpleNamespace(returncode=0, stdout="garbage")

        self.assertIsNone(be.memory_snapshot(str(meminfo), garbled)["gpu_used_mb"])

    def test_progress_events_report_phase_lifecycle_and_summary(self) -> None:
        world = World()
        events = []
        self.run_phases(world, [[4, 1], [4, 4]], progress=lambda event, **fields: events.append(event))
        self.assertEqual(
            ["batch_phase_start", "batch_phase_done", "batch_phase_start", "batch_phase_done", "batch_summary"],
            events,
        )


if __name__ == "__main__":
    unittest.main()
