"""The orchestrator driving the REAL ``NebiusBackend`` against ``FakeNebius`` (no network, no cloud)."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import Callable, Dict, List

from robot_debug import ledger as lg
from robot_debug import orchestrator as orch
from robot_debug.backends.nebius import NebiusBackend
from tests.fakes.backend_fakes import FakeClock
from tests.fakes.fake_nebius import IMAGE, FakeNebius
from tests.test_orchestrator import (
    MOMENT, RATE, SOUP_ONLY, FakeTools, reduce_one, screen_summary, spec_for)

CONTAINER_SECONDS = 780              # FakeNebius's default plan: RUNNING at 120 s, COMPLETED at 900 s


def nebius_spec(mode="scenario", cap=10.0, **overrides):
    backend = {"kind": "nebius", "image": IMAGE, "hf_token_secret": "faultline-hf-token", "hourly_usd": RATE}
    return spec_for(mode=mode, cap=cap, backend=backend, **overrides)


class WorldS3:
    """A fake S3 client whose objects are the summaries of the Jobs FakeNebius has created."""

    def __init__(self, world: "NebiusWorld") -> None:
        self.world = world
        self.listed: List[str] = []
        self.downloaded: List[str] = []

    def objects(self) -> Dict[str, bytes]:
        found: Dict[str, bytes] = {}
        for name in self.world.cli.jobs:
            path = self.world.run_dir / "jobs" / name / "workload.json"
            step = re.search(r"-(screen|reduce\d*|audit|replay)(?:-[a-z])?\Z", name)
            if not path.is_file() or step is None or step.group(1) not in self.world.summaries:
                continue
            workload = json.loads(path.read_text(encoding="utf-8"))
            summary = self.world.summaries[step.group(1)](workload)
            found["faultline-runs/%s/scenario/scenario_summary.json" % name] = json.dumps(summary).encode("utf-8")
        return found

    def get_paginator(self, name):
        client = self

        class Paginator:
            def paginate(self, Bucket, Prefix=""):
                client.listed.append(Prefix)
                objects = client.objects()
                keys = sorted(k for k in objects if k.startswith(Prefix))
                yield {"Contents": [{"Key": k, "Size": len(objects[k])} for k in keys]}

        return Paginator()

    def download_file(self, Bucket, Key, Filename):
        self.downloaded.append(Key)
        Path(Filename).write_bytes(self.objects()[Key])


class NebiusWorld:
    """One run folder, one FakeNebius, the real backend and the real orchestrator."""

    def __init__(self, test: unittest.TestCase, spec, summaries: Dict[str, Callable], *, run_dir=None,
                 cli=None, clock=None, tools=None, **options) -> None:
        temp = tempfile.TemporaryDirectory()
        test.addCleanup(temp.cleanup)
        self.spec, self.summaries = spec, summaries
        self.clock = clock or FakeClock()
        self.cli = cli or FakeNebius(self.clock)
        self.tools = tools or FakeTools()
        self.run_dir = run_dir or orch.create_run_dir(Path(temp.name) / "runs", spec, None, MOMENT)
        self.s3 = WorldS3(self)
        self.backend = NebiusBackend.from_spec(
            spec.raw, runner=self.cli, s3_factory=lambda endpoint, region, key, secret: self.s3,
            clock=self.clock, sleep=self.clock.sleep, suffix=lambda: "abc123",
            which=lambda name: "/usr/bin/nebius", system=lambda: "Linux")
        self.ledger = lg.Ledger.load(self.run_dir / "ledger.json", cap_usd=spec.budget.max_spend_usd,
                                     max_hours=spec.budget.max_hours, hourly_usd=spec.backend.hourly_usd,
                                     clock=self.clock)
        self.lines: List[str] = []
        options.setdefault("poll_seconds", 60.0)
        self.runner = orch.Orchestrator(spec, self.run_dir, self.backend, self.tools, self.ledger,
                                        out=self.lines.append, **options)

    def real_creates(self):
        return [c for c in self.cli.calls if c[:3] == ["ai", "job", "create"] and "--dry-run" not in c]


def reduced_script():
    return {"screen": lambda workload: screen_summary(),
            "reduce": reduce_one(stop_reason="reduced", selection=SOUP_ONLY, entity_minimal=True, reduced=True)}


class WholeDiagnosisOnNebius(unittest.TestCase):
    def test_mode_1_runs_end_to_end_through_the_real_nebius_backend(self):
        world = NebiusWorld(self, nebius_spec(), reduced_script())
        result = world.runner.diagnose()
        self.assertEqual((result.status, result.reason), ("completed", None), "\n".join(world.lines))
        tag = world.runner.tag
        self.assertEqual(sorted(world.cli.jobs), ["soup-start-{}-reduce".format(tag), "soup-start-{}-screen".format(tag)])
        self.assertEqual(len(world.real_creates()), 2)
        self.assertEqual(world.cli.keys, {}, "the per-run access key is deleted at the end")
        self.assertAlmostEqual(world.ledger.spent, 2 * (CONTAINER_SECONDS + 240) / 3600.0 * RATE)
        for name in world.cli.jobs:
            self.assertTrue((world.run_dir / "jobs" / name / "evidence" / "scenario" / "scenario_summary.json").is_file())
        self.assertTrue((world.run_dir / "case.json").is_file())
        self.assertTrue((world.run_dir / "report.md").is_file())


if __name__ == "__main__":
    unittest.main()
