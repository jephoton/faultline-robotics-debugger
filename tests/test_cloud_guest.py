"""Local contract checks for fixed-purpose guest scripts; no cloud or GPU calls."""

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
GUEST = ROOT / "scripts" / "cloud_guest"


def wsl_path(path):
    resolved = Path(path).resolve().as_posix()
    if os.name == "posix":
        return resolved
    return "/mnt/" + resolved[0].lower() + resolved[2:]


def bash(script, *args, env=None):
    prefix = ["C:/Windows/System32/wsl.exe", "--exec"] if os.name == "nt" else []
    return subprocess.run([*prefix, "bash", wsl_path(script), *map(str, args)],
                          capture_output=True, text=True, env=env, timeout=15)


class GuestTests(unittest.TestCase):
    def test_pair_claim_refuses_lost_ack_and_existing_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            guest_root = Path(temporary)
            session = guest_root / "run"; session.mkdir()
            script = guest_root / "launch-pair.sh"
            script.write_text((GUEST / script.name).read_text().replace("/home/robot", str(guest_root)))
            (session / "run-pair.sh").write_text("#!/bin/bash\nsleep 1\n")
            (session / "validate-mode.py").write_text("# fixture\n")
            first = bash(script, session)
            self.assertEqual(0, first.returncode, first.stderr)
            self.assertTrue((session / "pair-claim" / "pid").is_file())
            self.assertIn("run_label=sequential-jobs+adaptive-portfolio", (session / "pair-claim" / "identity").read_text())
            second = bash(script, session)
            self.assertNotEqual(0, second.returncode)
            self.assertEqual((session / "pair-claim" / "pid").read_text(), (session / "runner.pid").read_text())
            (session / "pair-claim" / "pid").unlink()
            self.assertNotEqual(0, bash(script, session).returncode)

    def test_pair_runner_preserves_exit_one_and_exact_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            guest_root = Path(temporary)
            session = guest_root / "run"; session.mkdir()
            source = session / "source" / "scripts"; source.mkdir(parents=True)
            (source / "run_failure_search.py").write_text("ghcr.io/allenai/vla-evaluation-harness/libero@sha256:d0c45bc5a3720d569180e6b8dd92510da895f16c3cc509ccc76e4b4ffbb9e0f0")
            (source / "run_diagnostic_portfolio.py").write_text("# fixture")
            bundle = b"bounded source"; (session / "source.bundle").write_bytes(bundle)
            (session / "expected-source-sha.txt").write_text(hashlib.sha256(bundle).hexdigest())
            (session / "manifest.json").write_text("{}")
            (session / "deadline.txt").write_text("2099-01-01T00:00:00Z")
            (session / "hourly-rate.txt").write_text("4.5")
            (session / "model-server.log").write_text("nvidia/gr00t17-lerobot-libero_object-640")
            (session / "checkpoint-resolution.log").write_text("1499db357f6ca3762b56c2e8c00b530eb9a09444")
            (session / "pair-claim").mkdir()
            (session / "validate-mode.py").write_text("# fixture")
            upstream = guest_root / "vla-evaluation-harness"; upstream.mkdir()
            fakebin = guest_root / "bin"; fakebin.mkdir()
            def executable(name, body):
                path = fakebin / name; path.write_text("#!/bin/bash\n" + body); path.chmod(0o755)
            executable("git", "echo 35f1200eb15608aa898f727a3722f7eef889c6cd\n")
            executable("curl", "echo nvidia/gr00t17-lerobot-libero_object-640\n")
            executable("docker", "exit 0\n")
            evaluator = guest_root / "vla-eval-python"
            evaluator.write_text("#!/bin/bash\nif [[ $1 == -c ]]; then echo 2.25; exit 0; fi\nif [[ $1 == */run_diagnostic_portfolio.py ]]; then printf '%s\\n' \"$*\" >> '" + str(session / "calls.log") + "'; exit 1; fi\nexit 0\n")
            evaluator.chmod(0o755)
            script = guest_root / "run-pair.sh"
            script.write_text((GUEST / script.name).read_text().replace("/home/robot/.venvs/vla-eval/bin/python", str(evaluator)).replace("/home/robot", str(guest_root)))
            environment = os.environ.copy(); environment["PATH"] = str(fakebin) + os.pathsep + environment["PATH"]
            result = bash(script, session, env=environment)
            self.assertEqual(0, result.returncode, result.stderr)
            calls = (session / "calls.log").read_text().splitlines()
            self.assertEqual(2, len(calls))
            self.assertIn("--mode sequential-jobs", calls[0]); self.assertIn("--mode adaptive-portfolio --max-workers 2", calls[1])
            for call in calls:
                self.assertIn("--episodes 111 --seconds 1800 --estimated-usd 2.25 --hourly-rate 4.5", call)
            self.assertIn("pair terminal exit=0", (session / "pair-events.log").read_text())
            (session / "calls.log").unlink()
            (session / "deadline.txt").write_text("2000-01-01T00:00:00Z")
            self.assertNotEqual(0, bash(script, session, env=environment).returncode)
            self.assertFalse((session / "calls.log").exists())
            (session / "deadline.txt").write_text("2099-01-01T00:00:00Z")
            (session / "expected-source-sha.txt").write_text("0" * 64)
            self.assertNotEqual(0, bash(script, session, env=environment).returncode)
            self.assertFalse((session / "calls.log").exists())
            (session / "expected-source-sha.txt").write_text(hashlib.sha256(bundle).hexdigest())
            evaluator.write_text(evaluator.read_text().replace("exit 0\n", "if [[ $1 == */validate-mode.py ]]; then exit 2; fi\nexit 0\n"))
            self.assertNotEqual(0, bash(script, session, env=environment).returncode)
            self.assertEqual(1, len((session / "calls.log").read_text().splitlines()))

    def test_bash_syntax(self):
        for name in ("preflight.sh", "model-launch.sh", "launch-pair.sh", "run-pair.sh"):
            with self.subTest(name=name):
                prefix = ["C:/Windows/System32/wsl.exe", "--exec"] if os.name == "nt" else []
                result = subprocess.run([*prefix, "bash", "-n", wsl_path(GUEST / name)],
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_session_validation_refuses_traversal_before_any_side_effect(self):
        for name in ("preflight.sh", "model-launch.sh", "launch-pair.sh", "run-pair.sh"):
            with self.subTest(name=name):
                result = bash(GUEST / name, "/home/robot/../etc/bad")
                self.assertNotEqual(0, result.returncode)

    def test_validator_accepts_accounted_live_partial_with_distinct_media(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = Path(temporary)
            rate = 4.5
            (session / "hourly-rate.txt").write_text(str(rate))
            manifest = {"suite": "libero_object", "task_ids": [0, 1, 2], "seed": 7,
                        "family": "agentview_rect_occlusion",
                        "checkpoint_id": "nvidia/gr00t17-lerobot-libero_object-640",
                        "checkpoint_revision": "1499db357f6ca3762b56c2e8c00b530eb9a09444"}
            (session / "manifest.json").write_text(json.dumps(manifest))
            parent = session / "sequential" / "portfolio-one"
            parent.mkdir(parents=True)
            records = {}
            results = []
            for task in (0, 1, 2):
                case = f"task-{task:02d}--nominal-01"
                media = parent / "waves" / "wave-1" / "jobs" / f"task-{task:02d}"
                media.mkdir(parents=True)
                aggregate = media / "task_aggregate.json"
                aggregate.write_text(json.dumps({"tasks": [{"episodes": [{"task_id": task, "episode_idx": 0}]}]}))
                trace = media / "trace.jsonl"; trace.write_text("trace")
                video = media / "task0000.mp4"; video.write_bytes(b"video")
                records[case] = {"state": "terminal"}
                results.append({"case_id": case, "status": "valid", "output_path": str(media),
                                "evidence_paths": [str(p) for p in (aggregate, trace, video)]})
            ledger = parent / "ledger.json"
            ledger.write_text(json.dumps({"attempt_records": records, "in_flight_ids": []}))
            summary = {"mode": "sequential-jobs", "execution_kind": "live", "synthetic": False, "dry_run": False,
                       "manifest": manifest,
                       "manifest_hash": hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                       "accounting_incomplete": False, "invalid_attempts": 0, "uncertain_attempts": 0,
                       "physical_attempts": 3, "valid_episodes": 3, "max_observed_evaluator_calls": 1, "max_workers": 1,
                       "limits": {"episodes": 111, "seconds": 1800.0, "estimated_usd": 2.25, "hourly_rate": rate},
                       "waves": [{"ledger_path": "ledger.json", "results": results}], "stop_reason": "shared_budget_exhausted"}
            path = parent / "portfolio_summary.json"; path.write_text(json.dumps(summary))
            cmd = [sys.executable, str(GUEST / "validate-mode.py"), str(session), "sequential-jobs"]
            good = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(0, good.returncode, good.stderr)
            summary["uncertain_attempts"] = 1; path.write_text(json.dumps(summary))
            bad = subprocess.run([sys.executable, "-O", *cmd[1:]], capture_output=True, text=True)
            self.assertNotEqual(0, bad.returncode)
            summary["uncertain_attempts"] = 0; path.write_text(json.dumps(summary))
            results[0]["evidence_paths"][2] = str(parent / "outside.mp4")
            (parent / "outside.mp4").write_bytes(b"video")
            path.write_text(json.dumps(summary))
            bad = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(0, bad.returncode)


if __name__ == "__main__":
    unittest.main()
