# M3 Three-Task Nominal Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify that the pinned GR00T/LIBERO environment can run one all-visible nominal episode for each approved LIBERO Object task ID 0, 1, and 2 before spending on a multi-job comparison.

**Architecture:** Reuse the existing three-job manifest and contained portfolio CLI with a *shared three-attempt ceiling*. Its first wave requests one nominal case per task; the budget stops before any occlusion search. This is a compatibility screen, not a reliability baseline or performance comparison. One execution owner controls the existing stopped Nebius L40S VM and copies evidence back before stopping it.

**Tech Stack:** Python 3.11, existing `robot_debug.portfolio_*` modules, pinned VLA harness/GR00T checkpoint, Nebius CLI, exact-VM watchdog, JSON/trace/MP4 artifacts.

**Authority boundary:** Jethro approved task IDs `(0, 1, 2)` as *screening candidates*. This document does not authorize a VM start, a dollar cap, a public push, a different VM shape, or a claim that IDs 1 and 2 are nominally reliable. The former single-loop live comparison remains paused.

**Execution update, September 30:** Jethro separately approved US$3/60 minutes. The local test was integrated at `9344c62` and passed; one guarded exact-shape start then timed out with Nebius `NotEnoughResources` before any episode. The VM is confirmed stopped, temporary ingress removed, and guard unregistered. See [the attempt record](../../experiments/m3-three-task-screen.md). No automatic retry or different shape is authorized by this attempt.

**Retry update, September 30:** Jethro approved one same-cap retry and waived a fresh balance check. It timed out with the same `NotEnoughResources` result before guest access. The exact VM is again confirmed stopped, no temporary ingress exists, and the second guard was unregistered. No task-validity conclusion follows; another start or resource change requires a new decision.

---

## Frozen experiment contract and cost gate

- Suite `libero_object`; seed `7`; family `agentview_rect_occlusion`; checkpoint ID/revision from `PortfolioManifest` defaults. The pinned source provisionally maps IDs 0/1/2 to alphabet soup / cream cheese / salad dressing, each placed in a basket. Verify the runtime catalog before using these labels in a result.
- `adaptive-portfolio` mode with `episodes=3` and a fresh ignored results root. Assert from a local dry run that the sole requests are `task-00--nominal-01`, `task-01--nominal-01`, and `task-02--nominal-01`; no search, confirmation, or reduction case is admitted. The existing measured worker chooser may use at most two evaluator processes on the one GPU; no extra GPU is allocated.
- A valid screen requires the exact task ID and episode index 0 in each nonempty aggregate, a nonempty trace and MP4, no infrastructure/uncertain attempt, and three terminal-valid outcomes. Record each success/failure separately. One success per task proves only a single initial state worked, **not** a stable nominal success rate; any nominal failure pauses the portfolio comparison for interpretation.
- Current read-only CLI preflight on September 30: existing exact L40S Intel `1gpu-16vcpu-64gb` VM is `STOPPED` in eu-north1. Calculator: US$1.7468/VM-on hour pre-tax and US$0.0194444/hour for its retained 200 GiB Network SSD. Capacity advice: one on-demand slot for the exact shape, `LOW` availability; restart is not guaranteed. Balance/expiry and any billing lag still require a console check.
- **Approved for the September 30 attempt, now ended:** US$3 maximum incremental spend, at most 60 minutes VM-on, and at most 24 further hours of retained disk before a separate retention decision. At quoted rates, 60 minutes VM-on plus 24 hours of disk was US$2.2135 before tax, about US$2.4127 with an assumed 9% tax. The start failed before any episode; these figures remain estimates, not a billed total. A later attempt needs a fresh cap/readiness decision.
- A 60-minute exact-VM workstation watchdog must be armed *while the VM is stopped* and confirmed alive; guest shutdown is backup. The launch cutoff is at most 45 minutes after VM start, leaving 15 minutes for a possible 300-second evaluator timeout, evidence copy, and stop verification. The CLI's estimated-dollar bound is advisory; the independently armed VM stop deadline is the spending boundary. No retry of an uncertain start/stop.

## Task 1 — Freeze accepted candidates and prove three nominal requests (green)

**Files:** `tests/test_diagnostic_portfolio_cli.py`, `docs/experiments/m3-task-selection-contract.md`, `docs/superpowers/plans/2026-09-30-m3-multi-job-portfolio.md`.

