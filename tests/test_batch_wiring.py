"""Runtime wiring for the M3 batched-inference experiment (server variants, config)."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from robot_debug import job_entry
from robot_debug.job_entry import ImageLayout, ProductionModelFactory, model_server_argv
from robot_debug.job_model import ModelProcess
from robot_debug.job_runtime import JobRuntimeError, validate_workload_config


ROOT = Path(__file__).resolve().parents[1]

SMOKE = {
    "schema_version": 1,
    "mode": "m3-batch-smoke",
    "run_id": "m3-batch-smoke-1",
    "deadline_seconds": 1080,
    "repeats_per_kind": 2,
    "phases": [[4, 4]],
}
MEASUREMENT = {
    "schema_version": 1,
    "mode": "m3-batch",
    "run_id": "m3-batch-measure-1",
    "deadline_seconds": 1920,
    "repeats_per_kind": 12,
    "phases": [[8, 1], [8, 8], [12, 1], [12, 12], [4, 1]],
}

HISTORICAL_FLAGS = [
    "--port=8000",
    "--args.device=cuda",
    "--args.policy_type=groot",
    "--args.checkpoint=nvidia/gr00t17-lerobot-libero_object-640",
    "--args.state_key=observation.state",
    "--args.chunk_size=null",
    '--args.image_keys={"agentview":"observation.images.image","wrist":"observation.images.wrist_image"}',
    '--args.policy_kwargs={"base_model_path":"nvidia/GR00T-N1.7-3B"}',
]


class ArgvTests(unittest.TestCase):
    def test_default_argv_is_byte_identical_to_the_historical_invocation(self) -> None:
        self.assertEqual(
            [
                "/opt/model-env/bin/python",
                "/opt/upstream/src/vla_eval/model_servers/lerobot.py",
                *HISTORICAL_FLAGS,
            ],
            model_server_argv(ImageLayout()),
        )
        self.assertEqual(model_server_argv(ImageLayout()), model_server_argv(ImageLayout(), server="upstream"))
        self.assertEqual(
            model_server_argv(ImageLayout(), 8001)[2], "--port=8001"
        )

    def test_batched_faultline_argv_adds_only_the_batch_and_timing_flags(self) -> None:
        timing = Path("/tmp/faultline-work/run/m3-batch/phase-02/server-timing.jsonl")
        argv = model_server_argv(ImageLayout(), server="faultline", max_batch_size=8, timing_log=timing)
        self.assertEqual(
            [
                "/opt/model-env/bin/python",
                "/opt/robot-debug/scripts/model_servers/faultline_groot_server.py",
                *HISTORICAL_FLAGS,
                "--args.max_batch_size=8",
                "--args.timing_log=/tmp/faultline-work/run/m3-batch/phase-02/server-timing.jsonl",
            ],
            argv,
        )

    def test_unbatched_faultline_phase_states_batch_size_one_explicitly(self) -> None:
        argv = model_server_argv(ImageLayout(), server="faultline")
        self.assertEqual("--args.max_batch_size=1", argv[-1])
        self.assertFalse(any(item.startswith("--args.timing_log") for item in argv))

    def test_invalid_variants_and_options_are_rejected(self) -> None:
        layout = ImageLayout()
        bad_calls = (
            dict(server="other"),
            dict(server="faultline", max_batch_size=0),
            dict(server="faultline", max_batch_size=True),
            dict(server="faultline", max_batch_size=65),
            dict(server="upstream", max_batch_size=4),
            dict(server="upstream", timing_log=Path("/tmp/x.jsonl")),
            dict(server="faultline", timing_log=Path("relative.jsonl")),
            dict(server="faultline", timing_log=Path("/tmp/with space.jsonl")),
        )
        for kwargs in bad_calls:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                model_server_argv(layout, **kwargs)

    def test_flags_for_scripts_omit_interpreter_script_and_port(self) -> None:
        flags = job_entry.model_flags_for_scripts(ImageLayout(), max_batch_size=4)
        self.assertEqual([*HISTORICAL_FLAGS[1:], "--args.max_batch_size=4"], flags)

    def test_model_script_lives_where_the_image_copies_scripts(self) -> None:
        script = job_entry.faultline_server_script(ImageLayout())
        self.assertEqual("/opt/robot-debug/scripts/model_servers/faultline_groot_server.py", script.as_posix())
        self.assertTrue((ROOT / "scripts" / "model_servers" / "faultline_groot_server.py").is_file())
        self.assertIn("COPY scripts /opt/robot-debug/scripts", (ROOT / "deploy/serverless/Dockerfile").read_text())


def _layout(root: Path) -> ImageLayout:
    for name in ("project", "upstream", "work", "hf", "export"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return ImageLayout(
        project_root=root / "project",
        upstream_root=root / "upstream",
        simulator_source=root / "simulator-src",
        model_python=Path(sys.executable),
        evaluator=root / "vla-eval",
        work_root=root / "work",
        hf_home=root / "hf",
        export_root=root / "export",
    )


class FactoryTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.layout = _layout(self.root)
        self.run_root = self.layout.work_root / "run"
        (self.run_root / "logs").mkdir(parents=True)
        self.prefetches = []

        def fake_prefetch(layout, **kwargs):
            self.prefetches.append(kwargs)
            return {"repositories": {"a": "b"}}

        patcher = mock.patch.object(job_entry, "prefetch_models", side_effect=fake_prefetch)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.events = []
        self.factory = ProductionModelFactory(
            self.layout,
            base_env={"HF_TOKEN": "hf_value"},
            deadline=10_000.0,
            clock=lambda: 0.0,
            progress=lambda event, **fields: self.events.append(event),
        )

    def test_prefetch_runs_once_and_later_starts_reuse_it(self) -> None:
        log_root = self.run_root / "logs"
        first = self.factory(log_root=log_root, server="faultline", max_batch_size=4,
                             timing_log=Path("/tmp/a.jsonl"))
        second = self.factory(log_root=log_root, server="faultline", max_batch_size=1,
                              timing_log=Path("/tmp/b.jsonl"))
        self.assertEqual(1, len(self.prefetches))
        self.assertEqual(["prefetch_start", "prefetch_done"], self.events)
        self.assertIsInstance(first, ModelProcess)
        self.assertIsInstance(second, ModelProcess)
        self.assertIn("--args.max_batch_size=4", first._argv)
        self.assertIn("--args.max_batch_size=1", second._argv)
        self.assertIn("--args.timing_log=/tmp/b.jsonl", second._argv)
        self.assertIsNone(first._process)

    def test_provenance_records_the_first_server_variant_and_no_secret(self) -> None:
        self.factory(log_root=self.run_root / "logs", server="faultline", max_batch_size=8)
        provenance = (self.run_root / "provenance.json").read_text(encoding="utf-8")
        loaded = json.loads(provenance)
        self.assertIn("scripts/model_servers/faultline_groot_server.py", loaded["model_server_argv"][0])
        self.assertIn("--args.max_batch_size=8", loaded["model_server_argv"])
        self.assertNotIn("hf_value", provenance)

    def test_default_call_still_describes_the_upstream_server(self) -> None:
        model = self.factory(log_root=self.run_root / "logs")
        self.assertEqual(model_server_argv(self.layout), list(model._argv))
        loaded = json.loads((self.run_root / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(model_server_argv(self.layout)[1:], loaded["model_server_argv"])

    def test_invalid_options_fail_before_any_prefetch(self) -> None:
        with self.assertRaises(ValueError):
            self.factory(log_root=self.run_root / "logs", server="faultline", max_batch_size=0)
        self.assertEqual([], self.prefetches)
        self.assertFalse((self.run_root / "provenance.json").exists())

    def test_each_start_gets_a_model_only_environment(self) -> None:
        model = self.factory(log_root=self.run_root / "logs", server="faultline")
        self.assertNotIn("HF_TOKEN", model._env)
        self.assertEqual("1", model._env["HF_HUB_OFFLINE"])


class BatchConfigTests(unittest.TestCase):
    def copy(self, base, **changes):
        config = json.loads(json.dumps(base))
        config.update(changes)
        return config

    def test_smoke_and_measurement_workloads_validate_and_round_trip(self) -> None:
        for config in (SMOKE, MEASUREMENT):
            with self.subTest(mode=config["mode"]):
                result = validate_workload_config(config)
                self.assertEqual(config, result)
                self.assertIsNot(config["phases"], result["phases"])
                self.assertEqual(result, json.loads(json.dumps(result)))

    def test_other_modes_still_reject_batch_fields(self) -> None:
        config = {"schema_version": 1, "mode": "pilot", "run_id": "a", "deadline_seconds": 60}
        validate_workload_config(config)
        for extra in ({"phases": [[4, 4]]}, {"repeats_per_kind": 2}):
            with self.assertRaises(JobRuntimeError):
                validate_workload_config(dict(config, **extra))

    def test_batch_modes_require_exactly_the_batch_fields(self) -> None:
        for missing in ("phases", "repeats_per_kind"):
            config = self.copy(SMOKE)
            del config[missing]
            with self.subTest(missing=missing), self.assertRaises(JobRuntimeError):
                validate_workload_config(config)
        with self.assertRaises(JobRuntimeError):
            validate_workload_config(dict(self.copy(SMOKE), private="x"))

    def test_repeats_are_frozen_per_mode(self) -> None:
        for mode, repeats in (("m3-batch-smoke", 12), ("m3-batch", 2), ("m3-batch", 8), ("m3-batch-smoke", 0)):
            with self.subTest(mode=mode, repeats=repeats), self.assertRaises(JobRuntimeError):
                validate_workload_config(self.copy(SMOKE, mode=mode, repeats_per_kind=repeats))
        for value in (True, 2.0, "2", None):
            with self.subTest(value=value), self.assertRaises(JobRuntimeError):
                validate_workload_config(self.copy(SMOKE, repeats_per_kind=value))

    def test_phase_pairs_are_restricted(self) -> None:
        rejected = (
            [],
            [[4, 4]] * 2,
            [[4]],
            [[4, 4, 1]],
            [[2, 2]],
            [[16, 16]],
            [[8, 4]],
            [[4, 2]],
            [[4, 0]],
            [[True, 1]],
            [[4.0, 4]],
            [[4, "4"]],
            [(4, 4)],
            "4,4",
            None,
            [[4, 1], [4, 4], [8, 1], [8, 8], [12, 1], [12, 12], [4, 1]],
        )
        for phases in rejected:
            with self.subTest(phases=phases), self.assertRaises(JobRuntimeError):
                validate_workload_config(self.copy(MEASUREMENT, phases=phases))

    def test_workers_cannot_exceed_the_manifest(self) -> None:
        with self.assertRaises(JobRuntimeError):
            validate_workload_config(self.copy(SMOKE, phases=[[8, 8]]))

    def test_accepted_pairs_cover_the_planned_phases(self) -> None:
        for workers in (4, 8, 12):
            for batch in (1, workers):
                validate_workload_config(self.copy(MEASUREMENT, phases=[[workers, batch]]))

    def test_deadline_rules_still_apply(self) -> None:
        for deadline in (0, 3001, True, float("nan")):
            with self.subTest(deadline=deadline), self.assertRaises(JobRuntimeError):
                validate_workload_config(self.copy(MEASUREMENT, deadline_seconds=deadline))

    def test_unhashable_mode_is_a_rejection_not_a_crash(self) -> None:
        with self.assertRaises(JobRuntimeError):
            validate_workload_config({"schema_version": 1, "mode": ["m3-batch"], "run_id": "a", "deadline_seconds": 1})

    def test_load_workload_reads_a_batch_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "workload.json"
            path.write_text(json.dumps(MEASUREMENT), encoding="utf-8")
            self.assertEqual(MEASUREMENT, job_entry.load_workload(path))


class PrepareJobTests(unittest.TestCase):
    """The prepare script is mode-agnostic: it only bounds and injects the workload file."""

    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("prepare_serverless_job_batch", ROOT / "scripts" / "prepare_serverless_job.py")
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.module
        spec.loader.exec_module(cls.module)

    def test_batch_workload_files_are_prepared_like_any_other(self) -> None:
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            os.chdir(temporary)
            try:
                for name, workload in (("smoke.json", SMOKE), ("measure.json", MEASUREMENT)):
                    Path(name).write_text(json.dumps(workload), encoding="utf-8")
                    argv = self.module.prepare({
                        "run_id": workload["run_id"],
                        "project_id": "project-example123",
                        "image": "registry.example/robot-debug@sha256:" + "a" * 64,
                        "platform": "gpu-l40s-a",
                        "preset": "1gpu-16vcpu-64gb",
                        "subnet_id": "vpcsubnet-example123",
                        "bucket_id": "storagebucket-example123",
                        "hf_secret": "mbsec-example123@mbsecver-version123",
                        "workload_file": name,
                    })
                    self.assertIn(name + ":/etc/faultline/workload.json", argv)
                    self.assertIn("--dry-run", argv)
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
