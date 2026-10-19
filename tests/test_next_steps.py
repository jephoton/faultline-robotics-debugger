"""Research-backed next steps: validation, the Token Factory request, storage and the library block.

Fakes only: no Tavily and no Token Factory call is made.
"""

from __future__ import annotations

import copy
import json
import unittest

from robot_debug import next_steps as ns
from robot_debug import pipeline_research as pr
from robot_debug import token_factory as tf
from robot_debug.viewer.library import _next_steps_block, _research_block
from tests.test_scenario_packet import ContinuationShrinkNotesTests

KEY = "TEST-SECRET-DO-NOT-LOG"

CONTEXT = {
    "facts": {"suite": "LIBERO-10"},
    "evidence": [{"evidence_id": "c3", "meaning": "The failing start itself: F F F F, so it DOES reproduce."}],
    "sources": [{"source_id": "S1", "title": "A paper", "url": "https://example.invalid/a", "snippet": "Studies it."},
                {"source_id": "S2", "title": "Another", "url": "https://example.invalid/b", "snippet": "Studies more."}],
}


def answer(*items):
    return json.dumps({"next_steps": [{"text": t, "cites": c} for t, c in items]})


GOOD = answer(("Rerun starts near the failing one to see how wide the failing region is.", ["S1"]),
              ("Add this failing start to the evaluation suite as a regression test.", ["c3", "S2"]))


class ValidationTests(unittest.TestCase):
    def check(self, text, context=CONTEXT):
        return ns.validate_next_steps(text, context)

    def rejected(self, text, context=CONTEXT):
        with self.assertRaises(ns.NextStepsError):
            ns.validate_next_steps(text, context)

    def test_a_good_answer_keeps_its_items_and_cites(self):
        items = self.check(GOOD)
        self.assertEqual(2, len(items))
        self.assertEqual(["c3", "S2"], items[1]["cites"])
        self.assertEqual({"text", "cites"}, set(items[0]))

    def test_an_evidence_id_of_the_case_is_a_valid_cite(self):
        self.check(answer(("Rerun the failing start with a new seed.", ["c3"]),
                          ("Add a regression test.", ["S1"])))

    def test_an_id_that_was_not_offered_is_rejected(self):
        self.rejected(answer(("Rerun nearby starts.", ["S9"]), ("Add a regression test.", ["S1"])))
        self.rejected(answer(("Rerun nearby starts.", ["c4"]), ("Add a regression test.", ["S1"])))

    def test_an_item_needs_a_cite_and_at_most_three(self):
        self.rejected(answer(("Rerun nearby starts.", []), ("Add a regression test.", ["S1"])))
        self.rejected(answer(("Rerun nearby starts.", ["S1", "S2", "c3", "S1"]), ("Add a test.", ["S1"])))

    def test_two_to_four_items_only(self):
        self.rejected(answer(("Only one suggestion.", ["S1"])))
        self.rejected(answer(*[("Suggestion number {}.".format(n), ["S1"]) for n in range(5)]))
        self.check(answer(*[("Suggestion number {}.".format(n), ["S1"]) for n in range(4)]))

    def test_output_that_is_not_the_contract_is_rejected(self):
        for text in ("not json", "[]", "{}", json.dumps({"next_steps": "x"}),
                     json.dumps({"next_steps": [], "extra": 1}),
                     json.dumps({"next_steps": [{"text": "a", "cites": ["S1"], "why": "b"}] * 2}),
                     '{"next_steps": [], "next_steps": []}', "NaN", None, 5):
            with self.subTest(text=text):
                self.rejected(text)

    def test_a_link_or_a_claim_of_proof_is_rejected(self):
        self.rejected(answer(("See https://example.invalid/a for details.", ["S1"]), ("Add a test.", ["S2"])))
        self.rejected(answer(("Read example.com/paper first.", ["S1"]), ("Add a test.", ["S2"])))
        self.rejected(answer(("This proves the blur is the problem.", ["S1"]), ("Add a test.", ["S2"])))
        self.rejected(answer(("Find what causes the failure.", ["S1"]), ("Add a test.", ["S2"])))

    def test_an_inline_marker_must_be_cited_and_is_moved_out_of_the_text(self):
        items = self.check(answer(("Rerun nearby starts [S1].", ["S1"]), ("Add a regression test [c3] [S2].",
                                                                          ["c3", "S2"])))
        self.assertEqual("Rerun nearby starts.", items[0]["text"])
        self.assertEqual("Add a regression test.", items[1]["text"])
        self.rejected(answer(("Rerun nearby starts [S2].", ["S1"]), ("Add a regression test.", ["S1"])))

    def test_long_padded_or_repeated_text_is_rejected(self):
        self.rejected(answer(("x " * 300, ["S1"]), ("Add a test.", ["S2"])))
        self.rejected(answer((" padded ", ["S1"]), ("Add a test.", ["S2"])))
        self.rejected(answer(("Same.", ["S1"]), ("Same.", ["S2"])))

    def test_a_context_without_sources_is_invalid(self):
        self.rejected(GOOD, {"facts": {}, "sources": []})

    def test_rejection_reasons_never_hold_the_answer(self):
        reason = ns.rejection_reason(answer(("Secret words here https://x.invalid", ["S1"]), ("b", ["S1"])), CONTEXT)
        self.assertNotIn("Secret", reason)
        self.assertEqual("valid", ns.rejection_reason(GOOD, CONTEXT))


