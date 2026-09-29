# One-GPU Adaptive Diagnostic Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute the existing find → confirm → reduce rules with bounded 1/2/4-worker rounds on one GPU and compare complete diagnostic outcomes with a one-worker baseline.

**Architecture:** Preserve the existing M2/M4 commands and M3 fixed benchmark. New pure policy modules decide worker count and ordered controller transitions; a narrow episode-runner adapter delegates each bounded round to M3's durable ledger and evaluator containment. A fake evaluator validates the full flow locally before a separately authorized cloud experiment.

**Tech Stack:** Python 3.11 standard library, `unittest`, existing GR00T/LIBERO config builders, M3 attempt ledger and POSIX evaluator launcher, JSON evidence.

**Accepted design:** [`2026-09-29-adaptive-loop-parallelism-design.md`](../specs/2026-09-29-adaptive-loop-parallelism-design.md). **Cloud gate:** this plan authorizes local code/tests only. It does not authorize starting a VM or extra GPU, changing the failure definition, or a new perturbation family.

---

## File map and ownership

| File | Responsibility |
| --- | --- |
| `src/robot_debug/worker_policy.py` | Pure 1/2/4-worker choice and persisted reason; no provisioning. |
| `src/robot_debug/diagnostic_flow.py` | Pure ordered find/confirm/reduce state transitions using existing rules. |
| `src/robot_debug/diagnostic_round.py` | Bounded round contract and adapter into a shared M3 safety core. |
| `scripts/run_parallel_eval.py` | Extract its internal ledger/launch/containment loop for reuse without changing the frozen benchmark/pilot wrappers. |
| `scripts/run_diagnostic_loop.py` | CLI/session orchestration and adaptation to existing evaluator launch/config/evidence functions. |
| `src/robot_debug/diagnostic_report.py` | Validate two completed sessions and produce honest end-to-end comparison. |
| `tests/test_worker_policy.py`, `tests/test_diagnostic_flow.py`, `tests/test_diagnostic_round.py`, `tests/test_diagnostic_loop_driver.py`, `tests/test_diagnostic_report.py` | Test-first behavior and fault cases. |
| `docs/codex-handoff/STATE.md`, `docs/codex-handoff/RUNBOOK.md`, `PROJECT_PLAN.md`, `FEEDBACK.md` | Update only after working local evidence or material provider interaction. |

Do not edit the frozen M3 manifest, `parallel_eval.summarize_modes`, historical M2/M4 outcomes, or viewer in this plan. Reuse M3 process containment and ledger; if the current `run_mode` cannot accept arbitrary round manifests safely, extract its shared launch/ledger mechanism behind an adapter, preserve the M3 CLI, and regression-test M3 before committing. Do not copy/paste a second unsafe subprocess scheduler.

## Task 1 — Pure worker selector (green)

Desired test/API shape (write the test before the implementation):

```python
choice = choose_workers(
    ready_count=4, seconds_left=180.0, dollars_left=0.10,
    hourly_rate=1.7468, measured_seconds={1: 610.247 / 16, 2: 310.472 / 16, 4: 164.256 / 16},
    shutdown_reserve_seconds=20.0,
)
assert choice.workers == 4
assert choice.predicted_cost_usd <= 0.10
```

- [x] Add a failing `unittest` in `tests/test_worker_policy.py` for `choose_workers(ready_count, seconds_left, dollars_left, hourly_rate, measured_seconds)` returning a `WorkerChoice(workers, reason, predicted_seconds, predicted_cost_usd)`. Exact fixtures: zero ready → `workers=0`; one ready → `1`; four ready with M3 table `{1:610.247/16, 2:310.472/16, 4:164.256/16}` and enough budget → `4`; insufficient cost reserve → `0`; missing/invalid measurements → `1` when one worker is affordable. Reject negative, NaN, infinite, boolean, and unsupported inputs.
- [x] Run `C:\Windows\py.exe -3.11 -m unittest tests.test_worker_policy -v`; verify failure is a missing policy API, not a test typo.
- [x] Implement `src/robot_debug/worker_policy.py`: immutable `WorkerChoice`; valid counts are `(1,2,4)` capped by ready work; predict each candidate from observed per-batch timing with conservative ceiling; require both wall deadline and dollar budget, where dollars = full VM hourly rate × predicted wall seconds / 3600 plus a caller-supplied shutdown reserve. Choose the cheapest feasible configuration satisfying the deadline; at equal VM cost choose fewer workers. Return a reason naming the measurement source/fallback. Never invent a second-GPU option.
- [x] Re-run focused tests, add high-queue and tie-break fixtures, run `git diff --check`, then commit `feat(hpc): add bounded one-GPU worker policy` staging only the two related files.

