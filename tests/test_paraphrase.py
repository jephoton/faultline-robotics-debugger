"""Paraphrase generation (fake Token Factory transport) and the word-edit model."""

from __future__ import annotations

import ast
import json
import random
import unittest
from pathlib import Path

from robot_debug import paraphrase as pp
from robot_debug import token_factory as tf

ROOT = Path(__file__).resolve().parents[1]
KEY = "SECRET-KEY-VALUE-123"
MODEL = pp.PARAPHRASE_MODEL
ORIGINAL = "pick up the alphabet soup and place it in the basket"
GOOD = [
    "Please pick up the alphabet soup and put it in the basket.",
    "grab the alphabet soup, then set it in the basket",
    "Take the alphabet soup and drop it into the basket",
    "put the alphabet soup in the basket",
    "Could you move the alphabet soup into the basket?",
]


class FakeTransport:
    def __init__(self, reply=None, catalog=(MODEL, "nvidia/other"), catalog_error=None, post_error=None,
                 response=None, finish="stop"):
        self.reply = reply if reply is not None else json.dumps({"paraphrases": GOOD})
        self.catalog, self.catalog_error, self.post_error = list(catalog), catalog_error, post_error
        self.response, self.finish = response, finish
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
        return {"model": payload["model"], "usage": {"prompt_tokens": 120, "completion_tokens": 90,
                                                     "total_tokens": 210},
                "choices": [{"finish_reason": self.finish, "message": {"content": self.reply}}]}


class TokenizeTests(unittest.TestCase):
    def test_words_keep_inner_hyphens_and_apostrophes_and_punctuation_stands_alone(self):
        self.assertEqual(["Pick", "up", "the", "bowl", ",", "then", "don't", "re-do", "it", "."],
                         pp.tokenize("Pick up the bowl, then don't re-do it."))
        self.assertEqual([], pp.tokenize("   "))
        self.assertEqual(["put", "(", "x", ")"], pp.tokenize("put (x)"))

    def test_normalize_collapses_whitespace(self):
        self.assertEqual("a b c", pp.normalize("  a \t b\n c "))


