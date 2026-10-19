"""Optional web context for the cases of a diagnosis run (ADR 0035; next steps added October 19, 2026).

For one new case this plans a few fixed-template queries, retrieves public sources with Tavily and asks
Nemotron 3 Ultra for 2 to 4 source-cited next steps (:mod:`robot_debug.next_steps`). It reuses the primitives of
the earlier occlusion-case research path (``scripts/research_case.py``): :mod:`robot_debug.tavily_search` (cache,
credit ledger) and the source numbering of :func:`robot_debug.research_store.assign_sources`. What differs is the
evidence it describes: that path is bound to an occlusion evidence packet in the case store, while a scenario,
stress-test or wording case has no such packet, so the queries and the facts sent to the model are built here
from the case record. The Nano related-work summary the first version stored was replaced by the next steps: it
was rejected for a scenario case and nothing used it.

The record is *context, not evidence*: the page shows it apart from the measurements. It holds only public
search results and the model's suggestions; the queries come from allowlisted descriptors (suite, family names,
kinds), never from paths, ids or recordings. No key is ever stored, printed or logged.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Optional, Sequence

SUITE_NAMES = {"libero_object": "LIBERO-Object", "libero_10": "LIBERO-10", "libero_spatial": "LIBERO-Spatial",
               "libero_goal": "LIBERO-Goal"}
FAMILY_PHRASES = {
    "darken": "low-light image darkening", "noise": "image sensor noise", "blur": "image blur",
    "contrast": "reduced image contrast", "jpeg": "JPEG compression artifacts",
    "colour_cast": "colour cast white balance error", "motion_blur": "camera motion blur",
    "dead_pixels": "dead pixels sensor damage", "viewpoint": "camera viewpoint shift", "lighting": "scene lighting change",
}
MAX_QUERIES = 3

class ResearchDeps(NamedTuple):
    """The outside calls, so a test can fake Tavily and Token Factory."""

    load_tavily_key: Callable[..., str]
    tavily_search: Callable[..., Mapping[str, Any]]
    load_nebius_key: Callable[..., str]
    request_next_steps: Callable[..., Mapping[str, Any]]
    ledger_root: Path
    cache_root: Path


def default_deps() -> ResearchDeps:
    from robot_debug import tavily_search as ts
    from robot_debug import token_factory as tf

    return ResearchDeps(ts.load_api_key, ts.search, tf.load_api_key, tf.request_next_steps,
                        ts.LEDGER_ROOT, ts.CACHE_ROOT)


def key_available(env_file: Optional[Path], deps: Optional[ResearchDeps] = None) -> bool:
    """Whether a Tavily key can be loaded. The key itself is dropped at once."""

    loader = (deps or default_deps()).load_tavily_key
    try:
        return bool(loader(env_file))
    except Exception:                   # noqa: BLE001 - any failure to find a usable key means "not available"
        return False


def _suite(case: Mapping[str, Any]) -> str:
    return SUITE_NAMES.get(str(case.get("suite")), "LIBERO")


def case_facts(case: Mapping[str, Any]) -> Dict[str, Any]:
    """The deterministic facts sent to the model: kind, suite and the measured result in words."""

    kind = case.get("kind")
    facts: Dict[str, Any] = {"policy": "GR00T N1 vision-language-action policy", "suite": _suite(case)}
    if kind == "audit":
        families = case.get("families") if isinstance(case.get("families"), Mapping) else {}
        failing = {n: i.get("threshold_severity") for n, i in families.items()
                   if isinstance(i, Mapping) and isinstance(i.get("threshold_severity"), (int, float))}
        holding = sorted(n for n in families if n not in failing)
        facts.update(kind="stress test of image and scene disturbances, one start, each family searched from "
                          "severity 0 to 1",
                     failed_from_severity={FAMILY_PHRASES.get(n, n): s for n, s in sorted(failing.items())},
                     held_to_full_strength=[FAMILY_PHRASES.get(n, n) for n in holding])
    elif kind == "paraphrase_reduction":
        minimal = case.get("minimal") if isinstance(case.get("minimal"), Mapping) else {}
        facts.update(kind="rewordings of the task instruction screened for a policy failure",
                     a_rewording_failed=bool(minimal.get("text")),
                     word_edits_needed=len(minimal.get("labels") or ()))
    else:
        minimal = case.get("minimal") if isinstance(case.get("minimal"), Mapping) else {}
        facts.update(kind="reduction of a failing start's scene layout to the smallest set of differences from "
                          "a passing start that still fails",
                     differences_found=len(case.get("differences") or ()),
                     kept_in_minimal_cause=len(minimal.get("selection") or ()))
    return facts


def build_queries(case: Mapping[str, Any]) -> List[str]:
    """Up to three fixed-template queries from the allowlisted descriptors of a case."""

    suite = _suite(case)
    kind = case.get("kind")
    if kind == "audit":
        families = case.get("families") if isinstance(case.get("families"), Mapping) else {}
        failing = sorted(n for n, i in families.items()
                         if isinstance(i, Mapping) and isinstance(i.get("threshold_severity"), (int, float)))
        queries = ["vision-language-action policy robustness to {} robot manipulation".format(FAMILY_PHRASES[n])
                   for n in failing[:2] if n in FAMILY_PHRASES]
        queries.append("GR00T N1 {} image perturbation robustness".format(suite))
        if not failing:
            queries.append("vision-language-action policy robustness to camera and lighting perturbation")
    elif kind == "paraphrase_reduction":
        queries = ["vision-language-action policy sensitivity to instruction paraphrase",
                   "language instruction robustness robot manipulation benchmark",
                   "GR00T N1 {} language instruction variation".format(suite)]
    else:
        queries = ["robot manipulation policy failure sensitivity to initial object position",
                   "vision-language-action policy sensitivity to initial scene layout {}".format(suite),
                   "delta debugging failure-inducing input minimization robot policy"]
    unique = []
    for query in queries:
        if query not in unique:
            unique.append(query)
    return unique[:MAX_QUERIES]


def _fit(context: Dict[str, Any], scored: List, deps_check: Callable[[Dict[str, Any]], None]) -> Dict[str, Any]:
    """Drop the lowest-scoring sources until the request fits its size bound (ids are never renumbered)."""

    from robot_debug.token_factory import TokenFactoryError

    remaining = list(scored)
    while True:
        try:
            deps_check(context)
            return context
        except TokenFactoryError:
            if len(remaining) <= 1:
                return context
        lowest = min(range(len(remaining)), key=lambda i: (remaining[i][1], -i))
        del remaining[lowest]
        context = dict(context, sources=[s for s, _score in remaining])


def build_context(case: Mapping[str, Any], queries: Sequence[Mapping[str, Any]],
                  run_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """The next-steps request for a case: its verified facts, the citable reruns and the retrieved sources.

    ``queries`` are the numbered searches (:func:`robot_debug.research_store.assign_sources`, or the ``queries``
    of a stored record). Titles and snippets are clipped. ``None`` when there is no source. The lowest-scoring
    sources are dropped until the request fits; ids are never renumbered."""

    from robot_debug import next_steps as ns
    from robot_debug import research_summary as rsum
    from robot_debug import token_factory as tf

    scored = [({"source_id": item["source_id"], "title": rsum._clip_bytes(item["title"], rsum.MAX_TITLE_BYTES_IN_CONTEXT),
                "url": item["url"],
                "snippet": rsum._clip_bytes(item["snippet"][:rsum.MAX_SNIPPET_IN_CONTEXT].rstrip(),
                                            rsum.MAX_SNIPPET_BYTES_IN_CONTEXT)}, item["score"])
              for entry in queries for item in entry["results"]]
    if not scored:
        return None
    details, evidence = ns.case_details(case, run_dir)
    context: Dict[str, Any] = {"facts": dict(case_facts(case), **details), "sources": [s for s, _score in scored]}
    if evidence:
        context["evidence"] = evidence
    return _fit(context, scored, tf.check_next_steps_request)


def request_record(context: Mapping[str, Any], env_file: Optional[Path],
                   deps: Optional[ResearchDeps] = None) -> Dict[str, Any]:
    """One Token Factory call for the next steps; returns the ``next_steps`` block to store."""

    from robot_debug import next_steps as ns

    deps = deps or default_deps()
    result = deps.request_next_steps(dict(context), deps.load_nebius_key(env_file))
    return ns.build_record(result, context)


def run(case: Mapping[str, Any], env_file: Optional[Path], deps: Optional[ResearchDeps] = None,
        now: Optional[Callable[[], dt.datetime]] = None, run_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Research one case; returns the record to store, or ``None`` when nothing could be retrieved.

    ``run_dir`` is the run folder, from which a stress test's levels are read for the facts. Raises the callee's
    errors (``TavilyError``, ``TokenFactoryError``...) for the caller to turn into a skipped step; their messages
    are fixed codes and never hold a key. A model answer that fails its checks is not an error: the record then
    holds ``next_steps`` with status ``rejected`` and no items, and the sources.
    """

    from robot_debug import research_store as rs

    deps = deps or default_deps()
    tavily_key = deps.load_tavily_key(env_file)
    searches = [deps.tavily_search(query, tavily_key, ledger_root=deps.ledger_root, cache_root=deps.cache_root)
                for query in build_queries(case)]
    queries = rs.assign_sources(searches)
    context = build_context(case, queries, run_dir)
    if context is None:
        return None
    created = (now or (lambda: dt.datetime.now(dt.timezone.utc)))().strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema_version": 1, "kind": "diagnosis_research", "case_id": case.get("case_id"), "created_at": created,
        "queries": [{"query": q["query"], "retrieved_at": q["retrieved_at"], "results": q["results"]}
                    for q in queries],
        "next_steps": request_record(context, env_file, deps),
    }