## Task 2 — Ordered diagnostic state (green; red rules already accepted)

Test the two distinct accepted gates explicitly:

```python
assert is_reproducible(["policy_failure"] * 4 + ["success"])
assert classify_attempts(["policy_failure"] * 4) is GateDecision.PASS
with self.assertRaises(ValueError):
    is_reproducible(["policy_failure"] * 4)  # M2 still needs five.
```

- [x] Write failing tests for `DiagnosticFlow` in `tests/test_diagnostic_flow.py`: nominal gate precedes search; out-of-order search completion cannot select a later candidate over an earlier eligible one; M2 confirmation requires **five valid replays with at least four failures**; M4 candidate gate can pass after four failures or reject after two non-failures; reduction keeps `left, bottom, right, top` order and only moves the parent on a passed candidate; controls are required before certification. Invalid or infrastructure outcomes stop certification. Use two concrete `Rect` fixtures and assert exact next requested case IDs and terminal states.
- [x] Run `C:\Windows\py.exe -3.11 -m unittest tests.test_diagnostic_flow -v`; verify red for missing flow API.
- [x] Implement `src/robot_debug/diagnostic_flow.py` as a pure state machine using `session.is_reproducible`, `reduce.candidates`, and `reduce.classify_attempts`; distinguish the exactly-five M2 gate from the adaptive M4 gate. Persist ordered decisions and counters through a serializable snapshot; restore must reject unknown state or mismatched frozen config hash. Do not make subprocess/network calls here.
- [x] Re-run focused tests and existing `tests.test_reduce tests.test_failure_reduction tests.test_failure_search_driver`; commit `feat(diagnostics): add ordered adaptive flow` with explicit paths.

## Task 3 — Durable bounded round adapter (amber: implementation structure inside accepted topology)

The caller-facing value types should be immutable and serializable, for example:

```python
@dataclass(frozen=True)
class RoundRequest:
    case_id: str
    config_path: Path
    output_dir: Path

@dataclass(frozen=True)
class RoundResult:
    case_id: str
    status: str  # valid, invalid_evidence, infrastructure_error, or uncertain
    outcome: str | None
    evidence_paths: tuple[str, ...]
```

- [x] Add failing `tests/test_diagnostic_round.py` cases for bounded concurrent requests, durable ordered results, unknown launch identity, timeout, unique/bound config and output paths, exclusive round-root ownership, and fail-closed resume. The adapter contract is covered locally; the POSIX late-completion/containment proof remains in Task 4.
- [x] Run `C:\Windows\py.exe -3.11 -m unittest tests.test_diagnostic_round -v` and verify the adapter API was initially missing.
- [x] Extract a narrow internal safety core from `scripts/run_parallel_eval.py` so the existing fixed `run_mode`/`run_pilot_mode` wrappers still enforce their exact manifest, purpose, hash, and reporter contract. The local `diagnostic_round.py` adapter now uses that core, immutable config hashes, unique bound paths, exact launch sidecars, and the same ledger states. Production containment wiring is the remaining Task 4 dependency; the adapter alone is not live-safe.
- [x] Run round tests plus `tests.test_parallel_eval_driver` (72 passed, 1 POSIX-only skip), review the adapter fixes independently, and commit `feat(hpc): add fail-closed adaptive round adapter`. Production POSIX cleanup and late-completion tests remain in Task 4.

## Task 4 — Local full-loop CLI with fake evaluator first (amber)

The core local assertion is about the final result, not a fake speedup:

```python
sequential = run_local_fixture(policy="sequential", outcomes=fixture_outcomes)
adaptive = run_local_fixture(policy="adaptive", outcomes=fixture_outcomes)
assert sequential["certified_rectangle"] == adaptive["certified_rectangle"]
assert sequential["controls_passed"] is adaptive["controls_passed"] is True
assert adaptive["physical_attempts"] >= adaptive["valid_episodes"]
```

