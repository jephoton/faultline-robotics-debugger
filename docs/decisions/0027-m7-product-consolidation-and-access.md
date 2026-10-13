# ADR 0027: M7 product consolidation and access options

**Status:** Direction accepted by Jethro on October 13, 2026. Details (spec
schema, command names, image distribution, publishing) go through the M7
design checkpoint before implementation.

## Problem

M2–M6 built and validated the engine (search, confirm, reduce; batched cloud
execution; rectangle and scalar families; viewer, explanation, research), but
the product surface lags: the cloud lifecycle lives in coordinator scratchpad
scripts, Job modes are named after experiments, task and seed are constants,
and only the M4 case reaches the viewer. Faultline should feel like a tool
anyone can run, not a series of personal experiments.

## Decision

After the M6 threshold Job, stop new experiments. M7 becomes two parts.

**M7a — product consolidation**

1. `faultline diagnose <spec.yaml>`: one command taking a declarative spec
   (policy/model server, task(s), seed(s), perturbation families, budget,
   backend). It owns the full lifecycle that scratchpad scripts did by hand:
   results bucket, Job submit, watchdog, download, teardown, with a per-run
   spend cap and hard deadline.
2. One general Serverless job mode driven by the spec, replacing the
   experiment-named modes for new runs (old modes stay for replaying recorded
   evidence).
3. Automatic case import: each confirmed, reduced failure becomes a viewer
   case with videos, minimal trigger, evidence, explanation and research, plus
   `faultline replay <case>`.
4. Optional service-account authentication so runs do not need daily
   interactive sign-in (key kept local, scoped to one project, never
   committed).

**Centrepiece (added October 13): reduce a failure you bring.** A robotics
team imports a failing simulation run (a LIBERO-format episode or start
state); Faultline confirms the failure repeats, then reduces the *scenario*:
it delta-debugs the differences between the failing start state and the
task's normal passing start state (object poses, robot pose), rerunning the
policy with the existing 4-of-5 repeatability gate, until only the
differences needed for the failure remain. Output: a minimal cause ("the soup
rotated 30 degrees is enough") as a replayable regression case. Nemotron may
propose the order in which differences are tried and explains the result;
only reruns establish the reduced case. This needs broader import (any
original LIBERO demo, task and suite, including failing runs) and state
interpolation in the simulator. Image-space families remain as the
stress-test mode ("smallest disturbance that breaks the policy"), with a
small curated catalog added as spec options.

**UI polish/overhaul (added October 13):** the viewer gets a product-grade
pass centred on the user journey: import → diagnose → reduced case →
replay, with clear status, original-versus-minimal comparison and the
explanation and research panels.

**Access options (all three):**

- **A. Public gallery of finished cases:** a read-only published page of the
  reduced failures already found. Free to browse. Publishing needs Jethro's
  explicit go at the time.
- **B. Local GPU backend:** the same image runs on a machine with a large
  NVIDIA GPU (`--backend local`), no cloud account needed.
- **C. Nebius backend in the user's own project:** framed as "deploy to your
  Nebius project". Each user's runs bill to their own account; Jethro's account
  pays only for runs he submits. Requires a way to obtain the image (build
  from the Dockerfile or a public registry such as GHCR; decided at the
  checkpoint).

Rejected: **D. hosted run service on Jethro's account** (needs auth, quotas
and abuse protection; Jethro would pay for others' runs).

**M7b — submission:** demo video, write-up and FEEDBACK reconciliation,
showing the M7a flow end to end with the M6 wrist and blur findings as the
example story. Deadline October 30, 10:00 PT; target October 29; M7 starts no
later than October 23 (ADR 0023), earlier now that M3 and M6 are done.

## Consequences

The roadmap in ADR 0023 is amended: the portfolio fallback is dropped (M3
batching succeeded) and remaining time goes to M7a then M7b. Each M7a piece
still needs its own plan, review and spend gate.
