# M3 Durable Attempt Ownership Design

**Status:** Proposed implementation of Jethro's accepted per-episode state-machine approach; no cloud spending authorized

**Parent:** [M3 evaluator containment](2026-09-28-m3-evaluator-containment-design.md)

## Problem

The M3 scheduler currently tracks the same episode in `active`,
`uncertain_active`, `submitting_case_ids`, and `session_summary.json` lists.
Tests reproduced an interrupt after a Future was submitted but before its
registration, and review found another gap between removing a finished Future
and saving its result. These are not independent bugs: multiple ownership
representations must be updated in an order Python signals can interrupt.
The completed process-group containment fix remains unchanged.

## Single source of truth

Use one durable per-`case_id` attempt ledger for the 16 immutable manifest
items. Each item has exactly one state and, when known, one terminal result:

| State | Meaning | May be counted valid? |
| --- | --- | --- |
| `prepared` | Manifest item has no launch intent | No |
| `submitting_unknown` | Intent saved before calling `executor.submit`; a worker may or may not have been enqueued | No |
| `active` | A Future was obtained and is held in the runtime Future map | No |
| `completing_pending` | Finished Future's result has been captured in the ledger, but terminal accounting is not yet durably acknowledged | No |
| `terminal` | Exactly one durable valid, invalid-evidence, or infrastructure result exists | Only if normal completion before stop |

The ledger's serialized `attempt_records` map is authoritative and includes
the captured result for `completing_pending` as well as `terminal` entries.
An `attempt_states` map of short state names is only a derived audit view;
persisting that map alone would lose a pending result. The existing summary fields
(`results`, `valid_count`, `in_flight_ids`, `stop_reason`) are derived from it
on every atomic save, preserving the reporter's contract; they must not be
independently mutated. A runtime `Future -> case_id` map is an index, not a
second ownership authority. Each transition must be idempotent by `case_id`
and reject illegal backward transitions or duplicate terminal records.

## Transition and interruption rules

1. Before calling `submit`, persist `submitting_unknown`. An interruption
   before or within `submit` cannot be proven unlaunched, so it remains
   uncertain unless the returned Future is known and cancelled before start.
   This conservatism is intentional; no automatic retry or resume follows.
2. After obtaining a Future, register it in the runtime map, then persist
   `active`. If interrupted between those operations, the durable state stays
   `submitting_unknown`; finalization uses the known Future when available,
   but never deletes the case from the summary merely because registration
   was incomplete.
3. For a completed Future, capture its result into `completing_pending` and
   persist that state **before** removing the Future from the runtime map.
   Then persist `terminal` and remove the Future index. Repeated finalization
   must not duplicate a result. If a save is interrupted, the previous
   durable state remains uncertain or the pending result remains available.
4. A stop request closes the launch gate first. Futures already active may
   finish, but a result first accounted after interruption is not counted as
   a valid benchmark completion; preserve its observed evidence as an
   infrastructure/interrupt record. Unknown submission with no Future
   remains `in_flight_ids` and `interrupted_cleanup_risk`.
5. If every known Future is terminal/cancelled, join executor threads. If
   ownership remains unknown after the bounded observation window, save an
   explicit incomplete summary and use non-blocking shutdown without claiming
   that this bounds Python interpreter lifetime. The independent VM-stop
   watchdog remains mandatory for any later live run.

## Interfaces and scope

Implement a small project-owned `AttemptLedger` in
`src/robot_debug/attempt_ledger.py`, using plain JSON-compatible records and
pure transition validation. The runner in `scripts/run_parallel_eval.py` owns
atomic persistence through the existing `base._atomic_write_json` helper and
keeps the current CLI/report format. Add `attempt_states` to the mode summary
for audit. Do not alter manifest identity, 1/2/4-worker topology, model,
simulator, Docker process-group cleanup, viewer, or cloud provisioning.

Keep the already-written but uncommitted Task 3 regression tests as input;
review and revise them rather than discarding them. Local fake-evaluator and
real POSIX signal tests must prove all boundaries, including interrupted
summary writes and the submit/enqueue ambiguity. A complete normal 1/2/4
fake run must still be reportable, while any interrupted/unknown mode must
fail the comparison reporter's completeness check.

## Acceptance and residual boundary

- Deterministic red/green tests cover interruption before submit, inside an
  enqueue-then-raise submit, after Future return, after registration, during
  completion handoff, and during atomic summary write.
- No attempted case disappears from both terminal results and `in_flight_ids`;
  unlaunched `prepared` cases remain only in the planned manifest. No case
  appears twice or gains a fabricated successful outcome; valid counts equal
  normal terminal-valid records only.
- Tests deliver a real POSIX SIGTERM to the runner with an active fake child,
  and the delayed-descendant process-group regression stays green. Full local
  Windows and WSL suites pass, followed by independent spec and quality review.
- Local tests do not prove Docker-daemon or Nebius behavior. A bounded live
  pilot, independent VM-stop watchdog, and calculated run-specific cap require
  separate preflight and Jethro's approval.
