"""Progress of a diagnosis run: the route and the steps of the branch it took."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from robot_debug.viewer import processes as px
from tests.ui_fixtures import ledger_document, steps_document, write_json, write_text

SPEC = ("faultline: 1\nname: demo\nmode: diagnose\npolicy: {suite: libero_object}\n"
        "diagnose: {task: 0, start: 0}\nbudget: {max_spend_usd: 7.0, max_hours: 4}\n")


def make(root: Path, steps, run) -> Path:
    folder = root / "demo-20261018T100000Z"
    write_text(folder / "spec.yaml", SPEC)
    write_json(folder / "steps.json", steps_document("demo", "diagnose", steps, run))
    write_json(folder / "ledger.json", ledger_document(1.0))
    return folder


def done(**extra):
    return dict({"status": "done"}, **extra)


class DiagnoseProgress(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def progress(self):
        return px.run_progress(self.root, "demo-20261018T100000Z", lambda pid: px.ProcessInfo(False, None))

    def test_the_route_is_unknown_until_the_check_has_been_read(self):
        make(self.root, {"screen": {"status": "running"}}, {"status": "running"})
        progress = self.progress()
        self.assertIsNone(progress["route"])
        self.assertEqual([row["key"] for row in progress["steps"]], ["screen"])
        self.assertEqual(progress["mode"], "diagnose")

    def test_the_probe_route_lists_its_jobs_in_order_and_the_cases(self):
        steps = {"screen": done(), "probe-image-1": done(), "probe-image-2": done(), "probe-scene-1": {"status": "running"},
                 "rewording-screen": {"status": "pending"}}
        make(self.root, steps, {"status": "stopped", "reason": "stopped_by_user", "route": "probes"})
        progress = self.progress()
        self.assertEqual(progress["route"], "probes")
        keys = [row["key"] for row in progress["steps"]]
        self.assertEqual(keys, ["screen", "probe-image-1", "probe-image-2", "probe-scene-1", "rewording-screen",
                                "case-audit", "case-wording", "register"])
        labels = {row["key"]: row["label"] for row in progress["steps"]}
        self.assertEqual(labels["probe-image-2"], "Stress test: image disturbances (2)")
        self.assertEqual(labels["rewording-screen"], "Screen the rewordings")
        self.assertTrue(progress["resumable"])

    def test_the_layout_route_continues_like_the_scenario_mode(self):
        steps = {"screen": done(), "plan": done(), "reduce": done(), "reduce2": {"status": "running"}}
        make(self.root, steps, {"status": "stopped", "reason": "capacity_unavailable", "route": "layout"})
        keys = [row["key"] for row in self.progress()["steps"]]
        self.assertEqual(keys, ["screen", "plan", "reduce", "reduce2", "report", "case", "explain", "register"])

    def test_a_run_that_passes_untouched_points_at_its_run_page(self):
        make(self.root, {"screen": done(), "report": done()}, {"status": "completed", "reason": None, "route": "passes"})
        progress = self.progress()
        self.assertEqual((progress["route"], progress["status"]), ("passes", "completed"))
        self.assertEqual(progress["library_id"], "r-demo-20261018T100000Z")
        self.assertEqual([row["key"] for row in progress["steps"]], ["screen", "report"])

    def test_a_registered_case_is_the_library_id_and_an_unknown_route_value_is_ignored(self):
        steps = {"screen": done(), "register": done(case_id="ab" * 32, case_ids=["ab" * 32, "cd" * 32])}
        make(self.root, steps, {"status": "completed", "route": "nonsense"})
        progress = self.progress()
        self.assertIsNone(progress["route"])
        self.assertEqual(progress["library_id"], "d-" + "ab" * 32)

    def test_the_replay_of_several_jobs_lists_each(self):
        folder = self.root / "replay-20261018T110000Z"
        write_text(folder / "spec.yaml", "faultline: 1\nname: replay\nmode: replay\nbudget: {max_spend_usd: 3, max_hours: 2}\n")
        write_json(folder / "steps.json", steps_document("replay", "replay", {"replay": done(), "replay-2": {"status": "running"}},
                                                         {"status": "running"}))
        write_json(folder / "ledger.json", ledger_document(0.5))
        progress = px.run_progress(self.root, folder.name, lambda pid: px.ProcessInfo(False, None))
        self.assertEqual([row["key"] for row in progress["steps"]], ["replay", "replay-2"])
        self.assertEqual(progress["steps"][1]["label"], "Replay the case (2)")


if __name__ == "__main__":
    unittest.main()
