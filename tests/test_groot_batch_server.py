"""Tests for the instrumented, batch-capable GR00T model server.

The server runs under the model environment (torch, lerobot and vla_eval),
none of which exist on a development workstation. These tests load the script
against stub modules so the pure helpers and the batching glue are exercised
without a GPU; the end-to-end behaviour is covered by the in-image parity check.
"""

from __future__ import annotations

import ast
import asyncio
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "scripts" / "model_servers" / "faultline_groot_server.py"


class FakeTensor:
    """Minimal tensor stand-in backed by a numpy array."""

    def __init__(self, array) -> None:
        self.array = np.asarray(array)

    @property
    def shape(self):
        return self.array.shape

    def detach(self):
        return self

    def to(self, *_args, **_kwargs):
        return self

    def numpy(self):
        return self.array


class _InferenceMode:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def fake_torch_module() -> types.ModuleType:
    module = types.ModuleType("torch")
    module.cat = lambda values, dim=0: FakeTensor(np.concatenate([v.array for v in values], axis=dim))
    module.inference_mode = lambda: _InferenceMode()
    return module


def fake_prepare(frame, device, task=None, robot_type=None):
    """Same contract as lerobot's helper: per item, batch dim of one, plus strings."""

    prepared = {key: FakeTensor(np.asarray(value)[None]) for key, value in frame.items()}
    prepared["task"] = task if task else ""
    prepared["robot_type"] = robot_type if robot_type else ""
    return prepared


class StubLeRobotModelServer:
    """Stands in for ``vla_eval.model_servers.lerobot.LeRobotModelServer``."""

    def __init__(
        self,
        policy_type="groot",
        checkpoint="checkpoint",
        image_keys=None,
        state_key="observation.state",
        device="cuda",
        robot_type="",
        *,
        max_batch_size=1,
        use_select_action=False,
        **kwargs,
    ) -> None:
        self.policy_type = policy_type
        self.checkpoint = checkpoint
        self.state_key = state_key
        self.robot_type = robot_type
        self.max_batch_size = max_batch_size
        self._use_select_action = use_select_action
        self.unused_kwargs = kwargs
        self.upstream_calls = []
        self.observed = []
        self.ended = []

    def _resolve_image_map(self, images):
        mapping = {"agentview": "observation.images.image", "wrist": "observation.images.wrist_image"}
        return {key: value for key, value in mapping.items() if key in images}

    def _resize_to_declared(self, img, _policy_key):
        return img

    def predict(self, obs, ctx):
        self.upstream_calls.append((obs, ctx))
        return {"actions": np.zeros((2, 3), dtype=np.float32)}

    async def on_observation(self, obs, ctx):
        self.observed.append(ctx.session_id)

    async def on_episode_end(self, result, ctx):
        self.ended.append(ctx.session_id)


def stub_modules() -> dict:
    modules = {}
    for name in ("vla_eval", "vla_eval.model_servers", "lerobot", "lerobot.policies"):
        modules[name] = types.ModuleType(name)
    lerobot_module = types.ModuleType("vla_eval.model_servers.lerobot")
    lerobot_module.LeRobotModelServer = StubLeRobotModelServer
    modules["vla_eval.model_servers.lerobot"] = lerobot_module
    utils = types.ModuleType("lerobot.policies.utils")
    utils.prepare_observation_for_inference = fake_prepare
    modules["lerobot.policies.utils"] = utils
    modules["torch"] = fake_torch_module()
    return modules


def load_server_module():
    spec = importlib.util.spec_from_file_location("faultline_groot_server_under_test", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, stub_modules()):
        spec.loader.exec_module(module)
    return module


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Ctx:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id


def observation(marker: float, task: str = "pick up the alphabet soup"):
    return {
        "images": {
            "agentview": np.full((4, 4, 3), int(marker), dtype=np.uint8),
            "wrist": np.full((4, 4, 3), int(marker) + 1, dtype=np.uint8),
        },
        "states": np.full(8, marker, dtype=np.float64),
        "task_description": task,
    }


class RecordingProcessor:
    def __init__(self, fail: bool = False) -> None:
        self.inputs = []
        self.fail = fail

    def __call__(self, batch):
        self.inputs.append(batch)
        if self.fail:
            raise ValueError("expected a single task string")
        return batch


