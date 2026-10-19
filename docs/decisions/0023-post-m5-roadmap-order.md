# ADR 0023: Post-M5 roadmap order

**Status:** Order accepted by the project owner on October 11, 2026. Timeboxes accepted
the same day in a tighter form (see Guards).

## Decision (accepted)

1. **M5D** — Tavily public-research context beside the Nemotron interpretation.
2. **M3 batched inference** — a learning-focused stretch; the project owner wants to learn
   what he can from it.
3. If batching gets stuck: **M3 Serverless portfolio** (several diagnosis jobs
   sharing one GPU inside a Serverless Job; the old VM launcher is obsolete).
4. If that also gets stuck: move on to **M6** (LIBERO-Plus perturbation family,
   further tasks/suites).
5. **M7** submission afterwards. Deadline: October 30, 10:00 PT
   (October 31, 01:00 Singapore); target October 29.

## Guards (accepted October 11, tighter than first proposed)

The project owner chose a tighter M3 window than the first proposal (4 and 3 days).

- M5D: about 1.5 days (October 12–13). Design in ADR 0024.
- Batched inference: up to 3 working days. "Stuck" = GR00T cannot produce
  per-episode-equivalent actions in batch mode, or a working adapter shows no
  measurable throughput gain in a matched comparison.
- Portfolio fallback: up to 2 working days.
- M7 starts no later than October 23 regardless of where M3/M6 stand.

## Consequences

M5D comes first because it extends the just-completed explanation path and has
a defined prize rule (functional runtime Tavily use). Each stage still needs its
own design checkpoint, provider/spend caps and plan before paid work.

## Amendment (October 13)

M3 batching succeeded (ADR 0025), so the portfolio fallback is dropped. M6 ran
as ADR 0026. M7 is split into M7a product consolidation and M7b submission
(ADR 0027).