class WordEditTests(unittest.TestCase):
    def test_identical_texts_have_no_edits(self):
        self.assertEqual([], pp.word_edits(ORIGINAL, ORIGINAL))
        self.assertEqual([], pp.word_edits(ORIGINAL, "  " + ORIGINAL + " "))

    def test_edits_are_ordered_numbered_and_non_overlapping(self):
        edits = pp.word_edits(ORIGINAL, "Please pick up the alphabet soup and put it in the basket.")
        self.assertEqual([([], ["Please"]), (["place"], ["put"]), ([], ["."])],
                         [(e["original"], e["replacement"]) for e in edits])
        self.assertEqual(list(range(len(edits))), [e["id"] for e in edits])
        for before, after in zip(edits, edits[1:]):
            self.assertLess(before["end"], after["start"])
        for edit in edits:
            self.assertLessEqual(edit["start"], edit["end"])
            self.assertEqual(len(edit["replacement"]), len(edit["spaced"]))

    def test_a_replacement_an_insertion_and_a_deletion(self):
        edits = pp.word_edits("pick up the red bowl", "grab the bowl now")
        kinds = []
        for edit in edits:
            if not edit["original"]:
                kinds.append("insert")
            elif not edit["replacement"]:
                kinds.append("delete")
            else:
                kinds.append("replace")
        self.assertEqual({"replace", "delete", "insert"}, set(kinds))
        self.assertEqual(json.loads(json.dumps(edits)), edits)

    def test_applying_all_edits_reproduces_the_paraphrase_tokens(self):
        for paraphrase in GOOD + ["", "x", ORIGINAL.upper(), "bowl basket soup", "pick up , ! the soup"]:
            with self.subTest(paraphrase=paraphrase):
                edits = pp.word_edits(ORIGINAL, paraphrase)
                if not pp.tokenize(paraphrase):
                    continue
                self.assertEqual(pp.tokenize(paraphrase), pp.tokenize(pp.apply_edits(ORIGINAL, edits)))

    def test_applying_no_edits_gives_the_original_and_all_edits_a_typical_paraphrase(self):
        self.assertEqual(ORIGINAL, pp.apply_edits(ORIGINAL, []))
        for paraphrase in GOOD:
            with self.subTest(paraphrase=paraphrase):
                self.assertEqual(paraphrase, pp.apply_edits(ORIGINAL, pp.word_edits(ORIGINAL, paraphrase)))

    def test_every_subset_is_a_well_formed_text(self):
        edits = pp.word_edits(ORIGINAL, GOOD[0])
        self.assertGreaterEqual(len(edits), 3)
        for mask in range(1 << len(edits)):
            subset = [edit for index, edit in enumerate(edits) if mask >> index & 1]
            text = pp.apply_edits(ORIGINAL, subset)
            self.assertTrue(text and text == pp.normalize(text), text)
        # Spot-check readable results.
        self.assertEqual("pick up the alphabet soup and put it in the basket",
                         pp.apply_edits(ORIGINAL, [e for e in edits if e["replacement"] == ["put"]]))
        self.assertEqual("Please pick up the alphabet soup and place it in the basket",
                         pp.apply_edits(ORIGINAL, [e for e in edits if e["replacement"] == ["Please"]]))

    def test_applying_edits_is_deterministic_and_independent_of_the_other_edits(self):
        edits = pp.word_edits(ORIGINAL, GOOD[1])
        self.assertEqual(edits, pp.word_edits(ORIGINAL, GOOD[1]))
        self.assertEqual(pp.apply_edits(ORIGINAL, edits[:1]), pp.apply_edits(ORIGINAL, edits[:1]))

    def test_random_wordings_round_trip(self):
        rng = random.Random(7)
        vocabulary = ["pick", "up", "the", "bowl", "soup", ",", ".", "and", "put", "it", "in", "a-b", "don't"]
        for _ in range(200):
            original = " ".join(rng.choice(vocabulary) for _ in range(rng.randint(1, 8)))
            paraphrase = " ".join(rng.choice(vocabulary) for _ in range(rng.randint(1, 8)))
            edits = pp.word_edits(original, paraphrase)
            self.assertEqual(edits, pp.validate_edits(original, edits))
            text = pp.apply_edits(original, edits)
            self.assertEqual(pp.tokenize(paraphrase), pp.tokenize(text))
            self.assertEqual(pp.tokenize(original), pp.tokenize(pp.apply_edits(original, [])))
            for edit in edits:
                one = pp.tokenize(pp.apply_edits(original, [edit]))
                old = pp.tokenize(original)
                self.assertEqual(old[:edit["start"]] + edit["replacement"] + old[edit["end"]:], one)

    def test_words_are_not_glued_when_a_separating_mark_is_dropped(self):
        edits = pp.word_edits("bowl,now go", "bowl now go")
        self.assertEqual("bowl now go", pp.apply_edits("bowl,now go", edits))

    def test_edits_that_do_not_belong_to_the_original_are_refused(self):
        edits = pp.word_edits(ORIGINAL, GOOD[0])
        with self.assertRaises(pp.ParaphraseError):
            pp.apply_edits("something else entirely", edits)
        with self.assertRaises(pp.ParaphraseError):
            pp.apply_edits(ORIGINAL, list(reversed(edits)))
        with self.assertRaises(pp.ParaphraseError):
            pp.apply_edits("a", [{"id": 0, "start": 0, "end": 1, "original": ["a"], "replacement": [],
                                  "spaced": []}])

    def test_validate_edits_checks_shape_and_the_original(self):
        edits = pp.word_edits(ORIGINAL, GOOD[0])
        self.assertEqual(edits, pp.validate_edits(ORIGINAL, edits))
        broken = json.loads(json.dumps(edits))
        broken[0]["original"] = ["wrong"]
        bad = (None, "x", [1], [dict(edits[0], extra=1)], [dict(edits[0], spaced=[])],
               [dict(edits[0], start=-1)], [dict(edits[0], id="0")], [edits[0], edits[0]], broken,
               [dict(edits[0], replacement=["two words"])], [dict(edits[0], replacement=[""], spaced=[True])])
        for value in bad:
            with self.subTest(value=str(value)[:60]), self.assertRaises(pp.ParaphraseError):
                pp.validate_edits(ORIGINAL, value)

    def test_edit_labels(self):
        edits = pp.word_edits("pick up the red bowl", "grab the bowl now")
        labels = [pp.edit_label(edit) for edit in edits]
        self.assertIn('"pick up" -> "grab"', labels)
        self.assertIn('delete "red"', labels)
        self.assertIn('insert "now"', labels)


