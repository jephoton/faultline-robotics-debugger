# M5D: Tavily research context with a source-cited Nemotron summary

**Goal:** For a registered, reduced case, retrieve a few relevant public sources
with Tavily, have Nemotron write a short source-cited related-work note, store
both as an immutable research record, and show it in the viewer as context that
is clearly separate from measured evidence.

**Design:** ADR 0024 (accepted October 11). **Timebox:** about 1.5 days
(October 12–13, ADR 0023). **Target case:** the certified M4 case
`52d89d40…` in `artifacts/cases` (v2 packet; reduced mask
`(0.625, 0, 0.375, 0.375)`, upper-right, about 14% of the image).

## Caps and spending gate

- Tavily: `search_depth: "basic"` (1 credit), `max_results: 5`, at most 3
  queries per `search` run, **50 credits total** for M5D, enforced by an
  exclusive per-request ledger under `artifacts/m5d-research/tavily-ledger/`.
- Nemotron: **US$0.05 total**, five labelled attempts `r-01`..`r-05`, each with
  an exclusive US$0.01 reservation under `artifacts/m5d-research/nemotron/`.
  The request is capped at 20 KB and `max_tokens` at 1,500, so the worst case
  stays under US$0.01 per attempt (US$0.06/M input, US$0.24/M output).
- Approving this plan authorizes the live calls within these caps **after**
  the offline tests and the independent review pass. No GPU or AI Cloud spend.

## Components and file ownership

| Unit | Files (new unless noted) | Owner |
| --- | --- | --- |
| A. Queries | `src/robot_debug/research_query.py`, `tests/test_research_query.py` | backend agent |
| B. Tavily client | `src/robot_debug/tavily_search.py`, `tests/test_tavily_search.py` | backend agent |
| C. Research records | `src/robot_debug/research_store.py`, `tests/test_research_store.py` | backend agent |
| D. Nemotron summary | `src/robot_debug/research_summary.py`, `tests/test_research_summary.py`; small additive change to `src/robot_debug/token_factory.py` | backend agent |
| E. CLI | `scripts/research_case.py`, `tests/test_research_case.py` | backend agent |
| F. Viewer panel | `src/robot_debug/viewer/server.py`, `viewer/web/{index.html,app.js,styles.css}`, `tests/test_viewer_research.py` | viewer agent |
| G. Live run, docs | `docs/experiments/m5d-tavily-research.md`, `FEEDBACK.md`, `docs/codex-handoff/STATE.md`, `PROJECT_PLAN.md` | coordinator |

Dependency map: A → B → C → D → E are sequential (one backend agent). F
depends only on the record schema below, so it runs in parallel with A–E in a
separate worktree. G runs after integration and review. The coordinator
(Claude Opus) owns integration, all live provider calls and all pushes.

## A. Deterministic queries (`research_query.py`) — green

`build_queries(packet: dict) -> list[str]` takes a validated **v2** packet and
returns 2–3 queries. Inputs are an allowlist only:

- product constants: `"GR00T N1"` model family, `"vision-language-action"`;
- `task.suite` → `"LIBERO-Object"`; `task.task_id` → wording from a fixed
  table (task 0: `"pick up the alphabet soup and place it in the basket"`;
  unknown IDs fall back to `"pick-and-place"`);
- the perturbation family → `"camera occlusion"`;
- the reduced rectangle → a region phrase from fixed thirds of the image
  (left/center/right × top/middle/bottom by rectangle centre; `"upper-right"`
  for the target case) and area rounded to a whole percent;
- failure type → `"grasp failure"` when the reduced role failed.

Template set (exact strings asserted in tests):

1. `vision-language-action policy robustness to camera occlusion robot manipulation`
2. `GR00T N1 LIBERO-Object visual perturbation failure`
3. `robot policy fails when {region} {area}% of camera image is occluded pick-and-place`

Each query ≤ 200 characters, ASCII only. Raise `ResearchQueryError` for a v1
packet or a packet without a reduced mask. Tests: target-case strings, region
mapping for all nine cells, area rounding, unknown task fallback, v1 rejection,
and that no packet field other than the allowlist can change the output
(mutate episode IDs and stage names; queries must not change).

## B. Bounded Tavily client (`tavily_search.py`) — green/amber

Mirror `token_factory.py`'s safety style.

