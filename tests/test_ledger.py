"""The spend ledger: reservations, settlement, persistence and the wall-clock cap."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from robot_debug import ledger as lg

RATE = 1.8                      # US$ per hour: round numbers keep the arithmetic readable


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "ledger.json"
        self.clock = Clock()

    def make(self, cap=3.0, hours=2.0):
        return lg.Ledger(self.path, cap_usd=cap, max_hours=hours, hourly_usd=RATE, clock=self.clock)

    def test_worst_case_is_deadline_plus_start_allowance(self):
        ledger = self.make()
        # 1800 s + 240 s at US$1.80/h
        self.assertAlmostEqual(ledger.worst_case_usd(1800), (1800 + 240) / 3600 * RATE)

    def test_reserve_then_settle_converts_container_time(self):
        ledger = self.make()
        ledger.reserve("a", ledger.worst_case_usd(1800))
        self.assertAlmostEqual(ledger.reserved, 1.02)
        cost = ledger.settle("a", container_seconds=1200)
        self.assertAlmostEqual(cost, (1200 + 240) / 3600 * RATE)
        self.assertAlmostEqual(ledger.spent, 0.72)
        self.assertEqual(ledger.reserved, 0.0)

    def test_capacity_failure_costs_nothing(self):
        ledger = self.make()
        ledger.reserve("a", 1.0)
        self.assertEqual(ledger.settle("a", container_seconds=None), 0.0)
        self.assertEqual(ledger.spent, 0.0)
        self.assertEqual(ledger.reserved, 0.0)

    def test_refuses_when_spent_plus_reserved_plus_new_exceeds_cap(self):
        ledger = self.make(cap=3.0)
        ledger.reserve("a", 1.0)
        ledger.settle("a", container_seconds=3600)      # (3600+240)/3600*1.8 = 1.92
        ledger.reserve("b", 1.0)                          # 1.92 + 1.0 = 2.92 <= 3.0
        with self.assertRaises(lg.BudgetExceeded) as caught:
            ledger.reserve("c", 0.2)                      # 2.92 + 0.2 > 3.0
        self.assertIn("3.00", str(caught.exception))
        self.assertNotIn("c", ledger.jobs)

    def test_exactly_the_cap_is_allowed(self):
        ledger = self.make(cap=1.0)
        ledger.reserve("a", 1.0)
        with self.assertRaises(lg.BudgetExceeded):
            ledger.reserve("b", 0.01)

    def test_settle_is_idempotent_and_unknown_jobs_are_errors(self):
        ledger = self.make()
        ledger.reserve("a", 1.0)
        first = ledger.settle("a", container_seconds=600)
        self.assertEqual(ledger.settle("a", container_seconds=999), first)
        self.assertRaises(lg.LedgerError, ledger.settle, "missing", container_seconds=1)
        self.assertRaises(lg.LedgerError, ledger.reserve, "a", 0.1)

    def test_unknown_outcome_is_settled_at_the_reserved_worst_case(self):
        ledger = self.make()
        ledger.reserve("a", 1.25)
        self.assertEqual(ledger.settle_worst_case("a"), 1.25)
        self.assertEqual(ledger.spent, 1.25)

    def test_overrun_is_recorded_honestly(self):
        ledger = self.make()
        ledger.reserve("a", 0.5)
        ledger.settle("a", container_seconds=7200)
        self.assertGreater(ledger.spent, 0.5)

    def test_invalid_reservations_are_refused(self):
        ledger = self.make()
        for bad in (-1, float("nan"), float("inf"), "1", None):
            self.assertRaises(lg.LedgerError, ledger.reserve, "x", bad)

    def test_a_free_backend_can_reserve_zero(self):
        ledger = lg.Ledger(self.path, cap_usd=1.0, max_hours=1.0, hourly_usd=0.0, clock=self.clock)
        ledger.reserve("local", ledger.worst_case_usd(1800))
        self.assertEqual(ledger.settle("local", container_seconds=100), 0.0)

    def test_persisted_after_every_change_and_reloadable(self):
        ledger = self.make()
        ledger.reserve("a", 1.0)
        on_disk = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["jobs"]["a"]["state"], "reserved")
        ledger.settle("a", container_seconds=1800)
        again = lg.Ledger.load(self.path, cap_usd=3.0, max_hours=2.0, hourly_usd=RATE, clock=self.clock)
        self.assertAlmostEqual(again.spent, ledger.spent)
        self.assertEqual(again.jobs["a"]["state"], "settled")

    def test_reload_with_a_different_cap_or_rate_is_refused(self):
        self.make().reserve("a", 1.0)
        for kwargs in ({"cap_usd": 9.0}, {"hourly_usd": 9.0}, {"max_hours": 9.0}):
            values = dict(cap_usd=3.0, max_hours=2.0, hourly_usd=RATE)
            values.update(kwargs)
            with self.assertRaises(lg.LedgerError):
                lg.Ledger.load(self.path, clock=self.clock, **values)

    def test_load_creates_when_absent(self):
        ledger = lg.Ledger.load(self.path, cap_usd=3.0, max_hours=2.0, hourly_usd=RATE, clock=self.clock)
        self.assertEqual(ledger.spent, 0.0)
        self.assertTrue(self.path.exists())

    def test_corrupt_file_is_refused(self):
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(lg.LedgerError):
            lg.Ledger.load(self.path, cap_usd=3.0, max_hours=2.0, hourly_usd=RATE, clock=self.clock)

    def test_wall_clock_cap(self):
        ledger = self.make(hours=1.0)
        ledger.check_time()
        self.clock.now += 3000
        self.assertAlmostEqual(ledger.remaining_seconds(), 600)
        ledger.check_time(extra_seconds=500)
        with self.assertRaises(lg.TimeExhausted):
            ledger.check_time(extra_seconds=700)
        self.clock.now += 700
        with self.assertRaises(lg.TimeExhausted):
            ledger.check_time()

    def test_wall_clock_survives_a_resume_without_counting_downtime(self):
        ledger = self.make(hours=1.0)
        self.clock.now += 1800
        ledger.reserve("a", 0.1)                        # persists the elapsed 1800 s
        self.clock.now += 100000                         # the machine was off for a day
        again = lg.Ledger.load(self.path, cap_usd=3.0, max_hours=1.0, hourly_usd=RATE, clock=self.clock)
        self.assertAlmostEqual(again.remaining_seconds(), 1800, delta=1)

    def test_remaining_budget_and_status_text(self):
        ledger = self.make(cap=3.0)
        ledger.reserve("a", 1.0)
        ledger.settle("a", container_seconds=1800)       # 0.18 + ... = (1800+240)/3600*1.8
        self.assertAlmostEqual(ledger.remaining, 3.0 - 1.02)
        self.assertIn("US$1.02 / 3.00", ledger.status_text())


if __name__ == "__main__":
    unittest.main()
