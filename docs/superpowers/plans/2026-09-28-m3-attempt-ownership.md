# M3 Durable Attempt Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every M3 episode's launch and completion status durable across interruption without losing, duplicating, or fabricating results.

**Architecture:** A small per-case `AttemptLedger` is the only ownership authority. The scheduler persists a conservative `submitting_unknown` state before enqueueing work, captures completion before releasing Future ownership, and derives legacy mode-summary fields from the ledger so the reporter contract remains unchanged.

**Tech Stack:** Python 3.11-compatible standard library, `unittest`, existing `base._atomic_write_json`, Windows Python 3.11, WSL Python 3.12 for real signals. No real Docker or Nebius.

---

## Scope and handoff

**Accepted design:** `docs/superpowers/specs/2026-09-28-m3-attempt-ownership-design.md`. **Existing isolated checkout:** `C:\Users\Jethro\.codex\worktrees\m3-parallel-replay\nebius-nvidia-hackathon`, branch `codex/m3-parallel-replay`. Keep `a360b28` and `8a6e1e5` as history; the worktree also has two uncommitted Task 3 files (`scripts/run_parallel_eval.py`, `tests/test_parallel_eval_driver.py`) with a stale-token fix and test. Preserve and incorporate them; do not reset or overwrite them. Do not change manifest, worker counts, model, process-group containment, reporter, viewer, or cloud topology.

| Task | Owner | Paths | Concurrency |
| --- | --- | --- | --- |
| Pure ledger | smaller implementation agent | new `src/robot_debug/attempt_ledger.py`, `tests/test_attempt_ledger.py` | First; no scheduler edits concurrently |
| Scheduler integration and red/green interruption tests | same implementation agent | `scripts/run_parallel_eval.py`, `tests/test_parallel_eval_driver.py` | After ledger API is frozen |
| POSIX signal and final review | independent reviewer read-only; coordinator integrates | `tests/test_m3_posix_lifecycle.py` only if needed; docs below | After implementation |
| Handoff and docs | coordinator | `docs/experiments/m3-parallel.md`, `docs/codex-handoff/STATE.md`, `RUNBOOK.md` | After review |

Green: pure ledger, tests, local refactor, docs. Amber: timeout/finalization bookkeeping inside approved M3 design; explain at checkpoint. Red: changing workload, failure semantics, cloud architecture, spending cap, or public claims—stop for Jethro. No paid run is authorized. One implementation agent edits the two coupled code areas sequentially; reviewer does not edit them. Coordinator owns Git integration and any later Nebius lifecycle.

## Task 1: Pure ledger and derived summary

**Files:** Create `src/robot_debug/attempt_ledger.py`, `tests/test_attempt_ledger.py`.

- [ ] **Step 1: Write red tests for legal and illegal transitions.** Construct a two-case ledger (`nominal-01`, `mask-01`) and assert `prepared → submitting_unknown → active → completing_pending → terminal`; different duplicate terminal and backward transitions raise `ValueError`. `completing_pending` carries a copied result in the serialized `attempt_records` map, and repeating the exact same terminal result is idempotent. Round-trip the snapshot through JSON and restore the pending result. A `valid` terminal result increments derived `valid_count`; a nonterminal attempted case appears exactly once in derived `in_flight_ids`; `prepared` appears in neither. Test a late valid result after `stop_requested=True` becomes a nonvalid infrastructure record with its evidence metadata retained. Run `$env:PYTHONPATH='src'; & C:\Windows\py.exe -3.11 -m unittest tests.test_attempt_ledger -v`; expect missing module/failed assertions.
- [ ] **Step 2: Implement a small explicit API.** Use `AttemptLedger(case_ids)` with `begin_submit(case_id)`, `register_active(case_id)`, `capture_result(case_id, result, *, interrupted)`, `finish(case_id)`, `cancel_unstarted(case_id)`, `snapshot()`, and a minimal `from_snapshot(case_ids, snapshot)` restore method. Each transition validates the prior state and stores JSON-compatible dictionaries only; Futures stay outside. `snapshot()` returns full ordered `attempt_records` plus derived `attempt_states`, `results`, `valid_count`, and `in_flight_ids` from one map. Do not store duplicate mutable result lists. Example required invariant:

  ```python
  attempted = {case_id for case_id, attempt in ledger.attempts.items()
               if attempt["state"] != "prepared"}
  terminal = {record["case_id"] for record in ledger.snapshot()["results"]}
  in_flight = set(ledger.snapshot()["in_flight_ids"])
  assert attempted == terminal | in_flight
  assert not (terminal & in_flight)
  ```

- [ ] **Step 3: Verify/commit.** Run the focused suite and `git diff --check`; stage the new module/test only; commit `feat(hpc): model durable replay attempts`.

## Task 2: Integrate normal scheduling without changing outcomes

**Files:** Modify `scripts/run_parallel_eval.py`, `tests/test_parallel_eval_driver.py`.