class RecordTests(unittest.TestCase):
    def test_accepted_items_are_stored_with_the_model_and_status(self):
        record = ns.build_record({"response_json": GOOD, "provenance": {
            "model": tf.NEXT_STEPS_MODEL, "request_status": "completed", "prompt_tokens": 900,
            "completion_tokens": 120, "estimated_cost_usd": None, "endpoint": "https://example.invalid", "x": 1}},
            CONTEXT)
        self.assertEqual("interpreted", record["status"])
        self.assertEqual(2, len(record["items"]))
        self.assertEqual(tf.NEXT_STEPS_MODEL, record["provenance"]["model"])
        self.assertNotIn("x", record["provenance"])

    def test_invalid_output_fails_closed_with_no_items(self):
        record = ns.build_record({"response_json": answer(("One.", ["S9"]), ("Two.", ["S1"])),
                                  "provenance": {"model": "m", "request_status": "completed"}}, CONTEXT)
        self.assertEqual(("rejected", []), (record["status"], record["items"]))
        self.assertNotIn("S9", json.dumps(record))

    def test_a_refused_or_failed_request_has_no_items(self):
        refused = ns.build_record({"response_json": None, "provenance": {"request_status": "invalid_response",
                                                                         "model": "m"}}, CONTEXT)
        failed = ns.build_record({"response_json": None, "provenance": {"request_status": "http_error",
                                                                        "model": "m"}}, CONTEXT)
        self.assertEqual(("rejected", []), (refused["status"], refused["items"]))
        self.assertEqual(("provider_error", []), (failed["status"], failed["items"]))


