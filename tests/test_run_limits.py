"""Raising the spend cap or the hour limit of a stopped run before it is resumed."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from robot_debug import ledger as lg
from robot_debug import run_limits as rl
from robot_debug import spec as sp

BLOCK_SPEC = """faultline: 1
name: demo
mode: audit
policy: {suite: libero_object}
audit: {task: 0, start: 0, families: [blur]}
budget:
  max_spend_usd: 2.0   # the cap
  max_hours: 1.5
nemotron: {hypothesis: false, explain: false}
backend:
  kind: nebius
  image: cr.example.invalid/REGISTRY_ID/faultline@sha256:IMAGE_DIGEST
  hf_token_secret: faultline-hf-token
  hourly_usd: 1.8
"""

FLOW_SPEC = BLOCK_SPEC.replace("budget:\n  max_spend_usd: 2.0   # the cap\n  max_hours: 1.5\n",
                               "budget: {max_spend_usd: 2.0, max_hours: 1.5}\n")


class RaiseLimits(unittest.TestCase):
    def run_folder(self, text=BLOCK_SPEC, spent=1.2):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        folder = Path(directory.name)
        (folder / "spec.yaml").write_text(text, encoding="utf-8", newline="\n")
        jobs = {"job-a": {"state": "settled", "cost_usd": spent, "reserved_usd": 1.0, "container_seconds": 100}}
        (folder / "ledger.json").write_text(json.dumps({
            "schema_version": 1, "cap_usd": 2.0, "max_hours": 1.5, "hourly_usd": 1.8, "elapsed_seconds": 10.0,
            "jobs": jobs}), encoding="utf-8")
        return folder

    def budget(self, folder):
        parsed = sp.load_spec(folder / "spec.yaml")
        return parsed.budget.max_spend_usd, parsed.budget.max_hours

    def test_the_cap_and_the_hours_go_up_and_the_rest_of_the_spec_is_kept(self):
        folder = self.run_folder()
        limits = rl.raise_limits(folder, max_spend_usd=3.2, max_hours=3)
        self.assertEqual(limits, {"max_spend_usd": 3.2, "max_hours": 3.0})
        self.assertEqual(self.budget(folder), (3.2, 3.0))
        text = (folder / "spec.yaml").read_text(encoding="utf-8")
        self.assertIn("max_spend_usd: 3.2   # the cap", text, "the comment stays")
        self.assertIn("max_hours: 3\n", text)
        self.assertEqual(text.replace("3.2", "2.0").replace("max_hours: 3\n", "max_hours: 1.5\n"), BLOCK_SPEC)

    def test_one_limit_alone_can_be_raised(self):
        folder = self.run_folder()
        rl.raise_limits(folder, max_hours=2.5)
        self.assertEqual(self.budget(folder), (2.0, 2.5))

    def test_a_flow_style_budget_is_raised_too(self):
        folder = self.run_folder(FLOW_SPEC)
        rl.raise_limits(folder, max_spend_usd=4)
        self.assertEqual(self.budget(folder), (4.0, 1.5))

    def test_limits_are_never_lowered(self):
        folder = self.run_folder()
        for kwargs in ({"max_spend_usd": 1.9}, {"max_hours": 1.0}, {"max_spend_usd": 5, "max_hours": 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(rl.RunLimitError):
                rl.raise_limits(folder, **kwargs)
        self.assertEqual(self.budget(folder), (2.0, 1.5), "a refused request changes nothing")

    def test_the_cap_cannot_go_below_what_is_spent(self):
        folder = self.run_folder(spent=2.0)
        (folder / "spec.yaml").write_text(BLOCK_SPEC.replace("2.0   #", "1.0   #"), encoding="utf-8")
        with self.assertRaises(rl.RunLimitError) as caught:
            rl.raise_limits(folder, max_spend_usd=1.5)
        self.assertIn("already spent", str(caught.exception))

    def test_values_that_are_not_numbers_or_out_of_bounds_are_refused(self):
        folder = self.run_folder()
        for kwargs in ({"max_spend_usd": "5"}, {"max_hours": float("nan")}, {"max_spend_usd": True},
                       {"max_spend_usd": 100000}, {"max_hours": 1000}):
            with self.subTest(kwargs=kwargs), self.assertRaises(rl.RunLimitError):
                rl.raise_limits(folder, **kwargs)
        self.assertEqual(self.budget(folder), (2.0, 1.5))

    def test_the_same_values_change_nothing(self):
        folder = self.run_folder()
        self.assertEqual(rl.raise_limits(folder, max_spend_usd=2.0, max_hours=1.5),
                         {"max_spend_usd": 2.0, "max_hours": 1.5})
        self.assertEqual((folder / "spec.yaml").read_text(encoding="utf-8"), BLOCK_SPEC)

    def test_the_ledger_accepts_the_raised_limits_when_the_run_resumes(self):
        folder = self.run_folder()
        rl.raise_limits(folder, max_spend_usd=3.2, max_hours=3)
        spec = sp.load_spec(folder / "spec.yaml")
        ledger = lg.Ledger.load(folder / "ledger.json", cap_usd=spec.budget.max_spend_usd,
                                max_hours=spec.budget.max_hours, hourly_usd=spec.backend.hourly_usd)
        self.assertEqual((ledger.cap_usd, ledger.max_hours, ledger.spent), (3.2, 3.0, 1.2))


if __name__ == "__main__":
    unittest.main()
