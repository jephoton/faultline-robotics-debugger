# M3 Launch Identity and Safe Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two final-review gaps: durable exact evaluator identity during an active attempt and safe resumption of a partial local mode without duplicate completions.

**Architecture:** Keep `AttemptLedger` as the authoritative result/ownership record. Write an atomic per-case launch-identity sidecar immediately after `Popen`, before `wait`, via a callback that is included inside the evaluator's cleanup `try`. Resume only a validated partial session whose ledger has no in-flight or uncertain cases and whose terminal cases are valid; schedule only `prepared` entries. Mark resumed modes and reject them in the performance comparison, so recovery proof cannot masquerade as an uninterrupted benchmark.

**Tech Stack:** Python 3.11 standard library, existing `base._atomic_write_json`, `unittest`, Windows Python 3.11, WSL POSIX signal tests. No real Docker or Nebius.

---

## Boundaries and ownership

**Accepted requirements:** `docs/superpowers/specs/2026-09-27-m3-equal-work-parallel-evaluation-design.md` requires no-cloud proof of resumption without duplicate completions; `docs/superpowers/specs/2026-09-28-m3-evaluator-containment-design.md` requires durable owned PID and exact expected container name before cleanup interpretation. This plan does not change the fixed manifest, model, worker counts, failure definition, cost cap, or live topology. No paid run is authorized.

| Task | Owner | Paths | Dependency |
| --- | --- | --- | --- |
| 1. Launch identity | smaller implementation agent | `scripts/run_parallel_eval.py`, `tests/test_parallel_eval_driver.py`, `tests/test_m3_posix_lifecycle.py` | first |
| 2. Safe resume | smaller implementation agent | `scripts/run_parallel_eval.py`, `src/robot_debug/attempt_ledger.py` only if validation API needs it, `tests/test_parallel_eval_driver.py`, `tests/test_parallel_eval_report.py` | after Task 1 |
| 3. Review and integration | coordinator; independent reviewer read-only | handoff docs and branch | after Tasks 1–2 |

Green: tests, sidecar persistence, explicit CLI flag, docs. Amber: the conservative resume eligibility check and cost-report rejection; explain at next learning checkpoint. Red: extending resume to unknown/active attempts, accepting resumed modes in speed comparisons, changing live spending or workload—ask Jethro first. One agent edits the coupled runner tasks sequentially; reviewer does not edit; coordinator alone integrates and controls external resources.

## Task 1: Persist exact launch identity before waiting

**Files:** `scripts/run_parallel_eval.py`, `tests/test_parallel_eval_driver.py`, `tests/test_m3_posix_lifecycle.py`.

- [ ] Add a red test using an injected process whose `wait()` blocks: call `_run_evaluator_safely(..., launch_observer=observer)` in another thread, wait until observer runs, and assert it received the actual `pid` and `vla-eval-{pid}` before `wait()` finishes. Add a test where observer raises: the launched process must enter the existing cleanup path, never return successful evidence, and surface cleanup uncertainty if cleanup fails.
- [ ] Add `launch_observer: Callable[[int, str], None] | None = None` to `_run_evaluator_safely`. Immediately after `process_factory` returns, compute the exact PID/name, then invoke the observer inside the existing cleanup `try` before any `process.wait`. Preserve the PID/name on raised errors. Do not infer identity from a guessed PID or broad Docker scan.
- [ ] In `run_mode`, pass a per-case observer to the production command runner. It atomically writes `session/launches/<case-id>.json` containing schema version, case ID, evaluator PID, and exact expected container name. Validate path containment and create `launches/` during session setup. If the write fails, fail the episode and clean up its launched process. Keep injected fake command runners usable; their lack of a real PID is explicit local-test evidence, not a fabricated identity.
- [ ] Run focused Windows driver tests and WSL `tests.test_m3_posix_lifecycle tests.test_parallel_eval_driver`, then `git diff --check`. Commit only related paths as `fix(hpc): persist evaluator launch identity`.

## Task 2: Resume only proven-safe partial work

**Files:** `scripts/run_parallel_eval.py`, `tests/test_parallel_eval_driver.py`, `tests/test_parallel_eval_report.py`; `src/robot_debug/attempt_ledger.py` only if an existing validation method must change.

- [ ] Add red tests: create a partial session with terminal valid `nominal-01` and the remaining 15 cases `prepared`; a `resume=True` invocation runs only the 15 prepared cases and preserves the first result exactly once. Refuse resume if any attempt is `submitting_unknown`, `active`, or `completing_pending`, if any terminal result is nonvalid, if manifest bytes/digest, worker count, or case IDs differ, or if the partial summary is malformed. Refuse `resume=True` when no prior session exists and refuse a new run over an existing session. Test that a completed resumed summary is rejected by the speed comparison even if all 16 results are valid.
- [ ] Add an explicit `--resume` boolean to the `run` command and `resume: bool = False` to `run_mode`. On resume, load the existing `manifest.json` and `session_summary.json`; validate exact frozen ordered manifest, digest, worker count, and `AttemptLedger.from_snapshot`. Permit only terminal-valid/prepared states and a partial/interrupt/launch-cutoff stop reason with zero in-flight IDs; never auto-retry uncertain ownership. Do not overwrite existing configs or artifacts for terminal cases. Initialize `pending` from only `prepared` items. Persist a `resumed` marker and cumulative `elapsed_seconds` (previous mode elapsed plus new active run time), while keeping elapsed-time comparison disabled for resumed modes.
- [ ] Make `_load_report_record` reject `resumed=True` with an explicit message even if the mode is otherwise complete. Keep the existing local viewer and audit artifacts. Run focused runner/reporter tests and `git diff --check`; commit `feat(hpc): resume safe partial replay modes`.

## Task 3: Final review, handoff, and cloud gate

**Files:** `docs/experiments/m3-parallel.md`, `docs/codex-handoff/STATE.md`, `docs/codex-handoff/RUNBOOK.md`.

- [ ] Independent read-only spec and quality review against the two cited requirements, emphasizing `Popen`→identity-write race, cleanup when identity persistence fails, exact manifest validation, no duplicate results, and fail-closed reporting. Resolve Important findings before integration.
- [ ] Fresh verification: Windows full `unittest discover -s tests -q`, WSL focused POSIX lifecycle plus driver, `git diff --check`, scoped status, and secret/artifact scan. Document exact observed counts, not predicted counts.
- [ ] Update the three handoff docs and commit `docs(hpc): record safe M3 recovery boundary`. Integrate into `main` only after review and merged-result tests. Preserve the managed worktree until no task depends on it.
- [ ] Stop at the live-work gate. Refresh Nebius project, credits, quota, resource rate, VM state, and watchdog design; calculate a run-specific cap and obtain Jethro's separate approval before any billable pilot. Unknown Docker-daemon request state still requires exact-VM stop/verification.

## Self-review

Task 1 covers exact launch identity while active and observer-failure cleanup. Task 2 covers safe no-duplicate resumption and prevents resumed runs becoming throughput claims. Task 3 covers independent review, handoff, and the paid-run boundary. No automatic recovery of unknown attempts is allowed.
