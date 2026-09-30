import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SOURCE_ROOT = Path(__file__).parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))


def manifest_mapping():
    from robot_debug.portfolio_manifest import PortfolioManifest
    return PortfolioManifest(suite="libero_object", task_ids=(0, 1, 2), seed=7,
                             family="agentview_rect_occlusion").to_mapping()


class PortfolioCliTests(unittest.TestCase):
    def test_load_manifest_requires_exact_frozen_mapping(self):
        from scripts.run_diagnostic_portfolio import load_manifest
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text(json.dumps({"task_ids": [0, 1, 2]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_manifest(path)

    def test_dry_run_writes_explicit_synthetic_portfolio_artifact(self):
        from scripts.run_diagnostic_portfolio import run_cli
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); manifest = root / "manifest.json"
            manifest.write_text(json.dumps(manifest_mapping()), encoding="utf-8")
            summary = run_cli(manifest_path=manifest, mode="adaptive-portfolio", results_root=root / "results",
                              upstream_root=root, project_root=Path(__file__).parents[1], episodes=3,
                              seconds=600, estimated_usd=10, hourly_rate=1, dry_run=True)
            saved = json.loads((root / "results" / summary["session_id"] / "portfolio_summary.json").read_text(encoding="utf-8"))
        self.assertTrue(saved["synthetic"])
        self.assertEqual("dry_run", saved["execution_kind"])
        self.assertFalse(saved["certified"])

    def test_sequential_dry_run_and_existing_session_refusal(self):
        from scripts.run_diagnostic_portfolio import run_cli
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); manifest = root / "manifest.json"
            manifest.write_text(json.dumps(manifest_mapping()), encoding="utf-8")
            kwargs = dict(manifest_path=manifest, mode="sequential-jobs", results_root=root / "results",
                          upstream_root=root, project_root=Path(__file__).parents[1], episodes=3,
                          seconds=600, estimated_usd=10, hourly_rate=1, dry_run=True)
            summary = run_cli(**kwargs)
            self.assertTrue(summary["dry_run"])
            with self.assertRaisesRegex(ValueError, "existing portfolio session"):
                run_cli(**kwargs)

    def test_production_adapter_uses_contained_launcher_and_rejects_wrong_task(self):
        from robot_debug.diagnostic_round import RoundRequest, RoundLifecycle
        from scripts import run_diagnostic_portfolio as cli
        import threading
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); output = root / "output"; output.mkdir()
            aggregate = output / "task_aggregate.json"
            aggregate.write_text(json.dumps({"tasks": [{"episodes": [{"task_id": 1, "episode_idx": 0,
                "metrics": {"success": True}, "steps": 1, "elapsed_sec": .1}]}]}), encoding="utf-8")
            (output / "trace.jsonl").write_text("trace", encoding="utf-8"); (output / "video.mp4").write_bytes(b"video")
            request = RoundRequest("task-01--nominal-01", root / "config.yaml", output)
            lifecycle = RoundLifecycle(threading.Event(), threading.Event(), threading.Lock(), lambda: None)
            with patch.object(cli.parallel, "_run_evaluator_safely", return_value=SimpleNamespace(returncode=0)) as launcher:
                result = cli.production_evaluator(root, {"task-01": 1})(request,
                    launch_observer=lambda *_: None, lifecycle=lifecycle)
            self.assertEqual("valid", result["status"])
            self.assertIs(launcher.call_args.kwargs["stop_event"], lifecycle.stop_requested)
            aggregate.write_text(json.dumps({"tasks": [{"episodes": [{"task_id": 2, "episode_idx": 0,
                "metrics": {"success": True}, "steps": 1, "elapsed_sec": .1}]}]}), encoding="utf-8")
            with patch.object(cli.parallel, "_run_evaluator_safely", return_value=SimpleNamespace(returncode=0)):
                with self.assertRaisesRegex(ValueError, "task_id"):
                    cli.production_evaluator(root, {"task-01": 1})(request,
                        launch_observer=lambda *_: None, lifecycle=lifecycle)

    def test_production_adapter_rejects_wrong_episode_nonzero_launcher_and_missing_media(self):
        from robot_debug.diagnostic_round import RoundRequest, RoundLifecycle
        from scripts import run_diagnostic_portfolio as cli
        import threading
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); output = root / "output"; output.mkdir()
            aggregate = output / "task_aggregate.json"
            aggregate.write_text(json.dumps({"tasks": [{"episodes": [{"task_id": 1, "episode_idx": 1,
                "metrics": {"success": True}, "steps": 1, "elapsed_sec": .1}]}]}), encoding="utf-8")
            request = RoundRequest("task-01--nominal-01", root / "config.yaml", output)
            lifecycle = RoundLifecycle(threading.Event(), threading.Event(), threading.Lock(), lambda: None)
            evaluator = cli.production_evaluator(root, {"task-01": 1})
            with patch.object(cli.parallel, "_run_evaluator_safely", return_value=SimpleNamespace(returncode=0)):
                with self.assertRaisesRegex(ValueError, "episode_index"):
                    evaluator(request, launch_observer=lambda *_: None, lifecycle=lifecycle)
            aggregate.write_text(json.dumps({"tasks": [{"episodes": [{"task_id": 1, "episode_idx": 0,
                "metrics": {"success": True}, "steps": 1, "elapsed_sec": .1}]}]}), encoding="utf-8")
            with patch.object(cli.parallel, "_run_evaluator_safely", return_value=SimpleNamespace(returncode=2)):
                result = evaluator(request, launch_observer=lambda *_: None, lifecycle=lifecycle)
            self.assertEqual("infrastructure_error", result["status"])
            with patch.object(cli.parallel, "_run_evaluator_safely", return_value=SimpleNamespace(returncode=0)):
                with self.assertRaisesRegex(ValueError, "trace and MP4"):
                    evaluator(request, launch_observer=lambda *_: None, lifecycle=lifecycle)
            (output / "trace.jsonl").write_text("", encoding="utf-8"); (output / "video.mp4").write_bytes(b"")
            with patch.object(cli.parallel, "_run_evaluator_safely", return_value=SimpleNamespace(returncode=0)):
                with self.assertRaisesRegex(ValueError, "trace and MP4"):
                    evaluator(request, launch_observer=lambda *_: None, lifecycle=lifecycle)


if __name__ == "__main__":
    unittest.main()
