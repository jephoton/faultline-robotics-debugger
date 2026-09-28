"""Local, fake-CLI coverage for the exact-instance VM watchdog."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

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


class WatchStateMachineTests(unittest.TestCase):
    def _record(self, root: Path, deadline: datetime) -> GuardRecord:
        return GuardRecord(
            "computeinstance-test123", "project-test123", deadline, "m3-pilot",
            "/home/test/.nebius/bin/nebius", root / "m3-pilot" / "watchdog.jsonl",
        )

    @staticmethod
    def _instance(state: str = "RUNNING", project: str = "project-test123") -> dict[str, object]:
        return {"metadata": {"parent_id": project}, "status": {"state": state}}

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

    def test_arms_before_deadline_then_stops_exact_id_and_polls_to_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clock = [datetime(2030, 1, 1, tzinfo=UTC)]
            deadline = clock[0] + timedelta(seconds=2)
            record = self._record(root, deadline)
            calls: list[list[str]] = []
            replies = iter([self._instance(), {}, self._instance("STOPPING"), self._instance("STOPPED")])
            def invoke(argv: list[str]) -> object:
                calls.append(argv)
                return next(replies)
            def sleep(seconds: float) -> None:
                clock[0] += timedelta(seconds=seconds)
            result = watch(record, invoke=invoke, now=lambda: clock[0], sleep=sleep, poll_seconds=1)
            self.assertEqual(result, "stop_confirmed")
            self.assertNotIn("stop", calls[0])
            self.assertEqual(calls[1][3:7], ["compute", "instance", "stop", "--id"])
            self.assertEqual(calls[1][7], "computeinstance-test123")
            self.assertEqual([item["event"] for item in self._events(record)], [
                "verified", "armed", "deadline_reached", "stop_requested", "polling", "stop_confirmed",
            ])

    def test_already_stopped_never_sends_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            now = datetime(2030, 1, 1, tzinfo=UTC)
            record = self._record(root, now + timedelta(seconds=1))
            calls: list[list[str]] = []
            result = watch(record, invoke=lambda argv: calls.append(argv) or self._instance("STOPPED"),
                           now=lambda: now, sleep=lambda _: None)
            self.assertEqual(result, "already_stopped")
            self.assertEqual(len(calls), 1)

    def test_retries_cli_failures_then_logs_unconfirmed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            now = datetime(2030, 1, 1, tzinfo=UTC)
            record = self._record(root, now + timedelta(seconds=1))
            calls = 0
            def invoke(argv: list[str]) -> object:
                nonlocal calls
                calls += 1
                if calls == 1:
                    return self._instance()
                raise OSError("fake CLI unavailable")
            result = watch(record, invoke=invoke, now=lambda: now + timedelta(seconds=2),
                           sleep=lambda _: None, retries=2)
            self.assertEqual(result, "stop_unconfirmed")
            self.assertEqual(calls, 3)
            self.assertEqual(self._events(record)[-1]["event"], "stop_unconfirmed")


if __name__ == "__main__":
    unittest.main()
