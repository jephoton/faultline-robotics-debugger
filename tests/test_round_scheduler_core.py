"""Shared M3/adaptive attempt-ownership scheduler contracts."""

import tempfile
import threading
import time
import unittest
from pathlib import Path

from robot_debug.attempt_ledger import AttemptLedger
from robot_debug.round_scheduler import run_schedule


class SharedRoundSchedulerTests(unittest.TestCase):
    def test_two_workers_preserve_manifest_order_and_durable_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            items = [{"case_id": f"case-{i}"} for i in range(1, 5)]
            ledger = AttemptLedger([item["case_id"] for item in items])
            summary = {"results": [], "stop_reason": None}
            stop = threading.Event()
            interrupt = threading.Event()
            lock = threading.Lock()
            started = time.monotonic()
            maximum_active = 0
            active = 0
            saves = []

            def save():
                summary.update(ledger.snapshot())
                saves.append(ledger.snapshot())

            def paths(item):
                name = item["case_id"]
                return root / f"{name}.yaml", root / name

            def prepare(item, config, output):
                config.write_text(item["case_id"], encoding="utf-8")

            def execute(item, config, output, attempt_started):
                nonlocal active, maximum_active
                with lock:
                    active += 1
                    maximum_active = max(maximum_active, active)
                time.sleep((5 - int(item["case_id"][-1])) * .01)
                with lock:
                    active -= 1
                return {"case_id": item["case_id"], "status": "valid", "outcome": "success"}

            result = run_schedule(
                items=items, workers=2, ledger=ledger, summary=summary,
                elapsed=lambda: time.monotonic() - started,
                launch_cutoff_seconds=60, stop_requested=stop,
                interrupt_event=interrupt, launch_lock=lock,
                request_stop=stop.set, save=save, item_paths=paths,
                validate_prepared_artifacts=lambda item, config, output: config.exists(),
                prepare_config=prepare, execute=execute,
            )

            self.assertEqual(maximum_active, 2)
            self.assertIs(result, summary)
            self.assertEqual([item["case_id"] for item in items],
                             [record["case_id"] for record in result["results"]])
            self.assertTrue(any("submitting_unknown" in snapshot["attempt_states"].values()
                                for snapshot in saves))
            self.assertTrue(all(state == "terminal" for state in result["attempt_states"].values()))


if __name__ == "__main__":
    unittest.main()
