"""The paraphrase Job modes: configuration, deadlines, the instruction channel, gates, reduction, cases."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import threading
import types
import unittest
from pathlib import Path
import tempfile

import yaml

from robot_debug import language_experiment as le
from robot_debug import paraphrase as pp
from robot_debug import scenario_experiment as se
from robot_debug.job_runtime import JobRuntimeError, LANGUAGE_MODES, validate_workload_config
from tests.scenario_fakes import FakeExecutor
from tests.scenario_world import FakeSimulation
from tests.test_batch_experiment import World

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = "pick up the alphabet soup and place it in the basket"
PARAPHRASES = [
    "grab the alphabet soup, then put it in the basket.",          # fails: "grab"
    "take the alphabet soup and drop it into the basket",          # flaky: one failure only
    "put the alphabet soup in the basket",
    "move the soup into the basket",
]


def screen_config(**changes):
    config = {
        "schema_version": 1, "mode": "paraphrase-screen", "run_id": "lang-screen-1", "deadline_seconds": 1200,
        "suite": "libero_object", "task_id": 0, "init_state_index": 0, "original": ORIGINAL,
        "paraphrases": list(PARAPHRASES),
    }
    config.update(changes)
    return config


def reduce_config(paraphrase=PARAPHRASES[0], **changes):
    config = {
        "schema_version": 1, "mode": "paraphrase-reduce", "run_id": "lang-reduce-1", "deadline_seconds": 1200,
        "suite": "libero_object", "task_id": 0, "init_state_index": 0, "original": ORIGINAL,
        "paraphrase": paraphrase, "edits": pp.word_edits(ORIGINAL, paraphrase),
    }
    config.update(changes)
    return config


class ModeRegistrationTests(unittest.TestCase):
    def test_the_modes_are_registered_with_the_runtime(self):
        self.assertEqual(set(le.LANGUAGE_MODES), LANGUAGE_MODES)
        self.assertFalse(LANGUAGE_MODES & set(se.SCENARIO_MODES))


class ScreenConfigTests(unittest.TestCase):
    def test_defaults_and_round_trip(self):
        config = validate_workload_config(screen_config())
        self.assertEqual((1, 4, 4), (config["attempts"], config["confirm_attempts"], config["required_failures"]))
        self.assertEqual(PARAPHRASES, config["paraphrases"])
        self.assertEqual(json.loads(json.dumps(config)), config)

    def test_suite_defaults_to_libero_object_and_all_four_suites_are_accepted(self):
        config = screen_config()
        del config["suite"]
        self.assertEqual("libero_object", validate_workload_config(config)["suite"])
        for suite in le.LANGUAGE_SUITES:
            self.assertEqual(suite, validate_workload_config(screen_config(suite=suite))["suite"])

    def test_bad_fields_are_rejected(self):
        bad = (
            {"paraphrases": []}, {"paraphrases": "x"}, {"paraphrases": [PARAPHRASES[0]] * 2},
            {"paraphrases": [ORIGINAL.upper()]}, {"paraphrases": ["  padded "]}, {"paraphrases": [""]},
            {"paraphrases": ["café"]}, {"paraphrases": [1]}, {"paraphrases": ["x" + str(i) for i in range(13)]},
            {"original": ""}, {"original": "  x"}, {"original": "x" * 201}, {"original": None},
            {"task_id": 10}, {"task_id": -1}, {"task_id": True}, {"init_state_index": 50},
            {"init_state_index": -1}, {"suite": "libero_90"}, {"suite": None},
            {"attempts": 2}, {"attempts": 0}, {"confirm_attempts": 9}, {"confirm_attempts": -1},
            {"required_failures": 6}, {"required_failures": 1}, {"required_failures": 0},
            {"surprise": 1},
        )
        for changes in bad:
            with self.subTest(changes=str(changes)[:80]), self.assertRaises(JobRuntimeError):
                validate_workload_config(screen_config(**changes))

    def test_required_fields(self):
        for key in ("original", "paraphrases", "task_id", "init_state_index"):
            config = screen_config()
            del config[key]
            with self.subTest(missing=key), self.assertRaises(JobRuntimeError):
                validate_workload_config(config)

    def test_a_screen_without_confirmation_may_require_one_failure(self):
        config = validate_workload_config(screen_config(confirm_attempts=0, required_failures=1))
        self.assertEqual(1, config["required_failures"])

    def test_the_deadline_is_capped_by_the_runtime(self):
        with self.assertRaises(JobRuntimeError):
            validate_workload_config(screen_config(deadline_seconds=3001))


class ReduceConfigTests(unittest.TestCase):
    def test_defaults_and_round_trip(self):
        config = validate_workload_config(reduce_config())
        self.assertEqual((5, 4, 24, 3), (config["attempts"], config["required_failures"],
                                         config["max_candidates"], config["concurrency"]))
        self.assertEqual(pp.word_edits(ORIGINAL, PARAPHRASES[0]), config["edits"])
        self.assertEqual(json.loads(json.dumps(config)), config)

    def test_bad_fields_are_rejected(self):
        edits = pp.word_edits(ORIGINAL, PARAPHRASES[0])
        wrong = copy.deepcopy(edits)
        wrong[0]["replacement"] = ["totally", "different"]
        wrong[0]["spaced"] = [False, True]
        bad = (
            {"paraphrase": ORIGINAL}, {"paraphrase": ORIGINAL.upper()}, {"paraphrase": "café"},
            {"edits": []}, {"edits": "x"}, {"edits": wrong}, {"edits": edits[:-1]},
            {"edits": [dict(edits[0], extra=1)] + edits[1:]},
            {"original": ""}, {"task_id": 10}, {"init_state_index": 50}, {"suite": "libero_90"},
            {"attempts": 0}, {"attempts": 9}, {"required_failures": 6}, {"required_failures": 0},
            {"max_candidates": 0}, {"max_candidates": 61}, {"concurrency": 0}, {"concurrency": 4},
            {"surprise": 1},
        )
        for changes in bad:
            with self.subTest(changes=str(changes)[:80]), self.assertRaises(JobRuntimeError):
                validate_workload_config(reduce_config(**changes))

    def test_edits_that_belong_to_another_paraphrase_are_rejected(self):
        config = reduce_config()
        config["paraphrase"] = PARAPHRASES[1]
        with self.assertRaises(JobRuntimeError):
            validate_workload_config(config)

    def test_required_fields(self):
        for key in ("original", "paraphrase", "edits", "task_id", "init_state_index"):
            config = reduce_config()
            del config[key]
            with self.subTest(missing=key), self.assertRaises(JobRuntimeError):
                validate_workload_config(config)

    def test_a_screen_field_is_not_a_reduce_field(self):
        with self.assertRaises(JobRuntimeError):
            validate_workload_config(reduce_config(paraphrases=PARAPHRASES))
        with self.assertRaises(JobRuntimeError):
            validate_workload_config(screen_config(edits=[]))


class DeadlineTests(unittest.TestCase):
    def test_deadlines_respect_the_floor_and_the_cap(self):
        for mode, config in (("paraphrase-screen", screen_config()), ("paraphrase-reduce", reduce_config())):
            deadline = le.recommended_deadline_seconds(mode, config)
            self.assertGreaterEqual(deadline, se.MIN_DEADLINE_SECONDS)
            self.assertLessEqual(deadline, se.MAX_DEADLINE_SECONDS)
            validate_workload_config(dict(config, deadline_seconds=deadline))

    def test_more_work_never_shortens_the_deadline(self):
        small = le.recommended_deadline_seconds("paraphrase-reduce", {"max_candidates": 6})
        large = le.recommended_deadline_seconds("paraphrase-reduce", {"max_candidates": 24})
        self.assertGreaterEqual(large, small)
        few = le.recommended_deadline_seconds("paraphrase-screen", {"paraphrases": ["a"] * 2})
        many = le.recommended_deadline_seconds("paraphrase-screen", {"paraphrases": ["a"] * 12})
        self.assertGreaterEqual(many, few)

    def test_a_workload_over_the_cap_is_refused(self):
        with self.assertRaises(ValueError):
            le.recommended_deadline_seconds("paraphrase-reduce", {"max_candidates": 60, "concurrency": 1})
        with self.assertRaises(ValueError):
            le.recommended_deadline_seconds("scenario-screen", {})

    def test_planned_episodes(self):
        self.assertEqual(2 + 4 * 5, le.planned_episodes("paraphrase-screen", {"paraphrases": [1, 2, 3, 4]}))
        self.assertEqual(10 + 24 * 5, le.planned_episodes("paraphrase-reduce", {}))


class WorkloadBuilderTests(unittest.TestCase):
    def test_the_builders_make_valid_workloads_with_recommended_deadlines(self):
        screen = le.build_screen_workload(run_id="r1", suite="libero_object", task_id=0, start=3,
                                          original=ORIGINAL, paraphrases=PARAPHRASES)
        validate_workload_config(screen)
        self.assertEqual(le.recommended_deadline_seconds("paraphrase-screen", screen), screen["deadline_seconds"])
        reduce_ = le.build_reduce_workload(run_id="r2", suite="libero_object", task_id=0, start=3,
                                           original=ORIGINAL, paraphrase=PARAPHRASES[0], max_candidates=12)
        validate_workload_config(reduce_)
        self.assertEqual(pp.word_edits(ORIGINAL, PARAPHRASES[0]), reduce_["edits"])
        self.assertEqual(12, reduce_["max_candidates"])
        for workload in (screen, reduce_):
            self.assertLess(len(json.dumps(workload)), 64 * 1024)
            self.assertNotIn("key", " ".join(sorted(workload)))


class InstructionConfigTests(unittest.TestCase):
    """The shared config writer, then the two benchmark options appended to its params block."""

    def write(self, root, instruction="pick up the bowl"):
        from scripts import run_failure_search

        path = Path(root) / "case.yaml"
        channel = le.InstructionChannel(run_failure_search._write_config)
        output = Path(root) / "runs" / "case"
        channel.write_config(config_path=path, output_dir=output, project_root=Path(root), stage_name="lang-x",
                             episode_indices=(0,), task_id=2, suite="libero_object", init_state_index=5,
                             instruction=instruction)
        return channel, path, output

    def test_the_options_land_in_the_benchmark_params(self):
        with tempfile.TemporaryDirectory() as root:
            channel, path, output = self.write(root, 'say "hi" \\ there')
            params = yaml.safe_load(path.read_text(encoding="utf-8"))["benchmarks"][0]["params"]
            self.assertEqual('say "hi" \\ there', params["instruction"])
            self.assertEqual(str(output / le.INSTRUCTION_FILE), params["instruction_out"])
            self.assertEqual((2, 5, "libero_object"), (params["task_id"], params["init_state_index"], params["suite"]))
            self.assertEqual({"case": 'say "hi" \\ there'}, channel.requested)

    def test_a_config_of_another_shape_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "x.yaml"
            path.write_text("config", encoding="utf-8")
            with self.assertRaises(ValueError):
                le.with_instruction(path, "x", Path(root) / "i.json")
            _channel, good, _output = self.write(root)
            with self.assertRaises(ValueError):                   # twice
                le.with_instruction(good, "x", Path(root) / "i.json")

    def test_the_sidecar_may_be_a_record_or_a_list_of_one(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "i.json"
            for payload in ({"instruction_used": "a b"}, [{"instruction_used": "a b"}]):
                path.write_text(json.dumps(payload), encoding="utf-8")
                self.assertEqual("a b", le.read_instruction_sidecar(path))
            for payload in ([], [{"instruction_used": "a"}, {"instruction_used": "b"}], {"other": 1},
                            {"instruction_used": 3}, "x"):
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(ValueError):
                    le.read_instruction_sidecar(path)


# --- the fake world --------------------------------------------------------------------------------


class LanguageWorld(World):
    """The M3 process world with evidence from a ``FakeSimulation``, driven by the *written YAML*.

    ``rule(text, count)`` returns ``"policy_failure"``, ``"success"`` or ``None`` (the simulation's own
    start-based outcome) for the ``count``-th episode with that instruction text.
    """

    def __init__(self, rule, *, sidecar_text=None, **kwargs):
        super().__init__(**kwargs)
        self.counts = {}
        self.count_lock = threading.Lock()

        def flaky(_state, params, _count):
            text = params["instruction"]
            with self.count_lock:
                self.counts[text] = number = self.counts.get(text, 0) + 1
            return rule(text, number)

        self.simulation = FakeSimulation(suite="libero_object", flaky=flaky)
        self.sidecar_text = sidecar_text or (lambda case, text: text)
        self.params = {}
        self.results = {}

    def write_config(self, **kwargs):
        from scripts import run_failure_search

        run_failure_search._write_config(**kwargs)
        self.configs.append(kwargs)

    def run_item(self, command, *, item_timeout, cancel):
        super().run_item(command, item_timeout=item_timeout, cancel=cancel)
        path = Path(command[-1])
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        params = config["benchmarks"][0]["params"]
        self.params[path.stem] = params
        self.results[path.stem] = self.simulation.run(params, Path(config["output_dir"]))
        Path(params["instruction_out"]).write_text(json.dumps(
            {"instruction_used": self.sidecar_text(path.stem, params["instruction"])}), encoding="utf-8")

    def load_result(self, output):
        return self.results[Path(output).name]


def grab_fails(text, count):
    return "policy_failure" if "grab" in text.lower() else "success"


def flaky_once(text, count):
    if "grab" in text.lower():
        return "policy_failure"
    if text == PARAPHRASES[1]:
        return "policy_failure" if count == 1 else "success"
    return "success"


class RunCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.remaining_value = [10000.0]
        self.events = []

    def run_mode(self, world, config, **overrides):
        kwargs = dict(
            mode=config["mode"], config=validate_workload_config(config), batch_root=self.root / "language",
            log_root=self.root / "logs", project_root=self.root, model_factory=world.model_factory,
            set_model=world.set_model, run_item=world.run_item, failure=lambda: world.latched,
            remaining=lambda: self.remaining_value[0], launch_deadline=50000.0,
            progress=lambda event, **fields: self.events.append((event, fields)),
            server_clock=lambda: 0.5, write_config=world.write_config, load_result=world.load_result,
            snapshot=lambda: {"mem_available_mb": 1.0, "gpu_used_mb": 2.0, "gpu_total_mb": 3.0},
        )
        kwargs.update(overrides)
        return le.run_language(**kwargs)

    def saved(self):
        return json.loads((self.root / "language" / le.SUMMARY_NAME).read_text(encoding="utf-8"))


class ScreenRunTests(RunCase):
    def row(self, summary, label):
        return next(item for item in summary["instructions"] if item["label"] == label)

    def test_the_screen_runs_the_control_and_each_paraphrase_and_confirms_failures(self):
        world = LanguageWorld(flaky_once, item_seconds=0.0)
        summary = self.run_mode(world, screen_config())
        self.assertIsNone(summary["stop_reason"])
        self.assertTrue(summary["complete"], summary)
        self.assertEqual("paraphrase-screen", summary["mode"])
        self.assertEqual(["success", "success"], summary["control"]["outcomes"])
        self.assertTrue(summary["control"]["passed"])
        grab = self.row(summary, "p01")
        self.assertEqual(("reproduces", 5), (grab["decision"], grab["failures"]))
        self.assertEqual(["policy_failure"] * 5, grab["outcomes"])
        self.assertEqual(1, grab["skipped_attempts"])              # the fifth confirmation attempt, topped up
        once = self.row(summary, "p02")
        self.assertEqual(("does_not_reproduce", 1), (once["decision"], once["failures"]))
        for label in ("p03", "p04"):
            self.assertEqual((["success"], None), (self.row(summary, label)["outcomes"],
                                                   self.row(summary, label)["decision"]))
        self.assertEqual(["p01"], summary["reproducing"])
        self.assertEqual("p01", summary["reproducing_paraphrases"][0]["label"])
        self.assertEqual(len(pp.word_edits(ORIGINAL, PARAPHRASES[0])), summary["reproducing_paraphrases"][0]["edit_count"])
        self.assertEqual(self.saved(), json.loads(json.dumps(summary, sort_keys=True)))

    def test_every_instruction_text_and_the_sidecar_text_are_recorded(self):
        world = LanguageWorld(flaky_once, item_seconds=0.0)
        summary = self.run_mode(world, screen_config())
        self.assertEqual([ORIGINAL] + PARAPHRASES, [row["text"] for row in summary["instructions"]])
        self.assertEqual(["original"] + ["paraphrase"] * 4, [row["kind"] for row in summary["instructions"]])
        for row in summary["instructions"]:
            self.assertTrue(row["attempts"])
            for attempt in row["attempts"]:
                self.assertEqual(row["text"], attempt["instruction_used"])
                self.assertIsNotNone(attempt["seconds"])
                self.assertTrue(attempt["video"])
        self.assertEqual([], summary["instruction_mismatches"])
        self.assertEqual({"id": "nvidia/gr00t17-lerobot-libero_object-640", "revision": None, "pinned": None},
                         summary["checkpoint"])
        self.assertIsNotNone(summary["total_seconds"])
        self.assertEqual("paraphrase-screen", summary["config"]["mode"])
        self.assertNotIn("paraphrases", summary["config"])

    def test_the_evaluator_configs_carry_the_instruction_and_the_start(self):
        world = LanguageWorld(flaky_once, item_seconds=0.0)
        self.run_mode(world, screen_config(task_id=3, init_state_index=7))
        self.assertIn("orig-a01", world.params)
        first = world.params["orig-a01"]
        self.assertEqual((ORIGINAL, 3, 7, "libero_object"),
                         (first["instruction"], first["task_id"], first["init_state_index"], first["suite"]))
        self.assertTrue(first["instruction_out"].endswith("instruction.json"))
        self.assertEqual(PARAPHRASES[0], world.params["p01-a01"]["instruction"])
        self.assertTrue(any(case.startswith("warmup-orig") for case in world.ran))

    def test_a_failing_control_is_reported_not_hidden(self):
        world = LanguageWorld(lambda text, count: "policy_failure", item_seconds=0.0)
        summary = self.run_mode(world, screen_config(paraphrases=PARAPHRASES[:1]))
        self.assertFalse(summary["control"]["passed"])
        self.assertEqual(["policy_failure", "policy_failure"], summary["control"]["outcomes"])

    def test_a_screen_without_confirmation(self):
        world = LanguageWorld(flaky_once, item_seconds=0.0)
        summary = self.run_mode(world, screen_config(confirm_attempts=0, required_failures=1))
        self.assertIsNone(summary["confirm"])
        self.assertEqual([], summary["reproducing"])
        self.assertEqual(["policy_failure"], self.row(summary, "p01")["outcomes"])

    def test_nothing_reproduces_when_every_paraphrase_passes(self):
        summary = self.run_mode(LanguageWorld(lambda t, c: "success", item_seconds=0.0), screen_config())
        self.assertEqual([], summary["reproducing"])
        self.assertEqual([], summary["reproducing_paraphrases"])
        self.assertTrue(summary["complete"])

    def test_a_policy_that_ignores_the_instruction_is_caught(self):
        world = LanguageWorld(flaky_once, item_seconds=0.0,
                              sidecar_text=lambda case, text: ORIGINAL if case.startswith("p02") else text)
        summary = self.run_mode(world, screen_config())
        self.assertEqual("instruction_mismatch", summary["stop_reason"])
        self.assertFalse(summary["complete"])
        self.assertTrue(summary["instruction_mismatches"])
        self.assertTrue(all(name.startswith("p02") for name in summary["instruction_mismatches"]))

    def test_an_infrastructure_failure_stops_the_screen(self):
        world = LanguageWorld(flaky_once, item_seconds=0.0, fail_case="p03-a01")
        summary = self.run_mode(world, screen_config())
        self.assertEqual("evaluator_failed", summary["stop_reason"])
        self.assertFalse(summary["complete"])
        self.assertEqual([], summary["reproducing"])

    def test_a_deadline_stop_is_not_complete(self):
        self.remaining_value[0] = 100.0
        summary = self.run_mode(LanguageWorld(flaky_once, item_seconds=0.0), screen_config())
        self.assertFalse(summary["complete"])
        self.assertIsNotNone(summary["stop_reason"])


class ReduceRunTests(RunCase):
    def test_the_minimal_wording_is_the_one_edit_that_matters(self):
        world = LanguageWorld(grab_fails, item_seconds=0.0)
        summary = self.run_mode(world, reduce_config())
        self.assertIsNone(summary["stop_reason"])
        self.assertTrue(summary["complete"], summary["reduction"]["stop_reason"])
        reduction = summary["reduction"]
        self.assertEqual("reduced", reduction["stop_reason"])
        self.assertEqual({"paraphrase": "reproduces", "original": "passes"}, reduction["gates"])
        edits = pp.word_edits(ORIGINAL, PARAPHRASES[0])
        grab = [edit["id"] for edit in edits if edit["replacement"] == ["grab"]]
        self.assertEqual(1, len(grab))
        self.assertEqual(grab, reduction["final_edits"])
        minimal = summary["minimal"]
        self.assertEqual("grab the alphabet soup and place it in the basket", minimal["text"])
        self.assertEqual(['"pick up" -> "grab"'], minimal["labels"])
        self.assertTrue(minimal["verified"] and minimal["edit_minimal"])
        self.assertIsNotNone(reduction["final_candidate"])
        self.assertEqual(self.saved(), json.loads(json.dumps(summary, sort_keys=True)))

    def test_every_candidate_is_listed_with_its_text_outcomes_and_decision(self):
        summary = self.run_mode(LanguageWorld(grab_fails, item_seconds=0.0), reduce_config())
        candidates = summary["reduction"]["candidates"]
        roles = [c["role"] for c in candidates]
        self.assertEqual(["failing", "reference"], roles[:2])
        self.assertEqual(PARAPHRASES[0], candidates[0]["text"])
        self.assertEqual(ORIGINAL, candidates[1]["text"])
        self.assertEqual(("reproduces", "passes"), (candidates[0]["decision"], candidates[1]["decision"]))
        for candidate in candidates[2:]:
            self.assertEqual("hybrid", candidate["role"])
            self.assertTrue(candidate["text"])
            self.assertIn(candidate["decision"], ("reproduces", "does_not_reproduce"))
            self.assertEqual(candidate["decision"] == "reproduces", "grab" in candidate["text"])
        self.assertEqual(len({c["text"] for c in candidates}), len(candidates), "candidates are cached by text")
        self.assertEqual(summary["reduction"]["candidates_tested"], len(candidates) - 2)

    def test_the_evaluator_receives_each_candidate_text(self):
        world = LanguageWorld(grab_fails, item_seconds=0.0)
        summary = self.run_mode(world, reduce_config())
        sent = {params["instruction"] for params in world.params.values()}
        self.assertEqual({c["text"] for c in summary["reduction"]["candidates"]}, sent)

    def test_videos_of_the_three_roles_are_recorded(self):
        summary = self.run_mode(LanguageWorld(grab_fails, item_seconds=0.0), reduce_config())
        videos = summary["videos"]
        self.assertEqual({"original", "reference", "minimal"}, set(videos))
        self.assertEqual(PARAPHRASES[0], videos["original"]["text"])
        self.assertEqual(ORIGINAL, videos["reference"]["text"])
        self.assertEqual(summary["minimal"]["text"], videos["minimal"]["text"])
        self.assertEqual(("policy_failure", "success", "policy_failure"),
                         (videos["original"]["outcome"], videos["reference"]["outcome"], videos["minimal"]["outcome"]))
        for entry in videos.values():
            self.assertTrue(entry["video"].endswith(".mp4"))

    def test_two_edits_that_are_needed_together_are_both_kept(self):
        def both(text, count):
            lowered = text.lower()
            return "policy_failure" if "grab" in lowered and " put " in " " + lowered + " " else "success"

        summary = self.run_mode(LanguageWorld(both, item_seconds=0.0), reduce_config())
        self.assertEqual("reduced", summary["reduction"]["stop_reason"])
        self.assertEqual(['"pick up" -> "grab"', '"and place" -> ", then put"'], summary["minimal"]["labels"])
        self.assertEqual("grab the alphabet soup, then put it in the basket", summary["minimal"]["text"])

    def test_a_single_edit_needs_no_search(self):
        paraphrase = "grab the alphabet soup and place it in the basket"
        summary = self.run_mode(LanguageWorld(grab_fails, item_seconds=0.0), reduce_config(paraphrase))
        self.assertEqual("reduced", summary["reduction"]["stop_reason"])
        self.assertEqual(0, summary["reduction"]["candidates_tested"])
        self.assertEqual(paraphrase, summary["minimal"]["text"])

    def test_a_paraphrase_that_does_not_reproduce_stops_the_reduction(self):
        summary = self.run_mode(LanguageWorld(lambda t, c: "success", item_seconds=0.0), reduce_config())
        self.assertEqual("failing_not_reproducible", summary["stop_reason"])
        self.assertFalse(summary["complete"])
        self.assertIsNone(summary["minimal"])
        self.assertEqual(0, summary["reduction"]["candidates_tested"])

    def test_an_original_that_does_not_pass_stops_the_reduction(self):
        summary = self.run_mode(LanguageWorld(lambda t, c: "policy_failure", item_seconds=0.0), reduce_config())
        self.assertEqual("reference_not_passing", summary["stop_reason"])
        self.assertIsNone(summary["minimal"])

    def test_the_candidate_budget_stops_with_the_best_verified_wording(self):
        def three(text, count):
            lowered = text.lower()
            return "policy_failure" if "grab" in lowered and "put" in lowered and "." in text else "success"

        summary = self.run_mode(LanguageWorld(three, item_seconds=0.0),
                                reduce_config(max_candidates=1))
        self.assertEqual("budget_exhausted", summary["stop_reason"])
        self.assertFalse(summary["complete"])
        self.assertFalse(summary["reduction"]["reduced"])
        minimal = summary["minimal"]
        self.assertTrue(minimal["verified"])
        self.assertFalse(minimal["edit_minimal"])
        self.assertEqual(PARAPHRASES[0], minimal["text"])            # nothing smaller was verified
        self.assertEqual(1, summary["reduction"]["candidates_tested"])

    def test_a_deadline_stop_keeps_what_was_verified(self):
        world = LanguageWorld(grab_fails, item_seconds=0.0)
        self.remaining_value[0] = 100.0
        summary = self.run_mode(world, reduce_config())
        self.assertFalse(summary["complete"])
        self.assertIsNotNone(summary["stop_reason"])

    def test_an_instruction_the_policy_did_not_receive_is_caught(self):
        world = LanguageWorld(grab_fails, item_seconds=0.0, sidecar_text=lambda case, text: ORIGINAL)
        summary = self.run_mode(world, reduce_config())
        self.assertIn(summary["stop_reason"], ("instruction_mismatch", "warmup_failed"))
        self.assertTrue(summary["instruction_mismatches"])
        self.assertFalse(summary["complete"])


# --- the pure reducer ----------------------------------------------------------------------------------


def fake_prepare(ids_all):
    def prepare(spec):
        role = spec["role"]
        ids = sorted(spec.get("selection") or []) if role == "hybrid" else (list(ids_all) if role == "failing" else [])
        key = json.dumps(ids)
        return key, {"case_id": "{}-{}".format(role[:3], "-".join(map(str, ids)) or "none"), "kind": role, "ids": ids,
                     "role": role}

    return prepare


class PureReductionTests(unittest.TestCase):
    def run_reduction(self, culprits, ids=(0, 1, 2, 3, 4, 5), **kwargs):
        need = set(culprits)

        def outcome(item):
            if item["role"] == "reference":
                return "success"
            return "policy_failure" if need <= set(item["ids"]) else "success"

        executor = FakeExecutor(outcome)
        result = le.run_paraphrase_reduction(executor, fake_prepare(ids), list(ids), max_in_flight=12, **kwargs)
        return result, executor

    def test_the_result_is_one_minimal(self):
        for culprits in ([2], [0, 5], [1, 3, 4], [0, 1, 2, 3, 4, 5]):
            with self.subTest(culprits=culprits):
                result, _ = self.run_reduction(culprits, max_candidates=60)
                self.assertEqual("reduced", result["stop_reason"])
                self.assertEqual(sorted(culprits), result["final_edits"])
                self.assertIsNotNone(result["final_candidate"])

    def test_the_search_is_deterministic(self):
        first, _ = self.run_reduction([1, 4])
        second, _ = self.run_reduction([1, 4])
        self.assertEqual([c["selection"] for c in first["candidates"]], [c["selection"] for c in second["candidates"]])

    def test_the_empty_set_is_never_offered(self):
        result, _ = self.run_reduction([3])
        self.assertTrue(all(c["selection"] for c in result["candidates"] if c["role"] == "hybrid"))

    def test_attempts_are_skipped_once_a_gate_is_decided(self):
        result, _ = self.run_reduction([3])
        self.assertGreater(result["attempts_skipped"], 0)
        self.assertEqual(result["attempts_run"], result["attempts_run_gates"] + result["attempts_run_hybrid"])

    def test_the_candidate_budget_is_enforced(self):
        result, _ = self.run_reduction([0, 1, 2, 3, 4, 5], max_candidates=2)
        self.assertEqual("budget_exhausted", result["stop_reason"])
        self.assertLessEqual(result["candidates_tested"], 2)
        self.assertEqual([0, 1, 2, 3, 4, 5], result["final_edits"])     # nothing smaller was verified
        self.assertFalse(result["reduced"])

    def test_bad_input_is_refused(self):
        for ids in ([], [1, 1]):
            with self.assertRaises(ValueError):
                le.run_paraphrase_reduction(FakeExecutor(lambda i: "success"), fake_prepare(ids), ids)


# --- through run_workload, with the real written YAML ------------------------------------------------------


class WorkloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        from robot_debug.job_workload import WorkloadPaths

        self.paths = WorkloadPaths(*(root / n for n in ("project", "upstream", "work", "export")))
        for path in (self.paths.project_root, self.paths.upstream_root, self.paths.work_root,
                     self.paths.export_root):
            path.mkdir()
        self.exports = []

    def invoke(self, config):
        import time

        from robot_debug.job_workload import run_workload
        from tests.test_serverless_workload import FakeCompleted

        world = LanguageWorld(flaky_once, item_seconds=0.0)

        class Runner:
            def __call__(self_inner, command, *, cwd, check=False):
                parsed = yaml.safe_load(Path(command[-1]).read_text(encoding="utf-8"))
                params = parsed["benchmarks"][0]["params"]
                world.simulation.run(params, Path(parsed["output_dir"]))
                Path(params["instruction_out"]).write_text(
                    json.dumps({"instruction_used": params["instruction"]}), encoding="utf-8")
                return FakeCompleted(0)

        def exporter(source, destination, **kwargs):
            self.exports.append((Path(source), Path(destination), kwargs))
            return {"ok": True}

        return run_workload(
            config, paths=self.paths, model_factory=world.model_factory,
            evaluator_factory=lambda **kwargs: Runner(), exporter=exporter, clock=time.monotonic,
            progress=lambda *_a, **_k: None), world

    def detail(self, config):
        path = self.paths.work_root / config["run_id"] / "language" / le.SUMMARY_NAME
        return json.loads(path.read_text(encoding="utf-8"))

    def test_the_screen_job_completes_and_writes_the_language_summary(self):
        config = screen_config()
        summary, _world = self.invoke(config)
        self.assertEqual(("complete", "completed"), (summary["status"], summary["stop_reason"]), summary)
        self.assertEqual("paraphrase-screen", summary["mode"])
        self.assertTrue(summary["language_complete"])
        self.assertEqual(["p01"], summary["language_reproducing"])
        self.assertEqual("complete", self.exports[0][2]["status"])
        detail = self.detail(config)
        self.assertEqual(["p01"], detail["reproducing"])

    def test_the_reduce_job_completes_and_names_the_final_edits(self):
        config = reduce_config()
        summary, _world = self.invoke(dict(config, run_id="lang-reduce-2"))
        self.assertEqual(("complete", "completed"), (summary["status"], summary["stop_reason"]), summary)
        self.assertEqual("reduced", summary["language_reduction_stop_reason"])
        self.assertEqual(1, len(summary["language_final_edits"]))

    def test_a_stopped_reduction_makes_the_job_partial(self):
        config = reduce_config(paraphrase=PARAPHRASES[2], run_id="lang-reduce-3")
        config["edits"] = pp.word_edits(ORIGINAL, PARAPHRASES[2])
        summary, _world = self.invoke(config)             # "put the alphabet soup in the basket" never fails
        self.assertEqual("partial", summary["status"])
        self.assertEqual("failing_not_reproducible", summary["stop_reason"])
        self.assertFalse(summary["language_complete"])


# --- cases ----------------------------------------------------------------------------------------------------


class CaseTests(RunCase):
    def reduced_summary(self):
        return self.run_mode(LanguageWorld(grab_fails, item_seconds=0.0), reduce_config())

    def test_the_case_holds_the_wording_the_replay_recipe_and_the_videos(self):
        summary = self.reduced_summary()
        screen = self.run_mode(LanguageWorld(flaky_once, item_seconds=0.0), screen_config(),
                               batch_root=self.root / "screen-language")
        case = le.build_case(summary, screen)
        self.assertEqual("paraphrase_reduction", case["kind"])
        self.assertRegex(case["case_id"], r"^[0-9a-f]{64}$")
        self.assertEqual((ORIGINAL, PARAPHRASES[0]), (case["instruction"], case["paraphrase"]))
        self.assertTrue(case["reduced"])
        self.assertEqual("grab the alphabet soup and place it in the basket", case["minimal"]["text"])
        self.assertEqual(1, len(case["minimal"]["edits"]))
        self.assertGreater(case["minimal"]["edits_total"], 1)
        self.assertIn('"pick up" -> "grab"', case["minimal"]["sentence"])
        self.assertIn(ORIGINAL, case["minimal"]["sentence"])
        self.assertEqual({"suite": "libero_object", "task_id": 0, "init_state_index": 0,
                          "instruction": case["minimal"]["text"]}, case["replay"]["config"])
        self.assertEqual(ORIGINAL, case["replay"]["reference_instruction"])
        self.assertEqual({"attempts": 5, "required_failures": 4}, case["replay"]["gate"])
        self.assertEqual({"original", "reference", "minimal"}, set(case["videos"]))
        self.assertEqual(5, len(case["screen"]))
        self.assertIsNone(case["explanation"])
        self.assertEqual(case, json.loads(json.dumps(case)))

    def test_the_case_id_is_stable_and_depends_on_the_wording(self):
        summary = self.reduced_summary()
        first = le.build_case(summary)
        self.assertEqual(first["case_id"], le.build_case(copy.deepcopy(summary))["case_id"])
        other = copy.deepcopy(summary)
        other["minimal"]["text"] = "something else"
        self.assertNotEqual(first["case_id"], le.build_case(other)["case_id"])

    def test_no_case_without_a_verified_wording(self):
        summary = self.reduced_summary()
        for broken in (dict(summary, mode="paraphrase-screen"), dict(summary, minimal=None),
                       dict(summary, minimal=dict(summary["minimal"], verified=False)), None, {}):
            with self.assertRaises(ValueError):
                le.build_case(broken)

    def test_the_sentence_says_when_the_reduction_stopped_early(self):
        text = le.describe_minimal_wording("a b", "a c", ['"b" -> "c"'], reduced=False)
        self.assertIn("stopped early", text)
        self.assertIn("No smaller", le.describe_minimal_wording("a b", "a c", [], reduced=True))


class PythonCompatibilityTests(unittest.TestCase):
    def test_job_side_modules_parse_as_python_38(self):
        for name in ("language_experiment", "paraphrase", "job_runtime", "job_workload"):
            path = ROOT / "src" / "robot_debug" / (name + ".py")
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 8))


class DeadlineGuardTests(unittest.TestCase):
    def test_the_prepare_script_guards_the_new_modes(self):
        import importlib.util
        import os
        import sys

        spec = importlib.util.spec_from_file_location(
            "prepare_serverless_job_language", ROOT / "scripts" / "prepare_serverless_job.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        for mode in le.LANGUAGE_MODES:
            self.assertIn(mode, module._BATCH_MODES)
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            os.chdir(temporary)
            try:
                for config, deadline, ok in ((screen_config(), 999, False), (screen_config(), 1000, True),
                                             (reduce_config(), 999, False), (reduce_config(), 1000, True)):
                    Path("workload.json").write_text(json.dumps(dict(config, deadline_seconds=deadline)),
                                                     encoding="utf-8")
                    job = {
                        "run_id": "lang-1", "project_id": "project-example123",
                        "image": "registry.example/robot-debug@sha256:" + "a" * 64,
                        "platform": "gpu-l40s-a", "preset": "1gpu-16vcpu-64gb",
                        "subnet_id": "vpcsubnet-example123", "bucket_id": "storagebucket-example123",
                        "hf_secret": "mbsec-example123@mbsecver-version123", "workload_file": "workload.json"}
                    if ok:
                        self.assertIn("--dry-run", module.prepare(job))
                    else:
                        with self.assertRaisesRegex(module.ConfigError, "deadline"):
                            module.prepare(job)
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
