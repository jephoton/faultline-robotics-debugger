import sys
import unittest
from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))


class PortfolioPolicyTests(unittest.TestCase):
    def setUp(self):
        self.ready = {
            "task-0": ("search-01", "search-02"),
            "task-1": ("confirm-01",),
            "task-2": ("nominal-01",),
        }

    def bounds(self, **changes):
        from robot_debug.portfolio_policy import PortfolioBounds
        values = {"episode_slots": 4, "seconds_left": 180.0, "dollars_left": .1}
        values.update(changes)
        return PortfolioBounds(**values)

    def test_rotates_first_job_and_takes_one_case_per_job(self):
        from robot_debug.portfolio_policy import choose_wave
        first = choose_wave(self.ready, cursor=0, slots=4, bounds=self.bounds())
        second = choose_wave(self.ready, cursor=first.next_cursor, slots=4, bounds=self.bounds())
        self.assertEqual([("task-0", "search-01"), ("task-1", "confirm-01"), ("task-2", "nominal-01")],
                         [(item.job_id, item.case_id) for item in first.requests])
        self.assertEqual("task-1", second.requests[0].job_id)
        self.assertEqual(3, len({(item.job_id, item.case_id) for item in first.requests}))

    def test_continuously_ready_job_is_not_starved_across_rotations(self):
        from robot_debug.portfolio_policy import choose_wave
        ready = {"task-0": ("a",), "task-1": ("b",), "task-2": ("c",)}
        cursor = 0
        first_jobs = []
        for _ in range(3):
            wave = choose_wave(ready, cursor=cursor, slots=1, bounds=self.bounds(episode_slots=1))
            first_jobs.append(wave.requests[0].job_id)
            cursor = wave.next_cursor
        self.assertEqual(["task-0", "task-1", "task-2"], first_jobs)

    def test_full_frozen_job_set_prevents_dynamic_readiness_starvation(self):
        from robot_debug.portfolio_policy import choose_wave
        cursor = 0
        first_jobs = []
        # The runner retains every manifest key even while one job is paused.
        # With a cursor over just eligible jobs this can select task-0 then
        # task-2 forever, starving continuously-ready task-1.
        for ready in (
            {"task-0": ("a",), "task-1": ("b",), "task-2": None},
            {"task-0": None, "task-1": ("b",), "task-2": ("c",)},
            {"task-0": ("a",), "task-1": ("b",), "task-2": None},
        ):
            wave = choose_wave(ready, cursor=cursor, slots=1, bounds=self.bounds(episode_slots=1))
            first_jobs.append(wave.requests[0].job_id)
            cursor = wave.next_cursor
        self.assertIn("task-1", first_jobs)

    def test_rotation_uses_sorted_full_keys_with_more_than_four_jobs(self):
        from robot_debug.portfolio_policy import choose_wave
        ready = {"task-4": ("e",), "task-2": ("c",), "task-0": ("a",),
                 "task-3": ("d",), "task-1": ("b",)}
        wave = choose_wave(ready, cursor=3, slots=4, bounds=self.bounds())
        self.assertEqual(["task-3", "task-4", "task-0", "task-1"],
                         [item.job_id for item in wave.requests])
        self.assertEqual(4, wave.next_cursor)

    def test_admission_failure_or_ineligible_job_produces_no_work(self):
        from robot_debug.portfolio_policy import choose_wave
        for bounds in (self.bounds(episode_slots=0), self.bounds(seconds_left=0), self.bounds(dollars_left=0)):
            self.assertEqual((), choose_wave(self.ready, cursor=0, slots=4, bounds=bounds).requests)
        paused = {"task-0": ("search-01",), "task-1": None, "task-2": ()}
        wave = choose_wave(paused, cursor=0, slots=4, bounds=self.bounds())
        self.assertEqual(["task-0"], [item.job_id for item in wave.requests])

    def test_rejects_invalid_bounds_cursor_slots_and_duplicate_cases(self):
        from robot_debug.portfolio_policy import choose_wave
        with self.assertRaises(ValueError):
            choose_wave(self.ready, cursor=-1, slots=4, bounds=self.bounds())
        with self.assertRaises(ValueError):
            choose_wave(self.ready, cursor=0, slots=5, bounds=self.bounds())
        with self.assertRaises(ValueError):
            choose_wave({"task-0": ("same", "same")}, cursor=0, slots=1, bounds=self.bounds())


if __name__ == "__main__":
    unittest.main()
