"""Optional web context and next steps for the cases of a diagnosis run: fakes only, no Tavily and no Token Factory calls."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Dict, List

from robot_debug import orchestrator as orch
from robot_debug import pipeline_research as pr
from robot_debug import spec as sp
from robot_debug.tavily_search import TavilyError
from robot_debug.viewer.library import Library
from tests.test_diagnose_pipeline import (
    FAMILIES, M6, ORIGINAL, Base, diag_spec, lang_step, m6_step, reduce_step, screen_step)
from tests.test_orchestrator import finished, reduce_one, SOUP_ONLY
from tests.test_paraphrase_pipeline import ParaphraseTools

TAVILY_KEY = "tvly-FAKEFAKEFAKE0001"
NEBIUS_KEY = "FAKE-NEBIUS-KEY-0001"


class FakeResearch:
    def __init__(self, fail=None, results=3):
        self.calls: List[Any] = []
        self.requests: List[Dict[str, Any]] = []
        self.fail, self.results = fail, results

    def load_tavily_key(self, env_file=None):
        if self.fail == "no-key":
            raise TavilyError("missing_api_key")
        return TAVILY_KEY

    def search(self, query, key, *, ledger_root, cache_root, refresh=False):
        assert key == TAVILY_KEY
        if self.fail == "search":
            raise TavilyError("http_error")
        self.calls.append(query)
        number = len(self.calls)
        return {"query": query, "retrieved_at": "2026-10-19T01:00:00Z", "request_id": None, "credits": 1,
                "from_cache": False, "ledger_entries": 1,
                "results": [{"title": "Paper {}.{}".format(number, i), "snippet": "Studies robustness of robot "
                             "policies to perturbation {}.".format(i),
                             "url": "https://example.invalid/p/{}/{}".format(number, i), "score": 0.9 - i / 10}
                            for i in range(self.results)]}

    def load_nebius_key(self, env_file=None):
        return NEBIUS_KEY

    def next_steps(self, context, key):
        assert key == NEBIUS_KEY
        self.requests.append({"context": context})
        ids = [source["source_id"] for source in context["sources"]]
        note = {"next_steps": [
            {"text": "Collect more starts near the failing one and rerun them, since a source studies robustness of "
                     "robot policies to perturbation.", "cites": [ids[0]]},
            {"text": "Add this case to the evaluation suite as a regression test.", "cites": [ids[-1]]}]}
        return {"response_json": json.dumps(note),
                "provenance": {"request_status": "completed", "model": "fake/ultra", "estimated_cost_usd": None}}

    def deps(self):
        return pr.ResearchDeps(self.load_tavily_key, self.search, self.load_nebius_key, self.next_steps,
                               Path("ledger-unused"), Path("cache-unused"))


def research_spec(**kwargs) -> sp.Spec:
    return sp.parse_spec(dict(diag_spec(**kwargs).raw, research=True))


class Queries(unittest.TestCase):
    def test_queries_come_from_allowlisted_descriptors_only(self):
        audit = {"kind": "audit", "suite": "libero_object", "case_id": "ab" * 32,
                 "families": {"blur": {"threshold_severity": 0.4}, "noise": {"threshold_severity": 0.2},
                             "lighting": {"threshold_severity": None}},
                 "summary": "jobs/some-job-2610181000/evidence/m6_summary.json"}
        queries = pr.build_queries(audit)
        self.assertEqual(queries[0], "vision-language-action policy robustness to image blur robot manipulation")
        self.assertLessEqual(len(queries), pr.MAX_QUERIES)
        self.assertEqual(len(set(queries)), len(queries))
        for query in queries:
            self.assertTrue(query.isascii() and len(query) <= 200)
            for private in ("ab" * 32, "jobs/", "some-job", "evidence"):
                self.assertNotIn(private, query)

    def test_every_kind_has_queries_and_facts(self):
        for case in ({"kind": "audit", "suite": "libero_10", "families": {}},
                     {"kind": "paraphrase_reduction", "suite": "libero_10", "minimal": None},
                     {"kind": "scenario_reduction", "suite": "libero_10", "differences": [1, 2]}):
            with self.subTest(kind=case["kind"]):
                self.assertTrue(pr.build_queries(case))
                facts = pr.case_facts(case)
                self.assertEqual(facts["suite"], "LIBERO-10")
                self.assertIn("kind", facts)

    def test_the_facts_never_hold_ids_wordings_or_paths(self):
        case = {"kind": "paraphrase_reduction", "suite": "libero_object", "case_id": "cd" * 32,
                "instruction": ORIGINAL, "minimal": {"text": "secret wording", "labels": ["x", "y"]}}
        text = json.dumps(pr.case_facts(case))
        for private in ("cd" * 32, "secret wording", ORIGINAL):
            self.assertNotIn(private, text)


class RepeatedCitations(unittest.TestCase):
    def test_adjacent_repeats_collapse_and_other_markers_stay(self):
        from robot_debug.research_store import collapse_citations

        self.assertEqual("A study [S1] says so.", collapse_citations("A study [S1] [S1] says so."))
        self.assertEqual("A study [S1].", collapse_citations("A study [S1][S1]  [S1]."))
        self.assertEqual("A [S1] and [S2] [S1].", collapse_citations("A [S1] and [S2] [S1]."))
        self.assertEqual("no markers", collapse_citations("no markers"))

    def test_the_stored_step_never_carries_an_inline_marker(self):
        class Marking(FakeResearch):
            def next_steps(self, context, key):
                note = {"next_steps": [
                    {"text": "Rerun nearby starts [S1] [S1] to see whether the failure repeats.", "cites": ["S1"]},
                    {"text": "Add the case as a regression test.", "cites": ["S2"]}]}
                return {"response_json": json.dumps(note), "provenance": {"request_status": "completed",
                                                                         "model": "fake/ultra"}}

        case = {"case_id": "ab" * 32, "kind": "audit", "suite": "libero_object", "task_id": 0,
                "families": {"blur": {"threshold_severity": 0.4, "stop_reason": "threshold_found"}}}
        record = pr.run(case, None, deps=Marking().deps())
        self.assertEqual("Rerun nearby starts to see whether the failure repeats.",
                         record["next_steps"]["items"][0]["text"])
        self.assertNotIn("summary", record)

    def test_the_library_cites_each_source_once(self):
        from robot_debug.viewer.library import _research_block

        def note(text, ids):
            return {"summary": {"status": "interpreted", "related_work": [{"text": text, "source_ids": ids}]}}

        self.assertEqual("Study says so [S1]", _research_block(note("Study says so [S1]", ["S1"]))["related"])
        self.assertEqual("Study says so [S1]", _research_block(note("Study says so [S1] [S1]", ["S1"]))["related"])
        self.assertEqual("Study says so [S1] [S2]", _research_block(note("Study says so [S1]", ["S1", "S2"]))["related"])
        self.assertEqual("Study says so [S1, S2]", _research_block(note("Study says so", ["S1", "S2"]))["related"])


class SystemPrompt(unittest.TestCase):
    CONTEXT = {"facts": {"suite": "LIBERO-10"}, "sources": [
        {"source_id": "S1", "title": "t", "url": "https://example.invalid/a", "snippet": "s"}]}

    def sent_prompt(self, **kwargs):
        from robot_debug import token_factory as tf

        captured = []

        def transport(method, path, payload, key):
            captured.append(payload)
            raise RuntimeError("stop here")

        tf.request_research_summary(self.CONTEXT, "TEST-SECRET-DO-NOT-LOG", transport, **kwargs)
        return captured[0]["messages"][0]["content"]

    def test_the_occlusion_prompt_stays_the_default_and_a_caller_may_pass_its_own(self):
        from robot_debug.research_summary import RESEARCH_SYSTEM_PROMPT

        self.assertEqual(self.sent_prompt(), RESEARCH_SYSTEM_PROMPT)
        self.assertEqual(self.sent_prompt(system_prompt="my prompt"), "my prompt")

    def test_the_size_check_takes_the_prompt_too(self):
        from robot_debug import token_factory as tf

        tf.check_research_request(self.CONTEXT, "a short prompt")
        with self.assertRaises(tf.TokenFactoryError):
            tf.check_research_request(self.CONTEXT, "x" * 30000)


class PipelineResearch(Base):
    def script(self):
        return [screen_step(), m6_step(["blur", "noise"], thresholds={"blur": 0.4}), m6_step(["lighting"]),
                lang_step(failing=("p01",)), reduce_step()]

    def world_with(self, research, spec=None, **options):
        tools = ParaphraseTools()
        tools.research_deps = research.deps() if research is not None else None
        return self.world(self.script(), spec=spec or research_spec(), tools=tools, **options)

    def test_each_new_case_gets_context_stored_registered_and_shown(self):
        research = FakeResearch()
        runner, backend, tools, ledger, lines = self.world_with(research)
        result = runner.diagnose()
        self.assertEqual(result.status, "completed")
        for name in ("audit", "wording"):
            record = self.read(runner, "cases", name, "research.json")
            self.assertEqual((record["kind"], record["next_steps"]["status"]), ("diagnosis_research", "interpreted"))
            self.assertEqual(record["next_steps"]["provenance"]["model"], "fake/ultra")
            self.assertNotIn("summary", record)
            self.assertEqual(len(record["next_steps"]["items"]), 2)
            self.assertEqual(len(record["queries"]), 2 if name == "audit" else 3)
            case = self.read(runner, "cases", name, "case.json")
            self.assertEqual(record["case_id"], case["case_id"])
        steps = self.header(runner)["steps"]
        self.assertEqual((steps["research-audit"]["status"], steps["research-audit"]["sources"]), ("done", 6))
        self.assertEqual(steps["research-audit"]["next_steps"], "interpreted")
        self.assertEqual(steps["research-wording"]["status"], "done")
        self.assertEqual(len(research.requests), 2)
        # The model sees the facts and the public sources, never ids or the run's files.
        sent = json.dumps(research.requests[0]["context"])
        self.assertIn("image blur", sent)
        self.assertNotIn(self.read(runner, "cases", "audit", "case.json")["case_id"], sent)

        library = Library(runner.run_dir.parent.parent, runs_root=runner.run_dir.parent)
        audit = next(i for i in library.list()["items"] if i["kind"] == "audit")
        detail = library.detail(audit["id"])
        self.assertEqual(len(detail["research"]["sources"]), 6)
        self.assertTrue(detail["research"]["sources"][0]["url"].startswith("https://"))
        steps = detail["next_steps"]
        self.assertEqual((steps["status"], steps["model"], len(steps["items"])), ("interpreted", "fake/ultra", 2))
        self.assertEqual(steps["items"][0]["cites"], ["S1"])
        self.assertEqual([s["id"] for s in steps["sources"]], ["S{}".format(i) for i in range(1, 7)])
        self.assertTrue(all(set(s) == {"id", "title", "url"} for s in steps["sources"]))

    def test_the_keys_never_reach_the_run_folder_the_log_or_the_library(self):
        research = FakeResearch()
        runner, backend, tools, ledger, lines = self.world_with(research)
        runner.diagnose()
        everything = "\n".join(lines)
        for path in runner.run_dir.rglob("*.json"):
            everything += path.read_text(encoding="utf-8")
        library = Library(runner.run_dir.parent.parent, runs_root=runner.run_dir.parent)
        everything += json.dumps([library.detail(i["id"]) for i in library.list()["items"]])
        for key in (TAVILY_KEY, NEBIUS_KEY):
            self.assertNotIn(key, everything)

    def test_without_a_tavily_key_the_step_is_skipped_and_noted(self):
        research = FakeResearch(fail="no-key")
        runner, backend, tools, ledger, lines = self.world_with(research)
        result = runner.diagnose()
        self.assertEqual((result.status, research.calls), ("completed", []))
        steps = self.header(runner)["steps"]
        self.assertEqual((steps["research"]["status"], steps["research"]["reason"]), ("skipped", "no Tavily key"))
        self.assertFalse((runner.run_dir / "cases" / "audit" / "research.json").exists())
        self.assertTrue(any("skipped (no Tavily key)" in line for line in lines))

    def test_research_off_in_the_spec_skips_silently_with_a_note(self):
        research = FakeResearch()
        runner, backend, tools, ledger, lines = self.world_with(research, spec=diag_spec())
        runner.diagnose()
        steps = self.header(runner)["steps"]
        self.assertEqual((steps["research"]["status"], steps["research"]["reason"]),
                         ("skipped", "research is off in the spec"))
        self.assertEqual(research.calls, [])
        self.assertFalse(any("research" in line for line in lines))

    def test_no_llm_skips_the_summary_that_needs_nemotron(self):
        research = FakeResearch()
        runner, backend, tools, ledger, lines = self.world_with(research, no_llm=True,
                                                                spec=research_spec(probes={"families": FAMILIES,
                                                                                           "rewordings": 0}))
        runner.diagnose()
        self.assertEqual(self.header(runner)["steps"]["research"]["reason"], "--no-llm")
        self.assertEqual(research.calls, [])

    def test_a_failing_lookup_never_fails_the_run(self):
        research = FakeResearch(fail="search")
        runner, backend, tools, ledger, lines = self.world_with(research)
        result = runner.diagnose()
        self.assertEqual(result.status, "completed")
        steps = self.header(runner)["steps"]
        self.assertEqual((steps["research-audit"]["status"], steps["research-audit"]["error"]),
                         ("failed", "TavilyError"))
        self.assertFalse((runner.run_dir / "cases" / "audit" / "research.json").exists())
        self.assertEqual(len(self.diagnoses(runner)), 2)

    def test_a_search_with_no_sources_is_skipped(self):
        runner, backend, tools, ledger, lines = self.world_with(FakeResearch(results=0))
        runner.diagnose()
        self.assertEqual(self.header(runner)["steps"]["research-audit"]["status"], "skipped")

    def test_a_resumed_run_does_not_research_a_case_twice(self):
        research = FakeResearch()
        runner, backend, tools, ledger, lines = self.world_with(research)
        runner.diagnose()
        first = len(research.calls)
        runner._research_cases()
        self.assertEqual(len(research.calls), first)

    def test_the_layout_route_researches_its_one_case(self):
        research = FakeResearch()
        tools = ParaphraseTools()
        tools.research_deps = research.deps()
        script = [screen_step(failing=True),
                  finished(reduce_one(stop_reason="reduced", selection=SOUP_ONLY, entity_minimal=True, reduced=True))]
        runner, backend, tools, ledger, lines = self.world(script, spec=research_spec(), tools=tools)
        result = runner.diagnose()
        self.assertEqual(result.route, "layout")
        self.assertTrue((runner.run_dir / "research.json").is_file())
        self.assertEqual(self.header(runner)["steps"]["research-case"]["status"], "done")
        self.assertIn("scene layout", json.dumps(research.requests[0]["context"]["facts"]))

    def test_the_import_route_researches_its_one_case_too(self):
        import tempfile

        from robot_debug.scenario_import import write_scenario_candidate
        from tests.test_import_pipeline import failing_state, imported_reduce
        from robot_debug.scenario_import import build_candidate

        research = FakeResearch()
        tools = ParaphraseTools()
        tools.research_deps = research.deps()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "failing.candidate.json"
        write_scenario_candidate(path, build_candidate("libero_10", 3, failing_state(), {"kind": "benchmark",
                                                                                         "init_state_index": 31}))
        raw = dict(research_spec().raw, diagnose={"task": 3, "import": str(path), "probes": {"enabled": False}})
        script = [screen_step(),
                  finished(imported_reduce(stop_reason="reduced", selection=SOUP_ONLY, entity_minimal=True,
                                           reduced=True))]
        runner, backend, tools, ledger, lines = self.world(script, spec=sp.parse_spec(raw), tools=tools)
        result = runner.diagnose()
        self.assertEqual((result.status, result.route), ("completed", "layout"))
        self.assertTrue((runner.run_dir / "research.json").is_file())
        self.assertEqual(self.header(runner)["steps"]["research-case"]["status"], "done")


if __name__ == "__main__":
    unittest.main()
