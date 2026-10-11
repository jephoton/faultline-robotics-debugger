# M5D: Tavily research context (October 11, 2026)

Design: ADR 0024. Plan: `docs/superpowers/plans/2026-10-11-m5d-tavily-research.md`.
Case: certified M4 case `52d89d40…`, reduced mask `(0.625, 0, 0.375, 0.375)`,
upper-right, about 14% of the agent-view image.

## Run

| Step | Result | Spend |
| --- | --- | --- |
| `queries` (offline) | 3 fixed queries from allowlisted descriptors | none |
| `search` | 15 distinct sources, record stored, `not_requested` | 3 Tavily credits (of 50 cap) |
| `summarize r-01` | interpreted, but S2 misattributed (described S4's sensor-attack paper) and cross-benchmark success-rate comparisons | US$0.00022 |
| `summarize r-02` (prompt: one main source per entry, own-snippet paraphrase, follow-up experiment) | rejected by validator: "causes" while paraphrasing a source; one follow-up was the already-measured mask | US$0.00023 |
| `summarize r-03` (prompt: new follow-ups only; banned words apply to paraphrase) | interpreted; two entries (S2, S11) | US$0.00021 |

Total: 3 Tavily credits, about US$0.0007 Nemotron (5 attempts reserved at
US$0.01 each; 2 unused). No GPU or AI Cloud spend.

## Observations

- Query 1 (generic occlusion robustness) was the most useful: S2 LIBERO-Occ
  studies scene-induced occlusion that hides task-relevant evidence, close to
  this case. Query 2 found a GR00T LIBERO GitHub issue and benchmark papers.
  Query 3 (literal "upper-right 14%") drifted to industrial bin-picking.
- r-03's S11 entry is muddled. S11's snippet reports that π0 relied mainly on
  its wrist camera, so side-view occlusion barely mattered. The useful
  hypothesis it suggests for us, which the model missed: check how much GR00T
  relies on the wrist versus agent-view camera, since our mask occludes only
  the agent view.
- The validator worked as intended: it blocked causal wording, and
  misattribution is still only catchable by a human reading the snippets.

## Status

Awaiting Jethro's usefulness judgement in the viewer (panel "Related public
research (context, not evidence)"). Records and snippets stay in ignored
`artifacts/`.
