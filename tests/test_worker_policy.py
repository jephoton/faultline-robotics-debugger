"""One-GPU worker selection contracts."""

import math
import unittest

from robot_debug.worker_policy import choose_workers


M3_PER_ITEM = {1: 610.247 / 16, 2: 310.472 / 16, 4: 164.256 / 16}


class WorkerPolicyTests(unittest.TestCase):
    def choose(self, **overrides):
        values = dict(
            ready_count=4,
            seconds_left=180.0,
            dollars_left=0.10,
            hourly_rate=1.7468,
            measured_seconds=M3_PER_ITEM,
            shutdown_reserve_seconds=20.0,
        )
        values.update(overrides)
        return choose_workers(**values)

    def test_no_ready_work_uses_no_workers(self):
        choice = self.choose(ready_count=0)
        self.assertEqual(choice.workers, 0)
        self.assertEqual(choice.predicted_cost_usd, 0)

    def test_one_ready_case_uses_one_worker(self):
        self.assertEqual(self.choose(ready_count=1).workers, 1)

    def test_four_ready_cases_use_measured_four_worker_mode(self):
        choice = self.choose()
        self.assertEqual(choice.workers, 4)
        self.assertLessEqual(choice.predicted_cost_usd, 0.10)
        self.assertIn("measured", choice.reason)

    def test_budget_that_cannot_cover_reserve_refuses_launch(self):
        self.assertEqual(self.choose(dollars_left=0.001).workers, 0)

    def test_missing_measurements_fall_back_to_one_only_when_affordable(self):
        self.assertEqual(self.choose(measured_seconds={}).workers, 1)
        self.assertEqual(self.choose(measured_seconds={}, dollars_left=0.001).workers, 0)

    def test_rejects_invalid_scalar_inputs(self):
        for field, value in (
            ("ready_count", True), ("ready_count", -1), ("ready_count", 1.5),
            ("seconds_left", math.nan), ("seconds_left", math.inf),
            ("dollars_left", -1), ("hourly_rate", False),
            ("shutdown_reserve_seconds", -1),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.choose(**{field: value})

    def test_unusable_measurement_is_not_trusted(self):
        choice = self.choose(measured_seconds={1: math.nan, 2: -1, 4: math.inf})
        self.assertEqual(choice.workers, 1)
        self.assertIn("fallback", choice.reason)


if __name__ == "__main__":
    unittest.main()