class StatePolicy:
    """Returns one chunk per item whose values encode that item's own state."""

    def __init__(self, drop_last: bool = False) -> None:
        self.batches = []
        self.drop_last = drop_last

    def predict_action_chunk(self, batch):
        self.batches.append(batch)
        states = batch["observation.state"].array
        count = states.shape[0] - (1 if self.drop_last else 0)
        chunk = np.stack([np.full((3, 7), states[i, 0], dtype=np.float32) for i in range(count)])
        return FakeTensor(chunk)


class ModuleCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_server_module()

    def setUp(self) -> None:
        patcher = mock.patch.dict(sys.modules, stub_modules())
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_server(self, **kwargs):
        with mock.patch.object(self.module, "install_shutdown_flush"):
            server = self.module.FaultlineGrootServer(**kwargs)
        server._torch = sys.modules["torch"]
        server._device = "cpu"
        server._preprocess = RecordingProcessor()
        server._postprocess = lambda chunk: chunk
        server._policy = StatePolicy()
        return server


class SourceContractTests(unittest.TestCase):
    def test_script_does_not_import_the_runtime_package(self) -> None:
        tree = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertNotIn("robot_debug", imported)
        self.assertNotIn("scripts", imported)

    def test_script_uses_the_upstream_entry_point_and_has_lf_endings(self) -> None:
        data = SERVER_PATH.read_bytes()
        self.assertNotIn(b"\r\n", data)
        text = data.decode("utf-8")
        self.assertIn("run_server(FaultlineGrootServer)", text)
        self.assertIn("from vla_eval.model_servers.lerobot import LeRobotModelServer", text)

    def test_module_is_importable_without_torch(self) -> None:
        modules = stub_modules()
        del modules["torch"]
        spec = importlib.util.spec_from_file_location("faultline_groot_server_no_torch", SERVER_PATH)
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, modules):
            sys.modules.pop("torch", None)
            spec.loader.exec_module(module)
        self.assertTrue(hasattr(module, "stack_frames"))


class StackFramesTests(ModuleCase):
    def cat(self):
        return sys.modules["torch"].cat

    def prepared(self, marker, task="t"):
        return fake_prepare(
            {"observation.state": np.full(8, marker, dtype=np.float32)}, "cpu", task=task, robot_type="rb"
        )

    def test_tensors_are_concatenated_in_order_and_tasks_become_a_list(self) -> None:
        frames = [self.prepared(1.0, "a"), self.prepared(2.0, "b"), self.prepared(3.0, "c")]
        batch = self.module.stack_frames(frames, self.cat())
        self.assertEqual((3, 8), batch["observation.state"].shape)
        self.assertEqual([1.0, 2.0, 3.0], list(batch["observation.state"].array[:, 0]))
        self.assertEqual(["a", "b", "c"], batch["task"])
        self.assertEqual("rb", batch["robot_type"])

    def test_single_item_batches_still_use_a_task_list(self) -> None:
        batch = self.module.stack_frames([self.prepared(1.0, "only")], self.cat())
        self.assertEqual(["only"], batch["task"])
        self.assertEqual((1, 8), batch["observation.state"].shape)

    def test_mismatched_keys_fail_loudly(self) -> None:
        first = self.prepared(1.0)
        second = self.prepared(2.0)
        del second["observation.state"]
        with self.assertRaisesRegex(ValueError, "same keys"):
            self.module.stack_frames([first, second], self.cat())

    def test_differing_scalar_metadata_fails_loudly(self) -> None:
        first, second = self.prepared(1.0), self.prepared(2.0)
        second["robot_type"] = "other"
        with self.assertRaisesRegex(ValueError, "robot_type"):
            self.module.stack_frames([first, second], self.cat())

    def test_empty_batch_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.module.stack_frames([], self.cat())


