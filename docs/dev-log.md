# Development issue log

This log records observed engineering issues separately from provider
feedback in [`FEEDBACK.md`](../FEEDBACK.md). A risk identified by review or
tests is not necessarily a failure seen in the live pilot.

## M3: parallel replay and two-episode pilot

| Issue | Evidence and cause | Resolution or boundary | Status |
| --- | --- | --- | --- |
| Evaluator timeout could leave work behind | A local POSIX reproduction showed the pinned harness CLI exiting on SIGTERM while its spawned Docker-client child survived; the old parent-only cleanup reported success too early. | Each evaluator now has its own process group; timeout closes the launch gate, terminates the group, and checks its exact container. A delayed-child regression passes. Docker-daemon requests can still be in flight, so uncertainty aborts the mode and the independent VM watchdog bounds cloud spend. | Local bug reproduced and fixed; residual daemon risk remains. |
| Episode ownership could become ambiguous on interruption | Tests reproduced interruption after submission but before Future registration; review found a second gap when a completed Future was removed before its result was saved. Several mutable lists represented the same attempt. | A durable per-case ledger records intent before submit and result before releasing ownership. Unknown attempts cannot be retried automatically or counted valid. | Local bug reproduced and fixed. |
| Launch or resume could duplicate uncertain work | A missing persisted launch identity made it unsafe to infer whether an evaluator/container had started; partial sessions could not simply rerun missing-looking rows. | Persist exact evaluator PID/container sidecar. Resume only proven-prepared rows in a validated partial session; exclude resumed modes from throughput comparison. | Safety design implemented; no live resume claimed. |
| VM spend could continue after a guest hang | Process cleanup and runner deadlines do not stop the billable VM. A Python thread or Docker request can outlive the runner's summary deadline. | Detached exact-VM workstation guard, guest shutdown backup, approved cap, and stop verification. The September 29 pilot was stopped manually after evidence copy, before the guard deadline. | Mitigation exercised, not a proof against workstation sleep/network/auth loss. |
| Initial pilot SSH and server launch failed | A previously removed temporary SSH ingress rule caused TCP timeout. A first model-server command used the wrong working directory and could not find its script. | Created a temporary narrow SSH rule, launched from the pinned harness directory, then removed the rule after the run. | Operator setup errors resolved; not Nebius/model faults. |
| M3 performance claim is not yet established | The September 29 two-worker pilot produced nominal success and reduced-mask failure with both videos/traces, but it did not run the equal-work 1/2/4-worker comparison or reconcile billing. | Keep the pilot separate from benchmark reporting. Require a new spending decision and complete comparison evidence before claiming throughput or cost improvement. | Open experiment, not a pilot failure. |

The key boundary is **one Nebius VM with several evaluator processes and one
shared GR00T model server**—not several independently started VMs. See the
[M3 experiment record](experiments/m3-parallel.md), [containment design](superpowers/specs/2026-09-28-m3-evaluator-containment-design.md), and [attempt-ownership design](superpowers/specs/2026-09-28-m3-attempt-ownership-design.md).
