import copy
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from robot_debug.cloud_run_record import (
    CloudRunRecord,
    RecordError,
    RunStore,
    load_record,
)


NOW = datetime(2030, 1, 1, 0, 0, tzinfo=timezone.utc)


class RecordFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.run_dir = self.root / "runs" / "local-example"
        self.run_dir.mkdir(parents=True)
        self.bundle = self.root / "source.bundle"
        self.bundle.write_bytes(b"synthetic source bundle\n")
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text('{"fixture":true}\n', encoding="utf-8")
        self.known_hosts = self.root / "known_hosts"
        self.known_hosts.write_text("synthetic host key\n", encoding="utf-8")
        self.identity = self.root / "identity"
        self.identity.write_text("synthetic key placeholder\n", encoding="utf-8")
        self.data = self.valid_data()
        self.record_path = self.root / "record.json"
        self.write_record()

    def tearDown(self):
        self.temp.cleanup()

    def valid_data(self):
        return {
            "schema_version": 1,
            "run_label": "local-example",
            "project_id": "project-example",
            "temporary": {
                "instance_id": "computeinstance-clone",
                "disk_id": "computedisk-clone",
                "snapshot_id": "computedisksnapshot-clone",
                "ssh_rule_id": "vpcsecurityrule-clone",
            },
            "protected": {
                "instance_id": "computeinstance-original",
                "disk_id": "computedisk-original",
            },
            "approval": {
                "reference": "local-test-only",
                "max_total_usd": 8.0,
                "max_starts": 1,
                "max_runtime_seconds": 5400,
                "temporary_cleanup": True,
            },
            "deadlines": {
                "start_not_after_utc": "2030-01-01T00:10:00Z",
                "stop_request_utc": "2030-01-01T01:27:00Z",
                "stop_confirm_by_utc": "2030-01-01T01:30:00Z",
                "storage_cleanup_utc": "2030-01-01T03:00:00Z",
            },
            "paths": {
                "run_dir": str(self.run_dir),
                "source_bundle": str(self.bundle),
                "manifest": str(self.manifest),
                "known_hosts": str(self.known_hosts),
                "ssh_identity_file": str(self.identity),
                "guest_session": "/home/robot/local-example",
                "wsl_cli": "/home/local/.nebius/bin/nebius",
            },
            "pins": {
                "source_sha": "1" * 40,
                "bundle_sha256": hashlib.sha256(self.bundle.read_bytes()).hexdigest(),
                "manifest_sha256": hashlib.sha256(self.manifest.read_bytes()).hexdigest(),
                "upstream_sha": "35f1200eb15608aa898f727a3722f7eef889c6cd",
                "checkpoint_id": "nvidia/gr00t17-lerobot-libero_object-640",
                "checkpoint_revision": "1499db357f6ca3762b56c2e8c00b530eb9a09444",
                "simulator_digest": "sha256:" + "d" * 64,
            },
            "ssh": {
                "user": "robot",
                "host_key_sha256": "SHA256:" + "A" * 43,
                "port": 22,
            },
            "preflight": {
                "checked_at_utc": "2030-01-01T00:00:00Z",
                "balance_usd": 10.0,
                "pending_usd": 0.0,
                "estimated_total_usd": 7.55,
                "hourly_rate_usd": 4.5,
                "expiry_checked": True,
                "quota_checked": True,
                "capacity_checked": True,
                "billing_checked": True,
            },
        }

    def write_record(self):
        self.record_path.write_text(json.dumps(self.data), encoding="utf-8")

    def load(self, **kwargs):
        return load_record(
            self.record_path,
            control_root=self.root,
            now_utc=NOW,
            **kwargs,
        )

    def assert_invalid(self):
        self.write_record()
        with self.assertRaises(RecordError):
            self.load()

    def record_for_run_dir(self, run_dir, filename):
        data = copy.deepcopy(self.data)
        data["paths"]["run_dir"] = str(run_dir)
        path = self.root / filename
        path.write_text(json.dumps(data), encoding="utf-8")
        return path, load_record(path, control_root=self.root, now_utc=NOW)