- [ ] **Step 1: Add red normal-flow tests.** For 1/2/4 fake evaluators, assert all 16 entries become `terminal`, `in_flight_ids=[]`, `valid_count=16`, and the three existing mode summaries still pass `summarize_modes`. Assert a nonzero, invalid-evidence, or timeout attempt is terminal nonvalid while unlaunched cases remain `prepared`. Verify every atomic summary save contains exactly the ledger-derived `results`, `valid_count`, and `in_flight_ids`, not a separately mutated list.
- [ ] **Step 2: Replace parallel ownership collections.** Keep one `Future -> case_id` runtime index only. Before `executor.submit`, call `ledger.begin_submit(case_id)` and `save()`; after obtaining the Future, register it in the runtime index and call `ledger.register_active(case_id)` then `save()`. On completed Future, call `ledger.capture_result(case_id, record, interrupted=False)` and persist `completing_pending` before removing Future ownership; then `ledger.finish(case_id)` and persist `terminal`. Derive summary fields in `save()` from `ledger.snapshot()`. A failed summary write must leave the prior durable state conservative. Remove `uncertain_active` and `submitting_case_ids` only after the new tests cover their behavior.
- [ ] **Step 3: Verify/commit.** Run focused Windows tests, then full Windows suite: `$env:PYTHONPATH='src'; & C:\Windows\py.exe -3.11 -m unittest discover -s tests -q`. Run `git diff --check`; stage only runner/driver test and commit `refactor(hpc): derive replay summaries from attempt ledger`.

## Task 3: Interruption and save-boundary regressions

**Files:** Modify `scripts/run_parallel_eval.py`, `tests/test_parallel_eval_driver.py`; modify `tests/test_m3_posix_lifecycle.py` only for a focused real-signal assertion.

- [ ] **Step 1: Write red boundary tests before each fix.** Inject interruption (a) before submit, (b) after enqueue but before a Future returns, (c) after Future return but before active registration, (d) after active registration but before durable save, (e) after completion capture but before Future removal, and (f) during atomic summary write. Assert every attempted case remains terminal or in-flight, never both; no duplicate terminal record; a late result after interruption is not counted valid. Retain and revise the two currently uncommitted tests instead of deleting them. Ensure the enqueue-then-raise fake worker completes or is joined before TemporaryDirectory cleanup. For save interruption, patch `base._atomic_write_json` to raise once, then allow finalization to write the conservative summary.
- [ ] **Step 2: Implement one reconciliation path.** On `KeyboardInterrupt`, set the stop/launch gate, preserve ledger states, cancel Futures known not to have started, and observe known Futures for the bounded cleanup window. Persist captured records as nonvalid if first accounted after interruption. Unknown submissions without a returned Future stay `submitting_unknown` and `interrupted_cleanup_risk`; do not retry them. If all known Futures reach terminal/cancelled and no submission remains unknown, `executor.shutdown(wait=True)`; otherwise persist incomplete state before `shutdown(wait=False)` and do not claim this bounds interpreter lifetime.
- [ ] **Step 3: Real OS signal and process test.** In WSL, run `PYTHONPATH=src python3 -m unittest tests.test_m3_posix_lifecycle tests.test_parallel_eval_driver -q`. The existing test must deliver actual `SIGTERM` to a separate runner process while a fake evaluator child is active, verify the child stops, and inspect its durable summary for interruption/uncertainty. Keep the delayed-descendant test green and ensure its fixture never signals a numeric PID/PGID after the leader is reaped.
- [ ] **Step 4: Verify/commit.** Run full Windows suite and focused WSL suite, `git diff --check`, and inspect `git status --short`; stage only scoped files; commit `fix(hpc): reconcile interrupted replay attempts`.

## Task 4: Independent review, handoff, and cloud gate

**Files:** Modify `docs/experiments/m3-parallel.md`, `docs/codex-handoff/STATE.md`, `docs/codex-handoff/RUNBOOK.md` after code review. Do not update `FEEDBACK.md` with local-only speculation.

- [ ] **Step 1: Independent spec review, then code-quality review.** Give the reviewer the accepted spec, this plan, commit range, and red/green evidence. Require explicit checks for every transition boundary, result uniqueness, reporter compatibility, true OS SIGTERM, process-group containment, and no invented cleanup guarantee. Resolve Important findings before claiming local readiness.
- [ ] **Step 2: Fresh final verification.** Windows Python 3.11 full suite, WSL `test_m3_posix_lifecycle` plus driver, `git diff --check`, clean scoped status, and inspect staged paths for secrets/large artifacts. Report exact counts and platform skips. A passing fake suite does not certify real Docker or Nebius.
- [ ] **Step 3: Update the persistent handoff and commit.** Record state-machine rationale, verified commands, current local result, Docker-daemon residual uncertainty, and the no-cloud gate in the three named docs. Commit `docs(hpc): record M3 attempt ownership`.
- [ ] **Step 4: Learning checkpoint before any paid work.** Explain what the ledger fixes and what it cannot prove. A later live pilot still needs refreshed Nebius account/price/credit/quota preflight, an external exact-VM stop watchdog, a calculated run-specific cap, and Jethro's separate spending approval. Do not start the VM from this plan.

## Completion boundary

Local work is complete only when deterministic interruption tests, real POSIX process/signal tests, full local suites, reporter compatibility, and independent reviews pass with no Important findings. This is not M3 benchmark completion: 2 live pilot plus 48 comparison episodes remain behind the separate paid-run gate.