class ValidationTests(unittest.TestCase):
    def test_clean_instruction_normalises_and_bounds(self):
        self.assertEqual("pick it up", pp.clean_instruction("  pick\n it   up "))
        self.assertEqual("don't \"stop\" - ok", pp.clean_instruction("don’t “stop” – ok"))
        for bad in ("", "   ", "x" * 201, "café", "tab\x00bed", 5, None, "中文"):
            with self.subTest(bad=repr(bad)[:20]), self.assertRaises(pp.ParaphraseError):
                pp.clean_instruction(bad)
        self.assertEqual(200, len(pp.clean_instruction("x" * 200)))

    def test_accepted_are_distinct_and_not_the_original(self):
        accepted, rejected = pp.validate_paraphrases(ORIGINAL, [
            ORIGINAL.upper(), "Pick  up the ALPHABET soup and place it in the basket", GOOD[0], GOOD[0].lower(),
            GOOD[1], "", "x" * 300, 7, "café soup"])
        self.assertEqual([GOOD[0], GOOD[1]], accepted)
        self.assertEqual(7, len(rejected))
        self.assertEqual({"duplicate", "bad_length", "not_text", "not_ascii"},
                         {item["reason"] for item in rejected})
        self.assertTrue(all(len(item["text"]) <= 200 for item in rejected))

    def test_text_without_a_word_is_rejected(self):
        self.assertTrue(pp.has_words("go"))
        self.assertFalse(pp.has_words("... !"))
        accepted, rejected = pp.validate_paraphrases(ORIGINAL, ["...", "?!", GOOD[0]])
        self.assertEqual([GOOD[0]], accepted)
        self.assertEqual(["no_words", "no_words"], [item["reason"] for item in rejected])

    def test_the_known_instruction_is_the_one_the_benchmark_uses(self):
        self.assertEqual(ORIGINAL, pp.KNOWN_INSTRUCTIONS[("libero_object", 0)])

    def test_the_count_caps_the_accepted_list(self):
        accepted, rejected = pp.validate_paraphrases(ORIGINAL, GOOD, count=2)
        self.assertEqual(GOOD[:2], accepted)
        self.assertEqual(["over_count"] * 3, [item["reason"] for item in rejected])

    def test_replies_are_parsed_strictly(self):
        self.assertEqual(["a"], pp.parse_reply('{"paraphrases": ["a"]}'))
        bad = ("not json", '["a"]', '{"paraphrases": []}', '{"paraphrases": "a"}', '{"paraphrases": [1]}',
               '{"paraphrases": ["a"], "extra": 1}', '{"paraphrases": ["a"], "paraphrases": ["b"]}',
               '{"paraphrases": [NaN]}', '{"other": ["a"]}', json.dumps({"paraphrases": ["a"] * 41}), None, 3)
        for content in bad:
            with self.subTest(content=str(content)[:40]), self.assertRaises(pp.ParaphraseError):
                pp.parse_reply(content)

    def test_the_prompt_asks_for_a_little_more_than_the_count(self):
        prompt = pp.build_prompt(ORIGINAL, 10)
        self.assertEqual(pp.SYSTEM_PROMPT, prompt["system"])
        self.assertEqual({"instruction": ORIGINAL, "paraphrase_count": 12}, json.loads(prompt["user"]))
        for count in (0, 13, True, "3", None):
            with self.subTest(count=count), self.assertRaises(ValueError):
                pp.build_prompt(ORIGINAL, count)
        with self.assertRaises(ValueError):
            pp.build_prompt("", 3)