class LoadRecordTests(RecordFixture):
    def test_loads_valid_synthetic_record_and_canonical_digest(self):
        record = self.load()
        self.assertIsInstance(record, CloudRunRecord)
        canonical = json.dumps(self.data, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(record.digest, hashlib.sha256(canonical).hexdigest())
        self.assertEqual(record.paths["run_dir"], str(self.run_dir))

    def test_rejects_unknown_top_level_and_nested_secret_fields(self):
        self.data["command"] = "nebius instance start"
        self.assert_invalid()
        del self.data["command"]
        self.data["ssh"]["private_key"] = "secret"
        self.assert_invalid()

    def test_approval_reference_is_a_narrow_safe_identifier(self):
        for reference in ("token-abc", "password.foo", "private_key_xyz", "approval reference with spaces"):
            with self.subTest(reference=reference):
                self.data["approval"]["reference"] = reference
                self.assert_invalid()

    def test_rejects_wrong_schema_version(self):
        self.data["schema_version"] = True
        self.assert_invalid()

    def test_rejects_bool_and_nonfinite_numbers(self):
        self.data["approval"]["max_total_usd"] = True
        self.assert_invalid()
        self.data["approval"]["max_total_usd"] = float("nan")
        self.assert_invalid()
        self.data["approval"]["max_total_usd"] = 8.0
        self.data["preflight"]["pending_usd"] = float("inf")
        self.assert_invalid()
        self.data["preflight"]["pending_usd"] = 0.0
        self.data["approval"]["max_total_usd"] = 10**1000
        self.assert_invalid()

    def test_rejects_malformed_service_ids_and_digests(self):
        for field, value in (("instance_id", "computeinstance-../x"), ("disk_id", "wrong-id")):
            self.data["temporary"][field] = value
            self.assert_invalid()
            self.data = self.valid_data()
        self.data["pins"]["source_sha"] = "g" * 40
        self.assert_invalid()

    def test_rejects_collision_with_protected_instance_or_disk(self):
        self.data["temporary"]["instance_id"] = self.data["protected"]["instance_id"]
        self.assert_invalid()

    def test_rejects_paths_outside_required_containment(self):
        self.data["paths"]["run_dir"] = str(self.root)
        self.assert_invalid()
        self.data = self.valid_data()
        self.data["paths"]["source_bundle"] = str(self.root.parent / "outside.bundle")
        self.assert_invalid()

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_rejects_symlinked_writable_run_path(self):
        real = self.root / "real"
        real.mkdir()
        link = self.root / "linked"
        try:
            link.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation is unavailable")
        self.data["paths"]["run_dir"] = str(link / "run")
        (link / "run").mkdir()
        self.assert_invalid()

    def test_rejects_expired_unordered_and_runtime_incoherent_deadlines(self):
        self.data["deadlines"]["start_not_after_utc"] = "2029-12-31T23:59:59Z"
        self.assert_invalid()
        self.data = self.valid_data()
        self.data["deadlines"]["stop_request_utc"] = "2030-01-01T00:09:00Z"
        self.assert_invalid()
        self.data = self.valid_data()
        self.data["deadlines"]["stop_request_utc"] = "2030-01-01T01:39:00Z"
        self.data["deadlines"]["stop_confirm_by_utc"] = "2030-01-01T01:45:00Z"
        self.assert_invalid()

    def test_rejects_stop_confirmation_reserve_shorter_than_three_minutes(self):
        self.data["deadlines"]["stop_confirm_by_utc"] = "2030-01-01T01:29:59Z"
        self.assert_invalid()

    def test_rejects_bundle_or_manifest_aliasing_the_ssh_identity(self):
        self.data["paths"]["source_bundle"] = str(self.identity)
        self.data["pins"]["bundle_sha256"] = hashlib.sha256(self.identity.read_bytes()).hexdigest()
        self.write_record()
        from robot_debug import cloud_run_record
        with patch.object(cloud_run_record, "_hash_file", wraps=cloud_run_record._hash_file) as hash_file:
            with self.assertRaises(RecordError):
                self.load()
            hash_file.assert_not_called()

    def test_rejects_manifest_hardlink_to_ssh_identity_before_hashing(self):
        alias = self.root / "key-alias-manifest"
        try:
            os.link(self.identity, alias)
        except OSError as exc:
            self.skipTest(f"hard links unavailable: {exc}")
        self.data["paths"]["manifest"] = str(alias)
        self.data["pins"]["manifest_sha256"] = hashlib.sha256(self.identity.read_bytes()).hexdigest()
        self.write_record()
        from robot_debug import cloud_run_record
        with patch.object(cloud_run_record, "_hash_file", wraps=cloud_run_record._hash_file) as hash_file:
            with self.assertRaises(RecordError):
                self.load()
            hash_file.assert_not_called()

    def test_preflight_must_be_recent_and_cover_estimate(self):
        self.data["preflight"]["checked_at_utc"] = "2029-12-31T23:49:59Z"
        self.assert_invalid()
        self.data = self.valid_data()
        self.data["preflight"]["balance_usd"] = 7.0
        self.assert_invalid()
        self.data = self.valid_data()
        self.data["preflight"]["billing_checked"] = False
        self.assert_invalid()

    def test_require_future_false_allows_expired_inspection_only(self):
        self.data["deadlines"]["start_not_after_utc"] = "2030-01-01T00:00:00Z"
        self.data["deadlines"]["stop_request_utc"] = "2030-01-01T01:27:00Z"
        self.write_record()
        self.bundle.write_bytes(b"changed or unavailable")
        self.manifest.unlink()
        self.identity.unlink()
        record = self.load(require_future=False)
        self.assertIsInstance(record, CloudRunRecord)

    def test_nested_record_data_is_immutable_and_files_are_rehashed(self):
        record = self.load()
        with self.assertRaises(TypeError):
            record.paths["run_dir"] = "changed"
        with self.assertRaises(TypeError):
            record.raw["temporary"]["instance_id"] = "changed"
        self.bundle.write_bytes(b"tampered")
        with self.assertRaises(RecordError):
            self.load()

    def test_rejects_duplicate_json_keys(self):
        self.record_path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        with self.assertRaises(RecordError):
            self.load()


class RunStoreTests(RecordFixture):
    def setUp(self):
        super().setUp()
        self.record = self.load()
        self.store = RunStore(self.run_dir, record_path=self.record_path)
        self.store.create(self.record.digest)

    def test_create_is_exclusive_and_identity_digest_is_stable(self):
        with self.assertRaises(RecordError):
            self.store.create("b" * 64)
        self.assertEqual(self.store.record_digest, self.record.digest)

    def test_create_revalidates_record_digest_after_constructor(self):
        other_dir = self.root / "create-check"
        other_dir.mkdir()
        alternate_record_path, alternate_record = self.record_for_run_dir(other_dir, "create-check-record.json")
        store = RunStore(other_dir, record_path=alternate_record_path)
        alternate_data = json.loads(alternate_record_path.read_text(encoding="utf-8"))
        alternate_data["run_label"] = "changed-after-open"
        alternate_record_path.write_text(json.dumps(alternate_data), encoding="utf-8")
        with self.assertRaises(RecordError):
            store.create(alternate_record.digest)
        self.assertFalse(store.identity_path.exists())

    def test_same_record_cannot_own_two_run_directories(self):
        other_dir = self.root / "second-run"
        other_dir.mkdir()
        with self.assertRaises(RecordError):
            RunStore(other_dir, record_path=self.record_path)

    def test_reopened_store_rejects_identity_digest_replacement(self):
        self.store.snapshot({"phase": "ready"})
        self.store.identity_path.write_text(json.dumps({"record_digest": "f" * 64}), encoding="utf-8")
        with self.assertRaises(RecordError):
            RunStore(self.run_dir, record_path=self.record_path)

    def test_create_refuses_stale_owned_state_and_temp_snapshot(self):
        for stale_name in ("events.jsonl", "status.json", "lease.json", ".status-leftover.tmp"):
            with self.subTest(stale_name=stale_name):
                other = self.root / ("other-" + stale_name.replace("/", "_"))
                other.mkdir()
                (other / stale_name).write_text("stale", encoding="utf-8")
                record_path, record = self.record_for_run_dir(other, f"record-{stale_name.replace('.', '-')}.json")
                store = RunStore(other, record_path=record_path)
                with self.assertRaises(RecordError):
                    store.create(record.digest)
                self.assertFalse(store.identity_path.exists())

    def test_lease_is_exclusive_and_release_requires_owner(self):
        self.store.acquire_lease("controller-a")
        with self.assertRaises(RecordError):
            self.store.acquire_lease("controller-a")
        with self.assertRaises(RecordError):
            self.store.acquire_lease("controller-b")
        with self.assertRaises(RecordError):
            self.store.release_lease("controller-b")
        self.store.release_lease("controller-a")
        self.store.acquire_lease("controller-b")
        self.store.release_lease("controller-b")

    def test_append_is_durable_and_rejects_unsafe_or_unknown_fields(self):
        self.store.append("controller_ready", owner_id="controller-a", phase="waiting_release")
        self.assertEqual(self.store.read_events()[0]["event"], "controller_ready")
        with self.assertRaises(RecordError):
            self.store.append("controller_ready", command="nebius start")
        with self.assertRaises(RecordError):
            self.store.append("controller_ready", stderr="Authorization: token")
        self.store.close()
        with self.store.events_path.open("ab") as stream:
            stream.write(b'{"event":"truncated')
        self.assertEqual(len(self.store.read_events()), 1)

    def test_read_rejects_corruption_before_truncated_tail(self):
        self.store.events_path.write_bytes(b"{bad}\n{\"event\":\"truncated")
        with self.assertRaises(RecordError):
            self.store.read_events()

    def test_append_refuses_to_join_a_truncated_final_event(self):
        self.store.append("before", phase="ready")
        with self.store.events_path.open("ab") as stream:
            stream.write(b'{"event":"truncated')
        original = self.store.events_path.read_bytes()
        self.assertEqual(len(self.store.read_events()), 1)
        with self.assertRaises(RecordError):
            self.store.append("after", phase="ready")
        self.assertEqual(self.store.events_path.read_bytes(), original)
        self.assertEqual(len(self.store.read_events()), 1)

    def test_snapshot_replacement_failure_preserves_previous_status(self):
        self.store.snapshot({"phase": "ready", "record_digest": self.record.digest})
        with patch("robot_debug.cloud_run_record.os.replace", side_effect=OSError("simulated interruption")):
            with self.assertRaises(OSError):
                self.store.snapshot({"phase": "partial", "record_digest": self.record.digest})
        self.assertEqual(self.store.read_status()["phase"], "ready")

    def test_record_file_change_blocks_every_mutator(self):
        self.store.snapshot({"phase": "ready", "record_digest": self.record.digest})
        self.store.append("before", phase="ready")
        original_record = self.record_path.read_bytes()
        self.store.acquire_lease("controller-a")
        another_dir = self.root / "another-run"
        another_dir.mkdir()
        another_record_path, another_record = self.record_for_run_dir(another_dir, "another-record.json")
        another_store = RunStore(another_dir, record_path=another_record_path)
        another_store.create(another_record.digest)
        original_alternate_record = another_record_path.read_bytes()
        paths = (self.store.identity_path, self.store.events_path, self.store.status_path, self.store.lease_path)
        previous = {path: path.read_bytes() for path in paths[:-1]}
        os.lseek(self.store._lease_fd, 0, os.SEEK_SET)
        previous[self.store.lease_path] = os.read(self.store._lease_fd, 4096)
        try:
            self.data["run_label"] = "changed-record"
            self.write_record()
            for mutate in (
                lambda: self.store.append("controller_ready", phase="waiting_release"),
                lambda: self.store.snapshot({"phase": "changed"}),
                lambda: self.store.release_lease("controller-a"),
            ):
                with self.assertRaises(RecordError):
                    mutate()
            alternate_data = json.loads(another_record_path.read_text(encoding="utf-8"))
            alternate_data["run_label"] = "changed-alternate-record"
            another_record_path.write_text(json.dumps(alternate_data), encoding="utf-8")
            with self.assertRaises(RecordError):
                another_store.acquire_lease("controller-b")
            current = {path: path.read_bytes() for path in paths[:-1]}
            os.lseek(self.store._lease_fd, 0, os.SEEK_SET)
            current[self.store.lease_path] = os.read(self.store._lease_fd, 4096)
            self.assertEqual(previous, current)
            self.assertFalse(another_store.lease_path.exists())
        finally:
            self.record_path.write_bytes(original_record)
            another_record_path.write_bytes(original_alternate_record)
            if another_store._lease_fd is not None:
                another_store.release_lease("controller-b")
            if self.store._lease_fd is not None:
                self.store.release_lease("controller-a")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_owned_store_symlinks_never_write_through_to_external_files(self):
        outside = self.root / "outside-owned-target"
        outside.write_bytes(b"must remain unchanged")
        for name, operation in (
            ("events.jsonl", lambda store: store.append("controller_ready", phase="ready")),
            ("status.json", lambda store: store.snapshot({"phase": "changed"})),
            ("lease.json", lambda store: store.acquire_lease("controller-a")),
        ):
            with self.subTest(name=name):
                target = self.run_dir / name
                try:
                    target.symlink_to(outside)
                except (OSError, NotImplementedError) as exc:
                    self.skipTest(f"symlink creation unavailable: {exc}")
                with self.assertRaises(RecordError):
                    operation(self.store)
                self.assertEqual(outside.read_bytes(), b"must remain unchanged")
                target.unlink()

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_identity_symlink_is_rejected_before_mutation(self):
        outside = self.root / "outside-identity"
        outside.write_bytes(b"identity target")
        self.store.identity_path.unlink()
        try:
            self.store.identity_path.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        with self.assertRaises(RecordError):
            self.store.append("controller_ready", phase="ready")
        self.assertEqual(outside.read_bytes(), b"identity target")

    def test_owned_store_hardlink_is_rejected_before_append(self):
        outside = self.root / "outside-hardlink-target"
        outside.write_bytes(b"must remain unchanged")
        target = self.store.events_path
        try:
            os.link(outside, target)
        except OSError as exc:
            self.skipTest(f"hard links unavailable: {exc}")
        with self.assertRaises(RecordError):
            self.store.append("controller_ready", phase="ready")
        self.assertEqual(outside.read_bytes(), b"must remain unchanged")


if __name__ == "__main__":
    unittest.main()
