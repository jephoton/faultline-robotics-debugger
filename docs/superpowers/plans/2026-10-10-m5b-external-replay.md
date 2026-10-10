# M5B External Replay and Certified-Case Re-run Plan

**Goal:** Finish M5 by (1) starting fresh GR00T episodes from the accepted
external LIBERO demo state (ADR 0016) and (2) re-running M4's certified reduced
case in a fresh Serverless session, which exercises the saved replay recipe.

**Status:** proposed October 10. Local implementation is within ADR 0016's
approval. The episode set and the paid Job need Jethro's explicit approval.

## Facts this plan builds on

- The kernel `src/robot_debug/external_reset.py` (reviewed) reads
  `demo_0`/state 0, resolves assets by full path, restores XML and state,
  checks the state hash and settles ten steps. `restoration_verified` stays false
  until a live run.
- The sample is the same task as the M4 case (alphabet soup, libero-object
  task 0). Its extracted candidate (state + scene XML + hashes) is **68 KB**
  JSON; h5py 3.11 is in the image's simulator environment.
- Upstream `LIBEROBenchmark.reset()` creates the env, calls `set_init_state`,
  then ten dummy steps. Our `DiagnosticLIBEROBenchmark` can override `reset()`.
- M4's certified reduced rectangle is `(0.625, 0, 0.375, 0.375)`; the October 10
  pilot used `(0.5, 0, 0.375, 0.375)` by design error.
- Dataset redistribution stays unapproved (CC BY 4.0 vs Apache-2.0 conflict):
  the candidate never enters Git, the image or public artifacts.

## Proposed episode set (one Serverless Job, red: needs approval)

| # | Start state | Mask | Purpose |
| --- | --- | --- | --- |
| 1 | benchmark init 0, seed 7 | `(0.625, 0, 0.375, 0.375)` | exercised replay of the certified M4 case |
| 2 | external demo_0 state 0 | none | external scenario enters the loop: nominal |
| 3 | external demo_0 state 0 | `(0.625, 0, 0.375, 0.375)` | does the certified failure transfer to the external start? |

About 2–3 minutes of episodes plus ~9 minutes of Job overhead: ≈US$0.40.
Proposed cap **US$1.00** for one Job (no automatic retry).

## Design (green/amber within ADR 0016)

- **Benchmark hook:** `DiagnosticLIBEROBenchmark(external_reset={"candidate":
  PATH})`. Its `reset()` builds the env exactly as upstream, then calls
  `resolve_external_assets` against the installed LIBERO/robosuite asset roots
  and `restore_external_reset`, records the frame, and writes the returned
  `reset_metadata` (hashes, pre/post-settle state) to a sidecar beside the
  episode outputs. No upstream file edits.
- **Candidate transport:** extract locally inside the image (h5py), gzip and
  base64 it into a dedicated injected file (expected well under the 64 KiB
  inject limit); the entrypoint decodes it to the run's private work directory
  and verifies `source_sha256`/`state_sha256` before use.
- **Workload mode `replay`:** runs the three stages above serially through the
  existing contained evaluator, deadline, export and evidence validation.
  Stage configs reuse `run_failure_search._write_config` with an optional
  `external_reset` parameter.
- **Viewer/case:** recovered episodes appear in the viewer like the pilot pair.
  Recording an "exercised replay: verified" capability for the M4 case is a
  follow-up decision after seeing the result, not automatic.

## Tests and commits

Fake-env unit tests for the reset override (restore called, upstream init state
not used, sidecar written, failures fail closed); candidate encode/decode and
hash verification; workload `replay` mode with injected fixtures; prepare-script
second injected file. Then image rebuild, in-image test of a real
`OffScreenRenderEnv` restore on CPU if rendering allows (otherwise deferred to
the Job), push, dry-run. Commits per coherent unit.

## Acceptance

All three stages produce videos, traces and aggregates recovered and verified
against the manifest; stage 2/3 sidecars show the expected source and state
hashes and a successful settle. Outcomes are reported as observed, whatever
they are; one episode per condition is evidence of the pipeline, not a
robustness claim.