class SplitActionsTests(ModuleCase):
    def test_splits_along_the_batch_axis_as_float32_copies(self) -> None:
        chunk = np.arange(2 * 4 * 7, dtype=np.float64).reshape(2, 4, 7)
        actions = self.module.split_actions(chunk, 2)
        self.assertEqual(2, len(actions))
        for index, action in enumerate(actions):
            self.assertEqual(["actions"], list(action))
            self.assertEqual(np.float32, action["actions"].dtype)
            self.assertEqual((4, 7), action["actions"].shape)
            np.testing.assert_array_equal(chunk[index].astype(np.float32), action["actions"])

    def test_wrong_batch_size_or_rank_is_an_error(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "batch"):
            self.module.split_actions(np.zeros((1, 4, 7)), 2)
        with self.assertRaisesRegex(RuntimeError, "chunk"):
            self.module.split_actions(np.zeros((4, 7)), 4)


class TimingRecordTests(ModuleCase):
    def test_record_has_only_numeric_fields(self) -> None:
        record = self.module.timing_record(12.3456789, 3, 41.23456, [0.5, 1.25, 2.0])
        self.assertEqual({"t", "batch_size", "inference_ms", "wait_ms"}, set(record))
        self.assertEqual(3, record["batch_size"])
        self.assertEqual(12.346, record["t"])
        self.assertEqual(41.235, record["inference_ms"])
        self.assertEqual([0.5, 1.25, 2.0], record["wait_ms"])

    def test_wait_list_must_match_the_batch(self) -> None:
        with self.assertRaises(ValueError):
            self.module.timing_record(1.0, 2, 1.0, [0.0])


class TimingLogTests(ModuleCase):
    def setUp(self) -> None:
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "nested" / "timing.jsonl"
        self.clock = FakeClock()

    def make(self, interval: float = 1.0):
        return self.module.TimingLog(str(self.path), clock=self.clock, flush_interval=interval)

    def lines(self):
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]

    def test_wait_is_arrival_to_inference_start_per_session(self) -> None:
        log = self.make()
        log.note_arrival("a")
        self.clock.advance(0.010)
        log.note_arrival("b")
        self.clock.advance(0.040)
        waits = log.take_waits(["a", "b"], self.clock())
        self.assertAlmostEqual(50.0, waits[0], places=3)
        self.assertAlmostEqual(40.0, waits[1], places=3)

    def test_unknown_session_waits_zero_and_arrival_is_consumed(self) -> None:
        log = self.make()
        log.note_arrival("a")
        self.assertEqual([0.0], log.take_waits(["missing"], self.clock()))
        log.take_waits(["a"], self.clock())
        self.assertEqual([0.0], log.take_waits(["a"], self.clock()))

    def test_writes_are_buffered_and_flushed_at_most_once_per_interval(self) -> None:
        log = self.make()
        log.record(self.clock(), 1, 5.0, [0.0])
        self.assertEqual([], self.lines())
        self.clock.advance(0.5)
        log.record(self.clock(), 2, 6.0, [0.0, 1.0])
        self.assertEqual([], self.lines())
        self.clock.advance(0.6)
        log.record(self.clock(), 3, 7.0, [0.0, 1.0, 2.0])
        self.assertEqual([1, 2, 3], [line["batch_size"] for line in self.lines()])
        self.clock.advance(0.2)
        log.record(self.clock(), 1, 8.0, [0.0])
        self.assertEqual(3, len(self.lines()))
        log.flush()
        self.assertEqual(4, len(self.lines()))

    def test_flush_is_idempotent_and_creates_parent_directory(self) -> None:
        log = self.make()
        log.flush()
        log.record(self.clock(), 1, 1.0, [0.0])
        log.flush()
        log.flush()
        self.assertEqual(1, len(self.lines()))

    def test_lines_never_contain_text_or_images(self) -> None:
        log = self.make()
        log.record(self.clock(), 1, 1.0, [0.0])
        log.flush()
        text = self.path.read_text(encoding="utf-8")
        self.assertNotIn("alphabet", text)
        for key in json.loads(text):
            self.assertIn(key, {"t", "batch_size", "inference_ms", "wait_ms"})

    def test_flush_with_a_timeout_gives_up_when_the_lock_is_held(self) -> None:
        log = self.make()
        log.record(self.clock(), 1, 1.0, [0.0])
        log._lock.acquire()  # as if the interrupted thread were inside record()
        try:
            self.assertFalse(log.flush(timeout=0.05))
        finally:
            log._lock.release()
        self.assertEqual([], self.lines())
        self.assertTrue(log.flush(timeout=0.05))
        self.assertEqual(1, len(self.lines()))

    def test_shutdown_handler_still_exits_when_the_lock_is_never_released(self) -> None:
        log = self.make()
        log.record(self.clock(), 1, 1.0, [0.0])
        exits = []
        log._lock.acquire()
        try:
            with mock.patch.object(self.module, "_SHUTDOWN_FLUSH_TIMEOUT_SECONDS", 0.05):
                self.module.make_shutdown_handler(log, exits.append)(15, None)
        finally:
            log._lock.release()
        self.assertEqual([143], exits)

    def test_shutdown_handler_flushes_then_exits_with_signal_status(self) -> None:
        log = self.make()
        log.record(self.clock(), 1, 1.0, [0.0])
        exits = []
        handler = self.module.make_shutdown_handler(log, exits.append)
        handler(15, None)
        self.assertEqual([143], exits)
        self.assertEqual(1, len(self.lines()))


