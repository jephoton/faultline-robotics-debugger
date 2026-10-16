"""The cached evidence catalog and its payload (ADR 0033)."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.request import urlopen

from robot_debug.viewer import evidence as ev
from robot_debug.viewer import server as viewer_server
from robot_debug.viewer.catalog import ArtifactCatalog, CatalogSnapshot
from tests.test_viewer_catalog import write_episode


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class CacheTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        write_episode(self.root, "first", success=True)
        self.clock = Clock()

    def catalog(self, **options):
        options.setdefault("clock", self.clock)
        return ev.CachedArtifactCatalog(self.root, **options)

    def test_two_concurrent_requests_scan_once_and_share_the_result(self):
        started, release = threading.Event(), threading.Event()
        calls = []
        real = ArtifactCatalog.snapshot

        def slow(self_):
            calls.append(threading.current_thread().name)
            started.set()
            release.wait(5)
            return real(self_)

        catalog = self.catalog()
        results = []
        with mock.patch.object(ArtifactCatalog, "snapshot", slow):
            threads = [threading.Thread(target=lambda: results.append(catalog.snapshot())) for _ in range(4)]
            for thread in threads:
                thread.start()
            self.assertTrue(started.wait(5))
            time.sleep(0.1)                         # the others are now waiting on the lock
            release.set()
            for thread in threads:
                thread.join(10)
        self.assertEqual(len(calls), 1, "one scan, however many callers")
        self.assertEqual(catalog.scans, 1)
        self.assertEqual(len(results), 4)
        self.assertTrue(all(r is results[0] for r in results))
        self.assertEqual(len(results[0].episodes), 1)

    def test_an_unchanged_tree_is_not_scanned_again(self):
        catalog = self.catalog(recheck_seconds=10)
        first = catalog.snapshot()
        self.clock.now += 5
        self.assertIs(catalog.snapshot(), first)
        self.clock.now += 60                         # past the recheck time: the tree is looked at, found unchanged
        self.assertIs(catalog.snapshot(), first)
        self.assertEqual(catalog.scans, 1)

    def test_a_new_file_after_the_recheck_time_triggers_one_new_scan(self):
        catalog = self.catalog(recheck_seconds=10)
        self.assertEqual(len(catalog.snapshot().episodes), 1)
        write_episode(self.root, "second", success=False)
        future = time.time() + 5
        os.utime(str(self.root / "second"), (future, future))
        self.clock.now += 5
        self.assertEqual(len(catalog.snapshot().episodes), 1, "trusted until the recheck time")
        self.clock.now += 60
        self.assertEqual(len(catalog.snapshot().episodes), 2)
        self.assertEqual(catalog.scans, 2)

    def test_the_stamp_is_the_newest_modification_anywhere_under_the_root(self):
        before = ev.newest_modification(self.root)
        deep = self.root / "first" / "episodes" / "libero-object" / "late.txt"
        deep.write_text("x", encoding="utf-8")
        future = time.time() + 100
        os.utime(str(deep), (future, future))
        self.assertAlmostEqual(ev.newest_modification(self.root), future, delta=2)
        self.assertGreater(ev.newest_modification(self.root), before)
        self.assertEqual(ev.newest_modification(self.root / "missing"), 0.0)

    def test_the_cached_catalog_still_serves_traces_and_media_paths(self):
        catalog = self.catalog()
        episode = catalog.list_episodes()[0]
        self.assertEqual(len(catalog.load_trace(episode.episode_id)["points"]), 2)
        self.assertTrue(catalog.resolve_media(episode.video_path).is_file())
        self.assertEqual(catalog.scans, 1)


class PayloadTests(unittest.TestCase):
    def test_rows_have_urls_not_paths_and_scrubbed_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_episode(root, "failed", success=False, failure_reason="exception")
            snapshot = ev.CachedArtifactCatalog(root).snapshot()
            payload = ev.evidence_payload(snapshot)
        [row] = payload["episodes"]
        self.assertEqual(row["outcome"], "infrastructure_error")
        self.assertEqual(row["video_url"], "/media/failed/episodes/libero-object/task0000_ep0000_error.mp4")
        self.assertEqual(row["trace_url"], "/api/episodes/{}/trace".format(row["episode_id"]))
        self.assertEqual(sorted(row), sorted([
            "episode_id", "run_name", "benchmark", "created_at", "instruction", "outcome", "steps", "elapsed_seconds",
            "task_id", "episode_index", "perturbation", "failure_detail", "video_url", "trace_url"]))
        self.assertNotIn("video_path", row)
        self.assertNotIn(directory.replace("\\", "\\\\"), json.dumps(payload))

    def test_failure_text_with_a_local_path_is_scrubbed(self):
        snapshot = CatalogSnapshot(episodes=[], warnings=["C:\\Users\\someone\\x.json: KeyError"])
        [warning] = ev.evidence_payload(snapshot)["warnings"]
        self.assertIn("[local path omitted]", warning)
        self.assertNotIn("someone", warning)


class EndpointTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        write_episode(self.root, "valid", success=True)
        self.catalog = ev.CachedArtifactCatalog(self.root)
        handler = viewer_server.make_handler(self.catalog)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 10)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self, path):
        with urlopen("http://127.0.0.1:{}{}".format(self.server.server_port, path)) as response:
            return response.status, dict(response.headers.items()), json.loads(response.read())

    def test_evidence_is_served_from_the_cache_and_the_old_runs_endpoint_shares_it(self):
        status, headers, payload = self.get("/api/evidence")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(len(payload["episodes"]), 1)
        self.assertEqual(payload["episodes"][0]["outcome"], "success")
        self.get("/api/evidence")
        self.get("/api/runs")
        self.assertEqual(self.catalog.scans, 1, "three requests, one scan")


if __name__ == "__main__":
    unittest.main()
