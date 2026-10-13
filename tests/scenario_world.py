"""A fake simulator world for the scenario Job modes (no simulator, no model).

``FakeSimulation`` plays the part of one LIBERO-10 task: it knows ten benchmark starts
(start ``i`` puts the soup at x = ``i / 10``), decides outcomes from the start state it
is given, and writes the evidence a real stage leaves behind: an aggregate with the
episode metrics, the scenario sidecar, the exported layout and start state, a video
and a trace. The policy fails exactly when the soup's x is at least ``FAIL_X``; a
scene whose basket sits at the soup's position is an ``invalid_scene``.
"""

import json
import threading
import types
from pathlib import Path

import numpy as np

from robot_debug import external_reset, scene_inspect
from robot_debug.scenario_import import candidate_from_benchmark, load_scenario_candidate, write_scenario_candidate
from tests.scene_fakes import standard_model
from tests.test_batch_experiment import World

FAIL_X = 0.45
INSTRUCTION = "put the alphabet soup in the basket"
SOUP_X = 1 + 3        # flat index of the soup's x (qpos_adr 3)
BASKET_X = 1 + 10     # flat index of the basket's x (qpos_adr 10)
ROBOT_JOINT = 1 + 0


class FakeSimulation:
    def __init__(self, suite="libero_10", instruction=INSTRUCTION, flaky=None, invalid_rule=None,
                 detect_overlap=True, invalid_starts=()):
        self.invalid_starts = set(invalid_starts)   # benchmark starts whose bodies interpenetrate
        self.invalid_rule = invalid_rule or (lambda state: False)   # extra scenes that interpenetrate
        self.detect_overlap = detect_overlap
        self.suite = suite
        self.instruction = instruction
        self.model = standard_model()
        self.length = self.model.state_length
        self.flaky = flaky or (lambda state, params, count: None)   # may force an outcome
        self.lock = threading.Lock()
        self.runs = []
        self.counts = {}

    def layout(self, task_id=0):
        return scene_inspect.build_layout(self.suite, task_id, self.model, self.length)

    def state_for(self, index):
        state = np.zeros(self.length)
        state[ROBOT_JOINT] = 0.01 * index
        state[SOUP_X:SOUP_X + 7] = [0.1 * index, 0.0, 0.8, 1.0, 0.0, 0.0, 0.0]
        state[BASKET_X:BASKET_X + 7] = [0.2, 0.3, 0.8, 1.0, 0.0, 0.0, 0.0]
        return state.tolist()

    def run(self, params, output):
        """Write the evidence of one single-episode stage; ``params`` are the benchmark params."""

        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        task_id = int(params.get("task_id", 0))
        scenario = params.get("scenario_start")
        if scenario:
            candidate = load_scenario_candidate(Path(scenario["candidate"]))
            state = candidate["state"]
        else:
            state = self.state_for(int(params.get("init_state_index", 0)))
        overlap = state[SOUP_X:SOUP_X + 3] == state[BASKET_X:BASKET_X + 3]
        invalid = bool(scenario) and ((overlap and self.detect_overlap) or bool(self.invalid_rule(state)))
        key = json.dumps(state)
        with self.lock:
            count = self.counts[key] = self.counts.get(key, 0) + 1
            self.runs.append(dict(params, _count=count))
        forced = None if invalid else self.flaky(state, params, count)
        if invalid:
            outcome, steps = "invalid_scene", 1
        elif forced is not None:
            outcome, steps = forced, (520 if forced == "policy_failure" else 100)
        elif state[SOUP_X] >= FAIL_X:
            outcome, steps = "policy_failure", 520
        else:
            outcome, steps = "success", 100
        metrics = {"success": outcome == "success"}
        if invalid:
            metrics["invalid_scene"] = True
        episode = {"task_id": task_id, "episode_idx": 0, "name": self.instruction, "steps": steps,
                   "elapsed_sec": 1.5, "metrics": metrics, "failure_reason": None}
        (output / "pilot_aggregate.json").write_text(json.dumps({
            "benchmark": "pilot", "created_at": "2026-10-13T00:00:00Z", "eval_id": "eval-pilot",
            "config": {"benchmark": "robot_debug.libero:DiagnosticLIBEROBenchmark",
                       "params": {"task_id": task_id, "seed": 7, "env_seed": 7}},
            "tasks": [{"task": self.instruction, "episodes": [episode]}]}), encoding="utf-8")
        media = output / "episodes" / "pilot"
        media.mkdir(parents=True, exist_ok=True)
        (media / "task0000_ep0000_fixture.mp4").write_bytes(b"mp4")
        (media / "task0000_ep0000_fixture.jsonl").write_text('{"step":0}\n', encoding="utf-8")
        if scenario:
            digest = external_reset.state_sha256(state)
            Path(scenario["metadata_out"]).write_text(json.dumps([{
                "schema_version": 1, "episode_index": 0, "suite": self.suite, "task_id": task_id,
                "source": candidate["source"], "candidate_state_sha256": digest,
                "pre_settle_state_sha256": digest,
                "post_settle_state_sha256": None if invalid else digest,
                "validity": "invalid_scene" if invalid else "valid", "settling_steps": 0 if invalid else 10,
                "penetration_limit_m": 0.005, "deepest_penetration_m": 0.03 if invalid else 0.0,
                "deepest_pair": ["alphabet_soup_1", "basket_1"] if invalid else None,
                "invalid_contacts": 1 if invalid else 0, "settle_displacement_m": {}}]), encoding="utf-8")
        if params.get("layout_out"):
            Path(params["layout_out"]).write_text(json.dumps(self.layout(task_id)), encoding="utf-8")
        if params.get("state_out"):
            index = int(params.get("init_state_index", 0))
            write_scenario_candidate(Path(params["state_out"]), candidate_from_benchmark(
                self.suite, task_id, index, self.state_for(index)))
            bad = index in self.invalid_starts
            Path(scene_inspect.validity_companion(str(params["state_out"]))).write_text(json.dumps({
                "schema_version": 1, "suite": self.suite, "task_id": task_id, "init_state_index": index,
                "validity": "invalid_scene" if bad else "valid", "penetration_limit_m": 0.005,
                "deepest_penetration_m": 0.012 if bad else 0.0,
                "deepest_pair": ["alphabet_soup_1", "basket_1"] if bad else None,
                "invalid_contacts": 1 if bad else 0}), encoding="utf-8")
        return types.SimpleNamespace(
            outcome="success" if outcome == "success" else "policy_failure", episode_index=0, steps=steps)


class ScenarioWorld(World):
    """The M3 fake process world, with each item's evidence written by a FakeSimulation."""

    def __init__(self, simulation=None, **kwargs):
        super().__init__(**kwargs)
        self.simulation = simulation or FakeSimulation()
        self.by_case = {}
        self.results = {}

    def write_config(self, **kwargs):
        stem = kwargs["config_path"].stem
        params = {key: value for key, value in kwargs.items()
                  if key in ("task_id", "init_state_index", "layout_out", "state_out")}
        params["suite"] = kwargs.get("suite")
        output = Path(kwargs["output_dir"])
        if kwargs.get("scenario_start") is not None:
            params["scenario_start"] = {"candidate": str(kwargs["scenario_start"]),
                                        "metadata_out": str(output / "scenario_start.json")}
        self.by_case[stem] = params
        super().write_config(**kwargs)

    def run_item(self, command, *, item_timeout, cancel):
        super().run_item(command, item_timeout=item_timeout, cancel=cancel)
        case = Path(command[-1]).stem
        output = Path(command[-1]).parent.parent / "runs" / case
        self.results[case] = self.simulation.run(self.by_case[case], output)

    def load_result(self, output):
        return self.results[Path(output).name]