- [x] Add a focused dry-run test for the three exact task-nominal requests, ownership, no search, and `physical_attempts == 3`.
- [x] Run focused/full Windows tests and focused WSL lifecycle/driver tests; commit the related test at `9344c62`.
- [x] Record Jethro's candidate choice as **accepted for screening**, not a passed runtime baseline.

## Task 2 — Read-only resource and model preflight (green/amber)

**Files:** `docs/experiments/m3-three-task-screen.md` (create after observation), `FEEDBACK.md` only if a new provider behavior is materially observed.

- [ ] Recheck CLI-authenticated tenant/project/region and exact stopped instance by ID, current calculator prices, on-demand availability and quota. Read current account balance/expiry in the Nebius console; do not infer it from September 29's US$10.42. Record only non-sensitive summarized figures in the experiment note.
- [ ] Confirm local `main` source is what will run on the VM. The main checkout is currently ahead of GitHub, so either obtain Jethro's approval to push this reviewed code to the existing remote or transfer the exact commit to the VM over the existing guarded SSH path. Do not run the older VM checkout as if it contained the new task selector.
- [ ] After a separately approved cap but before any evaluator launch, verify the VM's pinned harness/container digest, model cache and actual served checkpoint revision, and task catalog IDs/instructions. If those are not observable, stop rather than trust the manifest label alone.

## Task 3 — Explicit paid-start gate and one-owner screen (red, then amber)

**Files:** ignored run directory and watchdog log; no tracked code file is required for execution.

- [ ] Present the current balance, rate, capacity, exact task identities, the three-episode screen, and US$3/60-minute proposal to Jethro. Wait for an explicit numeric cap/deadline decision. A candidate-ID approval alone is not spend approval.
- [ ] With approved bounds, arm the existing exact-VM workstation watchdog while stopped, check its live scheduled-task/process ownership and durable `armed` event, and set guest shutdown backup. Recheck CLI auth and VM `STOPPED` immediately before a single regular-instance start. If launch capacity is unavailable, do not switch to preemptible or another shape.
- [ ] Use a fresh exact manifest and ignored results root; run the existing `scripts/run_diagnostic_portfolio.py` without `--dry-run`, with `--mode adaptive-portfolio --episodes 3 --seconds 2700 --estimated-usd 1.5 --hourly-rate 1.7468`. Resolve and record the actual upstream/project paths before launch. Stop if any case is invalid, uncertain, or attached to the wrong task ID. Do not continue into a search/reduction experiment.
- [ ] Copy compact JSON and traces first, then MP4s. Independently stop/poll the exact VM to `STOPPED`; remove temporary SSH ingress and verify watchdog/guest state. An unconfirmed stop is urgent manual-console action, not success. Do not delete the retained disk without a separate decision.

## Task 4 — Evidence review and next decision (green/red)

**Files:** `docs/experiments/m3-three-task-screen.md`, `docs/codex-handoff/STATE.md`, `PROJECT_PLAN.md`, `FEEDBACK.md` for actual Nebius/NVIDIA observations only.

- [ ] Validate three exact task/episode outcomes and artifact paths against the saved ledger/aggregates; annotate any mismatch or missing media as infrastructure-invalid. Summarize per-task nominal outcome and actual physical launches. Reconcile calculator estimate with console billing when posted; never call estimated warm time a bill.
- [ ] Ask Jethro to interpret the results before turning them into a product claim. If all three pass once, recommend a separately bounded repeatability baseline and then matched sequential-versus-portfolio sessions. If a task fails nominally, diagnose or choose a different task *with Jethro*; if infrastructure fails, repair and re-propose the same screen. Update relevant handoff/feedback files and commit a factual `docs(experiment): record three-task screen`.

## Dependency and agent ownership

Task 1 and read-only Task 2 can proceed independently. A smaller implementation agent may own only the Task 1 test/docs slice; the coordinator owns all Nebius CLI/console lifecycle checks, the single paid run, Git integration, and final claims. An independent reviewer gets the frozen manifest, session summary, ledgers, and acceptance criteria after the run, not VM mutation authority. Task 3 depends on Task 1, a fresh Task 2 preflight, and Jethro's numeric cap. Task 4 depends on verified stop and copied evidence. Green work may proceed autonomously; task IDs, cap/VM start, alternative shape/family, and claims are red.

## Completion boundary

Passing this plan proves only that the three selected task IDs can each produce one valid all-visible episode under the pinned setup. It does not establish nominal reliability, cross-task diagnostic quality, cost efficiency, or an end-to-end speedup. Those require later, separately bounded experiments.