class FrameTests(ModuleCase):
    def test_raw_frame_matches_the_upstream_construction(self) -> None:
        server = self.make_server()
        frame = server._raw_frame(observation(5.0))
        self.assertEqual(
            {"observation.images.image", "observation.images.wrist_image", "observation.state"}, set(frame)
        )
        self.assertEqual(np.uint8, frame["observation.images.image"].dtype)
        self.assertEqual(np.float32, frame["observation.state"].dtype)
        np.testing.assert_array_equal(np.full(8, 5.0, dtype=np.float32), frame["observation.state"])

    def test_state_key_none_sends_no_state(self) -> None:
        server = self.make_server(state_key="None")
        server.state_key = None
        self.assertNotIn("observation.state", server._raw_frame(observation(1.0)))

    def test_state_may_arrive_under_the_singular_key(self) -> None:
        server = self.make_server()
        obs = observation(2.0)
        obs["state"] = obs.pop("states")
        np.testing.assert_array_equal(
            np.full(8, 2.0, dtype=np.float32), server._raw_frame(obs)["observation.state"]
        )


class PredictBatchTests(ModuleCase):
    def test_batch_is_preprocessed_once_with_a_task_list_and_split_per_item(self) -> None:
        server = self.make_server(max_batch_size=3)
        observations = [observation(1.0, "task one"), observation(2.0, "task two"), observation(3.0, "task three")]
        results = server.predict_batch(observations, [Ctx("a"), Ctx("b"), Ctx("c")])
        self.assertEqual(1, len(server._preprocess.inputs))
        batch = server._preprocess.inputs[0]
        self.assertEqual((3, 8), batch["observation.state"].shape)
        self.assertEqual(["task one", "task two", "task three"], batch["task"])
        self.assertEqual(1, len(server._policy.batches))
        self.assertEqual(3, len(results))
        for index, expected in enumerate((1.0, 2.0, 3.0)):
            actions = results[index]["actions"]
            self.assertEqual((3, 7), actions.shape)
            self.assertEqual(np.float32, actions.dtype)
            self.assertTrue(np.all(actions == expected), "each item must decode with its own state")

    def test_a_single_item_batch_matches_the_unbatched_shape(self) -> None:
        server = self.make_server(max_batch_size=2)
        (result,) = server.predict_batch([observation(4.0)], [Ctx("a")])
        self.assertEqual((3, 7), result["actions"].shape)

    def test_processor_rejection_raises_a_clear_runtime_error(self) -> None:
        server = self.make_server(max_batch_size=2)
        server._preprocess = RecordingProcessor(fail=True)
        with self.assertRaisesRegex(RuntimeError, "processor rejected a batched input"):
            server.predict_batch([observation(1.0), observation(2.0)], [Ctx("a"), Ctx("b")])

    def test_policy_returning_the_wrong_batch_size_is_an_error(self) -> None:
        server = self.make_server(max_batch_size=2)
        server._policy = StatePolicy(drop_last=True)
        with self.assertRaisesRegex(RuntimeError, "batch"):
            server.predict_batch([observation(1.0), observation(2.0)], [Ctx("a"), Ctx("b")])

    def test_mixed_state_presence_fails_loudly(self) -> None:
        server = self.make_server(max_batch_size=2)
        no_state = observation(2.0)
        del no_state["states"]
        with self.assertRaisesRegex(ValueError, "same keys"):
            server.predict_batch([observation(1.0), no_state], [Ctx("a"), Ctx("b")])

    def test_select_action_policies_cannot_be_batched(self) -> None:
        with self.assertRaisesRegex(ValueError, "select_action"):
            self.make_server(max_batch_size=2, use_select_action=True)

    def test_empty_batch_is_rejected(self) -> None:
        server = self.make_server(max_batch_size=2)
        with self.assertRaises(ValueError):
            server.predict_batch([], [])


