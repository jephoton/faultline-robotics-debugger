"""Cleanup of the results bucket: removed only when every Job was downloaded and it is empty."""

import json
import unittest
from pathlib import Path

from tests.test_backend_nebius import NebiusCase
from tests.test_orchestrator_nebius import NebiusWorld, nebius_spec, reduced_script


class BucketCleanup(NebiusCase):
    def finished_job(self, backend, name="soup-a"):
        handle = backend.submit(name, self.workload(name))
        backend.wait(handle, running_max_seconds=3000, total_max_seconds=6000, poll_seconds=60)
        self.s3.objects = {"faultline-runs/%s/manifest.json" % name: b"[]"}
        backend.download(handle, Path(self.temp.name) / ("evidence-" + name))
        return handle

    def test_finish_deletes_the_bucket_once_every_job_was_downloaded_and_the_bucket_is_empty(self):
        backend = self.prepared()
        self.finished_job(backend)
        backend.finish()
        self.assertEqual(self.cli.buckets, {})
        self.assertEqual(backend.cleanup_report, {"access_key": "deleted", "bucket": "deleted"})
        state = json.loads((self.run_dir / "backend-state.json").read_text("utf-8"))
        self.assertTrue(state["bucket_deleted"])

    def test_finish_keeps_a_bucket_that_still_holds_objects_and_records_why(self):
        backend = self.prepared()
        self.finished_job(backend)
        self.cli.bucket_nonempty = True
        backend.finish()                                      # must not raise
        self.assertEqual(len(self.cli.buckets), 1)
        self.assertTrue(backend.cleanup_report["bucket"].startswith("kept"))
        self.assertIn("not empty", backend.cleanup_report["bucket"])
        state = json.loads((self.run_dir / "backend-state.json").read_text("utf-8"))
        self.assertFalse(state.get("bucket_deleted"))
        self.assertIn("not empty", state["bucket_delete_outcome"])
        self.assertEqual([c for c in self.cli.calls if c[:3] == ["storage", "object", "delete"]], [])

    def test_finish_keeps_the_bucket_while_a_job_has_not_been_downloaded(self):
        backend = self.prepared()
        backend.submit("soup-a", self.workload())
        backend.finish()
        self.assertEqual(len(self.cli.buckets), 1)
        self.assertEqual(self.cli.count("storage", "bucket", "delete"), 0)
        self.assertIn("not downloaded", backend.cleanup_report["bucket"])

    def test_a_job_that_never_started_leaves_nothing_to_download(self):
        self.cli.job_plan = [(0, "PROVISIONING", None), (300, "ERROR", "NotEnoughResources")]
        backend = self.prepared()
        handle = backend.submit("soup-a", self.workload())
        backend.wait(handle, running_max_seconds=3000, total_max_seconds=6000, poll_seconds=60)
        backend.finish()
        self.assertEqual(self.cli.buckets, {})

    def test_resume_after_the_bucket_was_deleted_creates_a_fresh_one(self):
        backend = self.prepared()
        backend.finish()
        self.assertEqual(self.cli.buckets, {})
        again = self.make()
        again.prepare(again._test_dir, {"name": "soup-start14"})
        self.assertEqual(len(self.cli.buckets), 1)
        self.assertEqual(len(self.cli.keys), 1)
        again.submit("soup-b", self.workload("soup-b"))


class BucketCleanupInARun(unittest.TestCase):
    def test_the_cleanup_outcome_is_recorded_and_a_non_empty_bucket_is_kept(self):
        world = NebiusWorld(self, nebius_spec(), reduced_script())
        world.cli.bucket_nonempty = True
        result = world.runner.diagnose()
        self.assertEqual(result.status, "completed")
        run = json.loads((world.run_dir / "steps.json").read_text())["run"]
        self.assertEqual(run["cleanup"]["access_key"], "deleted")
        self.assertTrue(run["cleanup"]["bucket"].startswith("kept"))
        self.assertEqual(len(world.cli.buckets), 1)

    def test_an_empty_bucket_is_removed_after_every_download(self):
        world = NebiusWorld(self, nebius_spec(), reduced_script())
        world.runner.diagnose()
        self.assertEqual(world.cli.buckets, {})
        run = json.loads((world.run_dir / "steps.json").read_text())["run"]
        self.assertEqual(run["cleanup"]["bucket"], "deleted")


if __name__ == "__main__":
    unittest.main()
