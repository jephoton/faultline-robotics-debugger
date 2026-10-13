"""M7: choosing the benchmark start (A) and starting from validated scenario states (B)."""

import types
import unittest

import numpy as np

from tests.scene_fakes import FakeEnv, FakeHarnessCase, FakeTaskSuite


def _states(model_length, count=6):
    """``count`` distinct start states of the fake scene (row i is filled with i)."""
    return [np.full(model_length, float(index)) for index in range(count)]


class InitStateIndexTests(FakeHarnessCase):
    def make(self, **options):
        benchmark = self.benchmark_type(suite="libero_10", **options)
        env = FakeEnv()
        benchmark._make_env = lambda task: env
        benchmark._task_suite = FakeTaskSuite({0: _states(env.model.state_length)})
        return benchmark, env

    def task(self, episode_idx=0):
        return {"task_id": 0, "task_obj": object(), "name": "task 0", "episode_idx": episode_idx}

    def test_every_episode_starts_from_the_configured_init_state(self):
        benchmark, env = self.make(init_state_index=3)
        for episode in (0, 1, 2, 7):
            benchmark.reset(self.task(episode))
            self.assertEqual(3.0, env.state[0])
        self.assertTrue(all(call["episode_idx"] == 3 for call in benchmark.upstream_reset_tasks))

    def test_without_the_option_the_harness_episode_index_is_used(self):
        benchmark, env = self.make()
        task = self.task(4)
        benchmark.reset(task)
        self.assertIs(task, benchmark.upstream_reset_tasks[0])
        self.assertEqual(4.0, env.state[0])

    def test_the_callers_task_is_not_modified(self):
        benchmark, _env = self.make(init_state_index=2)
        task = self.task(5)
        benchmark.reset(task)
        self.assertEqual(5, task["episode_idx"])

    def test_index_zero_is_a_real_selection(self):
        benchmark, env = self.make(init_state_index=0)
        benchmark.reset(self.task(5))
        self.assertEqual(0.0, env.state[0])

    def test_option_is_not_forwarded_upstream_and_keeps_the_suite(self):
        benchmark, _env = self.make(init_state_index=1)
        self.assertEqual({"suite": "libero_10", "seed": 7, "send_wrist_image": False,
                          "send_state": False}, benchmark.upstream_kwargs)
        self.assertEqual(1, benchmark.init_state_index)
        self.assertIsNone(self.benchmark_type().init_state_index)

    def test_rejects_invalid_values(self):
        for value in (-1, True, 1.5, "2", float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.benchmark_type(init_state_index=value)

    def test_cannot_be_combined_with_an_external_reset(self):
        with self.assertRaises(ValueError):
            self.benchmark_type(init_state_index=1,
                                external_reset={"candidate": "a", "metadata_out": "b"})


if __name__ == "__main__":
    unittest.main()