class RequestTests(unittest.TestCase):
    def call(self, transport, **kwargs):
        kwargs.setdefault("model", MODEL)
        return pp.request_paraphrases(ORIGINAL, 4, KEY, transport=transport, **kwargs)

    def test_a_good_reply_gives_validated_paraphrases_and_provenance(self):
        transport = FakeTransport()
        result = self.call(transport)
        self.assertEqual(GOOD[:4], result["paraphrases"])
        self.assertEqual(ORIGINAL, result["original"])
        self.assertEqual("over_count", result["rejected"][0]["reason"])
        self.assertIsNone(result["fallback_reason"])
        self.assertEqual(MODEL, result["model"])
        self.assertEqual(MODEL, result["provenance"]["model"])
        self.assertEqual(120, result["provenance"]["prompt_tokens"])
        self.assertNotIn(KEY, json.dumps(result))
        self.assertEqual([("GET", "models"), ("POST", "chat/completions")], [c[:2] for c in transport.calls])

    def test_the_request_has_the_agreed_parameters_and_never_carries_the_key(self):
        transport = FakeTransport()
        self.call(transport)
        payload = transport.calls[1][2]
        self.assertEqual(MODEL, payload["model"])
        self.assertEqual(0.7, payload["temperature"])
        self.assertEqual({"enable_thinking": False}, payload["chat_template_kwargs"])
        self.assertEqual({"type": "json_object"}, payload["response_format"])
        self.assertFalse(payload["stream"])
        self.assertEqual(["system", "user"], [m["role"] for m in payload["messages"]])
        self.assertNotIn(KEY, json.dumps(payload))
        self.assertLess(len(json.dumps(payload)), 4000)

    def test_the_default_model_is_nemotron_3_super(self):
        self.assertEqual("nvidia/nemotron-3-super-120b-a12b", pp.PARAPHRASE_MODEL)
        result = pp.request_paraphrases(ORIGINAL, 3, KEY, transport=FakeTransport())
        self.assertEqual(MODEL, result["model"])

    def assert_fallback(self, result, reason):
        self.assertEqual([], result["paraphrases"])
        self.assertEqual(reason, result["fallback_reason"])
        self.assertNotIn(KEY, json.dumps(result))

    def test_problems_fall_back_with_a_fixed_code_and_never_raise(self):
        cases = (
            (FakeTransport(catalog_error=tf.TokenFactoryError("authentication_failed")), "authentication_failed"),
            (FakeTransport(catalog_error=tf.TokenFactoryError("timeout")), "timeout"),
            (FakeTransport(catalog=("nvidia/other",)), "model_unavailable"),
            (FakeTransport(post_error=tf.TokenFactoryError("timeout")), "timeout"),
            (FakeTransport(post_error=RuntimeError("boom")), "http_error"),
            (FakeTransport(finish="length"), "output_limit"),
            (FakeTransport(finish="tool_calls"), "invalid_response"),
            (FakeTransport(response={"model": "other/model", "choices": []}), "model_mismatch"),
            (FakeTransport(response={"model": MODEL, "choices": []}), "invalid_response"),
            (FakeTransport(reply="not json"), "invalid_json"),
            (FakeTransport(reply=json.dumps({"ideas": ["a"]})), "invalid_shape"),
            (FakeTransport(reply=json.dumps({"paraphrases": [ORIGINAL, "", "café"]})), "no_valid_paraphrases"),
        )
        for transport, reason in cases:
            with self.subTest(reason=reason, calls=len(transport.calls)):
                self.assert_fallback(self.call(transport), reason)

    def test_a_catalog_without_the_model_makes_no_post(self):
        transport = FakeTransport(catalog=("nvidia/other",))
        self.call(transport)
        self.assertEqual(["GET"], [c[0] for c in transport.calls])

    def test_a_reply_that_carries_the_key_is_dropped(self):
        for reply in (json.dumps({"paraphrases": ["grab it " + KEY]}),
                      json.dumps({"paraphrases": ["grab it " + KEY[:8] + "​" + KEY[8:]]})):
            result = self.call(FakeTransport(reply=reply))
            self.assert_fallback(result, "unsafe_response")
            self.assertIsNone(result["raw_content"])

    def test_a_bad_key_or_input_is_refused_without_a_call(self):
        transport = FakeTransport()
        result = pp.request_paraphrases(ORIGINAL, 3, "bad\nkey", MODEL, transport)
        self.assert_fallback(result, "invalid_api_key")
        self.assertEqual([], transport.calls)
        with self.assertRaises(ValueError):
            pp.request_paraphrases("", 3, KEY, MODEL, transport)
        with self.assertRaises(ValueError):
            pp.request_paraphrases(ORIGINAL, 99, KEY, MODEL, transport)
        self.assertEqual([], transport.calls)

    def test_raw_content_is_kept_for_the_record(self):
        reply = json.dumps({"paraphrases": GOOD[:2]})
        result = self.call(FakeTransport(reply=reply))
        self.assertEqual(reply, result["raw_content"])


class JobSafetyTests(unittest.TestCase):
    def test_the_module_parses_as_python_38_and_loads_only_the_standard_library(self):
        path = ROOT / "src" / "robot_debug" / "paraphrase.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 8))
        loaded = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                loaded.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(0, node.level, "no relative import at load time")
                loaded.add(node.module)
        self.assertEqual({"__future__", "difflib", "json", "re", "typing"}, loaded)


if __name__ == "__main__":
    unittest.main()


class InterpolationTests(unittest.TestCase):
    def test_config_interpolation_characters_are_rejected(self):
        from robot_debug import paraphrase as pp
        for text in ("pick up ${oc.env:HF_TOKEN}", "place it in {the} basket", "cost $5 soup"):
            with self.assertRaises(pp.ParaphraseError):
                pp.clean_instruction(text)


class SpacingTests(unittest.TestCase):
    ORIGINAL = "pick up the alphabet soup and place it in the basket"

    def test_all_edits_reproduce_the_paraphrase_text_exactly(self):
        from robot_debug import paraphrase as pp
        for para in ("Please, pick up the alphabet soup and put it in the basket.",
                     'pick up the "alphabet soup" and place it in the basket',
                     "Kindly grab the alphabet soup, then drop it into the basket!"):
            self.assertEqual(pp.normalize(para), pp.apply_edits(self.ORIGINAL, pp.word_edits(self.ORIGINAL, para)))

    def test_inserted_punctuation_keeps_the_paraphrase_spacing_in_a_hybrid(self):
        from robot_debug import paraphrase as pp
        edits = pp.word_edits(self.ORIGINAL, "Please, pick up the alphabet soup and put it in the basket.")
        self.assertEqual("Please, pick up the alphabet soup and place it in the basket",
                         pp.apply_edits(self.ORIGINAL, [edits[0]]))
