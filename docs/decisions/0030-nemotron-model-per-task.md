# ADR 0030: Nemotron model per task, chosen by measurement

**Status:** Accepted by Jethro on October 13–14, 2026.

## Problem

Faultline calls Nemotron on Nebius Token Factory for four jobs. Nano was the
default everywhere until the first scenario explanation (M7 mode 1) misread
its evidence. Jethro asked to choose each model by measurement rather than
assumption: the smallest model that states the known facts correctly and
passes Faultline's output checks.

## Method

For each task, one call per model (Nemotron 3 Nano, Super and Ultra) on the
identical stored input, temperature 0, scored against facts the input
supports and against the existing validators. Raw outputs are kept in
ignored `artifacts/m7-model-comparison/` and
`artifacts/m7-scenario-case-t0s14/explainer-comparison/`. One call per model
is a sensible basis for a choice, not a proof; outputs vary between calls.

## Results and decision

| Task | Nano | Super | Ultra | Decision |
| --- | --- | --- | --- | --- |
| Scenario hypothesis (before reruns) | - | fallback | used | **Ultra** (ADR 0028) |
| Scenario explanation | called an applied entity "reverted"; repeated tested reruns | inverted a correct prediction; failed format | all checked facts right | **Ultra** |
| Occlusion explanation (M4 case) | cited a non-existent evidence id (rejected) | valid; one garbled sentence | valid; named the critical x 0.625–0.75 column | **Ultra** |
| Research summary (M5D) | valid, correct, one source only | rejected by the causation-wording filter | richer but over the 400-character limit | **Nano** (only accepted output; context, not evidence) |

Two input fixes for scenario explanations mattered as much as the model: one
plain sentence per rerun and the list of shrink sizes already tested.

## Consequences

- Case explanations (scenario and occlusion) use Ultra; stored historical
  Nano explanations remain valid and are shown with their real model.
- Ultra's price is not pinned in code, so explanation cost estimates are left
  empty and reconciled with billing; each call is well under one cent.
- Research summaries stay on Nano. Revisit only with a validator change (for
  example a 600-character limit) and a fresh comparison.
- The instruction-paraphrase family (breadth pack) gets the same comparison
  before its model is fixed.
