"""Local, fake-CLI coverage for the exact-instance VM watchdog."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import importlib.util
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from robot_debug.vm_watchdog import GuardRecord, RecordError, load_record, watch


UTC = timezone.utc


class GuardRecordTests(unittest.TestCase):
    def _payload(self, root: Path, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": 1,
            "instance_id": "computeinstance-test123",
            "project_id": "project-test123",
            "deadline_utc": "2030-01-02T03:04:05Z",
            "run_label": "m3-pilot",
            "wsl_cli_path": "/home/test/.nebius/bin/nebius",
            "log_path": str(root / "m3-pilot" / "watchdog.jsonl"),
        }
        payload.update(overrides)
        return payload

    def _load(self, payload: dict[str, object], root: Path) -> GuardRecord:
        path = root / "record.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return load_record(path, control_root=root, now_utc=datetime(2030, 1, 1, tzinfo=UTC))

    def test_loads_exact_record_and_builds_argument_safe_get_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = self._load(self._payload(root), root)
        self.assertEqual(record.instance_id, "computeinstance-test123")
        self.assertEqual(record.project_id, "project-test123")
        self.assertEqual(
            record.get_command(),
            [
                r"C:\Windows\System32\wsl.exe", "--exec", "/home/test/.nebius/bin/nebius",
                "compute", "instance", "get", "--id", "computeinstance-test123",
                "--format", "json", "--no-browser", "--timeout", "30s", "--no-check-update",
            ],
        )

    def test_rejects_malformed_or_unsafe_records(self):
        cases = (
            {"instance_id": "instance-test123"},
            {"project_id": "tenant-test123"},
            {"deadline_utc": "2030-01-02T03:04:05+01:00"},
            {"deadline_utc": "yesterday"},
            {"deadline_utc": "2029-01-02T03:04:05Z"},
            {"log_path": "relative.jsonl"},
            {"log_path": str(Path(tempfile.gettempdir()) / "outside.jsonl")},
            {"token": "must-not-persist"},
        )
        for override in cases:
            with self.subTest(override=override), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with self.assertRaises(RecordError):
                    self._load(self._payload(root, **override), root)

    def test_rejects_missing_and_unexpected_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = self._payload(root)
            del payload["run_label"]
            with self.assertRaises(RecordError):
                self._load(payload, root)

    def test_rejects_record_outside_control_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record_path = root / "record.json"
            record_path.write_text(json.dumps(self._payload(root)), encoding="utf-8")
            with self.assertRaises(RecordError):
                load_record(record_path, control_root=root / "control", now_utc=datetime(2030, 1, 1, tzinfo=UTC))


class WatchStateMachineTests(unittest.TestCase):
    def _record(self, root: Path, deadline: datetime) -> GuardRecord:
        return GuardRecord(
            "computeinstance-test123", "project-test123", deadline, "m3-pilot",
            "/home/test/.nebius/bin/nebius", root / "m3-pilot" / "watchdog.jsonl",
        )

    @staticmethod
    def _instance(state: str = "RUNNING", project: str = "project-test123", instance_id: str = "computeinstance-test123") -> dict[str, object]:
        return {"metadata": {"id": instance_id, "parent_id": project}, "status": {"state": state}}

    def _events(self, record: GuardRecord) -> list[dict[str, object]]:
        return [json.loads(line) for line in record.log_path.read_text(encoding="utf-8").splitlines()]

    def test_refuses_readback_for_different_parent_without_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = self._record(root, datetime(2030, 1, 2, tzinfo=UTC))
            calls: list[list[str]] = []
            with self.assertRaises(RecordError):
                watch(record, invoke=lambda argv: calls.append(argv) or self._instance(project="project-other"),
                      now=lambda: datetime(2030, 1, 1, tzinfo=UTC), sleep=lambda _: None)
            self.assertEqual(len(calls), 1)
            self.assertIn("exception", [event["event"] for event in self._events(record)])

    def test_refuses_readback_for_different_instance_without_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            record = self._record(Path(directory), datetime(2030, 1, 2, tzinfo=UTC))
            calls: list[list[str]] = []
            with self.assertRaises(RecordError):
                watch(record, invoke=lambda argv: calls.append(argv) or self._instance(instance_id="computeinstance-other"),
                      now=lambda: datetime(2030, 1, 3, tzinfo=UTC), sleep=lambda _: None)
            self.assertEqual(len(calls), 1)

    def test_arms_before_deadline_then_stops_exact_id_and_polls_to_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clock = [datetime(2030, 1, 1, tzinfo=UTC)]
            deadline = clock[0] + timedelta(seconds=2)
            record = self._record(root, deadline)
            calls: list[list[str]] = []
            replies = iter([self._instance(), self._instance(), {}, self._instance("STOPPING"), self._instance("STOPPED")])
            def invoke(argv: list[str]) -> object:
                calls.append(argv)
                return next(replies)
            def sleep(seconds: float) -> None:
                clock[0] += timedelta(seconds=seconds)
            result = watch(record, invoke=invoke, now=lambda: clock[0], sleep=sleep, poll_seconds=1)
            self.assertEqual(result, "stop_confirmed")
            self.assertNotIn("stop", calls[0])
            self.assertEqual(calls[2][3:7], ["compute", "instance", "stop", "--id"])
            self.assertEqual(calls[2][7], "computeinstance-test123")
            self.assertEqual([item["event"] for item in self._events(record)], [
                "verified", "armed", "deadline_reached", "stop_requested", "polling", "stop_confirmed",
            ])

    def test_already_stopped_never_sends_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clock = [datetime(2030, 1, 1, tzinfo=UTC)]
            record = self._record(root, clock[0] + timedelta(seconds=1))
            calls: list[list[str]] = []
            result = watch(record, invoke=lambda argv: calls.append(argv) or self._instance("STOPPED"),
                           now=lambda: clock[0], sleep=lambda seconds: clock.__setitem__(0, clock[0] + timedelta(seconds=seconds)))
            self.assertEqual(result, "already_stopped")
            self.assertEqual(len(calls), 2)
            self.assertIn("armed", [event["event"] for event in self._events(record)])
            self.assertTrue(all("stop" not in call for call in calls))

    def test_retries_cli_failures_then_logs_unconfirmed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            now = datetime(2030, 1, 1, tzinfo=UTC)
            record = self._record(root, now + timedelta(seconds=1))
            calls = 0
            def invoke(argv: list[str]) -> object:
                nonlocal calls
                calls += 1
                if calls <= 2:
                    return self._instance()
                raise OSError("fake CLI unavailable")
            result = watch(record, invoke=invoke, now=lambda: now + timedelta(seconds=2),
                           sleep=lambda _: None, retries=2)
            self.assertEqual(result, "stop_unconfirmed")
            self.assertEqual(calls, 4)
            self.assertEqual(self._events(record)[-1]["event"], "stop_unconfirmed")

    def test_deadline_get_failure_still_stops_exact_preverified_target(self):
        with tempfile.TemporaryDirectory() as directory:
            record = self._record(Path(directory), datetime(2030, 1, 1, tzinfo=UTC))
            calls: list[list[str]] = []
            def invoke(argv: list[str]) -> object:
                calls.append(argv)
                if len(calls) == 1:
                    return self._instance("RUNNING")
                if len(calls) in (2, 3):
                    raise OSError("transient exact get failure")
                if "stop" in argv:
                    return ""  # CLI exit 0, no JSON body
                return self._instance("STOPPED")
            result = watch(record, invoke=invoke, now=lambda: datetime(2030, 1, 2, tzinfo=UTC),
                           sleep=lambda _: None, retries=2)
            self.assertEqual(result, "stop_confirmed")
            self.assertEqual([call for call in calls if "stop" in call][0][7], record.instance_id)

    def test_deadline_wrong_instance_refuses_stop_and_reports_unconfirmed(self):
        with tempfile.TemporaryDirectory() as directory:
            record = self._record(Path(directory), datetime(2030, 1, 1, tzinfo=UTC))
            calls: list[list[str]] = []
            replies = iter([self._instance(), self._instance(instance_id="computeinstance-other")])
            result = watch(record, invoke=lambda argv: calls.append(argv) or next(replies),
                           now=lambda: datetime(2030, 1, 2, tzinfo=UTC), sleep=lambda _: None)
            self.assertEqual(result, "stop_unconfirmed")
            self.assertTrue(all("stop" not in call for call in calls))


class ArmWrapperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        script_path = Path(__file__).parents[1] / "scripts" / "run_vm_watchdog.py"
        spec = importlib.util.spec_from_file_location("vm_watchdog_runner", script_path)
        cls.runner = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.runner
        assert spec.loader is not None
        spec.loader.exec_module(cls.runner)

    def _payload(self, root: Path, *, deadline_utc: str = "2030-01-02T03:04:05Z") -> Path:
        control = root / "control"
        record = control / "record.json"
        record.parent.mkdir(parents=True)
        record.write_text(json.dumps({
            "schema_version": 1,
            "instance_id": "computeinstance-test123",
            "project_id": "project-test123",
            "deadline_utc": deadline_utc,
            "run_label": "m3-pilot",
            "wsl_cli_path": "/home/test/.nebius/bin/nebius",
            "log_path": str(control / "m3-pilot" / "watchdog.jsonl"),
        }), encoding="utf-8")
        return record

    def test_check_uses_exact_get_only_and_rejects_malformed_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = self._payload(root)
            calls: list[list[str]] = []
            result = self.runner.check(record, root / "control", invoke=lambda argv: calls.append(argv) or {
                "metadata": {"id": "computeinstance-test123", "parent_id": "project-test123"}, "status": {"state": "STOPPED"},
            })
            self.assertEqual(result, "checked")
            self.assertEqual(len(calls), 1)
            self.assertNotIn("stop", calls[0])
            with self.assertRaises(RecordError):
                self.runner.check(record, root / "control", invoke=lambda _: "not json")

    def test_arm_refuses_existing_or_stale_lock_without_spawning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = self._payload(root)
            lock = root / "control" / "m3-pilot" / "arm.lock"
            lock.parent.mkdir()
            lock.write_text("999", encoding="utf-8")
            with self.assertRaises(self.runner.ArmError):
                self.runner.arm(record, root / "control", local_test=True, fake_cli=root / "fake.json")

    def test_arm_requires_live_child_and_durable_armed_event(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = self._payload(root)
            fake = root / "fake.json"
            fake.write_text("[]", encoding="utf-8")
            with self.assertRaises(self.runner.ArmError):
                self.runner.arm(
                    record, root / "control", local_test=True, fake_cli=fake,
                    process_factory=lambda *args, **kwargs: SimpleNamespace(pid=5, poll=lambda: 1),
                    handshake_seconds=0,
                )

    def test_arm_refuses_historical_log_even_after_lock_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = self._payload(root)
            log_path = root / "control" / "m3-pilot" / "watchdog.jsonl"
            log_path.parent.mkdir()
            log_path.write_text('{"event":"armed"}\n', encoding="utf-8")
            fake = root / "fake.json"
            fake.write_text("[]", encoding="utf-8")
            with self.assertRaises(self.runner.ArmError):
                self.runner.arm(record, root / "control", local_test=True, fake_cli=fake)

    def test_real_cli_subprocess_has_host_timeout(self):
        with patch.object(self.runner.subprocess, "run") as run:
            run.return_value.stdout = "{}"
            self.runner._real_invoke(["fake"])
            self.assertGreater(run.call_args.kwargs["timeout"], 0)

    def test_unconfirmed_watch_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = self._payload(root)
            with patch.object(self.runner, "watch", return_value="stop_unconfirmed"):
                self.assertNotEqual(self.runner.main(["watch", "--record", str(record),
                                                      "--control-root", str(root / "control")]), 0)

    def test_local_test_without_fake_cli_cannot_reach_real_invoker(self):
        with patch.object(self.runner, "_real_invoke") as real:
            with self.assertRaises(SystemExit):
                self.runner.main(["watch", "--record", "unused.json", "--control-root", "unused",
                                  "--local-test"])
            real.assert_not_called()

    def test_arm_production_mode_can_launch_a_watch_child_without_fake_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = self._payload(root)
            with self.assertRaisesRegex(self.runner.ArmError, "child exited"):
                self.runner.arm(
                    record, root / "control",
                    process_factory=lambda *args, **kwargs: SimpleNamespace(pid=6, poll=lambda: 1),
                    handshake_seconds=0,
                )

    def test_local_fake_arm_detaches_then_confirms_stop_without_nebius(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            deadline = (datetime.now(UTC) + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
            record = self._payload(root, deadline_utc=deadline)
            fake = root / "fake.json"
            fake.write_text(json.dumps([
                {"metadata": {"id": "computeinstance-test123", "parent_id": "project-test123"}, "status": {"state": "STOPPED"}},
                {"metadata": {"id": "computeinstance-test123", "parent_id": "project-test123"}, "status": {"state": "RUNNING"}},
                {},
                {"metadata": {"id": "computeinstance-test123", "parent_id": "project-test123"}, "status": {"state": "STOPPED"}},
            ]), encoding="utf-8")
            pid = self.runner.arm(record, root / "control", local_test=True, fake_cli=fake, handshake_seconds=5)
            log_path = root / "control" / "m3-pilot" / "watchdog.jsonl"
            limit = time.monotonic() + 5
            while not self.runner._has_event(log_path, "stop_confirmed") and time.monotonic() < limit:
                time.sleep(0.05)
            self.assertGreater(pid, 0)
            self.assertTrue(self.runner._has_event(log_path, "armed"))
            self.assertTrue(self.runner._has_event(log_path, "stop_confirmed"))
            # The detached child closes inherited stdout/stderr handles as it
            # exits; the fsynced final event can precede that exit on Windows.
            time.sleep(0.5)


if __name__ == "__main__":
    unittest.main()
