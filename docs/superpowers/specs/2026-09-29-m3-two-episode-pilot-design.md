# M3 two-episode concurrency pilot design

**Status:** accepted for implementation planning on September 29, 2026. **No Nebius start or spending is authorized by this document.**

## Purpose and workload

Before measuring the frozen 16-case M3 workload, run a separately labeled, two-case systems pilot on the accepted single-L40S VM and shared GR00T server. Its cases are the first nominal and reduced-mask entries from `build_manifest(1)`: task 0, episode 0, seed/env-seed 7, with the M4 accepted rectangle `(x=0.625, y=0, width=0.375, height=0.375)` for the mask. Use `workers=2` so both evaluator processes may overlap; the server's default inference path can still serialize model calls. This checks request/session isolation and evidence quality, not speedup or new failure discovery.

## Boundary and implementation shape

Add an explicit `pilot` CLI subcommand that creates `m3-pilot-workers-2/` under a new ignored results root. The normal `run` path remains pinned to the 16-case manifest, `m3-workers-{1,2,4}` directories, and unchanged reporter contract. Reuse the existing scheduler, evaluator process-group containment, exact launch-identity sidecars, attempt ledger, config generator, and evidence validator through an internal workload/session parameter; do not copy their safety logic into a second launcher. A pilot summary carries `purpose: "pilot"`, its own two-case manifest and hash, a complete/partial stop reason, and the same per-case result/ownership evidence. The M3 comparison reporter must reject pilot summaries even if they contain two valid cases. Pilot resume is disabled: after interruption or uncertainty, preserve artifacts and require a new, explicitly budgeted pilot session rather than retrying a possibly launched case.

The pilot accepts only the two known case IDs and exactly two workers. It does not accept arbitrary task IDs, masks, seeds, episode indices, or worker counts. This is a bounded compatibility test, not a general workload editor.

## Success, failure, and evidence

The pilot is usable only when both cases produce valid task-0/episode-0 aggregates, traces and MP4s; the nominal outcome is success and the known reduced mask is a policy failure. Outcome drift, missing media, server instability, timeout, incomplete cleanup, or ambiguous attempt ownership stops progression to the full modes. Record exact manifest/hash, per-case configs/outputs/launch identity, summary, UTC VM clock, and any server/host telemetry. The result is not itself a throughput comparison and cannot enter the 1/2/4 reporter. A successful pilot permits a separate remaining-budget decision; it does not automatically start the 48 comparison episodes.

## Local validation

Fake-evaluator tests must show exactly two submitted cases, at most two active, distinct config/output/launch paths, the same task/seed/rectangle as M4, valid and invalid evidence handling, SIGTERM/timeout cleanup, and no third launch. Run a real POSIX signal test in WSL. Reporter tests must reject the pilot summary by purpose and frozen-manifest mismatch. The normal 16-case manifest hash and all prior tests must remain unchanged. No Docker or Nebius call is needed for these tests.

## Decision boundary

Accepted: a dedicated pilot session sharing the scheduler/evidence/containment core with the full runner. Not accepted: a paid cap, a different model/benchmark/failure definition, or general user-supplied pilot cases. A separate [watchdog design](2026-09-29-m3-exact-vm-watchdog-design.md) governs the paid-run safety boundary.
