import copy
import json
import math
import os
import tempfile
import unittest
from pathlib import Path

from robot_debug import external_reset
from robot_debug import scenario_import as si


STATE = [0.0, 0.5, -1.25, 3.0e-3, 2.0]


def benchmark_candidate(**changes):
    candidate = si.candidate_from_benchmark("libero_10", 3, 7, STATE)
    candidate.update(changes)
    return candidate


def hybrid_source(**changes):
    source = {"kind": "hybrid", "reference": 7, "failing": 23,
              "applied": [{"entity": "alphabet_soup_1", "part": "position", "t": 0.5},
                          {"entity": "robot", "part": "joints", "t": 1.0}]}
    source.update(changes)
    return source


class BuildTests(unittest.TestCase):
    def test_benchmark_candidate_has_exactly_the_documented_keys(self):
        candidate = benchmark_candidate()
        self.assertEqual({"schema_version", "suite", "task_id", "state", "source", "state_sha256"},
                         set(candidate))
        self.assertEqual(1, candidate["schema_version"])
        self.assertEqual("libero_10", candidate["suite"])
        self.assertEqual(3, candidate["task_id"])
        self.assertEqual(STATE, candidate["state"])
        self.assertEqual({"kind": "benchmark", "init_state_index": 7}, candidate["source"])

    def test_hash_uses_the_external_reset_packing(self):
        self.assertEqual(external_reset.state_sha256(STATE), benchmark_candidate()["state_sha256"])
        self.assertEqual(external_reset._state_sha256(STATE), benchmark_candidate()["state_sha256"])

    def test_numpy_style_states_and_ints_become_plain_floats(self):
        import numpy as np
        candidate = si.candidate_from_benchmark("libero_object", 0, 0, np.array([1, 2, 3], dtype=np.float32))
        self.assertEqual([1.0, 2.0, 3.0], candidate["state"])
        self.assertTrue(all(type(item) is float for item in candidate["state"]))
        self.assertEqual(external_reset.state_sha256([1.0, 2.0, 3.0]), candidate["state_sha256"])

    def test_builder_rejects_bad_arguments(self):
        for kwargs in (
            dict(suite="libero_90"), dict(suite=3), dict(task_id=-1), dict(task_id=True),
            dict(init_state_index=-1), dict(init_state_index=1.5), dict(init_state_index=True),
            dict(state=[]), dict(state=[1.0, float("nan")]), dict(state="abc"),
        ):
            arguments = dict(suite="libero_10", task_id=0, init_state_index=0, state=STATE)
            arguments.update(kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(si.ScenarioImportError):
                si.candidate_from_benchmark(**arguments)

    def test_hybrid_candidates_can_be_built_and_validated(self):
        candidate = si.build_candidate("libero_10", 3, STATE, hybrid_source())
        self.assertEqual(candidate, si.validate_scenario_candidate(candidate))


class ValidationTests(unittest.TestCase):
    def test_valid_candidate_round_trips_detached(self):
        original = benchmark_candidate()
        checked = si.validate_scenario_candidate(original)
        self.assertEqual(original, checked)
        checked["state"][0] = 99.0
        checked["source"]["init_state_index"] = 1
        self.assertEqual(0.0, original["state"][0])
        self.assertEqual(7, original["source"]["init_state_index"])

    def test_integers_in_the_state_are_normalised_to_floats_before_hashing(self):
        candidate = benchmark_candidate()
        candidate["state"] = [0, 0.5, -1.25, 3.0e-3, 2]
        checked = si.validate_scenario_candidate(candidate)
        self.assertTrue(all(type(item) is float for item in checked["state"]))

    def test_exact_key_set(self):
        extra = dict(benchmark_candidate(), extra=1)
        with self.assertRaises(si.ScenarioImportError):
            si.validate_scenario_candidate(extra)
        for key in list(benchmark_candidate()):
            missing = benchmark_candidate()
            del missing[key]
            with self.subTest(missing=key), self.assertRaises(si.ScenarioImportError):
                si.validate_scenario_candidate(missing)
        for value in (None, [], "x", 3, tuple(benchmark_candidate().items())):
            with self.subTest(value=value), self.assertRaises(si.ScenarioImportError):
                si.validate_scenario_candidate(value)

    def test_scalar_fields_fail_closed(self):
        for changes in (
            {"schema_version": 2}, {"schema_version": True}, {"schema_version": "1"}, {"schema_version": 1.0},
            {"suite": "libero_90"}, {"suite": "libero_object "}, {"suite": None},
            {"task_id": -1}, {"task_id": True}, {"task_id": 1.0}, {"task_id": "3"}, {"task_id": 10 ** 6},
        ):
            with self.subTest(changes=changes), self.assertRaises(si.ScenarioImportError):
                si.validate_scenario_candidate(benchmark_candidate(**changes))

    def test_state_is_a_bounded_list_of_finite_numbers(self):
        bad_states = (
            [], (0.0, 1.0), "abc", None, {"a": 1},
            [0.0, float("nan")], [0.0, float("inf")], [0.0, -float("inf")],
            [0.0, True], [0.0, "1"], [0.0, None], [0.0, [1.0]],
            [0.0] * (si.MAX_STATE_LENGTH + 1),
            [10 ** 400],
        )
        for state in bad_states:
            candidate = benchmark_candidate()
            candidate["state"] = state
            with self.subTest(state=str(state)[:40]), self.assertRaises(si.ScenarioImportError):
                si.validate_scenario_candidate(candidate)

    def test_hash_must_match_the_state_exactly(self):
        digest = benchmark_candidate()["state_sha256"]
        for value in ("0" * 64, digest.upper(), digest[:-1], digest + "0", None, 5, ""):
            with self.subTest(value=value), self.assertRaises(si.ScenarioImportError):
                si.validate_scenario_candidate(benchmark_candidate(state_sha256=value))
        changed = benchmark_candidate()
        changed["state"][1] += 1e-12
        with self.assertRaises(si.ScenarioImportError):
            si.validate_scenario_candidate(changed)

    def test_benchmark_source_shapes(self):
        for source in (
            {"kind": "benchmark"}, {"kind": "benchmark", "init_state_index": -1},
            {"kind": "benchmark", "init_state_index": True}, {"kind": "benchmark", "init_state_index": 1.0},
            {"kind": "benchmark", "init_state_index": 1, "extra": 2},
            {"kind": "demo", "init_state_index": 1}, {"init_state_index": 1}, None, "benchmark", [],
            {"kind": "benchmark", "init_state_index": 10 ** 6},
        ):
            with self.subTest(source=source), self.assertRaises(si.ScenarioImportError):
                si.validate_scenario_candidate(benchmark_candidate(source=source))

    def test_hybrid_source_shapes(self):
        good = si.validate_scenario_candidate(benchmark_candidate(source=hybrid_source()))
        self.assertEqual(hybrid_source(), good["source"])
        bad = (
            hybrid_source(reference=-1), hybrid_source(reference=True), hybrid_source(failing="23"),
            hybrid_source(applied="all"), hybrid_source(applied=None),
            hybrid_source(applied=[{"t": float("nan")}]),
            hybrid_source(applied=[{"entity": "x" * 300}]),
            hybrid_source(applied=[{"entity": "a\nb"}]),
            hybrid_source(applied=[1] * (si.MAX_APPLIED + 1)),
            hybrid_source(applied=[{1: "non-string key"}]),
            hybrid_source(applied=[object()]),
            hybrid_source(applied=[[[[[["too deep"]]]]]]),
            dict(hybrid_source(), extra=1),
        )
        for source in bad:
            with self.subTest(source=str(source)[:60]), self.assertRaises(si.ScenarioImportError):
                si.validate_scenario_candidate(benchmark_candidate(source=source))
        missing = hybrid_source()
        del missing["failing"]
        with self.assertRaises(si.ScenarioImportError):
            si.validate_scenario_candidate(benchmark_candidate(source=missing))

    def test_input_is_not_modified(self):
        candidate = benchmark_candidate(source=hybrid_source())
        before = copy.deepcopy(candidate)
        si.validate_scenario_candidate(candidate)
        self.assertEqual(before, candidate)

    def test_errors_do_not_echo_the_content(self):
        secret = "SECRET-VALUE"
        candidate = benchmark_candidate(source={"kind": "benchmark", "init_state_index": secret})
        with self.assertRaises(si.ScenarioImportError) as context:
            si.validate_scenario_candidate(candidate)
        self.assertNotIn(secret, str(context.exception))


class TargetTests(unittest.TestCase):
    def test_target_must_match_suite_task_and_state_length(self):
        candidate = si.validate_scenario_candidate(benchmark_candidate())
        si.check_scenario_target(candidate, suite="libero_10", task_id=3, state_length=len(STATE))
        for kwargs in (dict(suite="libero_object"), dict(task_id=4), dict(state_length=len(STATE) + 1)):
            arguments = dict(suite="libero_10", task_id=3, state_length=len(STATE))
            arguments.update(kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(si.ScenarioImportError):
                si.check_scenario_target(candidate, **arguments)


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, text, name="candidate.json"):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_write_then_load_round_trip(self):
        candidate = benchmark_candidate()
        path = self.root / "out" / "candidate.json"
        si.write_scenario_candidate(path, candidate)
        self.assertEqual(candidate, si.load_scenario_candidate(path))
        self.assertEqual([], [name for name in os.listdir(path.parent) if "partial" in name or "tmp" in name])

    def test_write_refuses_an_invalid_candidate(self):
        with self.assertRaises(si.ScenarioImportError):
            si.write_scenario_candidate(self.root / "x.json", benchmark_candidate(task_id=-1))
        self.assertFalse((self.root / "x.json").exists())

    def test_load_rejects_bad_files(self):
        good = json.dumps(benchmark_candidate())
        duplicate = good[:-1] + ', "suite": "libero_object"}'
        cases = {
            "invalid json": "{",
            "not an object": "[1, 2]",
            "duplicate key": duplicate,
            "nan constant": good.replace("0.5", "NaN"),
            "infinity constant": good.replace("0.5", "Infinity"),
            "empty": "",
            "oversize": " " * (si.MAX_FILE_BYTES + 1),
        }
        for name, text in cases.items():
            with self.subTest(name), self.assertRaises(si.ScenarioImportError):
                si.load_scenario_candidate(self.write(text))
        with self.assertRaises(si.ScenarioImportError):
            si.load_scenario_candidate(self.root / "absent.json")
        with self.assertRaises(si.ScenarioImportError):
            si.load_scenario_candidate(self.root)

    def test_a_maximum_size_state_fits_in_the_file_bound(self):
        state = [-1.2345678901234567e-3] * si.MAX_STATE_LENGTH
        path = self.root / "big.json"
        si.write_scenario_candidate(path, si.candidate_from_benchmark("libero_10", 0, 0, state))
        self.assertLessEqual(path.stat().st_size, si.MAX_FILE_BYTES)
        self.assertEqual(si.MAX_STATE_LENGTH, len(si.load_scenario_candidate(path)["state"]))


if __name__ == "__main__":
    unittest.main()
