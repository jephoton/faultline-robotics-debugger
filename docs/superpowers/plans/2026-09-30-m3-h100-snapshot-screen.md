# M3 H100 Snapshot Migration and Three-Task Screen Implementation Plan

> **For agentic workers:** Use the existing exact-VM lifecycle and portfolio-screen contracts. Execute this plan task by task; stop at every red gate. The coordinator alone owns Nebius mutations, paid execution, and Git integration.

**Goal:** Complete the still-pending one-episode nominal screen for LIBERO Object task IDs 0, 1, and 2 despite L40S-A placement failures, without destroying the original VM or exceeding a newly approved cap.

**Architecture:** Snapshot the existing stopped L40S-A boot disk, create a separate same-project H100 VM with a managed boot disk sourced from that snapshot, verify its guest/model/task compatibility, then run only the frozen three-case nominal screen. Preserve the original instance and disk unchanged. Transfer the reviewed local source privately; use a new exact-VM watchdog and ignored evidence root. Stop and verify the H100 VM after evidence copy.

**Tech Stack:** Nebius CLI and console, existing Windows Task Scheduler-owned exact-VM watchdog, Network SSD snapshot/clone, Ubuntu/Docker/Python 3.11 guest environment, pinned GR00T/LIBERO harness, `scripts/run_diagnostic_portfolio.py`, JSON/trace/MP4 evidence.

**Authority boundary:** Jethro accepted H100 snapshot migration as the next design. This plan does **not** authorize creating a billable snapshot or VM, starting compute, extending the former US$3 cap, deleting the original VM/disk, changing task/family/model, public pushing, or claiming an HPC speedup. The numeric cap and retention period are a new red decision after current price/account checks.

**October 1 approval:** Jethro accepted the US$7.50 bounded attempt cap, one H100 start with at most 60 minutes VM-on, and deletion of only the temporary H100 clone/managed disk and snapshot after evidence copy within 24 hours. The original L40S VM/disk remain retained. This approval supersedes the pending-cap wording below; refresh live readiness before spending. CLI access was renewed for this attempt.

## Task 1 — Read-only financial and technical preflight (green)

**Files:** `docs/experiments/m3-three-task-screen.md`, `FEEDBACK.md` only for new observed provider behavior.

- [ ] Read the intended Nebius tenant/project/region and the exact original VM/disk IDs and states. Require original VM `STOPPED`, disk `READY`, 200 GiB, and no change to its managed ownership. Check the H100 1-GPU preset, quota, capacity advice, and current calculator rate. Capacity advice is not a reservation.
- [ ] Check the console balance/expiry and current snapshot, cloned Network SSD, and H100 pricing, including any effective-date rate change and tax treatment. If snapshot price or billing behavior cannot be established, pause before snapshot creation and present the uncertainty to Jethro; do not assume it is free. Estimate a bounded worst case that includes VM-on time and both disks/snapshot during approved retention.
- [ ] Confirm the source disk can produce a snapshot and the selected H100 preset can boot from a snapshot-backed managed disk with compatible image architecture. Inspect CLI options without mutating resources. Record non-sensitive observations and timestamps.
- [ ] Recheck that the locally reviewed source includes the exact three-case dry-run regression and that the run will request only `task-00--nominal-01`, `task-01--nominal-01`, and `task-02--nominal-01`.

