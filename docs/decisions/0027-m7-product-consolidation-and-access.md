# ADR 0027: M7 product consolidation and access options

**Status:** Direction accepted by the project owner on October 13, 2026. Details (spec
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

**Breadth pack (added October 13; details at the M7 checkpoint):** so the
product covers real ground without LIBERO-Plus's licence and reducibility
problems.

- **All four LIBERO suites** (spatial, object, goal, LIBERO-10): NVIDIA
  publishes `nvidia/gr00t17-lerobot-libero_{spatial,object,goal,10}-640`
  checkpoints, so suite and task become spec parameters.
- **Simulator-level, reducible families:** camera viewpoint (move the
  simulated camera by a shrinkable offset) and scene lighting (renderer
  lights), complementing the image-space families.
- **Instruction paraphrasing (language family):** Nemotron on Token Factory
  generates paraphrases of the task instruction; Faultline finds the smallest
  rewording that reproducibly breaks the policy.
- **Family catalog:** a few more curated image-space families as spec options.

**Two modes, one engine:** mode 1 "debug your failure" (scenario reduction,
the centrepiece) and mode 2 "audit your policy" (families across visual,
physical-scene and language layers). Both stay in the product and the demo;
the demo leads with mode 1.

**LIBERO-Plus:** still a post-M7 stretch. Its value is simulator-level
variety (real camera/lighting/backgrounds/distractors, language variants) and
comparability with a published benchmark; its costs are predefined variants
that cannot be reduced, no stated licence, and replacing the LIBERO package.
Revisit only if there is slack after about October 25.

**Order:** core story (scenario reduction, broader import, `diagnose`,
automatic cases) → breadth pack → UI overhaul → M7b demo and submission.

**Access options (all three):**

- **A. Public gallery of finished cases:** a read-only published page of the
  reduced failures already found. Free to browse. Publishing needs the project owner's
  explicit go at the time.
- **B. Local GPU backend:** the same image runs on a machine with a large
  NVIDIA GPU (`--backend local`), no cloud account needed.
- **C. Nebius backend in the user's own project:** framed as "deploy to your
  Nebius project". Each user's runs bill to their own account; the project owner's account
  pays only for runs he submits. Requires a way to obtain the image (build
  from the Dockerfile or a public registry such as GHCR; decided at the
  checkpoint).

Rejected: **D. hosted run service on the project owner's account** (needs auth, quotas
and abuse protection; the project owner would pay for others' runs).

**Deployment (added October 13): try deploying Faultline as a website,
likely on Vercel.** Vercel cannot run MuJoCo or a GPU policy, so the site is
the deployed form of access option A: a landing page plus a static export of
finished cases (videos, minimal triggers, evidence, explanation, research)
generated from the case store. It also serves as the submission's demo URL
(optional for the Physical AI track, but useful to judges). Video hosting,
any live Token Factory feature on the site, and the export command are
decided at the M7 checkpoint; publishing needs the project owner's explicit go at the
time. This is the last M7a item, after the UI overhaul.

**Submission track (accepted October 13):** Physical AI. Its text names
GR00T, robot-policy evaluation on Serverless Jobs, and exempts the demo URL;
the video still needs at least one minute of the key modules in action.

**To consider at the M7 checkpoint (October 13):** a demo-only Nebius
Serverless Endpoint serving GR00T, with the simulator running on the
user's CPU and calling it per action chunk (a variant of option B). It
matches the Physical AI track's "Endpoints for real-time inference" line,
which is encouraged, not required. Concerns: it bills the project owner's account while
active (scale-to-zero unconfirmed; an always-on L40S is about US$1.75/h),
needs token auth and rate limits, and adds a network round trip per action
chunk. Only acceptable, if at all, as a short window started by the project owner, with a
spend cap; it does not replace options A to C. **Update (October 13):** made
a stretch goal for the project owner to try closer to the judging period (ADR 0029).

**Startup cut (October 13, labelled M3, ADR 0029):** `faultline diagnose`
(step 4) includes measuring and cutting Job startup (in-region weight
storage, slimmer image), because about 12 minutes of every Job is startup.

**M7b — submission:** demo video, write-up and FEEDBACK reconciliation,
showing the M7a flow end to end with the M6 wrist and blur findings as the
example story. Deadline October 30, 10:00 PT; target October 29; M7 starts no
later than October 23 (ADR 0023), earlier now that M3 and M6 are done.

## Consequences

The roadmap in ADR 0023 is amended: the portfolio fallback is dropped (M3
batching succeeded) and remaining time goes to M7a then M7b. Each M7a piece
still needs its own plan, review and spend gate.
