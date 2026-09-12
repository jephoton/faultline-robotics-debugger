# ADR 0002: Use an immutable, JSON-compatible attempt record at the domain boundary

**Status:** accepted on September 12, 2026

## Context

An evaluation run can generate several kinds of data:

- the harness's raw SQLite recording and videos;
- our own perturbation parameters and reduction lineage; and
- an engineer-facing replay report.

Coupling all of those directly to the upstream SQLite schema would make the
debugger depend on an implementation detail of one evaluator. Storing only a
summary would lose the information required to replay a case.

## Decision

`src/robot_debug/records.py` defines `AttemptRecord`: an immutable,
JSON-compatible description of one attempted episode. It contains the identity
of the experiment/scenario/attempt, task and instruction, seeds and initial
state index, outcome category, configuration, perturbation, revisions, timing,
artifact locations, and an optional failure detail.

`AttemptLedger` is intentionally an in-memory uniqueness guard for now. It
refuses duplicate attempt IDs so a retry cannot silently replace earlier
evidence. Persistence remains an adapter concern: the future runner may write
JSONL beside upstream SQLite recordings, but the core record does not choose a
database.

## Why this is a useful boundary

The record is small enough to unit-test on a laptop and portable enough for a
cloud worker, a reducer, and a static report to use the same vocabulary. It
also makes outcome categories explicit: infrastructure failure and invalid
scenarios are not policy failures.

## Consequences

This does not yet launch an evaluator, persist records, or decide the final
artifact layout. Those choices wait for the first successful cloud baseline.
The module's serialization and duplicate-protection behavior are covered by
standard-library unit tests.