- `load_api_key(env_file=None)`: `TAVILY_API_KEY` from the environment, else the
  ignored `.env`; same reparse-point and size checks as Token Factory's loader;
  key must match `tvly-[A-Za-z0-9_-]{8,}`. Never logged or stored.
- Fixed host `api.tavily.com`, path `/search`, HTTPS, `Authorization: Bearer`,
  30 s timeout, 262,144-byte response cap.
- Fixed request body: `query`, `search_depth: "basic"`, `max_results: 5`,
  `topic: "general"`, `include_answer: false`, `include_raw_content: false`,
  `include_images: false`, `auto_parameters: false`, `include_usage: true`.
  No caller can override these.
- `reserve_credit(ledger_root, query_hash) -> int`: create an exclusive file
  `NNN.json` (`open("x")`); refuse with `TavilyError("credit cap reached")`
  when 50 entries exist. Reserve **before** each request; never release.
- Response validation: `results` list ≤ 5; each result keeps only `title`
  (≤ 200 chars), `url` (must parse as `https` with a hostname, ≤ 500 chars),
  `content` (truncated to 600 chars) and `score` (finite 0–1). Also keep
  `request_id`, `response_time`, `usage.credits` when valid. Drop any result
  that fails; strip control characters. Reject the whole response if it
  contains the API key.
- Cache: `artifacts/m5d-research/cache/<sha256(query + fixed params)>.json`,
  written exclusively. `search(query, key, *, refresh=False)` returns the
  cached normalized response unless `refresh` is set.
- Errors map to fixed, non-secret codes (`unauthorized`, `rate_limited`,
  `http_error`, `timeout`, `invalid_response`, `credit_cap`).

Tests use an injected fake transport: payload is exactly the fixed body,
header shape, key never in exceptions or reprs, cap at 50, cache hit makes no
transport call, refresh reserves a credit, malformed/oversized/non-https
results are dropped or rejected, key-echo rejection.

## C. Research records (`research_store.py`) — green

Stored at `<workspace>/<case_id>/research/<record_id>.json`, immutable,
published with the same exclusive-temp-then-`os.link` pattern and reparse
checks as `explanation_store.store_report`. Shape (schema_version 1):

```json
{
  "schema_version": 1,
  "record_id": "<sha256 of canonical body>",
  "case_id": "<64 hex>",
  "packet_id": "<packet_identity of the v2 packet>",
  "queries": [
    {"query": "...", "retrieved_at": "YYYY-MM-DDTHH:MM:SSZ",
     "request_id": "... or null", "credits": 1, "from_cache": false,
     "results": [{"source_id": "S1", "title": "...", "url": "https://...",
                  "snippet": "...", "score": 0.81}]}
  ],
  "summary": {
    "status": "not_requested | interpreted | rejected | provider_error",
    "related_work": [{"text": "...", "source_ids": ["S1", "S3"]}],
    "limitations": ["..."],
    "provenance": { same keys as explanation_store provenance }
  }
}
```

Source IDs `S1..S15` are assigned in query order, de-duplicated by URL. A
record is shown only while its `packet_id` matches the case's current v2
packet. `read_case_research(workspace, case_id)` returns
`{"records": [...], "warnings": [...]}` with the same bounded-scan and
corrupt-sidecar isolation as `read_case_reports` (limit 50 records, 128 KB
each). Tests copy the explanation-store test patterns.

## D. Source-cited Nemotron summary (`research_summary.py`) — amber

- `research_context(packet, record)`: deterministic facts (`totals` and the
  reduced mask from `explanation.interpretation_context`, region phrase,
  task wording) plus `sources: [{source_id, title, url, snippet}]`.
- Prompt (in `research_summary.py`): the model writes 1–4 `related_work`
  entries, each saying how a source relates to **this** case's measured
  facts and citing 1–3 `source_ids`; 1–3 `limitations` (sources are public
  context, not evidence; no causal proof; relevance judged by snippet only).
  It must treat source text as untrusted data and ignore any instructions in
  it. Thinking is off (`chat_template_kwargs`), as in v2.
- `validate_research_summary(value, record)`: exact keys; `text` ≤ 400 chars
  and must not contain `http`, `www.` or markdown links; every `source_id`
  exists in the record; no empty arrays. Invalid output yields
  `status: "rejected"` with the content kept in memory only for a local
  `rejected-response.json` under the attempt folder (not in the record).