class InstrumentationTests(ModuleCase):
    def setUp(self) -> None:
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "timing.jsonl"

    def lines(self, server):
        server._timing.flush()
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]

    def test_timing_log_is_optional_and_disabled_by_default(self) -> None:
        server = self.make_server()
        self.assertIsNone(server._timing)
        self.assertEqual(1, len(server.predict_batch([observation(1.0)], [Ctx("a")])))
        asyncio.run(server.on_observation(observation(1.0), Ctx("a")))

    def test_timing_log_flows_through_constructor_kwargs(self) -> None:
        server = self.make_server(timing_log=str(self.path), max_batch_size=4, chunk_size=None)
        self.assertEqual(4, server.max_batch_size)
        self.assertEqual({"chunk_size": None}, server.unused_kwargs)
        self.assertIsNotNone(server._timing)

    def test_shutdown_flush_is_installed_only_when_logging(self) -> None:
        with mock.patch.object(self.module, "install_shutdown_flush") as install:
            self.module.FaultlineGrootServer()
            install.assert_not_called()
            self.module.FaultlineGrootServer(timing_log=str(self.path))
            install.assert_called_once()

    def test_batched_call_logs_one_line_with_per_item_waits(self) -> None:
        server = self.make_server(timing_log=str(self.path), max_batch_size=2)
        for session in ("a", "b"):
            asyncio.run(server.on_observation(observation(1.0), Ctx(session)))
        server.predict_batch([observation(1.0), observation(2.0)], [Ctx("a"), Ctx("b")])
        (line,) = self.lines(server)
        self.assertEqual(2, line["batch_size"])
        self.assertEqual(2, len(line["wait_ms"]))
        self.assertGreaterEqual(min(line["wait_ms"]), 0.0)
        self.assertGreaterEqual(line["inference_ms"], 0.0)
        self.assertEqual({"t", "batch_size", "inference_ms", "wait_ms"}, set(line))

    def test_unbatched_predict_delegates_to_upstream_and_logs_batch_of_one(self) -> None:
        server = self.make_server(timing_log=str(self.path))
        obs = observation(1.0)
        result = server.predict(obs, Ctx("a"))
        self.assertEqual({"actions"}, set(result))
        self.assertEqual(1, len(server.upstream_calls))
        self.assertIs(obs, server.upstream_calls[0][0])
        (line,) = self.lines(server)
        self.assertEqual(1, line["batch_size"])
        self.assertEqual(1, len(line["wait_ms"]))

    def test_failed_inference_is_not_logged_as_a_successful_call(self) -> None:
        server = self.make_server(timing_log=str(self.path), max_batch_size=2)
        server._preprocess = RecordingProcessor(fail=True)
        with self.assertRaises(RuntimeError):
            server.predict_batch([observation(1.0), observation(2.0)], [Ctx("a"), Ctx("b")])
        server._timing.flush()
        self.assertFalse(self.path.exists() and self.path.read_text(encoding="utf-8").strip())

    def test_on_observation_notes_arrival_then_defers_to_upstream(self) -> None:
        server = self.make_server(timing_log=str(self.path))
        asyncio.run(server.on_observation(observation(1.0), Ctx("a")))
        self.assertEqual(["a"], server.observed)
        self.assertIn("a", server._timing._arrivals)

    def test_episode_end_forgets_the_session_arrival(self) -> None:
        server = self.make_server(timing_log=str(self.path))
        asyncio.run(server.on_observation(observation(1.0), Ctx("a")))
        asyncio.run(server.on_episode_end({}, Ctx("a")))
        self.assertNotIn("a", server._timing._arrivals)
        self.assertEqual(["a"], server.ended)


if __name__ == "__main__":
    unittest.main()
