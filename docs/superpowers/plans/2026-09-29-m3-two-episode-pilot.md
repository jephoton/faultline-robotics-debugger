# M3 Two-Episode Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a separately labeled nominal-plus-reduced-mask, two-worker local or later live compatibility pilot without changing the frozen M3 benchmark.

**Architecture:** Give the existing scheduler an internal, validated purpose/workload choice. The public `run` command remains 16 fixed items; a new `pilot` subcommand invokes the same containment, ledger, and evidence path with `build_manifest(1)`, two workers, and its own session directory. The reporter accepts benchmark summaries only.

**Tech Stack:** Python 3.11 standard library, existing `robot_debug.parallel_eval` and `scripts/run_parallel_eval.py`, `unittest`, Windows Python 3.11 and WSL POSIX tests. No real Docker or Nebius in implementation.

---

## Scope, ownership, and gates

**Accepted design:** `docs/superpowers/specs/2026-09-29-m3-two-episode-pilot-design.md`. One smaller implementation agent owns `scripts/run_parallel_eval.py`, `tests/test_parallel_eval_driver.py`, and `tests/test_m3_report.py`; a POSIX test may be added to `tests/test_m3_posix_lifecycle.py`. A separate agent may implement the watchdog plan concurrently because it owns different files. The coordinator owns integration and cloud execution; independent spec and quality reviewers are read-only. Green: local refactor/tests/docs. Amber: exact internal helper signature and pilot summary marker—explain at review. Red: different workload/model/failure definition, pilot retries, live cap or VM start—Jethro decides separately.

No paid run follows from this plan. Stage explicit related paths, use conventional commits, and keep artifacts ignored. Do not write account IDs, tokens, private keys, or user-specific absolute paths into code or docs.

## Task 1: Freeze the two-case pilot contract in tests

**Files:** `tests/test_parallel_eval_driver.py`, `tests/test_m3_report.py`.

- [ ] Add a red test calling the proposed `run_pilot_mode(...)` with a fake evaluator. Assert exactly `['nominal-01', 'mask-01']` are launched once, `workers == 2`, `purpose == 'pilot'`, `manifest == build_manifest(1)`, and all paths live under `m3-pilot-workers-2/` rather than `m3-workers-2/`. Assert the rectangle on `mask-01` equals the M4 accepted `(0.625, 0, 0.375, 0.375)` and nominal has no mask.
- [ ] Add a concurrency fake with an active counter and barriers: assert peak active is 2, never greater than 2; no third item can launch. Assert unique config, output, eval ID, and launch-sidecar paths per case. Inject an invalid aggregate, timeout, and interruption separately; each must produce a non-comparable partial pilot and retain durable attempt records.
- [ ] Add a report test constructing a complete two-case pilot summary and assert `report_mode_summaries` rejects it for `purpose: pilot` before cost/speedup computation. Keep a regression assertion that `manifest_hash(build_manifest(8)) == '2c815047f734a691b8b55db0dc15521afd175962d7483a7a9f8f06463cd0338a'`.
- [ ] Run `$env:PYTHONPATH='src'; & 'C:\Windows\py.exe' -3.11 -m unittest tests.test_parallel_eval_driver tests.test_m3_report -q`; expect the new tests to fail because the pilot entry point does not exist. Commit only tests as `test(hpc): define two-case replay pilot` after the red result is recorded.

## Task 2: Reuse the scheduler without weakening benchmark identity

**Files:** `scripts/run_parallel_eval.py`, `tests/test_parallel_eval_driver.py`.

- [ ] Add `run_pilot_mode` as a narrow wrapper with the same root/timeouts/runner seams as `run_mode`, but no `resume` option. It must enforce two workers and one nominal/one reduced-mask item, and call the same scheduler kernel. Keep `run_mode`'s default benchmark behavior and directory names. A minimal internal shape is `purpose: Literal['benchmark','pilot']`, `items = build_manifest(8 if purpose == 'benchmark' else 1)`, and `session_name = f"m3-workers-{workers}" if benchmark else "m3-pilot-workers-2"`; validation occurs before filesystem writes. Do not expose arbitrary manifest or mask inputs through CLI.
- [ ] Put `purpose` into every new summary. Keep full-mode reporter compatibility with historical summaries lacking this field, but explicitly reject `purpose != 'benchmark'` when present. Reject pilot resume even if a partial pilot directory exists. Ensure an interrupted pilot still uses the existing process-group cleanup, exact launch sidecars, ledger persistence, and no-new-launch gate.
- [ ] Add `pilot` CLI dispatch with the same required root and timeout arguments but no `--workers` or `--resume`; it always uses two workers. Print the pilot summary path and nonzero exit for incomplete/nonvalid evidence. The existing `run` and `report` commands keep their meanings and help text.
- [ ] Run focused Windows tests, the full Windows suite, and `git diff --check`. Commit `feat(hpc): add bounded two-episode M3 pilot` with only runner/driver/reporter-test paths.

## Task 3: POSIX containment and handoff verification

**Files:** `tests/test_m3_posix_lifecycle.py` or `tests/test_parallel_eval_driver.py`; then `docs/experiments/m3-parallel.md`, `docs/codex-handoff/STATE.md`, `docs/codex-handoff/RUNBOOK.md` (coordinator only).

- [ ] Add or adapt one real WSL SIGTERM test of the `pilot` CLI while a fake evaluator is active. Verify both the child termination and an explicitly partial `m3-pilot-workers-2/session_summary.json`; no result may be labeled a complete comparison mode. Run `PYTHONPATH=src python3 -m unittest tests.test_m3_posix_lifecycle tests.test_parallel_eval_driver -q` in WSL.
- [ ] Independent spec review checks exact two cases, no third launch, shared containment/ledger, output isolation, and reporter refusal. Independent quality review checks scheduler refactor regressions and signal/timeout safety. Resolve Important findings with fresh tests.
- [ ] Coordinator reruns Windows full suite, WSL focused suite, `git diff --check`, and a scoped tracked-file secret/artifact check. Record actual counts. Update the three handoff docs with the local pilot command and limitations; commit `docs(hpc): record M3 pilot readiness`.
- [ ] Stop at the live gate. The pilot may be run only after the watchdog plan is implemented and dry-run verified, current account/credit/price/quota/capacity/VM state are checked, and Jethro separately approves a numeric cap.

## Review checkpoint

Show Jethro the two-case manifest and explain that two workers test session overlap, not guaranteed parallel GPU inference. Ask for an outcome prediction before the paid pilot. A pilot pass is a prerequisite to, not authorization for, the full 1/2/4 comparison.
