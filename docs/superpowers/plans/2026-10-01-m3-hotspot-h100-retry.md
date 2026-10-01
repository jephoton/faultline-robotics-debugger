# M3 Hotspot H100 Retry Implementation Plan

> **For agentic workers:** Use executing-plans task by task. Root alone owns cloud lifecycle, spending, evidence transfer, and Git integration. A smaller-model reviewer may inspect local contracts/evidence but must not mutate infrastructure.

**Goal:** Test Nebius SSH from the hotspot, then complete only the three previously approved nominal screening cases if guest compatibility passes.

**Architecture:** Reuse the accepted snapshot-backed separate H100 design and exact-VM watchdog. Preserve the original stopped L40S VM and managed disk. A strict connectivity gate precedes all model/evaluator work; no automatic start retry or alternate resource.

**Tech Stack:** Nebius CLI, Windows Task Scheduler watchdog, snapshot-backed 200-GiB Network SSD, dedicated WSL SSH key, pinned GR00T/LIBERO harness, existing sequential portfolio runner.

## Authority and spend gate

The earlier one-start approval is exhausted. This plan proposes **US$6 additional total / one H100 start / 45 minutes maximum VM-on**, including temporary storage and the original disk's next 24 hours. At the last verified US$4.50/hour compute rate and approximately US$0.01945/hour per storage object, a conservative 45-minute compute plus 24-hour three-volume estimate is about US$5.21 with assumed 9% tax. These are estimates, not billing. Require explicit new approval and refreshed balance, expiry, price, quota, and capacity before creating resources. If fresh estimates exceed the cap, stop before creation. Delete only new clone/managed disk and snapshot after evidence copy, within 24 hours; never delete the original resources.

## Task 1 — Readiness and local contract (green)

Preparation verified: intended original VM remains STOPPED; CLI and console
sessions work; console displays US$9.53 balance with no expiry shown. The
focused Windows Python 3.11 CLI suite passes 7/7. Billing is still not reconciled
to the prior attempt. Price/capacity and source-disk readiness must be refreshed
at execution; the proposed US$6 cap is not yet approved.

**Files:** existing `tests/test_diagnostic_portfolio_cli.py`; ignored fresh control directory under `artifacts/m3-control/`; no code changes.

- [ ] Read back the original instance `STOPPED`, disk `READY`, unchanged managed ownership, and absence of previous temporary resources.
- [ ] Confirm active intended project/region, live balance/expiry, H100 price, snapshot/disk tariffs, quota, and capacity. CLI access succeeded in this turn; that is not a balance check.
- [ ] Resolve direct WSL public egress immediately before firewall creation. The hotspot address differs from hotel Wi-Fi; do not reuse its old rule.
- [ ] Run `py -3.11 -m unittest tests.test_diagnostic_portfolio_cli -q`; require seven passing tests. Freeze the existing manifest: task IDs 0/1/2, seed 7, current occlusion-family/model labels, checkpoint revision from the previous ignored manifest.
- [ ] Record fresh cap approval privately and in this plan without secrets or infrastructure IDs.

## Task 2 — One guarded clone and connectivity gate (amber after red cap)

**Files:** fresh ignored snapshot/instance request, resource record, watchdog record/log; reuse `scripts/run_vm_watchdog.py` without changes.

- [ ] Create one snapshot from the exact original stopped disk, await ready, then one separate explicitly stopped H100 clone with the accepted GPU preset, managed disk, recovery policy FAIL, and guest shutdown backup within 45 minutes of start.
- [ ] Read the new ID back stopped. Create a temporary stateful TCP/22 ingress rule restricted to the freshly resolved hotspot `/32`; confirm ready and attached group.
- [ ] Arm a fresh scheduled-task-owned watchdog against only that new ID with a fixed deadline no later than 45 minutes after start. Require durable verified/armed events and task Running before one start.
- [ ] Capture serial logs and poll guest/TCP readiness with bounded probes. **If SSH cannot complete a credentialed noninteractive command within five minutes after serial boot completion, or ten minutes after the start request (whichever occurs first), copy available logs and stop.** No alternate port, broad ingress, replacement VM, or blind start retry.
- [ ] If SSH succeeds, verify GPU/CUDA/container runtime and inspect the prior Fabric Manager failure. An unready GPU or unresolved inference-blocking driver failure ends the attempt; do not spend on an unplanned driver migration.

## Task 3 — Three nominal episodes only (amber)

**Files:** ignored new guest/local source bundle, frozen manifest, fresh results root.

- [ ] Privately transfer the reviewed local source into a fresh session checkout. Verify pinned upstream/checkpoint actually served and runtime task IDs/instructions before evaluating.
- [ ] Use `scripts/run_diagnostic_portfolio.py` with `--mode sequential-jobs --episodes 3`, the frozen manifest, actual upstream/project paths, `--hourly-rate` equal to the fresh price, and seconds/dollars bounded by the remaining deadline with at least five minutes reserved for copy and stop.
- [ ] Expect only `task-00--nominal-01`, `task-01--nominal-01`, and `task-02--nominal-01`; no search, confirmation, or reduction. The attempt-limited session may exit 1 with a partial summary; validate exact three attempts, terminal validity, and zero uncertainty rather than interpreting that exit alone as failure.
- [ ] Copy compact JSON/ledger/traces first, then MP4s. Require per-case task identity, initial-state index 0, nonempty media/trace, and valid terminal outcomes; never compensate with extra attempts.

## Task 4 — Stop, cleanup, review (green within approved cleanup)

**Files:** `docs/experiments/m3-three-task-screen.md`, `docs/dev-log.md`, `FEEDBACK.md`, `docs/codex-handoff/STATE.md`, `PROJECT_PLAN.md`.

- [ ] Stop the exact clone and independently verify STOPPED. Remove its temporary ingress and retire its watchdog only after confirmation.
- [ ] After local evidence recovery, delete only new clone/managed disk and snapshot. Read lists back to verify only the original stopped VM/ready disk remain.
- [ ] Smaller-model reviewer independently reconciles requested/attempted/valid cases and media, or checks the access-failure evidence. Root synthesizes; do not repeat paid work.
- [ ] Update the named handoff/experiment/feedback files with outcome, unresolved causes, cleanup, and estimated versus posted charges. Run `git diff --check`; explicitly stage those files and commit `docs(m3): record hotspot H100 retry outcome`. Do not push without separate authority.

## Dependency and learning checkpoints

Readiness → new cap approval → one root-owned cloud attempt → evidence recovery/stop/cleanup → independent local review → root synthesis. Local command review may run in parallel with root's read-only preflight; there are no concurrent cloud owners or overlapping file writers. Green local verification/review is handed to a smaller capable model after approval, while root retains live lifecycle/debugging. No extra checkpoint is needed between SSH success and already-scoped nominal execution; report the gate evidence and proceed. New hardware/driver architecture, spending increases, workload changes, and submission claims remain red decisions.

## Claim boundary

GitHub SSH banners on the hotspot prove outbound connectivity to GitHub only. A successful Nebius connection would establish this retry's path, not conclusively prove hotel filtering without a matched comparison. One nominal episode per task does not establish reliability or HPC speedup. The portfolio comparison still requires its own later design/cap.
