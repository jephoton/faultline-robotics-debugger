"""Workload configuration and Job preparation for the M6 modes (ADR 0026)."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from robot_debug import job_entry
from robot_debug.job_runtime import BATCH_MODES, JobRuntimeError, M6_MODES, validate_workload_config

ROOT = Path(__file__).resolve().parents[1]

SMOKE = {"schema_version": 1, "mode": "m6-smoke", "run_id": "m6-smoke-1", "deadline_seconds": 1080}
THRESHOLD = {
    "schema_version": 1,
    "mode": "m6-threshold",
    "run_id": "m6-threshold-1",
    "deadline_seconds": 1800,
    "families": ["darken", "noise", "blur", "contrast"],
    "sweep": [0.2, 0.4, 0.6, 0.8, 1.0],
    "attempts": 5,
    "required_failures": 4,
    "bisection_steps": 4,
}


def copy(base, **changes):
    config = json.loads(json.dumps(base))
    config.update(changes)
    return config


class M6ConfigTests(unittest.TestCase):
    def test_both_modes_are_new_and_not_m3_batch_modes(self):
        self.assertEqual({"m6-smoke", "m6-threshold"}, set(M6_MODES))
        self.assertFalse(set(M6_MODES) & set(BATCH_MODES))

    def test_valid_configs_round_trip_as_fresh_json(self):
        for config in (SMOKE, THRESHOLD):
            with self.subTest(mode=config["mode"]):
                result = validate_workload_config(config)
                self.assertEqual(config, result)
                self.assertEqual(result, json.loads(json.dumps(result)))
        result = validate_workload_config(THRESHOLD)
        self.assertIsNot(THRESHOLD["sweep"], result["sweep"])
        self.assertIsNot(THRESHOLD["families"], result["families"])

    def test_integer_one_in_the_sweep_is_accepted_and_normalised(self):
        result = validate_workload_config(copy(THRESHOLD, sweep=[0.5, 1]))
        self.assertEqual([0.5, 1.0], result["sweep"])
        self.assertIsInstance(result["sweep"][1], float)

    def test_smoke_takes_no_mode_specific_fields(self):
        for extra in ("families", "sweep", "attempts", "phases", "repeats_per_kind", "private"):
            with self.subTest(extra=extra), self.assertRaises(JobRuntimeError):
                validate_workload_config(dict(SMOKE, **{extra: 1}))

    def test_threshold_requires_exactly_its_fields(self):
        for missing in ("families", "sweep", "attempts", "required_failures", "bisection_steps"):
            config = copy(THRESHOLD)
            del config[missing]
            with self.subTest(missing=missing), self.assertRaises(JobRuntimeError):
                validate_workload_config(config)
        for extra in ("phases", "repeats_per_kind", "private"):
            with self.subTest(extra=extra), self.assertRaises(JobRuntimeError):
                validate_workload_config(dict(THRESHOLD, **{extra: 1}))

    def test_other_modes_still_reject_m6_fields(self):
        for mode in ("pilot", "m3-batch-smoke"):
            with self.subTest(mode=mode), self.assertRaises(JobRuntimeError):
                validate_workload_config(dict(copy(SMOKE, mode=mode), families=["darken"]))

    def test_family_lists_are_bounded_known_and_unique(self):
        bad = ([], ["sepia"], ["darken", "darken"], ["darken", "noise", "blur", "contrast", "darken"],
               "darken", None, [None], [["darken"]], ["Darken"])
        for families in bad:
            with self.subTest(families=families), self.assertRaises(JobRuntimeError):
                validate_workload_config(copy(THRESHOLD, families=families))
        validate_workload_config(copy(THRESHOLD, families=["blur"]))
        validate_workload_config(copy(THRESHOLD, families=["contrast", "darken"]))

    def test_sweeps_are_bounded_increasing_severities(self):
        bad = ([], [0.0, 0.5], [0.5, 0.2], [0.2, 0.2], [1.2], [-0.1], [float("nan")], [float("inf")],
               [True], ["0.5"], None, 0.5, [0.1234567],
               [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
        for sweep in bad:
            with self.subTest(sweep=sweep), self.assertRaises(JobRuntimeError):
                validate_workload_config(copy(THRESHOLD, sweep=sweep))
        validate_workload_config(copy(THRESHOLD, sweep=[0.0125, 0.5]))

    def test_gate_and_depth_are_bounded_integers(self):
        bad = (
            dict(attempts=0), dict(attempts=13), dict(attempts=5.0), dict(attempts=True), dict(attempts="5"),
            dict(required_failures=0), dict(required_failures=6), dict(required_failures=True),
            dict(required_failures=4.0),
            dict(bisection_steps=-1), dict(bisection_steps=7), dict(bisection_steps=4.0),
            dict(bisection_steps=True),
        )
        for changes in bad:
            with self.subTest(changes=changes), self.assertRaises(JobRuntimeError):
                validate_workload_config(copy(THRESHOLD, **changes))
        validate_workload_config(copy(THRESHOLD, attempts=3, required_failures=2, bisection_steps=0))

    def test_total_episode_bound(self):
        # 4 families x (8 sweep + 6 bisection) x 12 attempts is far above the bound.
        with self.assertRaises(JobRuntimeError):
            validate_workload_config(copy(
                THRESHOLD, sweep=[0.1 * i for i in range(1, 9)], attempts=12, required_failures=10,
                bisection_steps=6))
        # The planned workload is 5 controls + 4 x 9 levels x 5 attempts = 185.
        validate_workload_config(THRESHOLD)

    def test_deadline_rules_still_apply(self):
        for config in (SMOKE, THRESHOLD):
            for deadline in (0, 3001, True, float("nan")):
                with self.subTest(mode=config["mode"], deadline=deadline), self.assertRaises(JobRuntimeError):
                    validate_workload_config(copy(config, deadline_seconds=deadline))

    def test_the_audit_target_fields_are_optional_and_round_trip(self):
        # Absent: the configuration is exactly what recorded evidence used.
        self.assertEqual(THRESHOLD, validate_workload_config(THRESHOLD))
        target = copy(THRESHOLD, suite="libero_10", task_id=3, init_state_index=14)
        result = validate_workload_config(target)
        self.assertEqual(target, result)
        self.assertEqual(result, json.loads(json.dumps(result)))
        for changes in ({"suite": "libero_10"}, {"task_id": 9}, {"init_state_index": 0},
                        {"suite": "libero_object", "task_id": 0, "init_state_index": 49}):
            with self.subTest(changes=changes):
                self.assertEqual(copy(THRESHOLD, **changes),
                                 validate_workload_config(copy(THRESHOLD, **changes)))

    def test_the_audit_target_fields_are_bounded(self):
        bad = (dict(suite="libero_goal"), dict(suite=None), dict(suite=3), dict(task_id=-1),
               dict(task_id=10), dict(task_id=True), dict(task_id=1.0), dict(task_id="0"),
               dict(init_state_index=-1), dict(init_state_index=50), dict(init_state_index=True),
               dict(init_state_index=2.0), dict(init_state_index=None))
        for changes in bad:
            with self.subTest(changes=changes), self.assertRaises(JobRuntimeError):
                validate_workload_config(copy(THRESHOLD, **changes))

    def test_only_the_threshold_mode_takes_an_audit_target(self):
        for extra in ({"suite": "libero_10"}, {"task_id": 1}, {"init_state_index": 2}):
            with self.subTest(extra=extra), self.assertRaises(JobRuntimeError):
                validate_workload_config(dict(SMOKE, **extra))

    def test_load_workload_reads_m6_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            for config in (SMOKE, THRESHOLD):
                path = Path(temporary) / "workload.json"
                path.write_text(json.dumps(config), encoding="utf-8")
                self.assertEqual(config, job_entry.load_workload(path))


class PrepareM6Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "prepare_serverless_job_m6", ROOT / "scripts" / "prepare_serverless_job.py")
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.module
        spec.loader.exec_module(cls.module)

    def prepare(self, workload):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            os.chdir(temporary)
            try:
                Path("workload.json").write_text(json.dumps(workload), encoding="utf-8")
                return self.module.prepare({
                    "run_id": workload["run_id"],
                    "project_id": "project-example123",
                    "image": "registry.example/robot-debug@sha256:" + "a" * 64,
                    "platform": "gpu-l40s-a",
                    "preset": "1gpu-16vcpu-64gb",
                    "subnet_id": "vpcsubnet-example123",
                    "bucket_id": "storagebucket-example123",
                    "hf_secret": "mbsec-example123@mbsecver-version123",
                    "workload_file": "workload.json",
                })
            finally:
                os.chdir(previous)

    def test_the_batch_deadline_guard_covers_both_m6_modes(self):
        for base in (SMOKE, THRESHOLD):
            with self.subTest(mode=base["mode"]):
                with self.assertRaisesRegex(self.module.ConfigError, "deadline"):
                    self.prepare(dict(base, deadline_seconds=690))
                with self.assertRaisesRegex(self.module.ConfigError, "deadline"):
                    self.prepare(dict(base, deadline_seconds=999))
                self.assertIn("--dry-run", self.prepare(dict(base, deadline_seconds=1000)))

    def test_the_guard_constant_is_shared_by_every_batch_style_mode(self):
        self.assertEqual(1000, self.module.MIN_BATCH_DEADLINE_SECONDS)
        for mode in ("m3-batch", "m3-batch-smoke", "m6-smoke", "m6-threshold"):
            self.assertIn(mode, self.module._BATCH_MODES)


if __name__ == "__main__":
    unittest.main()
