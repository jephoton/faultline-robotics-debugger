"""Tests for the prepare-only Nebius AI Job configuration builder."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import importlib.util
import os
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "prepare_serverless_job.py"


class ServerlessJobConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("prepare_serverless_job", SCRIPT)
        assert spec is not None and spec.loader is not None
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.module
        spec.loader.exec_module(cls.module)

    def test_prepare_script_exists(self) -> None:
        self.assertTrue(SCRIPT.is_file())

    def test_prepare_function_exists(self) -> None:
        self.assertTrue(callable(getattr(self.module, "prepare", None)))

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.previous_directory = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.previous_directory)
        Path("workload.json").write_text(
            json.dumps({"mode": "pilot", "episodes": 1}), encoding="utf-8"
        )

    def valid_config(self, **overrides: object) -> dict[str, object]:
        config: dict[str, object] = {
            "run_id": "faultline-pilot-001",
            "project_id": "project-example123",
            "image": "registry.example/robot-debug@sha256:" + "a" * 64,
            "platform": "gpu-l40s-a",
            "preset": "1gpu-16vcpu-64gb",
            "subnet_id": "vpcsubnet-example123",
            "bucket_id": "storagebucket-example123",
            "hf_secret": "mbsec-example123@mbsecver-version123",
            "workload_file": "workload.json",
        }
        config.update(overrides)
        return config

    def test_valid_config_builds_exact_bounded_dry_run_argv(self) -> None:
        argv = self.module.prepare(self.valid_config())
        self.assertEqual(argv, [
            "nebius", "ai", "job", "create",
            "--parent-id", "project-example123",
            "--name", "faultline-pilot-001",
            "--image", "registry.example/robot-debug@sha256:" + "a" * 64,
            "--platform", "gpu-l40s-a",
            "--preset", "1gpu-16vcpu-64gb",
            "--subnet-id", "vpcsubnet-example123",
            "--disk-size", "150Gi",
            "--shm-size", "16Gi",
            "--timeout", "1h",
            "--restart-policy", "never",
            "--volume", "storagebucket-example123:/persistent:rw",
            "--env-secret", "HF_TOKEN=mbsec-example123@mbsecver-version123",
            "--inject-file", "workload.json:/etc/faultline/workload.json",
            "--working-dir", "/opt/robot-debug",
            "--container-command", "/opt/conda/envs/libero/bin/python",
            "--args", "/opt/robot-debug/scripts/run_serverless_workload.py --config /etc/faultline/workload.json",
            "--dry-run", "--async",
        ])
        self.assertNotIn("--execute", argv)

    def test_optional_registry_secret_adds_selector_only(self) -> None:
        argv = self.module.prepare(self.valid_config(registry_secret="mbsec-registry123"))
        index = argv.index("--registry-secret")
        self.assertEqual(argv[index + 1], "mbsec-registry123")
        self.assertNotIn("--username", argv)
        self.assertNotIn("--password", argv)

    def test_prepare_does_not_import_or_call_process_or_network_apis(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("subprocess", "requests", "urllib", "socket", "os.system"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_rejects_unknown_or_credential_fields(self) -> None:
        for field in ("token", "password", "raw_env", "username", "profile", "region"):
            with self.subTest(field=field):
                with self.assertRaises(self.module.ConfigError):
                    self.module.prepare(self.valid_config(**{field: "secret-value"}))

    def test_requires_all_fields_and_strict_string_types(self) -> None:
        for field in ("run_id", "project_id", "image", "platform", "preset", "subnet_id",
                      "bucket_id", "hf_secret", "workload_file"):
            with self.subTest(missing=field):
                config = self.valid_config()
                del config[field]
                with self.assertRaises(self.module.ConfigError):
                    self.module.prepare(config)
            for value in (True, 1, 1.5, None, [], {}):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(self.module.ConfigError):
                        self.module.prepare(self.valid_config(**{field: value}))

    def test_rejects_unsafe_run_names(self) -> None:
        for run_id in ("Uppercase", "has_underscore", "has.dot", "-starts", "ends-", "a" * 64, ""):
            with self.subTest(run_id=run_id):
                with self.assertRaises(self.module.ConfigError):
                    self.module.prepare(self.valid_config(run_id=run_id))

    def test_rejects_wrong_id_kinds_and_secret_values_as_ids(self) -> None:
        cases = (
            ("project_id", "tenant-example123"),
            ("project_id", "mbsec-example123"),
            ("subnet_id", "project-example123"),
            ("bucket_id", "hf_actual-token-value"),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                with self.assertRaises(self.module.ConfigError):
                    self.module.prepare(self.valid_config(**{field: value}))

    def test_rejects_mutable_or_malformed_images(self) -> None:
        for image in (
            "registry.example/robot-debug:latest",
            "registry.example/robot-debug@sha256:short",
            "registry.example/robot-debug@sha256:" + "G" * 64,
            "@sha256:" + "a" * 64,
        ):
            with self.subTest(image=image):
                with self.assertRaises(self.module.ConfigError):
                    self.module.prepare(self.valid_config(image=image))

    def test_rejects_non_one_gpu_platform_or_preset(self) -> None:
        for overrides in (
            {"platform": "gpu-h100-sxm"},
            {"preset": "2gpu-32vcpu-128gb"},
            {"preset": "1gpu-8vcpu-32gb"},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(self.module.ConfigError):
                    self.module.prepare(self.valid_config(**overrides))

    def test_secret_fields_accept_only_secret_stash_selectors(self) -> None:
        for field in ("hf_secret", "registry_secret"):
            for value in (
                "hf_actual-token-value",
                "plain-secret",
                "mbsec-UPPER",
                "mbsec-valid@wrong-version",
                "mbsec-valid@mbsecver-UPPER",
            ):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(self.module.ConfigError):
                        self.module.prepare(self.valid_config(**{field: value}))

    def test_rejects_missing_large_or_unsafe_workload_file(self) -> None:
        Path("too-large.json").write_bytes(b"x" * (64 * 1024 + 1))
        Path("safe.json").write_text("{}", encoding="utf-8")
        for value in ("missing.json", "too-large.json", "safe.json:other", "safe.json\n--execute"):
            with self.subTest(value=value):
                with self.assertRaises(self.module.ConfigError):
                    self.module.prepare(self.valid_config(workload_file=value))

    def test_rejects_non_object_config(self) -> None:
        for config in (None, [], "config", True):
            with self.subTest(config=config):
                with self.assertRaises(self.module.ConfigError):
                    self.module.prepare(config)

    def test_main_prints_json_argv_and_paid_gate_warning(self) -> None:
        config_path = Path("config.json")
        config_path.write_text(json.dumps(self.valid_config()), encoding="utf-8")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = self.module.main(["--config", str(config_path)])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(stdout.getvalue()), self.module.prepare(self.valid_config()))
        self.assertIn("paid", stderr.getvalue().lower())
        self.assertIn("does not create", stderr.getvalue().lower())

    def test_cli_has_no_execute_option(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            self.module.main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--config", stdout.getvalue())
        self.assertNotIn("--execute", stdout.getvalue())

    def test_main_rejects_duplicate_json_keys(self) -> None:
        config_path = Path("duplicate.json")
        config_path.write_text('{"run_id":"one","run_id":"two"}', encoding="utf-8")
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            result = self.module.main(["--config", str(config_path)])
        self.assertEqual(result, 2)
        self.assertIn("duplicate", stderr.getvalue().lower())

    def test_illustrative_example_is_safe_and_rejected_until_configured(self) -> None:
        example_path = ROOT / "configs" / "serverless-job.example.json"
        payload = json.loads(example_path.read_text(encoding="utf-8"))
        serialized = example_path.read_text(encoding="utf-8").lower()
        for mode in ("pilot", "search", "grid", "reduce"):
            self.assertIn(mode, serialized)
        self.assertNotIn("hf_actual", serialized)
        self.assertNotIn("token", serialized)
        self.assertNotIn("password", serialized)
        with self.assertRaises(self.module.ConfigError):
            self.module.prepare(payload)


if __name__ == "__main__":
    unittest.main()
