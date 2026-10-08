import ast
import hashlib
import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from robot_debug.job_runtime import export_closed_evidence, validate_workload_config


class StrSubclass(str):
    pass


class WorkloadConfigTests(unittest.TestCase):
    def valid(self):
        return {
            "schema_version": 1,
            "mode": "pilot",
            "run_id": "pilot-1",
            "deadline_seconds": 60,
        }

    def test_module_syntax_remains_compatible_with_python_38(self):
        module = Path(__file__).parents[1] / "src" / "robot_debug" / "job_runtime.py"
        ast.parse(module.read_text(encoding="utf-8"), filename=str(module), feature_version=(3, 8))

    def assert_invalid(self, config):
        with self.assertRaises(ValueError) as raised:
            validate_workload_config(config)
        message = str(raised.exception)
        self.assertNotIn("private", message)
        self.assertNotIn("secret-value", message)

    def test_returns_fresh_normalized_json_dictionary_for_every_mode(self):
        for mode in ("pilot", "search", "grid", "reduce"):
            with self.subTest(mode=mode):
                config = self.valid()
                config["mode"] = mode
                config["deadline_seconds"] = 1.5
                result = validate_workload_config(config)
                self.assertEqual(result, config)
                self.assertIsNot(result, config)
                self.assertEqual(json.loads(json.dumps(result)), result)

    def test_requires_exact_fields_and_rejects_extras(self):
        config = self.valid()
        del config["mode"]
        self.assert_invalid(config)
        config = self.valid()
        config["private"] = "secret-value"
        self.assert_invalid(config)

    def test_requires_plain_dictionary_and_plain_strings(self):
        class DictSubclass(dict):
            pass

        self.assert_invalid(DictSubclass(self.valid()))
        for field in ("mode", "run_id"):
            config = self.valid()
            config[field] = StrSubclass(config[field])
            self.assert_invalid(config)

    def test_schema_version_is_exact_integer_one(self):
        for value in (True, False, 0, 1.0, 2, "1"):
            with self.subTest(value=value):
                config = self.valid()
                config["schema_version"] = value
                self.assert_invalid(config)

    def test_mode_is_one_of_the_supported_values(self):
        for value in ("", "Pilot", "batch", 1, None):
            with self.subTest(value=value):
                config = self.valid()
                config["mode"] = value
                self.assert_invalid(config)

    def test_run_id_has_safe_lowercase_ascii_hyphen_shape(self):
        accepted = ("a", "a1", "a-b", "a--b", "a" * 63)
        rejected = (
            "", "-a", "a-", "Upper", "under_score", "has space",
            "café", "a" * 64, 7,
        )
        for value in accepted:
            with self.subTest(value=value):
                config = self.valid()
                config["run_id"] = value
                self.assertEqual(validate_workload_config(config)["run_id"], value)
        for value in rejected:
            with self.subTest(value=value):
                config = self.valid()
                config["run_id"] = value
                self.assert_invalid(config)

    def test_deadline_is_finite_positive_plain_number_at_most_3000(self):
        for value in (1, 0.25, 3000, 3000.0):
            with self.subTest(value=value):
                config = self.valid()
                config["deadline_seconds"] = value
                self.assertEqual(validate_workload_config(config)["deadline_seconds"], value)
        for value in (True, False, 0, -1, 3000.0001, math.nan, math.inf, -math.inf, "60"):
            with self.subTest(value=value):
                config = self.valid()
                config["deadline_seconds"] = value
                self.assert_invalid(config)


class EvidenceExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.destination = self.root / "export"

    def tearDown(self):
        self.temp.cleanup()

    def export(self, **kwargs):
        return export_closed_evidence(
            self.source,
            self.destination,
            status=kwargs.pop("status", "complete"),
            cleanup_confirmed=kwargs.pop("cleanup_confirmed", True),
            **kwargs,
        )

    def assert_rejected_without_destination(self, **kwargs):
        with self.assertRaises((ValueError, OSError)):
            self.export(**kwargs)
        self.assertFalse(self.destination.exists())

    def test_exports_minimal_fixture_and_persists_exact_report(self):
        (self.source / "episode.mp4").write_bytes(b"mp4")
        expected = {
            "schema_version": 1,
            "status": "complete",
            "files": [{
                "path": "episode.mp4",
                "size_bytes": 3,
                "sha256": hashlib.sha256(b"mp4").hexdigest(),
            }],
        }
        report = self.export()
        self.assertEqual(report, expected)
        self.assertEqual(
            json.loads((self.destination / "manifest.json").read_text(encoding="utf-8")),
            report,
        )
        self.assertEqual((self.source / "episode.mp4").read_bytes(), b"mp4")
        self.assertEqual((self.destination / "episode.mp4").read_bytes(), b"mp4")

    def test_accepts_partial_and_all_evidence_extensions(self):
        names = (
            "a.json", "b.jsonl", "c.mp4", "d.sqlite", "e.yaml", "f.yml",
            "g.txt", "h.log",
        )
        for name in names:
            (self.source / name).write_bytes(name.encode("ascii"))
        report = self.export(status="partial")
        self.assertEqual(report["status"], "partial")
        self.assertEqual([row["path"] for row in report["files"]], sorted(names))

    def test_status_and_cleanup_must_be_exact(self):
        (self.source / "evidence.json").write_text("{}", encoding="utf-8")
        for status in ("done", StrSubclass("complete"), 1):
            with self.subTest(status=status):
                self.assert_rejected_without_destination(status=status)
        for cleanup in (False, 1, "true"):
            with self.subTest(cleanup=cleanup):
                self.assert_rejected_without_destination(cleanup_confirmed=cleanup)

    def test_rejects_existing_destination_and_source_overlap_before_mutation(self):
        (self.source / "evidence.json").write_text("{}", encoding="utf-8")
        self.destination.mkdir()
        with self.assertRaises(ValueError):
            self.export()
        self.assertEqual(list(self.destination.iterdir()), [])
        self.destination.rmdir()

        for destination in (self.source, self.source / "nested", self.root):
            with self.subTest(destination=destination):
                with self.assertRaises(ValueError):
                    export_closed_evidence(
                        self.source, destination, status="complete", cleanup_confirmed=True
                    )

    def test_rejects_missing_or_nondirectory_source(self):
        missing = self.root / "missing"
        with self.assertRaises(ValueError):
            export_closed_evidence(
                missing, self.destination, status="complete", cleanup_confirmed=True
            )
        file_source = self.root / "file-source"
        file_source.write_bytes(b"x")
        with self.assertRaises(ValueError):
            export_closed_evidence(
                file_source, self.destination, status="complete", cleanup_confirmed=True
            )

    def test_rejects_reserved_manifest_credentials_sqlite_companions_and_extensions(self):
        names = (
            "manifest.json", ".env", ".env.local", ".envrc", "private.key", "client.pem",
            "api-token.txt", "server-key.json", "creds.json", "case.sqlite-wal", "case.sqlite-shm",
            "weights.bin", "model.pt", "program.exe", "archive.zip",
        )
        for name in names:
            with self.subTest(name=name):
                path = self.source / name
                path.write_bytes(b"safe fixture")
                self.assert_rejected_without_destination()
                path.unlink()

        nested = self.source / "nested"
        nested.mkdir()
        (nested / "manifest.json").write_text("{}", encoding="utf-8")
        self.assert_rejected_without_destination()

    def test_does_not_guess_key_substrings_as_credentials(self):
        (self.source / "monkey.json").write_text("{}", encoding="utf-8")
        report = self.export()
        self.assertEqual(report["files"][0]["path"], "monkey.json")

    def test_rejects_unsafe_and_control_character_names(self):
        for name in ("line\nbreak.txt", "tab\tname.log", "back\\slash.txt"):
            with self.subTest(name=repr(name)):
                path = self.source / name
                try:
                    path.write_bytes(b"x")
                except OSError:
                    continue
                self.assert_rejected_without_destination()
                path.unlink()

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_rejects_symlinked_source_children_and_ancestors(self):
        outside = self.root / "outside.json"
        outside.write_bytes(b"outside")
        link = self.source / "linked.json"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        self.assert_rejected_without_destination()
        link.unlink()

        real = self.root / "real-parent"
        real.mkdir()
        linked_parent = self.root / "linked-parent"
        try:
            linked_parent.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"directory symlinks unavailable: {exc}")
        with self.assertRaises(ValueError):
            export_closed_evidence(
                self.source,
                linked_parent / "export",
                status="complete",
                cleanup_confirmed=True,
            )

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO files unavailable")
    def test_rejects_special_files(self):
        os.mkfifo(self.source / "pipe.log")
        self.assert_rejected_without_destination()

    def test_rejects_total_larger_than_one_gib_before_creating_destination(self):
        huge = self.source / "huge.log"
        with huge.open("wb") as stream:
            stream.truncate((1 << 30) + 1)
        self.assert_rejected_without_destination()

    def test_secret_values_are_explicit_plain_nonempty_string_tuple(self):
        (self.source / "evidence.log").write_bytes(b"ordinary evidence")
        for values in (["secret"], ("",), (StrSubclass("secret"),), (b"secret",)):
            with self.subTest(values=values):
                self.assert_rejected_without_destination(secret_values=values)

    def test_rejects_supplied_secret_across_stream_chunk_boundary_without_echo(self):
        secret = "DO-NOT-ECHO-THIS-SECRET"
        from robot_debug import job_runtime
        prefix = b"x" * (job_runtime._COPY_CHUNK_SIZE - 5)
        (self.source / "evidence.log").write_bytes(prefix + secret.encode("utf-8") + b"tail")
        with self.assertRaises(ValueError) as raised:
            self.export(secret_values=(secret,))
        self.assertNotIn(secret, str(raised.exception))
        self.assertFalse(self.destination.exists())

    def test_does_not_read_environment_secrets_or_guess_arbitrary_content(self):
        content = b"TOKEN_FROM_ENV_ONLY"
        (self.source / "evidence.log").write_bytes(content)
        with patch.dict(os.environ, {"FAULTLINE_TEST_SECRET": content.decode("ascii")}):
            report = self.export()
        self.assertEqual(report["files"][0]["sha256"], hashlib.sha256(content).hexdigest())

    def test_copy_failure_retains_partial_files_but_never_manifest(self):
        (self.source / "a.json").write_bytes(b"a")
        (self.source / "b.json").write_bytes(b"b")
        from robot_debug import job_runtime
        original = job_runtime._copy_file
        calls = []

        def fail_second(*args, **kwargs):
            calls.append(args[0])
            if len(calls) == 2:
                raise OSError("injected copy failure")
            return original(*args, **kwargs)

        with patch.object(job_runtime, "_copy_file", side_effect=fail_second):
            with self.assertRaises(OSError):
                self.export()
        self.assertTrue(self.destination.is_dir())
        self.assertEqual((self.destination / "a.json").read_bytes(), b"a")
        self.assertFalse((self.destination / "manifest.json").exists())

    def test_copy_refuses_a_target_introduced_before_publication(self):
        (self.source / "evidence.json").write_bytes(b"source")
        from robot_debug import job_runtime
        original = job_runtime.os.open
        target = self.destination / "evidence.json"

        def introduce_target(path, flags, *args):
            if Path(path) == target and flags & os.O_EXCL:
                target.write_bytes(b"intruder")
            return original(path, flags, *args)

        with patch.object(job_runtime.os, "open", side_effect=introduce_target):
            with self.assertRaises(OSError):
                self.export()
        self.assertEqual((self.destination / "evidence.json").read_bytes(), b"intruder")
        self.assertFalse((self.destination / "manifest.json").exists())

    def test_detects_source_change_during_copy_without_publishing_manifest(self):
        source_file = self.source / "evidence.json"
        source_file.write_bytes(b"before")
        from robot_debug import job_runtime
        original = job_runtime._copy_file

        def mutate_source(source, destination, secrets):
            result = original(source, destination, secrets)
            source_file.write_bytes(b"after")
            return result

        with patch.object(job_runtime, "_copy_file", side_effect=mutate_source):
            with self.assertRaises(ValueError):
                self.export()
        self.assertFalse((self.destination / "manifest.json").exists())

    def test_detects_copied_file_tampering_without_publishing_manifest(self):
        (self.source / "evidence.json").write_bytes(b"source")
        from robot_debug import job_runtime
        original = job_runtime._copy_file

        def tamper(source, destination, secrets):
            result = original(source, destination, secrets)
            destination.write_bytes(b"tampered")
            return result

        with patch.object(job_runtime, "_copy_file", side_effect=tamper):
            with self.assertRaises(ValueError):
                self.export()
        self.assertFalse((self.destination / "manifest.json").exists())

    def test_nested_files_are_sorted_by_portable_relative_path(self):
        (self.source / "z").mkdir()
        (self.source / "a").mkdir()
        (self.source / "z" / "last.txt").write_bytes(b"z")
        (self.source / "a" / "first.txt").write_bytes(b"a")
        (self.source / "middle.log").write_bytes(b"m")
        report = self.export()
        self.assertEqual(
            [row["path"] for row in report["files"]],
            ["a/first.txt", "middle.log", "z/last.txt"],
        )


if __name__ == "__main__":
    unittest.main()