def completion(content, model=None, finish="stop", usage=(900, 120)):
    return {"model": model or tf.NEXT_STEPS_MODEL, "choices": [{"finish_reason": finish,
                                                                 "message": {"content": content}}],
            "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1], "total_tokens": sum(usage)}}


class RequestTests(unittest.TestCase):
    def call(self, response=None, context=CONTEXT, error=None):
        sent = []

        def transport(method, path, payload, key):
            sent.append((method, path, payload))
            if error:
                raise error
            return response

        return tf.request_next_steps(context, KEY, transport), sent

    def test_one_post_to_ultra_with_the_next_steps_prompt_and_no_key_in_the_body(self):
        result, sent = self.call(completion(GOOD))
        self.assertEqual([("POST", "chat/completions")], [(m, p) for m, p, _ in sent])
        payload = sent[0][2]
        self.assertEqual("nvidia/Nemotron-3-Ultra-550b-a55b", payload["model"])
        self.assertEqual(ns.NEXT_STEPS_PROMPT, payload["messages"][0]["content"])
        self.assertIn("suggestion", payload["messages"][0]["content"])
        self.assertEqual(CONTEXT, json.loads(payload["messages"][1]["content"]))
        self.assertNotIn(KEY, json.dumps(payload))
        self.assertEqual(GOOD, result["response_json"])
        self.assertEqual(("completed", tf.NEXT_STEPS_MODEL, None),
                         (result["provenance"]["request_status"], result["provenance"]["model"],
                          result["provenance"]["estimated_cost_usd"]))
        self.assertNotIn(KEY, json.dumps(result))

    def test_every_kind_of_bad_reply_gives_no_answer(self):
        cases = {"wrong model": completion(GOOD, model="nvidia/other"),
                 "cut off": completion(GOOD, finish="length"),
                 "bad cite": completion(answer(("One.", ["S9"]), ("Two.", ["S1"]))),
                 "not json": completion("prose"),
                 "over the token cap": completion(GOOD, usage=(900, 5000)),
                 "key echoed": completion(answer(("Use {} now.".format(KEY), ["S1"]), ("Two.", ["S2"])))}
        for name, response in cases.items():
            with self.subTest(name):
                result, _ = self.call(response)
                self.assertIsNone(result["response_json"])
                self.assertEqual("invalid_response", result["provenance"]["request_status"])
                self.assertNotIn(KEY, json.dumps(result.get("rejected_content", "")))

    def test_a_transport_error_is_recorded_not_raised(self):
        result, _ = self.call(error=TimeoutError())
        self.assertIsNone(result["response_json"])
        self.assertEqual("transport_error", result["provenance"]["request_status"])

    def test_the_size_bound_applies_before_any_call(self):
        big = dict(CONTEXT, sources=[dict(CONTEXT["sources"][0], snippet="x" * 30000)])
        with self.assertRaises(tf.TokenFactoryError):
            tf.request_next_steps(big, KEY, lambda *a: self.fail("no call may be made"))
        self.assertGreater(tf.next_steps_request_size(CONTEXT), 500)


class ContextTests(unittest.TestCase):
    def scenario_case(self):
        return ContinuationShrinkNotesTests().case()

    def queries(self, count=3):
        return [{"query": "q", "retrieved_at": "2026-10-19T01:00:00Z", "results": [
            {"source_id": "S{}".format(i + 1), "title": "T{}".format(i), "url": "https://example.invalid/{}".format(i),
             "snippet": "s" * 900, "score": 0.9 - i / 20} for i in range(count)]}]

    def test_a_scenario_case_sends_its_cause_tested_sizes_and_citable_reruns(self):
        case = self.scenario_case()
        context = pr.build_context(case, self.queries())
        facts = context["facts"]
        self.assertIn("milk position", " ".join(facts["kept_sizes"]))
        self.assertTrue(any(n.startswith("milk ") and "87.5% reproduced it" in n for n in facts["sizes_already_tested"]))
        self.assertIn("enough to make the policy fail", facts["minimal_cause"])
        ids = [row["evidence_id"] for row in context["evidence"]]
        self.assertTrue(ids and all(i.startswith("c") for i in ids))
        self.assertEqual(ids, ns.context_ids(context)[1])
        self.assertLessEqual(len(context["sources"][0]["snippet"]), 300)

    def test_nothing_private_is_sent(self):
        case = dict(self.scenario_case())
        text = json.dumps(pr.build_context(case, self.queries()))
        self.assertNotIn(case["case_id"], text)
        for private in ("C:\\", "/home/", "artifacts"):
            self.assertNotIn(private, text)

    def test_a_stress_test_sends_the_levels_around_each_threshold(self):
        import tempfile
        from pathlib import Path

        def level(severity, failures):
            return {"severity": severity, "outcomes": ["policy_failure"] * failures + ["success"] * (5 - failures),
                    "failures": failures, "complete": True}

        summary = {"families": {"blur": {"levels": [level(0.2, 0), level(0.6, 5), level(0.4, 0), level(0.5, 5)]},
                                "noise": {"levels": [level(0.2, 0), level(1.0, 0)]}},
                   "nominal_controls": {"outcomes": {"success": 5}, "planned": 5}}
        case = {"kind": "audit", "suite": "libero_10", "summary": "cases/audit/merged-summary.json",
                "families": {"blur": {"threshold_severity": 0.5, "stop_reason": "threshold_found"},
                             "noise": {"threshold_severity": None, "stop_reason": "no_reproducible_failure"}}}
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            target = run / "cases" / "audit"
            target.mkdir(parents=True)
            (target / "merged-summary.json").write_text(json.dumps(summary), encoding="utf-8")
            context = pr.build_context(case, self.queries(), run)
            without = pr.build_context(case, self.queries(), None)
        families = {f["family"]: f for f in context["facts"]["families"]}
        blur = families["image blur"]
        self.assertEqual({"severity": 0.5, "failures": 5, "attempts": 5, "evidence_id": "blur@0.5"}, blur["at_threshold"])
        self.assertEqual(0.4, blur["last_level_below_threshold"]["severity"])
        self.assertEqual("blur@0.4", blur["last_level_below_threshold"]["evidence_id"])
        self.assertEqual(1.0, families["image sensor noise"]["highest_level_tried"]["severity"])
        self.assertEqual(["image sensor noise"], context["facts"]["families_that_never_failed"])
        self.assertEqual({"failures": 0, "attempts": 5}, context["facts"]["unperturbed_control"])
        self.assertEqual(["blur@0.4", "blur@0.5", "noise@1"], sorted(r["evidence_id"] for r in context["evidence"]))
        self.assertEqual(["blur@0.4", "blur@0.5", "noise@1"], sorted(ns.context_ids(context)[1]))
        self.assertEqual("not replayed", blur["latest_replay"])
        self.assertFalse(blur["borderline"])
        self.assertNotIn("at_threshold", without["facts"]["families"][0])      # no run folder: counts unknown

    def test_dropping_sources_to_fit_keeps_the_evidence(self):
        case = self.scenario_case()
        queries = self.queries(5)
        for result in queries[0]["results"]:
            result["snippet"] = "y" * 5000          # clipped to 300, so all five fit; shrink the bound instead
        context = pr.build_context(case, queries)
        self.assertIn("evidence", context)
        original = tf._MAX_REQUEST_BYTES_NEXT_STEPS
        try:
            tf._MAX_REQUEST_BYTES_NEXT_STEPS = tf.next_steps_request_size(context) - 200
            fitted = pr.build_context(case, queries)
        finally:
            tf._MAX_REQUEST_BYTES_NEXT_STEPS = original
        self.assertLess(len(fitted["sources"]), len(context["sources"]))
        self.assertEqual(context["evidence"], fitted["evidence"])
        self.assertEqual(context["sources"][0]["source_id"], fitted["sources"][0]["source_id"])

    def test_no_sources_means_no_context(self):
        self.assertIsNone(pr.build_context({"kind": "audit"}, [{"results": []}]))


class SettledFactsTests(unittest.TestCase):
    """October 19 first real answers: an ablation the reruns had already done, raw simulator names in the text."""

    FULL = {"robot": {"joints": 1.0}, "basket_1": {"position": 1.0}, "milk_1": {"position": 1.0},
            "orange_juice_1": {"position": 1.0}}

    def case(self, skip=(), reproduces=()):
        from tests import reduction_fixtures as rf

        case = copy.deepcopy(ContinuationShrinkNotesTests().case())
        kept = list(self.FULL)
        rows = []
        index = 20
        for entity in kept:
            if ("alone", entity) not in skip:
                decision = "reproduces" if ("alone", entity) in reproduces else "does_not_reproduce"
                rows.append(rf.candidate(index, "probe", {entity: dict(self.FULL[entity])}, decision))
            index += 1
            if ("without", entity) not in skip:
                rows.append(rf.candidate(index, "ddmin", {e: dict(self.FULL[e]) for e in kept if e != entity},
                                         "does_not_reproduce"))
            index += 1
        case["reruns"] = case["reruns"] + rows
        return case

    def facts(self, case=None):
        details, evidence = ns.case_details(case or self.case())
        return details, evidence

    def entity(self, details, name):
        return next(e for e in details["already_measured"]["each_kept_entity"] if e["entity"] == name)

    def test_each_kept_entity_reports_alone_and_removal_with_the_row(self):
        details, evidence = self.facts()
        juice = self.entity(details, "orange juice")
        self.assertEqual("yes", juice["alone_policy_passes"])
        self.assertEqual("yes", juice["removing_it_policy_passes"])
        self.assertEqual("0 of 4", juice["removing_it_attempts_failed"])
        ids = {row["evidence_id"] for row in evidence}
        self.assertIn(juice["alone_evidence_id"], ids)
        self.assertIn(juice["removing_it_evidence_id"], ids)
        for entity in details["already_measured"]["each_kept_entity"]:
            self.assertIn(entity["removing_it_evidence_id"], ids)

    def test_sizes_kept_largest_passed_and_parts_never_shrunk(self):
        details, _ = self.facts()
        milk = self.entity(details, "milk")
        self.assertEqual("position 87.5% of its difference", milk["kept_size"])
        self.assertEqual("position 75%", milk["largest_size_that_passed"])
        self.assertEqual("position 100% of its difference", self.entity(details, "orange juice")["kept_size"])
        self.assertEqual("none tested", self.entity(details, "orange juice")["largest_size_that_passed"])
        self.assertEqual(["orange juice position"], details["already_measured"]["parts_never_shrunk"])

    def test_a_missing_row_is_reported_as_not_saved_not_guessed(self):
        details, _ = self.facts(self.case(skip={("without", "orange_juice_1")}))
        juice = self.entity(details, "orange juice")
        self.assertEqual("not in the saved reruns", juice["removing_it_policy_passes"])
        self.assertNotIn("removing_it_evidence_id", juice)
        self.assertEqual("yes", juice["alone_policy_passes"])

    def test_a_shift_that_reproduces_alone_is_reported_as_no(self):
        details, _ = self.facts(self.case(reproduces={("alone", "robot")}))
        self.assertEqual("no", self.entity(details, "robot")["alone_policy_passes"])

    def test_nothing_the_model_reads_holds_a_raw_simulator_name(self):
        details, evidence = self.facts()
        text = json.dumps({"facts": details, "evidence": evidence})
        for raw in ("orange_juice_1", "milk_1", "basket_1", "_1"):
            self.assertNotIn(raw, text)
        self.assertIn("orange juice", text)

    def test_two_entities_that_read_the_same_keep_their_number(self):
        case = copy.deepcopy(self.case())
        case["minimal"]["selection"] = {"bowl_1": {"position": 1.0}, "bowl_2": {"position": 0.5}}
        details, _ = ns.case_details(case)
        self.assertEqual(["bowl 1", "bowl 2"], [e["entity"] for e in details["already_measured"]["each_kept_entity"]])

    def test_a_single_kept_entity_has_no_alone_or_removal_claim(self):
        case = copy.deepcopy(self.case())
        case["minimal"]["selection"] = {"milk_1": {"position": 0.875}}
        details, _ = ns.case_details(case)
        record = details["already_measured"]["each_kept_entity"][0]
        self.assertNotIn("alone_policy_passes", record)
        self.assertEqual("position 75%", record["largest_size_that_passed"])

    def test_the_rows_behind_the_facts_stay_citable_within_the_bound(self):
        details, evidence = self.facts()
        self.assertLessEqual(len(evidence), ns.MAX_EVIDENCE_ROWS)
        self.assertEqual(len(evidence), len({r["evidence_id"] for r in evidence}))
        context = {"facts": details, "evidence": evidence, "sources": CONTEXT["sources"]}
        self.assertEqual([r["evidence_id"] for r in evidence], ns.context_ids(context)[1])

    def test_the_prompt_forbids_settled_tests_unrelated_sources_and_raw_names(self):
        prompt = ns.NEXT_STEPS_PROMPT
        for phrase in ("Do not suggest a test whose answer is already in the facts", "borderline",
                       "plain words", "Put ids only in cites", "directly supports the step",
                       "cite the case evidence instead", "blur@0.4625"):
            self.assertIn(phrase, prompt)


class AuditSettledFactsTests(unittest.TestCase):
    def level(self, severity, failures):
        return {"severity": severity, "outcomes": ["policy_failure"] * failures + ["success"] * (5 - failures),
                "failures": failures, "complete": True}

    def run_tree(self, replay_text=None, replay_checkpoint=None, case_checkpoint=None):
        import tempfile
        from pathlib import Path

        summary = {"families": {"blur": {"levels": [self.level(0.4, 0), self.level(0.4625, 4)]},
                                "noise": {"levels": [self.level(0.3, 0), self.level(0.6, 5)]},
                                "darken": {"levels": [self.level(1.0, 0)]}},
                   "nominal_controls": {"outcomes": {"success": 5}, "planned": 5}}
        case = {"kind": "audit", "case_id": "a" * 64, "suite": "libero_10", "summary": "cases/audit/s.json",
                "families": {"blur": {"threshold_severity": 0.4625}, "noise": {"threshold_severity": 0.6},
                             "darken": {"threshold_severity": None, "stop_reason": "no_reproducible_failure"}}}
        if case_checkpoint:
            case["checkpoint"] = case_checkpoint
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        run = root / "audit-20261016T064528Z"
        (run / "cases" / "audit").mkdir(parents=True)
        (run / "cases" / "audit" / "s.json").write_text(json.dumps(summary), encoding="utf-8")
        if replay_text is not None:
            replay = root / "replay-20261018T010203Z"
            replay.mkdir()
            result = {"case_id": "a" * 64, "verdict_text": replay_text}
            if replay_checkpoint:
                result["checkpoint"] = replay_checkpoint
            (replay / "replay-result.json").write_text(json.dumps(result), encoding="utf-8")
        return case, run

    def families(self, case, run):
        details, evidence = ns.case_details(case, run)
        return {f["family"]: f for f in details["families"]}, details, evidence

    def test_a_family_the_latest_replay_did_not_repeat_is_borderline(self):
        case, run = self.run_tree("still fails at s = 0.60 (noise); no longer fails at s = 0.4625 "
                                  "(blur; fails only at higher s = 0.50)")
        families, details, _ = self.families(case, run)
        blur, noise = families["image blur"], families["image sensor noise"]
        self.assertEqual(("did not repeat the failure", True, 0.5),
                         (blur["latest_replay"], blur["borderline"], blur["failed_only_at_higher_severity"]))
        self.assertEqual(("repeated the failure", False), (noise["latest_replay"], noise["borderline"]))
        self.assertEqual(["low-light image darkening"], details["families_that_never_failed"])

    def test_without_a_replay_nothing_is_borderline(self):
        case, run = self.run_tree()
        blur = self.families(case, run)[0]["image blur"]
        self.assertEqual(("not replayed", False), (blur["latest_replay"], blur["borderline"]))

    def test_a_replay_of_a_new_checkpoint_says_nothing_about_the_original(self):
        case, run = self.run_tree("no longer fails at s = 0.4625 (blur)", {"id": "new-ckpt"}, {"id": "orig"})
        self.assertFalse(self.families(case, run)[0]["image blur"]["borderline"])
        same, run = self.run_tree("no longer fails at s = 0.4625 (blur)", {"id": "orig"}, {"id": "orig"})
        self.assertTrue(self.families(same, run)[0]["image blur"]["borderline"])

    def test_every_level_is_a_citable_evidence_id(self):
        case, run = self.run_tree()
        _, _, evidence = self.families(case, run)
        ids = sorted(row["evidence_id"] for row in evidence)
        self.assertEqual(["blur@0.4", "blur@0.4625", "darken@1", "noise@0.3", "noise@0.6"], ids)
        row = next(r for r in evidence if r["evidence_id"] == "blur@0.4625")
        self.assertIn("4 of 5 attempts failed", row["meaning"])
        self.assertNotIn("_", " ".join(r["meaning"] for r in evidence))

    def test_a_replay_sentence_is_parsed_per_family(self):
        found = ns.replay_outcome_by_family(
            "still fails at s = 0.50 (blur); no longer fails at s = 0.60 (noise), s = 0.40 (contrast; "
            "fails only at higher s = 0.80); not tested: jpeg")
        self.assertEqual({"blur": {"repeated": True, "higher": None}, "noise": {"repeated": False, "higher": None},
                          "contrast": {"repeated": False, "higher": 0.8}}, found)
        self.assertEqual({}, ns.replay_outcome_by_family("inconclusive"))


class PlainTextValidationTests(unittest.TestCase):
    CONTEXT = dict(CONTEXT, evidence=[{"evidence_id": "c3", "meaning": "m"},
                                      {"evidence_id": "blur@0.4625", "meaning": "Image blur at severity 0.4625"}])

    def rejected(self, text):
        with self.assertRaises(ns.NextStepsError):
            ns.validate_next_steps(answer((text, ["S1"]), ("Add a regression test.", ["c3"])), self.CONTEXT)

    def test_a_raw_entity_name_in_the_text_is_rejected(self):
        self.rejected("Rerun the scene without orange_juice_1 to check it.")
        self.rejected("Move the basket_1 slightly.")
        self.rejected("Shift milk_1 by a few centimetres.")
        self.rejected("Try the alphabet_soup in a new position.")
        self.rejected("Test motion_blur at lower severity.")

    def test_plain_words_pass(self):
        ns.validate_next_steps(answer(("Collect demonstrations with the orange juice placed nearer the basket.", ["S1"]),
                                      ("Add this start to the evaluation suite.", ["c3"])), self.CONTEXT)

    def test_an_id_written_into_the_text_is_rejected_but_a_marker_is_moved_out(self):
        self.rejected("Row c37 shows the failure, so add a test.")
        self.rejected("Source S2 studies this, so add a test.")
        self.rejected("Blur at blur@0.4625 is the edge, so add a test.")
        items = ns.validate_next_steps(answer(("Add a test near the edge [blur@0.4625].", ["blur@0.4625"]),
                                              ("Collect more data [c3].", ["c3", "S1"])), self.CONTEXT)
        self.assertEqual("Add a test near the edge.", items[0]["text"])

    def test_a_stress_test_level_id_is_a_valid_cite_only_when_offered(self):
        ns.validate_next_steps(answer(("Test blur nearer the edge.", ["blur@0.4625", "S1"]),
                                      ("Add a test.", ["c3"])), self.CONTEXT)
        with self.assertRaises(ns.NextStepsError):
            ns.validate_next_steps(answer(("Test blur nearer the edge.", ["blur@0.9"]), ("Add a test.", ["c3"])),
                                   self.CONTEXT)

    def test_the_context_accepts_stress_test_ids(self):
        self.assertEqual((["S1", "S2"], ["c3", "blur@0.4625"]), ns.context_ids(self.CONTEXT))
        bad = dict(CONTEXT, evidence=[{"evidence_id": "Blur@x", "meaning": "m"}])
        with self.assertRaises(ns.NextStepsError):
            ns.context_ids(bad)


class LibraryBlockTests(unittest.TestCase):
    QUERIES = [{"query": "q", "results": [
        {"source_id": "S1", "title": "Paper", "url": "https://example.invalid/a", "snippet": "secret snippet",
         "score": 0.9},
        {"source_id": "S2", "title": "Plain", "url": "http://example.invalid/b", "snippet": "x", "score": 0.5}]}]

    def record(self, **block):
        return {"queries": self.QUERIES, "next_steps": dict({"status": "interpreted", "items": [
            {"text": "Rerun nearby starts.", "cites": ["S1", "c3"]}],
            "provenance": {"model": tf.NEXT_STEPS_MODEL, "request_status": "completed"}}, **block)}

    def test_the_block_has_the_contract_shape_with_titles_and_https_urls_only(self):
        block = _next_steps_block(self.record())
        self.assertEqual({"model", "status", "items", "sources"}, set(block))
        self.assertEqual(tf.NEXT_STEPS_MODEL, block["model"])
        self.assertEqual([{"text": "Rerun nearby starts.", "cites": ["S1", "c3"]}], block["items"])
        self.assertEqual([{"id": "S1", "title": "Paper", "url": "https://example.invalid/a"}], block["sources"])
        self.assertNotIn("secret", json.dumps(block))

    def test_a_rejected_answer_shows_its_status_and_no_items(self):
        block = _next_steps_block(self.record(status="rejected", items=[{"text": "t", "cites": ["S1"]}]))
        self.assertEqual(("rejected", []), (block["status"], block["items"]))

    def test_an_earlier_record_has_no_next_steps_and_its_note_stays_readable(self):
        old = {"queries": self.QUERIES, "summary": {"status": "interpreted", "related_work": [
            {"text": "A paper studies it [S1].", "source_ids": ["S1"]}], "limitations": []}}
        self.assertIsNone(_next_steps_block(old))
        self.assertEqual("A paper studies it [S1].", _research_block(old)["related"])
        self.assertIsNone(_next_steps_block(None))
        self.assertIsNone(_next_steps_block({"next_steps": "oops"}))

    def test_malformed_items_are_dropped(self):
        record = self.record(items=[{"text": "ok", "cites": ["S1"]}, {"text": 5, "cites": ["S1"]},
                                    {"text": "no cites", "cites": []}, "junk"])
        self.assertEqual(["ok"], [i["text"] for i in _next_steps_block(record)["items"]])


if __name__ == "__main__":
    unittest.main()