- [x] Write failing fake-evaluator driver tests for the complete ordered loop, timeout/interruption, and sequential search stopping after its first eligible failure. The local sequential and adaptive fixtures reach the same certified rectangle and controls; a real POSIX SIGTERM test checks that the evaluator PID exits and the session stays partial.
- [x] Run focused driver tests with `PYTHONPATH=src` and verify red for the missing CLI/controller and subsequent regression cases.
- [x] Implement `scripts/run_diagnostic_loop.py` around Tasks 1–3 with required bounds, one immutable session per policy/config hash, atomic summaries, the exact prior position-grid order, one sentinel, five confirmation replays, five fresh controls, and contained evaluator cleanup. Dry-run is explicitly fake and makes no Nebius call.
- [x] Run focused tests and the full Windows suite, update the runbook, and commit `feat(diagnostics): orchestrate bounded parallel loop` plus a reviewed safety fix. The observed full-suite result is 298 tests with four POSIX-only skips; the focused WSL suite passes 92, including real SIGTERM.

## Task 5 — End-to-end comparison and claim guard (green)

The reporter must expose comparability before speedup:

```python
report = compare_sessions(sequential_summary, adaptive_summary)
assert report["comparable"] is True
assert report["same_terminal_result"] is True
assert report["billed_cost_usd"] is None
assert report["physical_attempts"]["adaptive"] >= report["valid_episodes"]["adaptive"]
```

- [x] Write failing reporter tests for matched runs, contract mismatches, partial/uncertain sessions, outcome drift, extra speculative attempts, and fake-timing claim refusal.
- [x] Run the focused report tests and verify red for the missing API and later claim-boundary regressions.
- [x] Implement `src/robot_debug/diagnostic_report.py` to replay the pure flow against ordered durable round results, reject unequal frozen contracts or missing evidence references, separate shared-outcome drift from extra attempted cases, and refuse speedup claims for dry runs. Only **warm diagnostic** cost is estimated from the full-VM rate and observed warm elapsed time; full allocation and billed costs remain `null` until lifecycle/billing records exist.
- [x] Run focused and full suite, `git diff --check`; commit `feat(hpc): compare end-to-end diagnosis modes` plus the claim-boundary fix.

## Task 6 — Integration review and local handoff (green)

- [x] Independent reviewer checked spec coverage and found signal, drift, cost-label, and direct-invocation gaps; integration owner fixed them and re-ran Windows (298 tests, four POSIX skips) and WSL focused (92 tests) suites. A final separate re-review was unavailable; the integration owner also added and verified the real POSIX SIGTERM test.
- [x] Execute both local fake-evaluator policies and inspect their JSON summaries: both complete the same nine decision rounds and rectangle in the no-drift fixture (32 physical attempts each). The report marks them logically comparable but refuses a fake speedup number. A first-grid-failure fixture confirms the sequential mode avoids unneeded later grid launches while adaptive extra work is counted explicitly.
- [x] Update `docs/codex-handoff/STATE.md`, `docs/codex-handoff/RUNBOOK.md`, and `PROJECT_PLAN.md` with the local evidence. `FEEDBACK.md` is unchanged because this implementation made no new Nebius/NVIDIA provider interaction. Conventional commit `docs(hpc): record local adaptive-loop readiness`.
- [x] Present a separate [live experiment proposal](../../experiments/m3-adaptive-live-proposal.md) with current Nebius balance/price/capacity, one exact VM, disk retention, watchdog, estimated cost, and sequential/adaptive workload contract. **Do not start the VM without Jethro's run-specific approval.**

## Dependency, agent, and review map

`Task 1` and `Task 2` are independent and may use separate agents with exclusive ownership of their respective source/test files. `Task 3` depends on the M3 runner but not Task 1/2; keep one builder because ledger/external-process safety is tightly coupled. `Task 4` depends on 1–3; `Task 5` depends on 4; `Task 6` integrates all. The stronger-model coordinator owns Git integration, cloud decisions, and final review. A smaller implementation agent may perform each bounded green/amber task. Review after Tasks 1–3 before the controller, and after Tasks 4–5 before any cloud proposal. No agent besides the single designated owner may mutate Nebius resources or publish artifacts.

## Completion boundary

Local completion means all tasks above pass and produce the same certified result in sequential and adaptive fake runs with honest costs and safety behavior. It does **not** establish real end-to-end speedup. That claim requires the separately approved Nebius comparison and billing reconciliation.
