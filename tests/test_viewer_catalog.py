import json
import shutil
import tempfile
import unittest
from pathlib import Path

from robot_debug.viewer.catalog import ArtifactCatalog


DEFAULT_OCCLUSION = object()


def write_episode(
    root: Path,
    run_name: str,
    *,
    success: bool,
    failure_reason=None,
    malformed_aggregate: bool = False,
    occlusion=DEFAULT_OCCLUSION,
) -> Path:
    run = root / run_name
    episode_dir = run / "episodes" / "libero-object"
    episode_dir.mkdir(parents=True)
    aggregate_path = run / "libero-object_aggregate.json"
    if malformed_aggregate:
        aggregate_path.write_text("{not json", encoding="utf-8")
        return run

    episode = {
        "episode_id": 0,
        "episode_idx": 0,
        "task_id": 0,
        "name": "pick up the object",
        "suite": "libero_object",
        "metrics": {"success": success},
        "steps": 12,
        "elapsed_sec": 2.5,
    }
    if failure_reason is not None:
        episode["failure_reason"] = failure_reason
        episode["failure_detail"] = "diagnostic detail"
    aggregate = {
        "benchmark": "libero-object",
        "harness_version": "0.5.0",
        "created_at": "2026-09-13T00:00:00+00:00",
        "eval_id": "eval-" + run_name,
        "tasks": [{"task": episode["name"], "episodes": [episode]}],
        "config": {
            "benchmark": "robot_debug.libero:DiagnosticLIBEROBenchmark",
            "params": {
                "seed": 7,
                "env_seed": 7,
                "agentview_occlusion": (
                    {"enabled": True, "x": 0.0, "y": 0.5, "width": 0.25}
                    if occlusion is DEFAULT_OCCLUSION
                    else occlusion
                ),
            },
        },
        "server_info": {"harness_version": "0.5.1", "model_server": "LeRobotModelServer"},
    }
    aggregate_path.write_text(json.dumps(aggregate), encoding="utf-8")
    stem = "task0000_ep0000_success" if success else "task0000_ep0000_error"
    (episode_dir / (stem + ".mp4")).write_bytes(b"video")
    (episode_dir / (stem + ".jsonl")).write_text(
        '{"step": 0, "reward": 0.0, "done": false, "success": false}\n'
        '{"step": 11, "reward": 1.0, "done": true, "success": true}\n',
        encoding="utf-8",
    )
    return run


class ArtifactCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    @staticmethod
    def configure_filtered_task(run: Path, task_id=2, *, benchmark_class=None):
        aggregate_path = run / "libero-object_aggregate.json"
        aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
        aggregate["config"]["params"]["task_id"] = task_id
        if benchmark_class is not None:
            aggregate["config"]["benchmark"] = benchmark_class
        for episode in aggregate["tasks"][0]["episodes"]:
            episode["task_id"] = task_id
        aggregate_path.write_text(json.dumps(aggregate), encoding="utf-8")
        return aggregate_path

    def test_catalog_classifies_success_and_exposes_perturbation(self):
        write_episode(self.root, "valid", success=True)

        episode = ArtifactCatalog(self.root).list_episodes()[0]

        self.assertEqual(episode.outcome, "success")
        self.assertEqual(episode.perturbation["x"], 0.0)
        self.assertEqual(episode.perturbation["y"], 0.5)
        self.assertEqual(episode.perturbation["width"], 0.25)
        self.assertEqual(episode.provenance["model_server"], "LeRobotModelServer")

    def test_catalog_separates_infrastructure_error_from_task_failure(self):
        write_episode(self.root, "infra", success=False, failure_reason="exception")
        write_episode(self.root, "failure", success=False)

        outcomes = {item.run_name: item.outcome for item in ArtifactCatalog(self.root).list_episodes()}

        self.assertEqual(outcomes["infra"], "infrastructure_error")
        self.assertEqual(outcomes["failure"], "task_failure")

    def test_catalog_preserves_explicit_null_occlusion(self):
        write_episode(self.root, "null-occlusion", success=True, occlusion=None)

        episode = ArtifactCatalog(self.root).list_episodes()[0]

        self.assertIsNone(episode.perturbation)

    def test_catalog_classifies_timeout(self):
        write_episode(self.root, "timeout", success=False, failure_reason="timeout")

        episode = ArtifactCatalog(self.root).list_episodes()[0]

        self.assertEqual(episode.outcome, "episode_timeout")

    def test_trace_is_parsed_as_json_lines(self):
        write_episode(self.root, "valid", success=True)
        catalog = ArtifactCatalog(self.root)

        trace = catalog.load_trace(catalog.list_episodes()[0].episode_id)

        self.assertEqual([point["step"] for point in trace["points"]], [0, 11])
        self.assertEqual(trace["warnings"], [])

    def test_malformed_aggregate_becomes_a_warning(self):
        write_episode(self.root, "bad", success=False, malformed_aggregate=True)

        snapshot = ArtifactCatalog(self.root).snapshot()

        self.assertEqual(snapshot.episodes, [])
        self.assertEqual(len(snapshot.warnings), 1)

    def test_catalog_deduplicates_copied_aggregate_and_prefers_media(self):
        full_run = write_episode(self.root / "full", "valid", success=True)
        metadata_run = self.root / "core" / "valid"
        metadata_run.mkdir(parents=True)
        shutil.copy2(
            full_run / "libero-object_aggregate.json",
            metadata_run / "libero-object_aggregate.json",
        )

        episodes = ArtifactCatalog(self.root).list_episodes()

        self.assertEqual(len(episodes), 1)
        self.assertIsNotNone(episodes[0].video_path)
        self.assertIn("full/valid/episodes/libero-object", episodes[0].video_path)

    def test_catalog_finds_media_beside_flat_layout_aggregate(self):
        run = write_episode(self.root, "flat", success=True)
        nested = run / "episodes" / "libero-object"
        for media in tuple(nested.iterdir()):
            media.replace(run / media.name)
        nested.rmdir()
        nested.parent.rmdir()

        episode = ArtifactCatalog(self.root).list_episodes()[0]

        self.assertEqual(episode.video_path, "flat/task0000_ep0000_success.mp4")
        self.assertEqual(episode.trace_path, "flat/task0000_ep0000_success.jsonl")

    def test_filtered_global_tasks_resolve_local_ordinal_zero_media(self):
        for task_id in (1, 2):
            with self.subTest(task_id=task_id):
                task_root = self.root / str(task_id)
                run = write_episode(task_root, "filtered-{}".format(task_id), success=True)
                self.configure_filtered_task(run, task_id)

                episode = ArtifactCatalog(task_root).list_episodes()[0]

                self.assertEqual(episode.task_id, task_id)
                self.assertEqual(episode.episode_index, 0)
                self.assertIn("task0000_ep0000", episode.video_path)
                self.assertIn("task0000_ep0000", episode.trace_path)

    def test_task_local_fallback_requires_proven_single_filtered_task(self):
        rejected_cases = (
            ("absent", "absent", None, None),
            ("boolean", True, None, None),
            ("mismatched", 1, None, None),
            ("wrong benchmark", 2, "some.OtherBenchmark", None),
            ("multiple groups", 2, None, "multiple"),
            ("mixed global ids", 2, None, "mixed"),
        )
        for name, filter_id, benchmark_class, group_shape in rejected_cases:
            with self.subTest(case=name):
                case_root = self.root / name.replace(" ", "-")
                run = write_episode(case_root, name.replace(" ", "-"), success=True)
                path = run / "libero-object_aggregate.json"
                aggregate = json.loads(path.read_text(encoding="utf-8"))
                if filter_id != "absent":
                    aggregate["config"]["params"]["task_id"] = filter_id
                if benchmark_class is not None:
                    aggregate["config"]["benchmark"] = benchmark_class
                aggregate["tasks"][0]["episodes"][0]["task_id"] = 2
                if group_shape == "multiple":
                    aggregate["tasks"].append({"task": "another", "episodes": []})
                elif group_shape == "mixed":
                    aggregate["tasks"][0]["episodes"].append(
                        {**aggregate["tasks"][0]["episodes"][0], "task_id": 3, "episode_idx": 1}
                    )
                path.write_text(json.dumps(aggregate), encoding="utf-8")

                episodes = ArtifactCatalog(case_root).list_episodes()

                expected_count = 2 if group_shape == "mixed" else 1
                self.assertEqual(len(episodes), expected_count)
                self.assertTrue(all(item.video_path is None for item in episodes))
                self.assertTrue(all(item.trace_path is None for item in episodes))

    def test_duplicate_local_media_is_ambiguous_and_keeps_episode(self):
        case_root = self.root / "duplicate-root"
        run = write_episode(case_root, "duplicate", success=True)
        self.configure_filtered_task(run, 2)
        root_copy = run / "task0000_ep0000_success.mp4"
        root_copy.write_bytes(b"second video")

        snapshot = ArtifactCatalog(case_root).snapshot()

        self.assertEqual(len(snapshot.episodes), 1)
        self.assertIsNone(snapshot.episodes[0].video_path)
        self.assertIsNotNone(snapshot.episodes[0].trace_path)
        self.assertTrue(any("ambiguous" in warning.lower() for warning in snapshot.warnings))

    def test_global_media_ambiguity_does_not_fall_back_to_local_media(self):
        case_root = self.root / "global-ambiguity-root"
        run = write_episode(case_root, "ambiguous-global", success=True)
        self.configure_filtered_task(run, 2)
        episode_dir = run / "episodes" / "libero-object"
        (episode_dir / "task0002_ep0000_success.mp4").write_bytes(b"global one")
        (run / "task0002_ep0000_success.mp4").write_bytes(b"global two")

        snapshot = ArtifactCatalog(case_root).snapshot()

        self.assertEqual(len(snapshot.episodes), 1)
        self.assertIsNone(snapshot.episodes[0].video_path)
        self.assertTrue(any("ambiguous video" in warning.lower() for warning in snapshot.warnings))

    def test_escaping_media_symlink_is_rejected_with_warning(self):
        case_root = self.root / "escaping-root"
        run = write_episode(case_root, "escaping", success=True)
        self.configure_filtered_task(run, 2)
        outside = case_root.parent / (case_root.name + "-outside.mp4")
        outside.write_bytes(b"outside")
        link = run / "episodes" / "libero-object" / "task0000_ep0000_success.mp4"
        link.unlink()
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are unavailable")
        try:
            snapshot = ArtifactCatalog(case_root).snapshot()
        finally:
            outside.unlink(missing_ok=True)

        self.assertEqual(len(snapshot.episodes), 1)
        self.assertIsNone(snapshot.episodes[0].video_path)
        self.assertIsNotNone(snapshot.episodes[0].trace_path)
        self.assertTrue(any("escape" in warning.lower() for warning in snapshot.warnings))

    def test_media_path_cannot_escape_artifact_root(self):
        write_episode(self.root, "valid", success=True)

        with self.assertRaises(ValueError):
            ArtifactCatalog(self.root).resolve_media("../secret.txt")


if __name__ == "__main__":
    unittest.main()
