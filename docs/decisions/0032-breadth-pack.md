# ADR 0032: Breadth pack — suites, image catalog, language and scene families

**Status:** Accepted by Jethro on October 15, 2026 (M7a step 3 checkpoint).

## Problem

Faultline covered one suite per run shape (LIBERO-Object for audits,
LIBERO-10 for scenario reduction) and four image-space families. ADR 0027
asked for breadth across suites and across the visual, language and
physical-scene layers, without LIBERO-Plus.

## Decision

1. **Suites:** add LIBERO-Spatial and LIBERO-Goal
   (`nvidia/gr00t17-lerobot-libero_{spatial,goal}-640`, both public, pinned
   revisions), so all four LIBERO suites run in every mode.
2. **Image catalog (mode 2):** four more single-strength families on both
   cameras, deterministic and replayable like M6: JPEG compression, colour
   cast (white balance), motion blur, and salt-and-pepper (dead pixels).
3. **Instruction paraphrases — find, then reduce (option B):** Nemotron
   writes about ten varied paraphrases of the task instruction; a screen finds
   one that fails at least 4 of 5; delta debugging over the word edits between
   the original and that paraphrase (the mode 1 reducer idea applied to
   language) finds the minimal wording change that still fails. Which Nemotron
   model writes paraphrases is decided by a measured comparison first (ADR
   0030 rule).
4. **Scene families (simulator level, reducible):** camera viewpoint (move and
   tilt the agent-view camera by a shrinkable offset) and lighting (scale the
   scene lights), searched with the existing sweep-then-bisect threshold
   engine. Bounds are calibrated on CPU before any paid run.

**Spend cap:** US$6.00 for the breadth pack's live runs (raised from US$4.00 by
Jethro on October 15). Verification order,
cutting from the end if the ledger runs low: suite smokes -> catalog audit ->
paraphrase screen and reduction -> viewpoint and lighting audit.

## Consequences

- All new families are spec options for `faultline diagnose` (mode 2) and
  register cases like the others; paraphrase runs get their own mode.
- Every new family records exactly what the policy saw (parameters, seeds,
  the exact instruction text) so a case replays bit-for-bit where the
  simulator allows.
- Claims stay per family, task and seed; image families approximate camera
  effects, they do not simulate them.
