"""Frozen multi-job portfolio identity contracts."""

from __future__ import annotations

import unittest

from robot_debug.portfolio_manifest import PortfolioManifest


class PortfolioManifestTests(unittest.TestCase):
    def make_manifest(self, **overrides):
        values = {
            "suite": "libero_object",
            "task_ids": (0, 1, 2),
            "seed": 7,
            "family": "agentview_rect_occlusion",
        }
        values.update(overrides)
        return PortfolioManifest(**values)

    def test_three_distinct_tasks_have_unique_safe_job_ids(self):
        manifest = self.make_manifest()

        self.assertEqual(tuple(job.task_id for job in manifest.jobs), (0, 1, 2))
        self.assertEqual(tuple(job.job_id for job in manifest.jobs),
                         ("task-00", "task-01", "task-02"))
        self.assertEqual(len({job.job_id for job in manifest.jobs}), 3)
        self.assertEqual(manifest.suite, "libero_object")
        self.assertEqual(manifest.family, "agentview_rect_occlusion")
        self.assertEqual(manifest.seed, 7)
        self.assertTrue(manifest.checkpoint_id)
        self.assertTrue(manifest.checkpoint_revision)

    def test_hash_is_stable_across_json_key_order(self):
        first = self.make_manifest()
        second = PortfolioManifest.from_mapping({
            "family": "agentview_rect_occlusion",
            "seed": 7,
            "task_ids": [0, 1, 2],
            "suite": "libero_object",
            "checkpoint_revision": first.checkpoint_revision,
            "checkpoint_id": first.checkpoint_id,
        })

        self.assertEqual(first.config_hash, second.config_hash)
        self.assertEqual(first.to_mapping(), second.to_mapping())

    def test_rejects_nonportable_or_nonportfolio_task_selection(self):
        for field, value in (
            ("suite", "libero_spatial"),
            ("task_ids", (0, 0, 1)),
            ("task_ids", (0, 1)),
            ("task_ids", (0, -1, 2)),
            ("task_ids", (0, True, 2)),
            ("seed", -1),
            ("seed", True),
            ("family", ""),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.make_manifest(**{field: value})

    def test_mapping_rejects_unknown_or_missing_frozen_fields(self):
        frozen = self.make_manifest().to_mapping()
        with self.assertRaises(ValueError):
            PortfolioManifest.from_mapping({**frozen, "unknown": "field"})
        without_seed = dict(frozen)
        without_seed.pop("seed")
        with self.assertRaises(ValueError):
            PortfolioManifest.from_mapping(without_seed)


if __name__ == "__main__":
    unittest.main()
