"""Tests for the frozen M3 replay workload and arithmetic-only mode report."""

from __future__ import annotations

import copy
import math
import unittest

from robot_debug.parallel_eval import (
    assign_items,
    build_manifest,
    manifest_hash,
    summarize_modes,
)


PINNED_MANIFEST_HASH = (
    "2c815047f734a691b8b55db0dc15521afd175962d7483a7a9f8f06463cd0338a"
)


class ParallelEvalTest(unittest.TestCase):
    def test_build_manifest_has_frozen_order_and_independent_rectangles(self) -> None:
        manifest = build_manifest(8)

        self.assertEqual(16, len(manifest))
        self.assertEqual(
            [f"nominal-{repeat:02d}" for repeat in range(1, 9)]
            + [f"mask-{repeat:02d}" for repeat in range(1, 9)],
            [item["case_id"] for item in manifest],
        )
        self.assertEqual(["nominal"] * 8 + ["mask"] * 8, [item["kind"] for item in manifest])
        self.assertEqual(list(range(1, 9)) * 2, [item["repeat"] for item in manifest])
        self.assertEqual(
            {"task_id": 0, "episode_index": 0, "seed": 7, "env_seed": 7},
            {key: manifest[0][key] for key in ("task_id", "episode_index", "seed", "env_seed")},
        )
        self.assertIsNone(manifest[0]["rectangle"])
        self.assertEqual(
            {"x": 0.625, "y": 0, "width": 0.375, "height": 0.375},
            manifest[8]["rectangle"],
        )
        self.assertIsNot(manifest[8]["rectangle"], manifest[9]["rectangle"])
        manifest[8]["rectangle"]["x"] = 0
        self.assertEqual(0.625, manifest[9]["rectangle"]["x"])

    def test_build_manifest_rejects_invalid_repeat_counts(self) -> None:
        for repeats in (True, False, 0, -1, 1.5, "8"):
            with self.subTest(repeats=repeats):
                with self.assertRaises(ValueError):
                    build_manifest(repeats)

    def test_manifest_hash_is_stable_and_pinned_for_eight_repeats(self) -> None:
        manifest = build_manifest(8)

        self.assertEqual(PINNED_MANIFEST_HASH, manifest_hash(manifest))
        self.assertEqual(manifest_hash(manifest), manifest_hash(copy.deepcopy(manifest)))

    def test_assign_items_round_robins_every_case_once(self) -> None:
        manifest = build_manifest(8)
        expected = [item["case_id"] for item in manifest]

        for workers in (1, 2, 4):
            with self.subTest(workers=workers):
                assignment = assign_items(manifest, workers)
                self.assertEqual(workers, len(assignment))
                self.assertCountEqual(expected, [item["case_id"] for lane in assignment for item in lane])
                self.assertEqual(
                    [expected[index::workers] for index in range(workers)],
                    [[item["case_id"] for item in lane] for lane in assignment],
                )

    def test_assign_items_rejects_invalid_workers_and_duplicate_ids(self) -> None:
        manifest = build_manifest(1)
        for workers in (True, False, 0, 1.0, 2.0, 4.0, 3, 5, "2"):
            with self.subTest(workers=workers):
                with self.assertRaises(ValueError):
                    assign_items(manifest, workers)
        with self.assertRaises(ValueError):
            assign_items(manifest + [copy.deepcopy(manifest[0])], 1)

    def test_summarize_modes_calculates_comparable_metrics_and_outcomes(self) -> None:
        manifest = build_manifest(8)
        digest = manifest_hash(manifest)
        records = [
            self._complete_record(manifest, digest, workers=1, elapsed_seconds=160, cost_usd=1.6),
            self._complete_record(manifest, digest, workers=2, elapsed_seconds=100, cost_usd=1.0),
            self._complete_record(manifest, digest, workers=4, elapsed_seconds=80, cost_usd=0.8),
        ]

        report = summarize_modes(records)

        self.assertEqual([1, 2, 4], [row["workers"] for row in report])
        self.assertEqual([360.0, 576.0, 720.0], [row["throughput_per_hour"] for row in report])
        self.assertEqual([1.0, 1.6, 2.0], [row["speedup"] for row in report])
        self.assertEqual([1.0, 0.8, 0.5], [row["efficiency"] for row in report])
        self.assertEqual([0.1, 0.0625, 0.05], [row["cost_per_valid"] for row in report])
        self.assertEqual(
            {"nominal": {"success": 8}, "mask": {"policy_failure": 8}},
            report[0]["outcome_counts"],
        )
        self.assertEqual([], report[0]["drift_case_ids"])

    def test_summarize_modes_allows_unknown_cost_and_reports_outcome_drift(self) -> None:
        manifest = build_manifest(1)
        digest = manifest_hash(manifest)
        records = [
            self._complete_record(manifest, digest, 1, 20, None),
            self._complete_record(manifest, digest, 2, 10, None),
            self._complete_record(manifest, digest, 4, 5, None),
        ]
        records[1]["results"][0]["outcome"] = "policy_failure"

        report = summarize_modes(records)

        self.assertEqual([None, None, None], [row["cost_per_valid"] for row in report])
        self.assertEqual(["nominal-01"], report[1]["drift_case_ids"])

    def test_summarize_modes_rejects_noncomparable_or_incomplete_records(self) -> None:
        manifest = build_manifest(1)
        digest = manifest_hash(manifest)
        base = [
            self._complete_record(manifest, digest, 1, 20, 0.2),
            self._complete_record(manifest, digest, 2, 10, 0.1),
            self._complete_record(manifest, digest, 4, 5, 0.05),
        ]
        invalid_cases = {
            "missing-mode": base[:2],
            "duplicate-mode": base + [copy.deepcopy(base[0])],
            "digest-mismatch": self._replace(base, 2, manifest_hash(build_manifest(2)), "manifest_hash"),
            "missing-result": self._with_result_removed(base, 4),
            "duplicate-result": self._with_result_duplicated(base, 4),
            "invalid-result": self._replace_result(base, 4, "status", "invalid"),
            "nonpositive-elapsed": self._replace(base, 4, 0, "elapsed_seconds"),
            "nonfinite-cost": self._replace(base, 4, math.inf, "cost_usd"),
            "wrong-valid-count": self._replace(base, 4, 1, "valid_count"),
            "float-workers": self._replace(base, 4, 4.0, "workers"),
            "empty-workload": self._empty_workload(base, 4),
            "infrastructure-outcome": self._replace_result(base, 4, "outcome", "infrastructure_error"),
            "unknown-outcome": self._replace_result(base, 4, "outcome", "unknown"),
            "nonstring-outcome": self._replace_result(base, 4, "outcome", []),
            "nonfinite-derived-metric": self._replace(base, 4, 5e-324, "elapsed_seconds"),
        }
        for name, records in invalid_cases.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    summarize_modes(records)

    @staticmethod
    def _complete_record(
        manifest: list[dict],
        digest: str,
        workers: int,
        elapsed_seconds: float,
        cost_usd: float | None,
    ) -> dict:
        return {
            "workers": workers,
            "manifest_hash": digest,
            "case_ids": [item["case_id"] for item in manifest],
            "elapsed_seconds": elapsed_seconds,
            "cost_usd": cost_usd,
            "valid_count": len(manifest),
            "results": [
                {
                    "case_id": item["case_id"],
                    "kind": item["kind"],
                    "status": "valid",
                    "outcome": "success" if item["kind"] == "nominal" else "policy_failure",
                }
                for item in manifest
            ],
        }

    @staticmethod
    def _replace(records: list[dict], workers: int, value: object, field: str) -> list[dict]:
        copied = copy.deepcopy(records)
        next(record for record in copied if record["workers"] == workers)[field] = value
        return copied

    @staticmethod
    def _with_result_removed(records: list[dict], workers: int) -> list[dict]:
        copied = copy.deepcopy(records)
        next(record for record in copied if record["workers"] == workers)["results"].pop()
        return copied

    @staticmethod
    def _with_result_duplicated(records: list[dict], workers: int) -> list[dict]:
        copied = copy.deepcopy(records)
        record = next(record for record in copied if record["workers"] == workers)
        record["results"].append(copy.deepcopy(record["results"][0]))
        return copied

    @staticmethod
    def _replace_result(records: list[dict], workers: int, field: str, value: object) -> list[dict]:
        copied = copy.deepcopy(records)
        next(record for record in copied if record["workers"] == workers)["results"][0][field] = value
        return copied

    @staticmethod
    def _empty_workload(records: list[dict], workers: int) -> list[dict]:
        copied = copy.deepcopy(records)
        record = next(record for record in copied if record["workers"] == workers)
        record["case_ids"] = []
        record["results"] = []
        record["valid_count"] = 0
        return copied


if __name__ == "__main__":
    unittest.main()
