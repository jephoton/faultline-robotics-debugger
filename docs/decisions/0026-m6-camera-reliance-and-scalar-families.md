# ADR 0026: M6 camera reliance and scalar image families

**Status:** Accepted by Jethro on October 12, 2026. **Outcome (October 13):**
wrist + agent-view masking stops the grasp; blur fails reliably from sigma
3.9 px, noise from sigma 95; darkening and contrast never fail in range. See
`docs/experiments/m6-camera-and-scalar-families.md`.

## Problem

M5D surfaced a lead: GR00T fails when only its third-person (agent-view)
camera is partly occluded, although its wrist camera still sees. Faultline's
search and reduction also only handle one perturbation family (opaque
rectangles). M6 tests the lead and shows the find → confirm → reduce loop on
perturbations defined by a single strength number.

## Decisions

1. **Wrist-camera conditions** (each with nominal controls):
   - the certified reduced agent-view mask `(0.625, 0, 0.375, 0.375)` **plus**
     the whole wrist image blacked out;
   - the same rectangle on the **wrist image only**, agent view clean.
   Not chosen: wrist black alone, and a lift-phase-only mask (would add a time
   parameter).
2. **Four scalar image families**, applied to **both cameras**: darkening
   (brightness ×1.0 → ×0.05), Gaussian sensor noise (σ 0 → 100 of 255,
   seeded per episode, step and camera so replays are exact), Gaussian blur
   (σ 0 → 8 px) and contrast reduction (×1.0 → ×0.1). Each uses a normalised
   severity s ∈ [0, 1] mapped to its physical parameter.
3. **One generic algorithm for all scalar families: coarse sweep, then
   bisection.** Sweep s ∈ {0.2, 0.4, 0.6, 0.8, 1.0} in increasing order; a
   level is a reproducible failure when at least 4 of 5 attempts are policy
   failures while nominal controls succeed (the existing gate). Then bisect
   for 4 steps between the last non-reproducible level and the first
   reproducible one, and report the smallest reproducibly failing severity
   (resolution 0.0125). If no level reproduces, report "no reproducible
   failure up to s = 1.0"; that is a valid result.
4. **Execution:** reuse the M3 batched 12-worker setup. A smoke Job runs the
   wrist conditions plus one sweep level per family; a main Job runs the four
   families concurrently.
5. **Spend cap: US$3.00** for M6, after Jethro tops up, keeping about US$0.6
   for M7.

## Not chosen

LIBERO-Plus: it replaces the LIBERO package, needs extra assets, offers
predefined variants that a reducer cannot shrink, and states no licence.
Deferred; its assessment is recorded in the M6 experiment note.

## Claim boundary

Results are specific to GR00T N1.7 on LIBERO-Object task 0 with seed 7.
Thresholds are budget-local (5 attempts per level, 4 bisection steps) and
describe reliable failure, not the onset of any failure. Image-space
transforms approximate, not simulate, lighting and sensor effects.
