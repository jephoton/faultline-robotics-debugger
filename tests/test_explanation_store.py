"""Immutable, evidence-bound explanation report persistence tests."""
import copy
import hashlib
import json
import math
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from robot_debug.case_io import import_m4
from robot_debug.case_store import register_case
from robot_debug.evidence_packet import make_evidence_packet
from robot_debug.explanation import build_offline_report
from robot_debug.explanation_store import (
    ExplanationStoreError, make_stored_report, read_case_reports, store_report,
    validate_stored_report,
)
from tests.test_case_io import fixture


class ExplanationStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        fixture(self.source)
        self.workspace = self.base / "workspace"
        self.case = import_m4(self.source)
        register_case(self.case, self.source, self.workspace)
        self.packet = make_evidence_packet(self.case)
        self.provenance = {
            "source": "offline", "provider": None, "model": None, "endpoint": None,
            "created_at": "2026-10-05T12:34:56Z", "request_status": "offline",
            "error_code": None, "latency_seconds": None, "prompt_tokens": None,
            "completion_tokens": None, "estimated_cost_usd": None,
            "billed_cost_usd": None, "reservation_usd": 0,
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_offline_round_trip_uses_report_hash_filename(self):
        record = make_stored_report(
            self.case["case_id"], self.packet, build_offline_report(self.packet), self.provenance)
        path = store_report(self.workspace, record)
        self.assertEqual(path.name, record["report_id"] + ".json")
        self.assertEqual(read_case_reports(self.workspace, self.case["case_id"]),
                         {"reports": [record], "warnings": []})

    def record(self, report=None, provenance=None):
        return make_stored_report(self.case["case_id"], self.packet,
                                  report or build_offline_report(self.packet),
                                  provenance or self.provenance)

    def live(self, **changes):
        value = {
            "source": "live", "provider": "nebius-token-factory",
            "model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
            "endpoint": "https://api.tokenfactory.nebius.com/v1/",
            "created_at": "2026-10-05T12:34:57Z", "request_status": "completed",
            "error_code": None, "latency_seconds": 1.25, "prompt_tokens": 100,
            "completion_tokens": 50, "estimated_cost_usd": 0.000018,
            "billed_cost_usd": None, "reservation_usd": 0.02,
        }
        value.update(changes)
        return value

    def assert_invalid(self, value):
        with self.assertRaisesRegex(ExplanationStoreError, "^invalid stored report$"):
            validate_stored_report(value)

    def test_validation_is_exact_detached_and_recomputes_report(self):
        interpretation = {"schema_version": 1, "observations": [], "hypotheses": [],
                          "limitations": []}
        report = build_offline_report(self.packet, json.dumps(interpretation))
        record = self.record(report, self.live())
        original = copy.deepcopy(record)
        checked = validate_stored_report(record)
        self.assertEqual(checked, record)
        checked["packet"]["episodes"][0]["role"] = "other"
        self.assertEqual(record, original)
        for field in ("facts", "packet_id", "disclaimer"):
            forged = copy.deepcopy(record)
            forged["report"][field] = {} if field == "facts" else "forged"
            self.assert_invalid(forged)

    def test_rejected_report_is_rederived_without_preserving_bad_input(self):
        rejected = build_offline_report(self.packet, "private malformed prose")
        record = self.record(rejected, self.live(request_status="invalid_response",
                                                 error_code="invalid_response"))
        self.assertEqual(validate_stored_report(record), record)
        forged = copy.deepcopy(record); forged["report"]["interpretation"] = "private"
        self.assert_invalid(forged)

    def test_schema_ids_keys_packet_and_hash_are_strict(self):
        record = self.record()
        bad = []
        for field, value in (("schema_version", True), ("schema_version", 2),
                             ("case_id", "A" * 64), ("report_id", "0" * 64)):
            item = copy.deepcopy(record); item[field] = value; bad.append(item)
        item = copy.deepcopy(record); item["extra"] = 1; bad.append(item)
        item = copy.deepcopy(record); item.pop("packet"); bad.append(item)
        item = copy.deepcopy(record); item["packet"]["schema_version"] = True; bad.append(item)
        for item in bad: self.assert_invalid(item)

    def test_provenance_rejects_unknown_missing_nonfinite_bounds_and_contradictions(self):
        valid = self.record(provenance=self.live())
        changes = [
            {"created_at": "2026-02-30T00:00:00Z"}, {"created_at": "2026-10-05T12:34:56+00:00"},
            {"latency_seconds": True}, {"latency_seconds": math.inf}, {"latency_seconds": -1},
            {"prompt_tokens": True}, {"prompt_tokens": 262145}, {"completion_tokens": 4097},
            {"estimated_cost_usd": 0.02}, {"billed_cost_usd": 0},
            {"reservation_usd": 0}, {"provider": None}, {"model": "other"},
            {"request_status": "transport_error", "error_code": "http_error"},
            {"request_status": "completed", "error_code": "timeout"},
            {"request_status": "completed", "error_code": "output_limit"},
            {"request_status": "invalid_response", "error_code": "private"},
            {"prompt_tokens": None}, {"completion_tokens": None},
        ]
        for change in changes:
            item = copy.deepcopy(valid); item["provenance"].update(change); self.assert_invalid(item)
        for mutation in ("extra", "missing"):
            item = copy.deepcopy(valid)
            if mutation == "extra": item["provenance"]["private"] = "secret"
            else: item["provenance"].pop("endpoint")
            self.assert_invalid(item)
        offline = self.record()
        for change in ({"latency_seconds": 0}, {"provider": "nebius-token-factory"},
                       {"reservation_usd": 0.02}, {"request_status": "completed"}):
            item = copy.deepcopy(offline); item["provenance"].update(change); self.assert_invalid(item)

    def test_live_error_status_matrix_and_unknown_usage_are_valid(self):
        cases = [
            ("transport_error", "timeout"), ("http_error", "http_error"),
            ("http_error", "authentication_failed"), ("http_error", "catalog_missing"),
            ("invalid_response", "invalid_response"),
            ("invalid_response", "output_limit"),
        ]
        for status, code in cases:
            provenance = self.live(request_status=status, error_code=code, prompt_tokens=None,
                                   completion_tokens=None, estimated_cost_usd=None)
            self.assertEqual(validate_stored_report(self.record(provenance=provenance))["provenance"], provenance)

    def test_live_reports_round_trip_new_limit_legacy_limit_and_output_fallback(self):
        completed = self.live(completion_tokens=4096,
                              estimated_cost_usd=0.00098904)
        completed_record = self.record(provenance=completed)
        self.assertEqual(validate_stored_report(completed_record), completed_record)

        legacy = self.live(completion_tokens=600, estimated_cost_usd=0.00015)
        legacy_record = self.record(provenance=legacy)
        self.assertEqual(legacy_record["report_id"],
                         "81a8de7f3734074371485378da1a2d47cc04b0eccbff78531eb771ba1b53c8c3")
        self.assertEqual(validate_stored_report(legacy_record), legacy_record)

        fallback = self.live(
            request_status="invalid_response", error_code="output_limit",
            completion_tokens=4096, estimated_cost_usd=0.00098904)
        fallback_record = self.record(provenance=fallback)
        self.assertEqual(validate_stored_report(fallback_record), fallback_record)
        for record in (completed_record, legacy_record, fallback_record):
            store_report(self.workspace, record)
        round_tripped = read_case_reports(self.workspace, self.case["case_id"])
        self.assertEqual(round_tripped["warnings"], [])
        self.assertEqual(
            {record["report_id"] for record in round_tripped["reports"]},
            {completed_record["report_id"], legacy_record["report_id"],
             fallback_record["report_id"]})

    def test_cycles_encoding_depth_and_size_have_fixed_error(self):
        record = self.record()
        cyclic = copy.deepcopy(record); cyclic["provenance"]["extra"] = cyclic
        self.assert_invalid(cyclic)
        surrogate = copy.deepcopy(record); surrogate["provenance"]["created_at"] = "\ud800"
        self.assert_invalid(surrogate)
        deep = copy.deepcopy(record); cursor = deep["report"]
        for _ in range(300): cursor["x"] = {}; cursor = cursor["x"]
        self.assert_invalid(deep)
        huge = copy.deepcopy(record); huge["provenance"]["extra"] = "x" * 70000
        self.assert_invalid(huge)

    def test_store_is_idempotent_exclusive_and_does_not_modify_sources(self):
        record = self.record()
        source_hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in self.source.rglob("*") if p.is_file()}
        first = store_report(self.workspace, record)
        self.assertEqual(store_report(self.workspace, copy.deepcopy(record)), first)
        self.assertEqual(source_hashes, {p: hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in self.source.rglob("*") if p.is_file()})
        self.assertEqual(sorted(p.name for p in first.parent.parent.iterdir()),
                         ["case.json", "local-source.json", "reports"])
        first.write_text("{}", encoding="utf-8")
        with self.assertRaises(ExplanationStoreError): store_report(self.workspace, record)

    def test_store_rejects_packet_mismatch_and_changed_source(self):
        record = self.record()
        mismatch = copy.deepcopy(record)
        mismatch["packet"]["episodes"][0]["role"] = "other"
        mismatch = make_stored_report(self.case["case_id"], mismatch["packet"],
                                      build_offline_report(mismatch["packet"]), self.provenance)
        with self.assertRaisesRegex(ExplanationStoreError, "^report case is unavailable or changed$"):
            store_report(self.workspace, mismatch)
        replay = self.source / "failure-reduction" / "replay_case.json"
        data = json.loads(replay.read_text()); data["seed"] = 99; replay.write_text(json.dumps(data))
        with self.assertRaisesRegex(ExplanationStoreError, "^report case is unavailable or changed$"):
            store_report(self.workspace, record)

    def test_store_rechecks_source_immediately_before_publication(self):
        record = self.record()
        from robot_debug import explanation_store
        real = explanation_store.inspect_case
        calls = 0
        def changing(workspace, case_id):
            nonlocal calls
            calls += 1
            result = real(workspace, case_id)
            if calls == 1:
                replay = self.source / "failure-reduction" / "replay_case.json"
                data = json.loads(replay.read_text()); data["seed"] = 23
                replay.write_text(json.dumps(data))
            return result
        with patch.object(explanation_store, "inspect_case", side_effect=changing):
            with self.assertRaisesRegex(ExplanationStoreError, "^report case is unavailable or changed$"):
                store_report(self.workspace, record)
        reports = self.workspace / self.case["case_id"] / "reports"
        self.assertFalse(any(p.suffix == ".json" for p in reports.iterdir()))

    def test_concurrent_identical_publication_has_one_valid_file(self):
        record = self.record()
        barrier = threading.Barrier(4)
        paths, errors = [], []
        def publish():
            try:
                barrier.wait()
                paths.append(store_report(self.workspace, copy.deepcopy(record)))
            except BaseException as exc:
                errors.append(exc)
        threads = [threading.Thread(target=publish) for _ in range(4)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(set(paths)), 1)
        reports = self.workspace / self.case["case_id"] / "reports"
        self.assertEqual([p.name for p in reports.iterdir()], [record["report_id"] + ".json"])
        self.assertEqual(read_case_reports(self.workspace, self.case["case_id"])["reports"], [record])

    def test_read_sorts_and_isolates_corrupt_oversize_and_wrong_filename(self):
        older = self.record()
        newer = self.record(provenance={**self.provenance, "created_at": "2026-10-05T12:34:57Z"})
        store_report(self.workspace, newer); store_report(self.workspace, older)
        reports = self.workspace / self.case["case_id"] / "reports"
        (reports / ("a" * 64 + ".json")).write_text("{bad", encoding="utf-8")
        (reports / ("b" * 64 + ".json")).write_bytes(b"x" * 65537)
        (reports / ("c" * 64 + ".json")).write_text(json.dumps(older), encoding="utf-8")
        result = read_case_reports(self.workspace, self.case["case_id"])
        self.assertEqual([r["report_id"] for r in result["reports"]],
                         [older["report_id"], newer["report_id"]])
        self.assertEqual(result["warnings"], ["one or more report records are unavailable or invalid"])

    def test_read_rejects_duplicate_json_keys_and_invalid_utf8(self):
        record = self.record(); path = store_report(self.workspace, record)
        duplicate = path.read_text().replace('{', '{"schema_version":1,', 1)
        path.write_text(duplicate, encoding="utf-8")
        result = read_case_reports(self.workspace, self.case["case_id"])
        self.assertEqual(result["reports"], [])
        self.assertEqual(len(result["warnings"]), 1)
        path.write_bytes(b"\xff")
        self.assertEqual(read_case_reports(self.workspace, self.case["case_id"])["reports"], [])

    def test_read_isolates_integer_conversion_limit_from_valid_report(self):
        record = self.record()
        path = store_report(self.workspace, record)
        (path.parent / ("a" * 64 + ".json")).write_bytes(
            b'{"schema_version":' + b"9" * 5000 + b"}")
        self.assertEqual(read_case_reports(self.workspace, self.case["case_id"]),
                         {"reports": [record], "warnings": [
                             "one or more report records are unavailable or invalid"]})

    def _assert_ancestor_link_refused(self, alias):
        from robot_debug import explanation_store
        via = alias / "workspace"
        record = self.record()
        with patch.object(explanation_store, "inspect_case",
                          wraps=explanation_store.inspect_case) as inspect:
            with self.assertRaises(ExplanationStoreError):
                store_report(via, record)
            self.assertEqual(read_case_reports(via, self.case["case_id"])["reports"], [])
            inspect.assert_not_called()
        self.assertFalse((self.workspace / self.case["case_id"] / "reports").exists())

    def test_workspace_ancestor_symlink_refused_before_inspection(self):
        alias = self.base / "alias"
        try:
            os.symlink(self.base, alias, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks unavailable")
        try:
            self._assert_ancestor_link_refused(alias)
        finally:
            alias.unlink()

    @unittest.skipUnless(os.name == "nt", "Windows junctions only")
    def test_workspace_ancestor_junction_refused_before_inspection(self):
        alias = self.base / "alias"
        # Relative names keep cmd's junction syntax independent of temp-path quoting.
        result = subprocess.run(
            [str(Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"),
             "/c", "mklink", "/J", "alias", "."],
            cwd=self.base, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, "temporary junction creation failed")
        try:
            self._assert_ancestor_link_refused(alias)
        finally:
            alias.rmdir()

    def test_read_fails_closed_after_100_entries_without_unbounded_processing(self):
        reports = self.workspace / self.case["case_id"] / "reports"; reports.mkdir()
        for index in range(101):
            (reports / f"junk-{index}").write_text("x")
        result = read_case_reports(self.workspace, self.case["case_id"])
        self.assertEqual(result, {"reports": [], "warnings": ["report collection exceeds the scan limit"]})

    def test_stale_case_returns_no_interpretations_and_fixed_warning(self):
        store_report(self.workspace, self.record())
        replay = self.source / "failure-reduction" / "replay_case.json"; replay.unlink()
        self.assertEqual(read_case_reports(self.workspace, self.case["case_id"]),
                         {"reports": [], "warnings": ["case evidence is unavailable or changed"]})

    def test_symlink_case_report_directory_and_file_are_rejected(self):
        if not hasattr(os, "symlink"): self.skipTest("symlinks unavailable")
        other = self.base / "other"; other.mkdir()
        case_dir = self.workspace / self.case["case_id"]
        moved = self.base / "real-case"; case_dir.rename(moved)
        try: os.symlink(moved, case_dir, target_is_directory=True)
        except OSError: self.skipTest("symlinks unavailable")
        with self.assertRaises(ExplanationStoreError): store_report(self.workspace, self.record())
        case_dir.unlink(); moved.rename(case_dir)
        reports = case_dir / "reports"; os.symlink(other, reports, target_is_directory=True)
        with self.assertRaises(ExplanationStoreError): store_report(self.workspace, self.record())
        reports.unlink(); path = store_report(self.workspace, self.record())
        target = self.base / "outside.json"; target.write_text(path.read_text()); path.unlink()
        os.symlink(target, path)
        self.assertEqual(read_case_reports(self.workspace, self.case["case_id"])["reports"], [])

    def test_source_change_during_read_discards_results(self):
        store_report(self.workspace, self.record())
        from robot_debug import explanation_store
        real = explanation_store.inspect_case
        calls = 0
        def changing(workspace, case_id):
            nonlocal calls
            calls += 1
            result = real(workspace, case_id)
            if calls == 1:
                replay = self.source / "failure-reduction" / "replay_case.json"
                data = json.loads(replay.read_text()); data["seed"] = 17
                replay.write_text(json.dumps(data))
            return result
        with patch.object(explanation_store, "inspect_case", side_effect=changing):
            result = read_case_reports(self.workspace, self.case["case_id"])
        self.assertEqual(result["reports"], [])
        self.assertIn("case evidence is unavailable or changed", result["warnings"])


if __name__ == "__main__":
    unittest.main()
