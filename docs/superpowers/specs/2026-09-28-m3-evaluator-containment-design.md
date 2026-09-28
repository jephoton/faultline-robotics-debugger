# M3 Evaluator Containment Design

**Status:** Proposed implementation detail for the accepted M3 single-VM design; no cloud spending authorized

**Parent:** [M3 equal-work parallel evaluation](2026-09-27-m3-equal-work-parallel-evaluation-design.md)

## Problem and evidence

The local M3 runner launches one pinned `vla-eval` CLI per fixed-manifest item.
On timeout it currently signals and reaps only the CLI parent, then checks for
its PID-named Docker container. In the pinned
[`_exec_docker` implementation](https://github.com/allenai/vla-evaluation-harness/blob/35f1200eb15608aa898f727a3722f7eef889c6cd/src/vla_eval/cli/main.py#L60-L88),
the CLI itself starts `docker run` as a child; its SIGTERM handler stops the
named container and exits without reaping that child. A POSIX reproduction
with the real M3 helper and simulated Docker inspection observed
`cleanup_confirmed=True` before a surviving descendant acted. Thus the
current flag is not proof of containment. A running executor thread may also
keep Python alive after its partial-summary deadline.

## Selected approach and alternatives

Jethro selected strengthening local process containment before the live
comparison, with an independent VM-stop watchdog as the final cost boundary.
The narrower alternative—running only a supervised two-episode pilot with a
watchdog and abort-on-uncertainty—would reach real hardware sooner but leave
the runner's autonomous cleanup gap unaddressed. Replacing the pinned harness
Docker launcher entirely would grant more lifecycle control but changes more
of the evaluated stack than M3 needs.

## Local containment contract

- The production runner supports its intended Linux/WSL POSIX host explicitly.
  Launch each evaluator in a new POSIX session/process group; do not silently
  fall back to parent-only signaling on an unsupported host. Injected fake
  runners remain usable on Windows for pure scheduling tests.
- Persist the owned evaluator PID and exact expected container name
  (`vla-eval-{pid}`) in each attempt's local evidence before interpreting
  cleanup. Do not match or remove other containers.
- On timeout, interruption, or an unexpected wait failure, first close the
  launch gate. Signal the owned group for graceful termination, wait a bounded
  interval, then escalate to group kill if any member survives. Reap the
  evaluator parent. Handle already-exited groups without signaling an
  unrelated reused process group; no PID-based broad process scan.
- Only after group quiescence, inspect and remove the exact owned Docker
  container if present; re-inspect after the removal. A failed signal, group
  quiescence check, Docker command, or inspection makes cleanup uncertain.
  A momentary absent-container result does **not** guarantee the Docker
  daemon has no outstanding request, so the durable record must describe
  these observations rather than assert unconditional safety.
- After any timeout or interruption, stop the mode and do not start another
  item or mode automatically, even if local cleanup observations look good.
  Keep completed records and uncertain in-flight IDs in the partial summary;
  never count an uncertain attempt as valid or comparable.
- Make the CLI shutdown behavior honest: either all worker processes finish
  within a bounded cleanup window or the command remains explicitly
  incomplete and the external VM watchdog must stop the machine. Do not
  present `shutdown(wait=False)` as a bound on interpreter exit.

## Tests and acceptance

1. Retain the 172 passing local tests as the pre-change baseline, then add a
   deterministic real-POSIX subprocess test: an evaluator-like parent spawns a
   delayed descendant and exits on SIGTERM. The new cleanup must terminate
   the group before reporting a clean local state; the descendant must not
   execute its delayed action. No real Docker or Nebius is needed for this.
2. Fake-Docker tests verify exact-name removal, failed inspection as uncertain,
   no unrelated-container action, no new launches after a timeout, and durable
   partial summaries. Deliver real OS SIGTERM/SIGINT to the CLI in a separate
   local process, rather than invoking a handler directly.
3. Review the direct `KeyboardInterrupt` API path and the pre-summary phase so
   already-submitted work is not silently removed from `in_flight_ids`.
   These are secondary to the POSIX CLI path but must be documented or fixed.
4. An independent reviewer checks the new tests against the pinned upstream
   lifecycle and rejects any claim that a Docker absence poll alone proves
   containment. Full local tests and `git diff --check` must pass.

## Cloud gate and residual risk

This design does not authorize starting the VM. Before even the two-episode
pilot, separately verify Nebius account, credit, quota, live VM/storage rate,
remaining resource state, and a user-approved run-specific cap. Arm an
independent watchdog outside the runner that stops the exact VM by the cap's
deadline and verifies `STOPPED`; do not rely on Python thread shutdown or
Docker inspection to enforce the spending limit. If any attempt is uncertain,
abort the pilot/comparison, stop the VM, preserve partial evidence, and
investigate before resuming. Real Docker and server behavior still require
that bounded pilot; local tests cannot certify them.