**Gate:** Present a proposed numeric cap for all charges in the bounded time window (including the original disk's ongoing charge), maximum VM-on minutes, snapshot/new-disk retention, and current balance to Jethro. Wait for explicit approval. The prior L40S cap is closed.

**Read-only preflight result, September 30:** The exact original VM/disk, H100 preset/capacity, console balance (US$9.89), CLI H100 and cloned-disk estimates, and detailed published snapshot tariff were checked. The three-case CLI contract passed 7/7 focused WSL tests. The conservative proposal in the [experiment note](../../experiments/m3-three-task-screen.md) is US$7.50 *total including the existing disk's next 24 hours*, 60 minutes H100 VM-on, and cleanup of only the new snapshot/clone by 24 hours; it is not approved. No credit-expiry date was displayed. Refresh live prices, capacity, and balance before any approved mutation.

## Task 2 — Snapshot and separate H100 guest (red gate, then amber)

**Files:** ignored local resource/operation record; `docs/experiments/m3-three-task-screen.md` after the attempt.

- [ ] After the new cap, create one snapshot from the **exact existing** boot disk and wait for `READY`; record its ID privately. Do not detach, update, stop/start, or delete the original VM or disk.
- [ ] Create one regular, non-preemptible H100 1-GPU VM in the same project/subnet with a snapshot-backed 200-GiB managed Network SSD. Set the CLI's explicit `--stopped` option; its create default is `stopped: false`. Use a non-restarting recovery policy if supported for the chosen shape. Give it a distinct name and exact ID; start with no broad inbound rule. Verify operation completion and read the new instance/disk back as `STOPPED`. If creation is uncertain, reconcile IDs before retrying—never create a second clone blindly.
- [ ] Before any paid VM start, arm the existing OS-owned watchdog against **only the new H100 instance ID**, while that instance is stopped. Confirm a live scheduled-task owner and durable `verified`/`armed` events. Use a fixed deadline within the approved cap. Check CLI auth and `STOPPED` immediately before one start. No automatic replacement shape, preemptible fallback, or blind start retry.
- [ ] Once reachable, use only narrow temporary workstation `/32` SSH ingress; set guest shutdown backup. Verify boot, GPU visibility, CUDA/container/runtime health, disk capacity, pinned harness and **actually served** checkpoint ID/revision, and runtime LIBERO task IDs/instructions 0/1/2. Copy the reviewed local commit privately rather than treating the older guest checkout as current. A failed compatibility check ends the screen and triggers controlled stop.

## Task 3 — One bounded screen and evidence recovery (amber)

**Files:** fresh ignored local results root and guard log; no tracked code mutation required.

- [ ] Resolve the actual upstream/project paths and dry-run the three exact nominal requests on the selected source. Configure at most two evaluator processes on the one H100 GPU; do not launch search, confirmation, or reduction cases.
- [ ] Run the existing `adaptive-portfolio` command with `episodes=3` and a fresh session label. Set the command's seconds and estimated-dollar options from the **fresh H100 rate and approved deadline**, with enough margin for a stuck evaluator, copy, and stop. The independent watchdog, not the advisory CLI estimate, is the final spend boundary.
- [ ] Require three terminal-valid aggregates with exact task IDs and episode index 0, nonempty trace and MP4, and no uncertain attempt. Copy compact JSON/ledgers/traces first, then videos. If any result is invalid, preserve evidence and stop; do not expand the workload to compensate.
- [ ] Stop and poll the exact H100 VM to `STOPPED`, remove temporary ingress, confirm the original L40S VM is still `STOPPED`, and retire the guard only after stop verification. If a stop is unconfirmed, escalate to manual console action immediately. Retain or delete snapshot/clone resources only under the approved retention decision; account for storage until then.

## Task 4 — Verify and communicate the evidence (green/red)

**Files:** `docs/experiments/m3-three-task-screen.md`, `docs/codex-handoff/STATE.md`, `PROJECT_PLAN.md`, `FEEDBACK.md` for actual provider/model interactions.

- [ ] Independently reconcile every requested case, launch attempt, terminal outcome, trace, MP4, and task instruction. Record nominal success/failure per task without inferring repeatability from one episode. Separate placement, clone/boot, model, and evaluator failures.
- [ ] Reconcile estimated cost with posted billing when available; label unposted amounts as estimates. Record H100-vs-L40S environment difference, so the previous 1/2/4-worker throughput numbers are not reused as H100 evidence.
- [ ] Ask Jethro to interpret the screen before making a product claim. If all three nominal cases pass, propose a separately capped repeatability baseline before matched sequential-vs-portfolio runs. If one fails, investigate that task or choose another with Jethro. Commit factual documentation with a Conventional Commit; do not push without separate publication direction.

## Dependency, ownership, and review map

Task 1 is read-only and may run before cap approval. Task 2 depends on the Task 1 price/account/capacity checks and Jethro's new numeric cap; Task 3 depends on verified guest/model/task preflight; Task 4 depends on copied evidence and verified stop. One coordinator owns all Nebius state, spending, watchdog registration, and final interpretation. A smaller model may independently review the local command/test contract or evidence parser, but may not mutate the same cloud resource. A reviewer should check frozen request IDs, validity criteria, and copied evidence against ledgers rather than repeat the paid run. Checkpoints are: before snapshot creation (red cap), after compatibility preflight (go/no-go within cap), and after evidence synthesis (human interpretation).

## Completion boundary

This plan completes only a three-task, one-initial-state-per-task H100 compatibility screen. It does not demonstrate nominal reliability, failure diagnosis quality, portfolio cost efficiency, cross-suite generalization, or end-to-end HPC speedup. Those remain later experiments under separately accepted designs and caps.
