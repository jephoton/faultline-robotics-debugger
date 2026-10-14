"""Reference choice, hypothesis prompt/parse/verdict and the Token Factory call (no network)."""

from __future__ import annotations

import json
import math
import unittest

from robot_debug import scenario_hypothesis as sh
from robot_debug import scenario_state as ss
from robot_debug import token_factory as tf
from tests import reduction_fixtures as rf
from tests.scenario_fakes import base_state, synthetic_layout, with_object_pose

KEY = "TEST-SECRET-DO-NOT-LOG"
ULTRA = "nvidia/test-Nemotron-3-Ultra-fake"
SUPER = "nvidia/test-Nemotron-3-Super-fake"
NANO = tf.MODEL
INSTRUCTION = "put the black bowl in the bottom drawer of the cabinet and close it"


def make_world():
    layout = synthetic_layout()
    reference = base_state(layout)
    failing = with_object_pose(reference, 3, dxyz=(0.04, 0.0, 0.0), z_degrees=50.0)
    failing = with_object_pose(failing, 11, dxyz=(0.0, 0.01, 0.0))
    failing[1 + 10] += math.radians(15.0)
    return layout, reference, failing


class NearestReferenceTests(unittest.TestCase):
    def setUp(self):
        self.layout = synthetic_layout()
        failing = base_state(self.layout)
        self.states = {0: failing}
        # start i is moved i cm (soup) from the failing start
        for index in (1, 2, 3, 4, 5):
            self.states[index] = with_object_pose(failing, 3, dxyz=(0.01 * index, 0, 0))
        self.results = {0: [{"x": 1}], 1: ["success"] * 5}
        self.results = {
            0: ["policy_failure"] * 5, 1: ["success"], 2: ["success"], 3: ["policy_failure"],
            4: ["success"], 5: ["success", "policy_failure"],
        }

    def call(self, **kwargs):
        args = dict(task_id=3, failing_index=0, screen_results={3: self.results},
                    states={3: self.states}, layout=self.layout)
        args.update(kwargs)
        return sh.nearest_reference(**args)

    def test_nearest_passing_starts_first_with_fallbacks(self):
        ranked = self.call()
        self.assertEqual([r["start_index"] for r in ranked], [1, 2, 4])
        self.assertAlmostEqual(ranked[0]["distance"], 1.0)
        self.assertAlmostEqual(ranked[2]["distance"], 4.0)
        self.assertEqual(ranked[0]["outcomes"], ["success"])

    def test_failing_flaky_and_stateless_starts_are_excluded(self):
        del self.states[2]
        self.assertEqual([r["start_index"] for r in self.call()], [1, 4])      # 3 failed, 5 flaky
        self.assertEqual([r["start_index"] for r in self.call(count=1)], [1])

    def test_json_style_string_keys_and_outcome_objects(self):
        results = {"3": {str(k): {"outcomes": v} for k, v in self.results.items()}}
        states = {"3": {str(k): v.tolist() for k, v in self.states.items()}}
        ranked = self.call(screen_results=results, states=states)
        self.assertEqual([r["start_index"] for r in ranked], [1, 2, 4])

    def test_ties_break_on_start_index(self):
        self.states[6] = self.states[2].copy()
        self.results[6] = ["success"]
        self.assertEqual([r["start_index"] for r in self.call(count=5)], [1, 2, 6, 4, 5][:4])

    def test_no_passing_start_gives_an_empty_list(self):
        self.assertEqual(self.call(screen_results={3: {0: ["policy_failure"] * 5}}), [])

    def test_bad_inputs_are_rejected(self):
        for kwargs in ({"count": 0}, {"failing_index": 99}, {"task_id": 9}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.call(**kwargs)


class PromptTests(unittest.TestCase):
    def test_prompt_carries_the_instruction_and_difference_sizes_only(self):
        layout, reference, failing = make_world()
        table = ss.differences(failing, reference, layout)
        prompt = sh.build_hypothesis_prompt(INSTRUCTION, table)
        body = json.loads(prompt["user"])
        self.assertEqual(set(body), {"task_instruction", "differences"})
        self.assertEqual(body["task_instruction"], INSTRUCTION)
        by_name = {entry["entity"]: entry for entry in body["differences"]}
        self.assertEqual(list(by_name), ["soup_1", "microwave_1", "bowl_1"])
        self.assertEqual(by_name["soup_1"]["position_cm"], 4.0)
        self.assertEqual(by_name["soup_1"]["rotation_deg"], 50.0)
        self.assertEqual(by_name["microwave_1"]["joints"][0]["unit"], "deg")
        self.assertNotIn("rotation_deg", by_name["bowl_1"])
        text = prompt["system"] + prompt["user"]
        for forbidden in ("image", "video", "\\", "state", "hash", "sha256", "http"):
            self.assertNotIn(forbidden, prompt["user"].lower().replace("task_instruction", ""), forbidden)
        self.assertNotIn(":\\", text)

    def test_instruction_is_cleaned_and_bounded(self):
        row = ss.differences(*reversed(make_world()[1:]), make_world()[0])[0]
        prompt = sh.build_hypothesis_prompt("pick\x00 up\n\tthe   bowl\u202e" + "x" * 1000, [row])
        text = json.loads(prompt["user"])["task_instruction"]
        self.assertTrue(text.startswith("pick up the bowl"))
        self.assertLessEqual(len(text), 400)

    def test_bad_inputs(self):
        row = {"entity": "soup_1", "position": None, "rotation": {"angle_deg": 3.0}, "joints": []}
        for instruction, table in (
            ("", [row]), (3, [row]), (INSTRUCTION, []), (INSTRUCTION, [dict(row, entity="C:\\x")]),
            (INSTRUCTION, [dict(row, entity="a b")]), (INSTRUCTION, [row, row]),
        ):
            with self.subTest(instruction=instruction, table=table), self.assertRaises(ValueError):
                sh.build_hypothesis_prompt(instruction, table)


class ParseReplyTests(unittest.TestCase):
    NAMES = ["soup_1", "bowl_1", "robot"]

    def reply(self, ranking=("bowl_1", "soup_1", "robot"), hypothesis="The bowl blocks the grasp."):
        return json.dumps({"ranking": list(ranking), "hypothesis": hypothesis})

    def test_valid_reply(self):
        parsed = sh.parse_hypothesis_reply(self.reply(), self.NAMES)
        self.assertEqual(parsed["ranking"], ["bowl_1", "soup_1", "robot"])
        self.assertEqual(parsed["completed"], [])
        self.assertEqual(parsed["hypothesis"], "The bowl blocks the grasp.")

    def test_missing_entities_are_appended_in_the_given_order(self):
        parsed = sh.parse_hypothesis_reply(self.reply(ranking=["robot"]), self.NAMES)
        self.assertEqual(parsed["ranking"], ["robot", "soup_1", "bowl_1"])
        self.assertEqual(parsed["completed"], ["soup_1", "bowl_1"])

    def test_every_kind_of_bad_reply_has_a_reason_code(self):
        cases = {
            "invalid_json": ["not json", "```json\n" + self.reply() + "\n```", "", None, "[1]x",
                             '{"ranking": ["robot"], "ranking": ["robot"], "hypothesis": "x"}',
                             '{"ranking": [NaN], "hypothesis": "x"}'],
            "invalid_shape": [json.dumps([1]), json.dumps({"ranking": ["robot"]}),
                              json.dumps({"ranking": "robot", "hypothesis": "x"}),
                              json.dumps({"ranking": [], "hypothesis": "x"}),
                              json.dumps({"ranking": [1], "hypothesis": "x"}),
                              json.dumps({"ranking": ["robot"], "hypothesis": "x", "extra": 1})],
            "unknown_entity": [self.reply(ranking=["robot", "toaster"])],
            "duplicate_entity": [self.reply(ranking=["robot", "robot"])],
            "invalid_hypothesis": [self.reply(hypothesis=""), self.reply(hypothesis="   "),
                                   self.reply(hypothesis="x" * 1300), self.reply(hypothesis="a\x00b"),
                                   json.dumps({"ranking": ["robot"], "hypothesis": 5})],
        }
        for code, replies in cases.items():
            for content in replies:
                with self.subTest(code=code, content=str(content)[:40]):
                    with self.assertRaises(sh.HypothesisError) as caught:
                        sh.parse_hypothesis_reply(content, self.NAMES)
                    self.assertEqual(str(caught.exception), code)


class VerdictTests(unittest.TestCase):
    def test_confirmed_partly_refuted(self):
        ranking = ["soup_1", "bowl_1", "robot"]
        self.assertEqual(sh.hypothesis_verdict(ranking, {"soup_1": {"rotation": 0.4}}), "confirmed")
        self.assertEqual(sh.hypothesis_verdict(
            ranking, {"soup_1": {"rotation": 0.4, "position": 1.0}}), "confirmed")
        self.assertEqual(sh.hypothesis_verdict(
            ranking, {"soup_1": {"rotation": 0.4}, "robot": {"joints": 1.0}}), "partly")
        self.assertEqual(sh.hypothesis_verdict(ranking, {"bowl_1": {"position": 0.2}}), "refuted")
        self.assertEqual(sh.hypothesis_verdict(
            ranking, {"bowl_1": {"position": 0.2}, "robot": {"joints": 1.0}}), "refuted")

    def test_empty_inputs_are_errors(self):
        for ranking, selection in (([], {"a": {"x": 1}}), (["a"], {}), (["a"], {"a": {}}), ("ab", {"a": {"x": 1}})):
            with self.subTest(ranking=ranking, selection=selection), self.assertRaises(ValueError):
                sh.hypothesis_verdict(ranking, selection)


class MeasureHypothesisTests(unittest.TestCase):
    RANKING = ["soup", "sauce", "robot", "cream", "milk"]

    def measure(self, reduction=None, ranking=None):
        return sh.measure_hypothesis(ranking or self.RANKING, reduction or rf.partial_reduction())

    def test_a_necessary_but_insufficient_top_suspect_is_labelled_so(self):
        result = self.measure()
        self.assertEqual("soup", result["top"])
        self.assertEqual("necessary_not_sufficient", result["verdict"])
        self.assertIs(result["necessary"], True)
        self.assertIs(result["sufficient"], False)
        self.assertTrue(result["in_final"])
        self.assertEqual(["soup", "cream", "milk", "robot"], result["survivors"])
        self.assertEqual(3, result["top_k"])
        self.assertEqual(2, result["ranked_survivors_overlap"], "soup and robot are in the top 3 and survive")
        self.assertEqual([2, 7], result["basis"])

    def test_the_complement_falls_back_to_an_entity_set_match_when_sizes_differ(self):
        soup = self.measure()["entities"][0]
        self.assertEqual("entity_set", soup["necessary_basis"], "candidate 7 has the robot at full size")
        self.assertEqual({"sufficient": [2], "necessary": [7]}, soup["basis"])

    def test_an_exact_size_match_is_preferred_and_labelled_exact(self):
        reduction = rf.partial_reduction()
        reduction["candidates"].append(rf.candidate(
            11, "shrink", {"cream": {"position": 1.0}, "milk": {"position": 1.0}, "robot": {"joints": 0.875}},
            "does_not_reproduce"))
        soup = self.measure(reduction)["entities"][0]
        self.assertEqual("exact", soup["necessary_basis"])
        self.assertEqual([11], soup["basis"]["necessary"])

    def test_an_entity_set_match_must_come_from_the_ddmin_phase(self):
        reduction = rf.partial_reduction()
        reduction["candidates"][7]["phase"] = "shrink"
        soup = self.measure(reduction)["entities"][0]
        self.assertIsNone(soup["necessary"])
        self.assertIsNone(soup["necessary_basis"])
        self.assertEqual("inconclusive", soup["label"])

    def test_a_reproducing_complement_means_not_necessary(self):
        reduction = rf.partial_reduction()
        reduction["candidates"][7]["decision"] = "reproduces"
        soup = self.measure(reduction)["entities"][0]
        self.assertIs(soup["necessary"], False)
        self.assertEqual("inconclusive", soup["label"], "neither necessary nor sufficient")

    def test_an_entity_that_did_not_survive_is_refuted_by_the_final_candidate(self):
        sauce = self.measure(ranking=["sauce", "soup"])
        self.assertEqual("not_in_final", sauce["verdict"])
        self.assertFalse(sauce["in_final"])
        entity = sauce["entities"][0]
        self.assertIs(entity["necessary"], False)
        self.assertEqual("not_in_final", entity["necessary_basis"])
        self.assertIs(entity["sufficient"], False, "the sauce alone passed")
        self.assertEqual([10], entity["basis"]["necessary"])

    def test_sufficient_not_necessary(self):
        reduction = rf.partial_reduction()
        reduction["candidates"][2]["decision"] = "reproduces"
        reduction["candidates"][7]["decision"] = "reproduces"
        result = self.measure(reduction)
        self.assertEqual("sufficient_not_necessary", result["verdict"])
        self.assertIs(result["sufficient"], True)

    def test_a_sole_survivor_that_is_necessary_and_sufficient_is_confirmed(self):
        reduction = rf.partial_reduction()
        final = {"soup": {"position": 0.25}}
        reduction.update(final_selection=final, surviving_entities=["soup"], final_candidate=11)
        reduction["candidates"][2]["decision"] = "reproduces"
        reduction["candidates"].append(rf.candidate(11, "shrink", final, "reproduces"))
        result = self.measure(reduction)
        self.assertEqual("confirmed", result["verdict"])
        self.assertIs(result["necessary"], True)
        self.assertEqual("reference", result["entities"][0]["necessary_basis"])
        self.assertEqual([1], result["entities"][0]["basis"]["necessary"], "the passing reference run")
        self.assertEqual([2, 11], result["entities"][0]["basis"]["sufficient"])

    def test_untested_means_none_not_false(self):
        reduction = rf.partial_reduction()
        reduction["candidates"] = [c for c in reduction["candidates"] if c["index"] not in (2, 7)]
        soup = self.measure(reduction)["entities"][0]
        self.assertIsNone(soup["sufficient"])
        self.assertIsNone(soup["necessary"])
        self.assertEqual("inconclusive", soup["label"])

    def test_invalid_scenes_are_not_evidence(self):
        reduction = rf.partial_reduction()
        reduction["candidates"][2]["decision"] = "invalid_scene"
        self.assertIsNone(self.measure(reduction)["entities"][0]["sufficient"])

    def test_zero_sized_parts_do_not_count_as_applied(self):
        reduction = rf.partial_reduction()
        reduction["candidates"][2]["selection"] = {"soup": {"position": 1.0}, "milk": {"position": 0.0}}
        self.assertIs(self.measure(reduction)["entities"][0]["sufficient"], False)

    def test_the_input_is_not_modified_and_no_new_runs_are_implied(self):
        reduction = rf.partial_reduction()
        before = json.dumps(reduction, sort_keys=True)
        self.measure(reduction)
        self.assertEqual(before, json.dumps(reduction, sort_keys=True))

    def test_bad_inputs_raise_value_error(self):
        for ranking, reduction in (([], rf.partial_reduction()), ("soup", rf.partial_reduction()),
                                   (["soup"], {"final_selection": None, "candidates": []}),
                                   (["soup"], {"final_selection": {"soup": {"position": 0}}, "candidates": []})):
            with self.subTest(ranking=ranking), self.assertRaises(ValueError):
                sh.measure_hypothesis(ranking, reduction)
        with self.assertRaises(ValueError):
            sh.measure_hypothesis(["soup"], rf.partial_reduction(), top=0)

    def test_top_limits_the_table(self):
        self.assertEqual(["soup"], [e["entity"] for e in sh.measure_hypothesis(
            self.RANKING, rf.partial_reduction(), top=1)["entities"]])


# --- Token Factory call --------------------------------------------------------------


class FakeTransport:
    def __init__(self, catalog=(NANO, ULTRA, SUPER), reply=None, catalog_error=None, post_error=None,
                 response=None):
        self.catalog, self.reply = list(catalog), reply
        self.catalog_error, self.post_error, self.response = catalog_error, post_error, response
        self.calls = []

    def __call__(self, method, path, payload, api_key):
        self.calls.append((method, path, payload))
        if method == "GET":
            if self.catalog_error:
                raise self.catalog_error
            return {"data": [{"id": name} for name in self.catalog]}
        if self.post_error:
            raise self.post_error
        if self.response is not None:
            return self.response
        model = payload["model"]
        return {"model": model, "usage": {"prompt_tokens": 200, "completion_tokens": 80, "total_tokens": 280},
                "choices": [{"finish_reason": "stop", "message": {"content": self.reply}}]}


class SelectModelTests(unittest.TestCase):
    def test_ultra_then_super_by_pattern_and_deterministic(self):
        self.assertEqual(tf.select_scenario_model([NANO, SUPER, ULTRA]), (ULTRA, "ultra"))
        self.assertEqual(tf.select_scenario_model([NANO, SUPER]), (SUPER, "super"))
        self.assertEqual(tf.select_scenario_model([NANO]), (None, None))
        self.assertEqual(tf.select_scenario_model([]), (None, None))
        self.assertEqual(tf.select_scenario_model(["b/NEMOTRON-3-ULTRA-b", "a/nemotron-3-ultra-a"]),
                         ("a/nemotron-3-ultra-a", "ultra"))

    def test_pinned_exact_ids_win_over_pattern_matches(self):
        pinned_ultra = tf.SCENARIO_MODEL_IDS[0][1]
        pinned_super = tf.SCENARIO_MODEL_IDS[1][1]
        self.assertEqual(tf.select_scenario_model(["a/nemotron-3-ultra-a", pinned_ultra]),
                         (pinned_ultra, "ultra"))
        self.assertEqual(tf.select_scenario_model([NANO, pinned_super]), (pinned_super, "super"))


class RequestHypothesisTests(unittest.TestCase):
    def setUp(self):
        layout, reference, failing = make_world()
        self.table = ss.differences(failing, reference, layout)       # soup_1, microwave_1, bowl_1
        self.fixed = ss.fixed_order(self.table)

    def good_reply(self, ranking=("soup_1", "bowl_1", "microwave_1")):
        return json.dumps({"ranking": list(ranking),
                           "hypothesis": "The soup rotation is the likely cause; the rerun will check it."})

    def call(self, transport, **kwargs):
        return tf.request_scenario_hypothesis(INSTRUCTION, self.table, KEY, transport, **kwargs)

    def assert_fixed(self, result, reason):
        self.assertEqual(result["source"], "fixed_order")
        self.assertEqual(result["ranking"], self.fixed)
        self.assertIsNone(result["hypothesis"])
        self.assertEqual(result["fallback_reason"], reason)
        self.assertNotIn(KEY, json.dumps(result))

    def test_ultra_is_used_when_the_catalog_has_it(self):
        transport = FakeTransport(reply=self.good_reply())
        result = self.call(transport)
        self.assertEqual(result["source"], "model")
        self.assertEqual((result["model"], result["tier"]), (ULTRA, "ultra"))
        self.assertEqual(result["ranking"], ["soup_1", "bowl_1", "microwave_1"])
        self.assertIn("soup rotation", result["hypothesis"])
        self.assertIsNone(result["fallback_reason"])
        self.assertEqual(result["provenance"]["model"], ULTRA)
        self.assertEqual(result["provenance"]["prompt_tokens"], 200)
        self.assertIsNone(result["provenance"]["estimated_cost_usd"])
        self.assertEqual(result["raw_content"], self.good_reply())
        self.assertEqual([c[:2] for c in transport.calls], [("GET", "models"), ("POST", "chat/completions")])
        self.assertNotIn(KEY, json.dumps(result))

    def test_the_request_contains_only_the_instruction_and_the_difference_table(self):
        transport = FakeTransport(reply=self.good_reply())
        self.call(transport)
        payload = transport.calls[1][2]
        self.assertEqual(payload["model"], ULTRA)
        self.assertEqual([m["role"] for m in payload["messages"]], ["system", "user"])
        self.assertEqual(payload["temperature"], 0)
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        user = json.loads(payload["messages"][1]["content"])
        self.assertEqual(set(user), {"task_instruction", "differences"})
        self.assertNotIn(KEY, json.dumps(payload))
        self.assertLess(len(json.dumps(payload)), 16_000)

    def test_super_is_the_fallback_model(self):
        result = self.call(FakeTransport(catalog=(NANO, SUPER), reply=self.good_reply()))
        self.assertEqual((result["source"], result["model"], result["tier"]), ("model", SUPER, "super"))

    def test_a_pinned_model_must_be_in_the_catalog(self):
        ok = self.call(FakeTransport(reply=self.good_reply()), model=SUPER)
        self.assertEqual((ok["model"], ok["tier"]), (SUPER, "pinned"))
        self.assert_fixed(self.call(FakeTransport(reply="x"), model="nvidia/other"), "model_unavailable")

    def test_no_nemotron_3_large_model_means_fixed_order_and_no_post(self):
        transport = FakeTransport(catalog=(NANO,), reply=self.good_reply())
        self.assert_fixed(self.call(transport), "model_unavailable")
        self.assertEqual([c[0] for c in transport.calls], ["GET"])

    def test_catalog_and_post_errors_fall_back_with_a_code(self):
        self.assert_fixed(self.call(FakeTransport(catalog_error=tf.TokenFactoryError("authentication_failed"))),
                          "authentication_failed")
        self.assert_fixed(self.call(FakeTransport(catalog_error=TimeoutError())), "timeout")
        self.assert_fixed(self.call(FakeTransport(catalog_error=RuntimeError("boom"))), "http_error")
        timeout = self.call(FakeTransport(post_error=TimeoutError()))
        self.assert_fixed(timeout, "timeout")
        self.assertEqual(timeout["provenance"]["request_status"], "transport_error")
        self.assertEqual(timeout["model"], ULTRA)
        self.assert_fixed(self.call(FakeTransport(post_error=tf.TokenFactoryError("http_error"))), "http_error")

    def test_bad_catalog_payload(self):
        class Odd(FakeTransport):
            def __call__(self, method, path, payload, api_key):
                return {"data": "nope"} if method == "GET" else {}
        self.assert_fixed(self.call(Odd()), "invalid_response")

    def test_every_bad_model_reply_falls_back_and_keeps_the_text_for_diagnosis(self):
        cases = {
            "invalid_json": "```json\n" + self.good_reply() + "\n```",
            "unknown_entity": self.good_reply(ranking=("soup_1", "toaster")),
            "duplicate_entity": self.good_reply(ranking=("soup_1", "soup_1")),
            "invalid_shape": json.dumps({"ranking": ["soup_1"]}),
            "invalid_hypothesis": json.dumps({"ranking": ["soup_1"], "hypothesis": ""}),
        }
        for reason, content in cases.items():
            with self.subTest(reason=reason):
                result = self.call(FakeTransport(reply=content))
                self.assert_fixed(result, reason)
                self.assertEqual(result["raw_content"], content)
                self.assertEqual(result["provenance"]["request_status"], "invalid_response")
                self.assertEqual(result["provenance"]["error_code"], reason)

    def test_partial_ranking_is_completed_in_fixed_order(self):
        result = self.call(FakeTransport(reply=self.good_reply(ranking=("microwave_1",))))
        self.assertEqual(result["source"], "model")
        self.assertEqual(result["ranking"], ["microwave_1"] + [n for n in self.fixed if n != "microwave_1"])
        self.assertEqual(sorted(result["completed"]), ["bowl_1", "soup_1"])

    def test_truncated_wrong_model_and_malformed_responses(self):
        ok_choice = {"finish_reason": "stop", "message": {"content": self.good_reply()}}
        usage = {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}
        truncated = {"model": ULTRA, "usage": usage,
                     "choices": [{"finish_reason": "length", "message": {"content": "{"}}]}
        self.assert_fixed(self.call(FakeTransport(response=truncated)), "output_limit")
        wrong = {"model": SUPER, "usage": usage, "choices": [ok_choice]}
        self.assert_fixed(self.call(FakeTransport(response=wrong)), "model_mismatch")
        for response in ({"model": ULTRA, "choices": []}, {"model": ULTRA, "choices": [1]},
                         {"model": ULTRA, "choices": [{"finish_reason": "stop", "message": {"content": 5}}]},
                         {"model": ULTRA, "choices": [{"finish_reason": "tool_calls", "message": {"content": "x"}}]},
                         {"model": ULTRA, "usage": "x", "choices": [ok_choice]}, "text", []):
            with self.subTest(response=str(response)[:50]):
                self.assert_fixed(self.call(FakeTransport(response=response)), "invalid_response")

    def test_a_reply_containing_the_key_is_dropped_and_never_stored(self):
        for content in (self.good_reply().replace("soup rotation", "key " + KEY),
                        json.dumps({"ranking": ["soup_1"], "hypothesis": "ok"})[:-1] + ', "x": "' + KEY + '"}'):
            with self.subTest(content=content[:30]):
                result = self.call(FakeTransport(reply=content))
                self.assert_fixed(result, "unsafe_response")
                self.assertIsNone(result["raw_content"])

    def test_bad_key_falls_back_without_any_call(self):
        transport = FakeTransport(reply=self.good_reply())
        result = tf.request_scenario_hypothesis(INSTRUCTION, self.table, "bad\nkey", transport)
        self.assert_fixed(result, "invalid_api_key")
        self.assertEqual(transport.calls, [])

    def test_bad_difference_table_raises_before_any_call(self):
        transport = FakeTransport(reply=self.good_reply())
        with self.assertRaises(ValueError):
            tf.request_scenario_hypothesis(INSTRUCTION, [], KEY, transport)
        self.assertEqual(transport.calls, [])

    def test_caller_supplied_fixed_order_is_used_for_the_fallback(self):
        result = self.call(FakeTransport(catalog=(NANO,)), fixed_order=["bowl_1", "soup_1", "microwave_1"])
        self.assertEqual(result["ranking"], ["bowl_1", "soup_1", "microwave_1"])


class ExistingBehaviourIsUntouched(unittest.TestCase):
    def test_the_original_model_constant_and_preflight_still_hold(self):
        self.assertEqual(tf.MODEL, "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")
        self.assertEqual(tf.preflight(KEY, FakeTransport())["model"], tf.MODEL)


if __name__ == "__main__":
    unittest.main()