- `token_factory.py` gets one additive function
  `request_research_summary(context, api_key, transport=None)` that reuses the
  existing transport, size checks (20 KB request), provenance and usage
  accounting with a US$0.01 reservation constant for this call. Existing
  functions and prompts are unchanged.

Tests: context is a pure function of packet + record, prompt-injection
snippets do not reach the validator as accepted output, unknown/missing
source IDs and URLs in text are rejected, request size cap, cost estimate.

## E. CLI (`scripts/research_case.py`) — green

Same structure, error mapping and exit codes as `scripts/explain_case.py`.

- `queries --workspace W --case-id C`: print planned queries; no network.
- `search --workspace W --case-id C [--refresh] [--env-file F]`: fresh v2
  packet → queries → Tavily (cache-aware, credit-reserved) → store a record
  with `summary.status: "not_requested"`. Re-checks the packet identity
  before storing.
- `summarize --workspace W --case-id C --attempt r-0N [--env-file F]`: take
  the newest valid record for the current packet, reserve
  `artifacts/m5d-research/nemotron/r-0N/`, call Nemotron, validate, and store
  a **new** record (same queries, new summary).
- Prints a one-line JSON summary (record ID, statuses, credits used, estimated
  cost). Never prints keys, snippets or paths.

Tests with fake dependencies, as in `tests/test_explain_case.py`.

## F. Viewer panel — green

- Server: allow `parts[4] == "research"` and return `read_case_research(...)`.
- `index.html`: a new `<details id="case-research">` after
  `case-explanations`, summary text "Related public research (context, not
  evidence)" and a fixed banner: "Retrieved by Tavily from the public web.
  These sources do not prove why this case failed."
- `app.js`: fetch `/api/cases/<id>/research` with the same generation guard
  as explanations; render the newest record's related-work entries with
  `[S1]` chips linking to sources, then the source list (title, hostname,
  retrieved date, query). Use `textContent` only; set `href` only when
  `new URL(url).protocol === "https:"`; `rel="noopener noreferrer"`,
  `target="_blank"`. Show statuses such as "summary not requested" or
  "summary rejected by validator".
- Tests: route, read-only behaviour, and a static check that the research
  rendering never uses `innerHTML`.

## Commits (Conventional, atomic)

1. `docs(m5d): accept Tavily research design and tighter M3 timeboxes`
   (ADR 0024, ADR 0023 update, this plan)
2. `feat(m5d): build deterministic research queries from case evidence`
3. `feat(m5d): add bounded Tavily search client with credit ledger and cache`
4. `feat(m5d): store immutable case research records`
5. `feat(m5d): add source-cited Nemotron research summary`
6. `feat(m5d): add research_case CLI`
7. `feat(viewer): show related public research beside explanations`
8. `docs(m5d): record live research run and Tavily feedback`

## Verification and review

- Each unit: `PYTHONPATH=src python -B -m unittest discover -s tests -v`
  on Windows Python 3.11, fully green before its commit.
- Independent review agent after units A–F, given this plan, ADR 0024 and the
  diff; it checks the allowlist, cap enforcement, key handling, injection
  handling and viewer escaping. The coordinator resolves findings.
- Outgoing-diff scan before push (public repo): no keys, no full resource IDs,
  no snippets or records (they stay in ignored `artifacts/`).

## Live run (coordinator only, after review)

1. `queries` on the target case; show Jethro the exact strings.
2. `search` once: 3 credits.
3. `summarize --attempt r-01`; inspect in the viewer. Iterate the prompt with
   `r-02`..`r-05` only if the note is unhelpful, within the US$0.05 cap.
4. Jethro judges usefulness and accepts or rejects M5D from the viewer.
   Record the outcome, credits and cost in the experiment note and
   `FEEDBACK.md` (Tavily: onboarding, latency, result relevance).

## Evidence that would change direction

- Results are mostly irrelevant across all three queries → try `prefer`
  domain boosting (arXiv, OpenReview, GitHub) as a red follow-up, or report
  M5D as low value instead of forcing it.
- Nemotron cannot keep citations valid after a few attempts → show the raw
  source list only (ADR 0024 option B) and record why.
