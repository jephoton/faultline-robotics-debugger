import json
import tempfile
import unittest
from pathlib import Path

from robot_debug.viewer.catalog import ArtifactCatalog


def write_episode(
    root: Path,
    run_name: str,
    *,
    success: bool,
    failure_reason=None,
    malformed_aggregate: bool = False,
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
                "agentview_occlusion": {"enabled": True, "width": 0.25},
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

    def test_catalog_classifies_success_and_exposes_perturbation(self):
        write_episode(self.root, "valid", success=True)

        episode = ArtifactCatalog(self.root).list_episodes()[0]

        self.assertEqual(episode.outcome, "success")
        self.assertEqual(episode.perturbation["width"], 0.25)
        self.assertEqual(episode.provenance["model_server"], "LeRobotModelServer")

    def test_catalog_separates_infrastructure_error_from_task_failure(self):
        write_episode(self.root, "infra", success=False, failure_reason="exception")
        write_episode(self.root, "failure", success=False)

        outcomes = {item.run_name: item.outcome for item in ArtifactCatalog(self.root).list_episodes()}

        self.assertEqual(outcomes["infra"], "infrastructure_error")
        self.assertEqual(outcomes["failure"], "task_failure")

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

    def test_media_path_cannot_escape_artifact_root(self):
        write_episode(self.root, "valid", success=True)

        with self.assertRaises(ValueError):
            ArtifactCatalog(self.root).resolve_media("../secret.txt")


if __name__ == "__main__":
    unittest.main()
