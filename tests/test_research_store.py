"""Immutable research record persistence tests (no network)."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from robot_debug.case_io import import_m4
from robot_debug.case_store import register_case
from robot_debug.evidence_packet import make_evidence_packet, packet_identity
from robot_debug.research_store import (
    ResearchStoreError,
    assign_sources,
    make_research_record,
    not_requested_summary,
    read_case_research,
    store_research_record,
    summary_text_violation,
    validate_research_record,
    validate_summary_content,
    with_summary,
)
from tests.test_case_io import fixture

MODEL = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
ENDPOINT = "https://api.tokenfactory.nebius.com/v1/"


def search_result(query, urls, retrieved_at="2026-10-12T09:00:00Z", **changes):
    value = {
        "query": query, "retrieved_at": retrieved_at, "request_id": "req-1",
        "response_time": 1.0, "credits": 1, "from_cache": False,
        "results": [{"title": f"Title {u}", "url": f"https://example.org/{u}",
                     "snippet": f"Snippet about {u}.", "score": 0.5} for u in urls],
    }
    value.update(changes)
    return value


def live_provenance(status="completed", code=None, **changes):
    tokens = status in ("completed", "invalid_response") and code != "invalid_response"
    value = {
        "source": "live", "provider": "nebius-token-factory", "model": MODEL,
        "endpoint": ENDPOINT, "created_at": "2026-10-12T10:00:00Z",
        "request_status": status, "error_code": code, "latency_seconds": 2.5,
        "prompt_tokens": 1000 if tokens else None,
        "completion_tokens": 100 if tokens else None,
        "estimated_cost_usd": 0.000084 if tokens else None,
        "billed_cost_usd": None, "reservation_usd": 0.01,
    }
    value.update(changes)
    return value


def interpreted(provenance=None, related=None, limitations=None):
    return {
        "status": "interpreted",
        "related_work": related if related is not None else [
            {"text": "Source S1 studies camera occlusion and matches this case.",
             "source_ids": ["S1", "S2"]}],
        "limitations": limitations if limitations is not None else [
            "Sources are public context, not evidence."],
        "provenance": provenance or live_provenance(),
    }


class ResearchStoreBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        fixture(self.source)
        self.workspace = self.base / "workspace"
        self.case = import_m4(self.source)
        register_case(self.case, self.source, self.workspace)
        self.case_id = self.case["case_id"]
        self.packet = make_evidence_packet(self.case, schema_version=2)
        self.queries = assign_sources([
            search_result("query one", ["a", "b"]),
            search_result("query two", ["b", "c"], retrieved_at="2026-10-12T09:00:05Z"),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def record(self, summary=None, queries=None, packet=None):
        return make_research_record(
            self.case_id, packet or self.packet, queries or self.queries,
            summary or not_requested_summary("2026-10-12T09:00:10Z"))

    @property
    def research_dir(self):
        return self.workspace / self.case_id / "research"

    def assert_invalid(self, value):
        with self.assertRaisesRegex(ResearchStoreError, "^invalid research record$"):
            validate_research_record(value)


class SourceTests(ResearchStoreBase):
    def test_source_ids_follow_query_order_and_duplicate_urls_are_dropped(self):
        self.assertEqual([[r["source_id"] for r in q["results"]] for q in self.queries],
                         [["S1", "S2"], ["S3"]])
        self.assertEqual(self.queries[1]["results"][0]["url"], "https://example.org/c")

    def test_duplicate_urls_ignore_case_fragment_and_trailing_slash(self):
        searches = [
            search_result("q1", ["x"]),
            {**search_result("q2", []), "results": [
                {"title": "T", "url": "https://EXAMPLE.org/x/#frag", "snippet": "", "score": 0.1},
                {"title": "T2", "url": "https://example.org:443/x", "snippet": "", "score": 0.1},
                {"title": "T3", "url": "https://example.org/y", "snippet": "", "score": 0.1}]},
        ]
        queries = assign_sources(searches)
        self.assertEqual([r["source_id"] for q in queries for r in q["results"]], ["S1", "S2"])

    def test_extra_search_fields_are_not_kept(self):
        self.assertEqual(set(self.queries[0]), {
            "query", "retrieved_at", "request_id", "credits", "from_cache", "results"})
        self.assertEqual(set(self.queries[0]["results"][0]), {
            "source_id", "title", "url", "snippet", "score"})

    def test_hand_edited_sources_are_invalid(self):
        record = self.record()
        mutations = [
            lambda r: r["queries"][0]["results"][0].update(source_id="S9"),
            lambda r: r["queries"][0]["results"][0].update(url="http://example.org/a"),
            lambda r: r["queries"][0]["results"][0].update(url="javascript:alert(1)"),
            lambda r: r["queries"][0]["results"][1].update(url=r["queries"][0]["results"][0]["url"]),
            lambda r: r["queries"][0]["results"][0].update(title="bad\x00title"),
            lambda r: r["queries"][0]["results"][0].update(snippet="s" * 601),
            lambda r: r["queries"][0]["results"][0].update(score=2),
            lambda r: r["queries"][0]["results"][0].update(extra=1),
            lambda r: r["queries"][0].update(query="café"),
            lambda r: r["queries"][0].update(retrieved_at="2026-02-30T00:00:00Z"),
            lambda r: r["queries"][0].update(from_cache=1),
            lambda r: r["queries"][0].update(credits=-1),
            lambda r: r["queries"][1].update(query=r["queries"][0]["query"]),
            lambda r: r.update(queries=[]),
            lambda r: r.update(queries=r["queries"] * 2),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                item = copy.deepcopy(record)
                mutate(item)
                self.assert_invalid(item)

    def test_at_most_five_results_per_query_and_three_queries(self):
        queries = assign_sources([search_result(f"q{i}", [f"{i}-{j}" for j in range(5)])
                                  for i in range(3)])
        record = self.record(queries=queries)
        self.assertEqual(len(record["queries"][2]["results"]), 5)
        self.assertEqual(record["queries"][2]["results"][4]["source_id"], "S15")
        with self.assertRaises(ResearchStoreError):
            self.record(queries=assign_sources(
                [search_result(f"q{i}", [f"{i}"]) for i in range(4)]))
        with self.assertRaises(ResearchStoreError):
            self.record(queries=assign_sources([search_result("q", list("abcdef"))]))


class RecordTests(ResearchStoreBase):
    def test_record_shape_and_identity(self):
        record = self.record()
        self.assertEqual(set(record), {"schema_version", "record_id", "case_id",
                                       "packet_id", "queries", "summary"})
        self.assertEqual(record["schema_version"], 1)
        self.assertEqual(record["case_id"], self.case_id)
        self.assertEqual(record["packet_id"], packet_identity(self.packet))
        self.assertEqual(set(record["summary"]),
                         {"status", "related_work", "limitations", "provenance"})
        self.assertEqual(record["summary"]["status"], "not_requested")
        body = {k: v for k, v in record.items() if k != "record_id"}
        expected = hashlib.sha256(json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(record["record_id"], expected)
        self.assertEqual(validate_research_record(record), record)

    def test_validation_is_detached_and_binds_every_field_to_the_id(self):
        record = self.record(interpreted())
        original = copy.deepcopy(record)
        checked = validate_research_record(record)
        checked["queries"][0]["results"][0]["title"] = "changed"
        self.assertEqual(record, original)
        mutations = [
            lambda r: r["queries"][0]["results"][0].update(title="changed"),
            lambda r: r["summary"]["related_work"][0].update(text="changed text"),
            lambda r: r["summary"]["limitations"].append("another"),
            lambda r: r["summary"]["provenance"].update(created_at="2026-10-13T00:00:00Z"),
            lambda r: r.update(packet_id="0" * 64),
            lambda r: r.update(case_id="1" * 64),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                item = copy.deepcopy(record)
                mutate(item)
                self.assert_invalid(item)

    def test_schema_ids_keys_and_size_are_strict(self):
        record = self.record()
        for field, value in (("schema_version", True), ("schema_version", 2),
                             ("case_id", "A" * 64), ("record_id", "0" * 64),
                             ("packet_id", "short")):
            item = copy.deepcopy(record)
            item[field] = value
            self.assert_invalid(item)
        item = copy.deepcopy(record)
        item["extra"] = 1
        self.assert_invalid(item)
        item = copy.deepcopy(record)
        item.pop("summary")
        self.assert_invalid(item)
        self.assert_invalid("not a dict")
        cyclic = copy.deepcopy(record)
        cyclic["summary"]["provenance"]["extra"] = cyclic
        self.assert_invalid(cyclic)

    def test_make_requires_a_v2_packet_and_a_valid_case_id(self):
        v1 = make_evidence_packet(self.case, schema_version=1)
        with self.assertRaises(ResearchStoreError):
            self.record(packet=v1)
        with self.assertRaises(ResearchStoreError):
            make_research_record("not-hex", self.packet, self.queries,
                                 not_requested_summary("2026-10-12T09:00:10Z"))
        with self.assertRaises(ResearchStoreError):
            make_research_record(self.case_id, {"schema_version": 2}, self.queries,
                                 not_requested_summary("2026-10-12T09:00:10Z"))

    def test_with_summary_keeps_sources_and_changes_the_record_id(self):
        base = self.record()
        summarized = with_summary(base, interpreted())
        self.assertNotEqual(summarized["record_id"], base["record_id"])
        self.assertEqual(summarized["queries"], base["queries"])
        self.assertEqual(summarized["packet_id"], base["packet_id"])
        self.assertEqual(summarized["summary"]["status"], "interpreted")


class SummaryTests(ResearchStoreBase):
    def test_not_requested_must_be_empty_and_offline(self):
        good = not_requested_summary("2026-10-12T09:00:10Z")
        self.assertEqual(self.record(good)["summary"], good)
        for change in ({"related_work": [{"text": "x", "source_ids": ["S1"]}]},
                       {"limitations": ["x"]}, {"status": "unknown"}, {"extra": 1}):
            with self.assertRaises(ResearchStoreError):
                self.record({**good, **change})
        for change in ({"source": "live"}, {"provider": "nebius-token-factory"},
                       {"request_status": "completed"}, {"reservation_usd": 0.01},
                       {"latency_seconds": 0.5}):
            with self.assertRaises(ResearchStoreError):
                self.record({**good, "provenance": {**good["provenance"], **change}})

    def test_interpreted_summary_round_trips_with_valid_cost(self):
        record = self.record(interpreted())
        self.assertEqual(record["summary"]["provenance"]["estimated_cost_usd"], 0.000084)
        self.assertEqual(validate_research_record(record), record)

    def test_interpreted_content_rules(self):
        ok = {"text": "Source S1 matches.", "source_ids": ["S1"]}
        bad_entries = [
            {"text": "See https://example.org/a", "source_ids": ["S1"]},
            {"text": "See HTTP://example.org/a", "source_ids": ["S1"]},
            {"text": "See www.example.org", "source_ids": ["S1"]},
            {"text": "See example.org for more", "source_ids": ["S1"]},
            {"text": "See [here](x) for more", "source_ids": ["S1"]},
            {"text": "x" * 401, "source_ids": ["S1"]},
            {"text": "", "source_ids": ["S1"]},
            {"text": " padded ", "source_ids": ["S1"]},
            {"text": "line\nbreak", "source_ids": ["S1"]},
            {"text": "Cites [S2] but only lists S1.", "source_ids": ["S1"]},
            {"text": "ok", "source_ids": []},
            {"text": "ok", "source_ids": ["S9"]},
            {"text": "ok", "source_ids": ["S1", "S1"]},
            {"text": "ok", "source_ids": ["S1", "S2", "S3", "S1"]},
            {"text": "ok", "source_ids": [1]},
            {"text": "ok", "source_ids": ["S1"], "extra": 1},
            {"text": "ok"},
        ]
        for entry in bad_entries:
            with self.subTest(entry=str(entry)[:40]):
                with self.assertRaises(ResearchStoreError):
                    self.record(interpreted(related=[entry]))
        for related in ([], [ok] * 5, "text", {}):
            with self.assertRaises(ResearchStoreError):
                self.record(interpreted(related=related))
        for limitations in ([], ["l"] * 4, [""], ["see https://a.example"], "text"):
            with self.assertRaises(ResearchStoreError):
                self.record(interpreted(limitations=limitations))
        cited = {"text": "Source [S1] and [S2] agree.", "source_ids": ["S1", "S2"]}
        self.record(interpreted(related=[cited, ok, ok, ok]))
        self.assertEqual(
            validate_summary_content([ok], ["lim"], ["S1"]), ([ok], ["lim"]))

    def test_stored_summaries_share_the_address_and_causal_claim_rules(self):
        bad_texts = [
            "Log in at bit.ly/abc to view [S1]",
            "See evil.xyz/login [S1]",
            "See arxiv" + chr(0x3002) + "org [S1]",
            "See arxiv" + chr(0xff0e) + "org [S1]",
            "This proves the gripper firmware caused the failure [S1]",
            "A causal link [S1]",
        ]
        for text in bad_texts:
            with self.subTest(text=text[:30]):
                entry = {"text": text, "source_ids": ["S1"]}
                with self.assertRaises(ResearchStoreError):
                    self.record(interpreted(related=[entry]))
                with self.assertRaises(ResearchStoreError):
                    self.record(interpreted(limitations=[text]))
        # A previously stored record is judged by the same rules when it is read back.
        stored = self.record(interpreted())
        tampered = json.loads(json.dumps(stored))
        tampered["summary"]["related_work"][0]["text"] = "Proof that evil.xyz is right [S1]"
        with self.assertRaises(ResearchStoreError):
            validate_research_record(tampered)
        self.assertIsNone(summary_text_violation("GR00T N1.7 at 0.375, x=0.625, 14% (e.g. LIBERO-Object)"))
        self.assertEqual(summary_text_violation("see bit.ly/abc"), "web address")
        self.assertEqual(summary_text_violation("it was caused by"), "proof or causation claim")

    def test_rejected_and_provider_error_statuses(self):
        rejected = {"status": "rejected", "related_work": [], "limitations": [],
                    "provenance": live_provenance("invalid_response", "invalid_response")}
        self.record(rejected)
        limited = live_provenance("invalid_response", "output_limit",
                                  prompt_tokens=1000, completion_tokens=1500,
                                  estimated_cost_usd=0.00042)
        self.record({**rejected, "provenance": limited})
        provider = {"status": "provider_error", "related_work": [], "limitations": [],
                    "provenance": live_provenance("transport_error", "timeout")}
        self.record(provider)
        self.record({**provider, "provenance": live_provenance("http_error", "http_error")})
        self.record({**provider, "provenance": live_provenance(
            "http_error", "authentication_failed")})
        for status, provenance in (
                ("rejected", live_provenance("completed")),
                ("provider_error", live_provenance("completed")),
                ("interpreted", live_provenance("http_error", "http_error")),
                ("rejected", live_provenance("http_error", "http_error")),
                ("provider_error", live_provenance("invalid_response", "invalid_response"))):
            with self.assertRaises(ResearchStoreError):
                self.record({"status": status, "related_work": [], "limitations": [],
                             "provenance": provenance})
        with self.assertRaises(ResearchStoreError):
            self.record({**rejected, "related_work": [
                {"text": "rejected content must not be stored", "source_ids": ["S1"]}]})
        with self.assertRaises(ResearchStoreError):
            self.record({**rejected, "limitations": ["kept?"]})

    def test_live_provenance_cost_and_bounds_are_checked(self):
        changes = [
            {"estimated_cost_usd": 0.01}, {"estimated_cost_usd": 0.5},
            {"estimated_cost_usd": 0.0}, {"reservation_usd": 0.02}, {"reservation_usd": 0},
            {"billed_cost_usd": 0}, {"completion_tokens": 1501, "estimated_cost_usd": 0.0004},
            {"prompt_tokens": True}, {"prompt_tokens": None}, {"latency_seconds": -1},
            {"latency_seconds": float("inf")}, {"model": "other"}, {"provider": None},
            {"created_at": "2026-10-12T10:00:00+00:00"}, {"extra": 1},
        ]
        for change in changes:
            with self.subTest(change=change):
                with self.assertRaises(ResearchStoreError):
                    self.record(interpreted(provenance=live_provenance(**change)))
        missing = live_provenance()
        missing.pop("endpoint")
        with self.assertRaises(ResearchStoreError):
            self.record(interpreted(provenance=missing))
        unknown_usage = live_provenance(prompt_tokens=None, completion_tokens=None,
                                        estimated_cost_usd=None)
        self.record(interpreted(provenance=unknown_usage))


class StorageTests(ResearchStoreBase):
    def test_round_trip_uses_record_hash_filename(self):
        record = self.record()
        path = store_research_record(self.workspace, record)
        self.assertEqual(path, self.research_dir / (record["record_id"] + ".json"))
        self.assertEqual(read_case_research(self.workspace, self.case_id),
                         {"records": [record], "warnings": []})

    def test_missing_directory_reads_empty(self):
        self.assertEqual(read_case_research(self.workspace, self.case_id),
                         {"records": [], "warnings": []})

    def test_store_is_idempotent_exclusive_and_leaves_no_temporaries(self):
        record = self.record()
        first = store_research_record(self.workspace, record)
        self.assertEqual(store_research_record(self.workspace, copy.deepcopy(record)), first)
        self.assertEqual([p.name for p in self.research_dir.iterdir()],
                         [record["record_id"] + ".json"])
        self.assertEqual(sorted(p.name for p in (self.workspace / self.case_id).iterdir()),
                         ["case.json", "local-source.json", "research"])
        first.write_text("{}", encoding="utf-8")
        with self.assertRaises(ResearchStoreError):
            store_research_record(self.workspace, record)

    def test_store_does_not_modify_sources(self):
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.source.rglob("*") if p.is_file()}
        store_research_record(self.workspace, self.record())
        after = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in self.source.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_store_rejects_a_record_for_a_different_packet(self):
        other = copy.deepcopy(self.packet)
        other["episodes"][0]["role"] = "other"
        record = self.record(packet=other)
        with self.assertRaisesRegex(ResearchStoreError, "^research case is unavailable or changed$"):
            store_research_record(self.workspace, record)
        self.assertFalse(self.research_dir.exists())

    def test_store_rejects_changed_source_and_unknown_case(self):
        record = self.record()
        replay = self.source / "failure-reduction" / "replay_case.json"
        data = json.loads(replay.read_text())
        data["seed"] = 99
        replay.write_text(json.dumps(data))
        with self.assertRaisesRegex(ResearchStoreError, "^research case is unavailable or changed$"):
            store_research_record(self.workspace, record)
        unknown = dict(record, case_id="9" * 64)
        with self.assertRaises(ResearchStoreError):
            store_research_record(self.workspace, unknown)

    def test_store_rechecks_the_case_immediately_before_publication(self):
        from robot_debug import explanation_store
        real = explanation_store.inspect_case
        calls = 0

        def changing(workspace, case_id):
            nonlocal calls
            calls += 1
            result = real(workspace, case_id)
            if calls == 1:
                replay = self.source / "failure-reduction" / "replay_case.json"
                data = json.loads(replay.read_text())
                data["seed"] = 23
                replay.write_text(json.dumps(data))
            return result

        with patch.object(explanation_store, "inspect_case", side_effect=changing):
            with self.assertRaisesRegex(ResearchStoreError, "^research case is unavailable or changed$"):
                store_research_record(self.workspace, self.record())
        self.assertFalse(any(p.suffix == ".json" for p in self.research_dir.iterdir()))

    def test_concurrent_identical_publication_has_one_valid_file(self):
        record = self.record()
        barrier = threading.Barrier(4)
        paths, errors = [], []

        def publish():
            try:
                barrier.wait()
                paths.append(store_research_record(self.workspace, copy.deepcopy(record)))
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=publish) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(set(paths)), 1)
        self.assertEqual([p.name for p in self.research_dir.iterdir()],
                         [record["record_id"] + ".json"])

    def test_records_sort_oldest_to_newest_by_creation_then_id(self):
        searched = self.record()
        summarized = with_summary(searched, interpreted())
        later_search = self.record(summary=not_requested_summary("2026-10-12T11:00:00Z"))
        for item in (later_search, summarized, searched):
            store_research_record(self.workspace, item)
        result = read_case_research(self.workspace, self.case_id)
        self.assertEqual(result["warnings"], [])
        self.assertEqual([r["record_id"] for r in result["records"]],
                         [searched["record_id"], summarized["record_id"],
                          later_search["record_id"]])
        tie_a = self.record(summary=not_requested_summary("2026-10-12T12:00:00Z"),
                            queries=assign_sources([search_result("tie one", ["t1"])]))
        tie_b = self.record(summary=not_requested_summary("2026-10-12T12:00:00Z"),
                            queries=assign_sources([search_result("tie two", ["t2"])]))
        for item in (tie_a, tie_b):
            store_research_record(self.workspace, item)
        tail = read_case_research(self.workspace, self.case_id)["records"][-2:]
        self.assertEqual([r["record_id"] for r in tail],
                         sorted([tie_a["record_id"], tie_b["record_id"]]))

    def test_read_isolates_corrupt_oversize_and_misnamed_files(self):
        older = self.record()
        newer = self.record(summary=not_requested_summary("2026-10-12T09:30:00Z"))
        store_research_record(self.workspace, newer)
        store_research_record(self.workspace, older)
        (self.research_dir / ("a" * 64 + ".json")).write_text("{bad", encoding="utf-8")
        (self.research_dir / ("b" * 64 + ".json")).write_bytes(b"x" * 131_073)
        (self.research_dir / ("c" * 64 + ".json")).write_text(json.dumps(older), encoding="utf-8")
        (self.research_dir / "notes.txt").write_text("stray", encoding="utf-8")
        result = read_case_research(self.workspace, self.case_id)
        self.assertEqual([r["record_id"] for r in result["records"]],
                         [older["record_id"], newer["record_id"]])
        self.assertEqual(result["warnings"],
                         ["one or more research records are unavailable or invalid"])

    def test_read_rejects_duplicate_keys_invalid_utf8_and_integer_bombs(self):
        record = self.record()
        path = store_research_record(self.workspace, record)
        path.write_text(path.read_text().replace("{", '{"schema_version":1,', 1),
                        encoding="utf-8")
        self.assertEqual(read_case_research(self.workspace, self.case_id)["records"], [])
        path.write_bytes(b"\xff")
        self.assertEqual(read_case_research(self.workspace, self.case_id)["records"], [])
        path.write_bytes(b'{"schema_version":' + b"9" * 5000 + b"}")
        result = read_case_research(self.workspace, self.case_id)
        self.assertEqual(result["records"], [])
        self.assertEqual(len(result["warnings"]), 1)

    def test_record_for_another_packet_is_hidden_with_a_warning(self):
        other = copy.deepcopy(self.packet)
        other["episodes"][0]["role"] = "other"
        stale = self.record(packet=other)
        self.research_dir.mkdir()
        (self.research_dir / (stale["record_id"] + ".json")).write_text(
            json.dumps(stale), encoding="utf-8")
        current = self.record()
        store_research_record(self.workspace, current)
        self.assertEqual(read_case_research(self.workspace, self.case_id), {
            "records": [current],
            "warnings": ["one or more research records do not match the current case evidence"]})

    def test_record_filed_under_another_case_is_ignored(self):
        record = self.record()
        other_case = dict(record)
        self.research_dir.mkdir()
        body = {k: v for k, v in record.items() if k != "record_id"}
        body["case_id"] = "7" * 64
        foreign = dict(body, record_id=hashlib.sha256(json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest())
        (self.research_dir / (foreign["record_id"] + ".json")).write_text(
            json.dumps(foreign), encoding="utf-8")
        result = read_case_research(self.workspace, self.case_id)
        self.assertEqual(result["records"], [])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertEqual(other_case, record)

    def test_read_fails_closed_after_50_entries(self):
        self.research_dir.mkdir()
        for index in range(51):
            (self.research_dir / f"junk-{index}").write_text("x")
        self.assertEqual(read_case_research(self.workspace, self.case_id),
                         {"records": [], "warnings": ["research collection exceeds the scan limit"]})

    def test_in_progress_temporary_files_are_not_records_or_corruption(self):
        record = self.record()
        store_research_record(self.workspace, record)
        for index in range(60):
            name = f".{index:064x}.{index:016x}.tmp"
            (self.research_dir / name).write_text("partial")
        self.assertEqual(read_case_research(self.workspace, self.case_id),
                         {"records": [record], "warnings": []})
        # Lookalike names that are not exact temporary files still warn.
        (self.research_dir / f".{'a' * 64}.nothex.tmp").write_text("x")
        self.assertEqual(read_case_research(self.workspace, self.case_id)["warnings"],
                         ["one or more research records are unavailable or invalid"])

    def test_temporary_files_cannot_make_the_directory_scan_unbounded(self):
        self.research_dir.mkdir()
        for index in range(201):
            (self.research_dir / f".{index:064x}.{index:016x}.tmp").write_text("partial")
        self.assertEqual(read_case_research(self.workspace, self.case_id),
                         {"records": [], "warnings": ["research collection exceeds the scan limit"]})

    def test_stale_case_returns_no_records_and_a_fixed_warning(self):
        store_research_record(self.workspace, self.record())
        (self.source / "failure-reduction" / "replay_case.json").unlink()
        self.assertEqual(read_case_research(self.workspace, self.case_id),
                         {"records": [], "warnings": ["case evidence is unavailable or changed"]})
        self.assertEqual(read_case_research(self.workspace, "f" * 64),
                         {"records": [], "warnings": ["case evidence is unavailable or changed"]})
        self.assertEqual(read_case_research(self.workspace, "../x"),
                         {"records": [], "warnings": ["case evidence is unavailable or changed"]})

    def test_source_change_during_read_discards_results(self):
        store_research_record(self.workspace, self.record())
        from robot_debug import explanation_store
        real = explanation_store.inspect_case
        calls = 0

        def changing(workspace, case_id):
            nonlocal calls
            calls += 1
            result = real(workspace, case_id)
            if calls == 1:
                replay = self.source / "failure-reduction" / "replay_case.json"
                data = json.loads(replay.read_text())
                data["seed"] = 17
                replay.write_text(json.dumps(data))
            return result

        with patch.object(explanation_store, "inspect_case", side_effect=changing):
            result = read_case_research(self.workspace, self.case_id)
        self.assertEqual(result["records"], [])
        self.assertIn("case evidence is unavailable or changed", result["warnings"])

    def test_symlinked_research_directory_and_file_are_rejected(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        other = self.base / "other"
        other.mkdir()
        record = self.record()
        try:
            os.symlink(other, self.research_dir, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks unavailable")
        with self.assertRaises(ResearchStoreError):
            store_research_record(self.workspace, record)
        self.assertEqual(list(other.iterdir()), [])
        self.research_dir.unlink()
        path = store_research_record(self.workspace, record)
        outside = self.base / "outside.json"
        outside.write_text(path.read_text())
        path.unlink()
        os.symlink(outside, path)
        self.assertEqual(read_case_research(self.workspace, self.case_id)["records"], [])

    def _assert_ancestor_link_refused(self, alias):
        from robot_debug import explanation_store
        via = alias / "workspace"
        with patch.object(explanation_store, "inspect_case",
                          wraps=explanation_store.inspect_case) as inspect:
            with self.assertRaises(ResearchStoreError):
                store_research_record(via, self.record())
            self.assertEqual(read_case_research(via, self.case_id)["records"], [])
            inspect.assert_not_called()
        self.assertFalse(self.research_dir.exists())

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
        result = subprocess.run(
            [str(Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"),
             "/c", "mklink", "/J", "alias", "."],
            cwd=self.base, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, "temporary junction creation failed")
        try:
            self._assert_ancestor_link_refused(alias)
        finally:
            alias.rmdir()


if __name__ == "__main__":
    unittest.main()
