# ADR 0007: Separate two-episode M3 pilot

**Status:** Accepted for implementation planning

**Date:** 2026-09-29

## Context

The M3 benchmark launches a fixed 16-case workload. A first live compatibility check should establish whether two evaluator sessions can overlap safely without paying for the full 1/2/4-worker comparison or contaminating its throughput report.

## Decision

Add a separately labeled two-case pilot: one nominal and one accepted M4 reduced-mask replay, using two workers and the existing scheduler, evidence validation, attempt ledger, and containment. Keep its session separate from benchmark sessions and make the comparison reporter reject pilot summaries. The pilot does not resume or authorize additional retries. This decision does not authorize a paid run.

## Alternatives and consequences

Running the full 16-case workload first would cost more before compatibility is established. A bespoke pilot evaluator would duplicate safety logic. The shared-core approach tests session overlap, but not guaranteed parallel GPU inference. A complete pilot is only a prerequisite to considering the fixed comparison, not proof of speedup.

See `docs/superpowers/specs/2026-09-29-m3-two-episode-pilot-design.md` and `docs/superpowers/plans/2026-09-29-m3-two-episode-pilot.md`.
