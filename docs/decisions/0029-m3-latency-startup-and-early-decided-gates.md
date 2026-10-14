# ADR 0029: M3 latency — startup cut and early-decided gates

**Status:** Accepted by Jethro on October 13, 2026. Labelled M3 (throughput
and latency) although delivered inside M7 work; commits use the `m3` scope.

## Problem

Batching (ADR 0025) gave +18% on the robot-work part of a Job, but users wait
mostly for startup. Across every Serverless Job so far (one L40S, preset
`1gpu-16vcpu-64gb`), about 12 minutes of each 13 to 22 minute Job passed
before any episode ran: roughly 5 minutes from submission to container start
(mostly the 21.7 GB image pull), 5.6 to 6.6 minutes downloading the pinned
GR00T weights from Hugging Face, and about a minute loading and warming the
server. Robot work was 8% (pilot) to about 45% (M3 measurement) of wall time.
Within the work part, the batched GPU is busy only 61 to 73% at 12 workers:
the 12 simulators on 16 vCPUs are now the bottleneck, so further batching
has a low ceiling.

## Decision

- **B. Early-decided gates and parallel candidates (in mode 1 now).** A
  4-of-5 repeatability gate is decided as soon as 4 failures or 2 successes
  are observed (the reference's 5-of-5 pass gate at its first failure).
  Attempts of a decided candidate that have not started are skipped and
  recorded as `decided_skipped`; started attempts finish and are recorded but
  cannot change the decision, so every decision equals the one all five
  attempts would give. Freed workers take queued attempts of other
  independent candidates (a delta-debugging round's candidates, or two
  bisection points at once). The existing pool's cancellation semantics are
  unchanged (no in-flight episode is killed). Applied in the mode 1 reducer
  first; the threshold search may adopt it later by decision.
- **A. Cut startup (with `faultline diagnose`, M7 step 4).** Measure, then
  serve the pinned weights from in-region Nebius storage instead of Hugging
  Face, and slim the image. Target startup about 5 to 6 minutes instead of
  about 12 (a replay about 13 to 6 minutes, an audit about 20 to 13), to be
  confirmed by measurement before any claim.
- **D. Warm Serverless Endpoint: stretch goal**, for Jethro to try closer to
  the judging period, under the concerns in ADR 0027 (idle billing, auth,
  spend cap).
- **C. More hardware** (bigger preset or two GPUs): not planned; optional HPC
  stretch per ADR 0019.

## What would change direction

- In-region storage is not materially faster than Hugging Face: consider
  baking weights into the image (larger pull) and compare.
- Early stopping saves little because most candidates are decided only at the
  fifth attempt: report it and keep the simpler path.

## Amendment (October 14)

B is implemented and measured: early-decided gates skipped 13 screen
attempts and 31 and 33 attempts in the two LIBERO-10 reduction Jobs
(`docs/experiments/m7-scenario-reduction.md`). A (startup cut) is skipped for
now by Jethro's choice at the `faultline diagnose` checkpoint (ADR 0031).

