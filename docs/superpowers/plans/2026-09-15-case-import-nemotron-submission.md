# Replayable Case Import and Submission Completeness Plan

**Status:** proposed for Jethro's design review; no new model, import format,
search algorithm, or Token Factory spend is authorized by this document.
Jethro subsequently delegated the license choice: Apache-2.0 is selected and
implemented. Jethro also prioritized a usable, scalable first import: pursue
one replay-feasible LIBERO/robomimic-style HDF5 adapter after inspecting a real
sample. Exact reader/schema and Nemotron endpoint remain design decisions.
See the [artifact and model research](../../research/2026-09-15-production-artifacts-and-nemotron.md).

**Goal:** Let a robotics engineer bring a supported failure case, confirm and
shrink it under a compute budget, then inspect a grounded diagnostic report.
Use Nemotron where it helps triage or explain evidence, and meet the hackathon's
repository-license requirement.

## Product boundary

A video is evidence of an episode, not a sufficient replay input. It does not
normally reveal the policy checkpoint, simulator version, initial state, random
seeds, robot state, camera streams, task instruction, actions, or exact
perturbation. Inferring those from pixels and claiming a replayable failure
would be misleading.

The first import should accept an **existing supported artifact**, not require
users to export a proprietary bundle. Generate the internal case index below
from its available metadata and ask only for missing replay prerequisites:

```text
case manifest
  + policy/checkpoint and evaluator/simulator revisions
  + task, instruction, episode index, seed and initial state
  + approved perturbation family and exact parameters
  + recorded outcome, action/trace references and evidence paths
  + MP4 preview (optional for computation, important for inspection)
```

Existing aggregate/config/evidence artifacts are the starting point for this
contract. Import must validate identity and file references before any GPU
replay; an unsupported checkpoint, missing initial state, inconsistent outcome,
or media path outside the selected bundle is rejected with a useful reason.
The deterministic evaluator, not an AI narrative, decides whether the robot
completed the task. An imported result is a **suspected case** until fresh
replays and matched nominal controls support it.

An MP4-only mode is a later, separate **visual triage** feature: it can propose
what appears to happen and which supported fault family might be worth testing,
but must display `unverified / cannot replay from video alone`. It cannot feed
the reducer or create a regression test without a compatible case bundle.

## Scope and ordering

| Phase | Deliverable | Gate |
| --- | --- | --- |
| 0. Finish the accepted fixed-area cloud grid | Real bounded M2 evidence, even if negative | Fresh Nebius preflight and Jethro-approved cap; no import/Nemotron changes in that preregistered run |
| 1. License decision | Apache-2.0 added by Terra under delegated choice; README and package metadata updated | Local verification complete; GitHub visibility checked after authorized publication |
| 2. Existing-artifact adapter and case contract | Read-only import of a real replay-feasible LIBERO/robomimic-style HDF5 episode; episode/capability interface can accept later adapters | Inspect actual sample/reset prerequisites before implementation; exact schema and rejection rules are reviewed; fixture and traversal tests pass |
| 3. Confirm and reduce | Replays imported suspected case, checks matched nominal controls, reduces only the already-approved fault family | Jethro approves reducer/search budget and failure predicate; positive demo requires actual valid outcomes |
| 4. Nemotron pilot | Evidence-grounded triage and candidate suggestions through Nebius Token Factory | Model/API availability, input format, cost, credentials, and output quality are checked before billable calls |
| 5. Product demonstration | Viewer shows import identity, budget/progress, nominal/failing/reduced videos, exact replay recipe, cost, and uncertainty | A fresh operator can complete the flow; no unsupported causal or robustness claims |

Phases 2–5 should be separately scoped design/spec/implementation cycles. They
are not prerequisites for the fixed-area grid session. If that session finds no
failure, Jethro chooses the next bounded fault-search space before Phase 3;
the import interface must not be used to manufacture a positive outcome.

### License decision (Phase 1)

Devpost requires an open-source license visible at the top of the public
repository. Recommend **Apache-2.0** for this robotics tooling project because
its explicit patent grant can help future reuse; **MIT** is a shorter,
permissive alternative. This choice governs *our code*, not GR00T weights,
LIBERO assets, third-party libraries, or imported videos. Their upstream terms
and redistribution rights must be documented separately. Jethro delegated the
choice on September 15; Apache-2.0 was selected and Terra added the exact steward
text at `LICENSE`, with README and package metadata. No copyright holder was
invented. Verify GitHub displays the license after publication. Do not generate a custom
license or copy third-party media into the public repository without rights.

### Nemotron role (Phase 4)

Keep GR00T as the action-producing robot policy on Nebius AI Cloud. The first
meaningful Nemotron contribution should be an **evidence-grounded diagnostic
assistant**, not a substitute for success metrics:

1. Receive a compact, bounded evidence packet: task identity, nominal and
   failing outcomes, exact perturbation, timings, selected trace events, and
   optionally sampled frames if the verified Token Factory model/API supports
   them.
2. Return structured *hypotheses* and suggested next tests restricted to the
   already-approved fault family, each citing input evidence and stating what
   is unknown. It must not assert causality, change the failure predicate, or
   secretly reorder the current fixed grid.
3. Show suggestions beside deterministic replay/reduction results in the
   viewer. The operator chooses whether to run a suggestion, inside a separate
   approved budget.
4. Compare useful suggestions, unsupported claims, latency, and token cost on
   held-out cases or expert-reviewed fixtures against a no-Nemotron report and
   a simple rule-based candidate list. Retain Nemotron only if it improves the
   user's diagnosis or test choice measurably.

Nebius lists Nemotron models through Token Factory's compatible API, and has
described Nemotron Nano 2 VL as capable of video understanding. The exact
currently accessible model, video/frame API shape, data-retention setting,
regional availability, and price still need live verification. A text-only
Nemotron model can consume structured traces; it must not be described as
having inspected video. Token Factory credentials stay in local auth/secret
storage and never in chat, experiment artifacts, or Git.

### Design acceptance (Phase 5)

One coherent demo path should answer the user's questions in order:

```text
What case did I import?
  -> Is it compatible and safe to replay?
  -> Did the suspected failure repeat, and did nominal controls pass?
  -> What smaller trigger still fails?
  -> How much GPU time and money did this take?
  -> How do I replay the regression case?
```

The viewer already supplies paired video, timeline, fault coordinates, outcome
labels, and preserved raw artifacts. Extend that existing workbench around the
case lifecycle rather than building a separate general dashboard. A CLI may
run paid experiments if the viewer clearly exposes status, evidence, and a
recipe. The Physical AI video should show the key application modules working
for at least one minute, including import, search/confirmation, reduction,
and the final report. A staged fixture may explain UI behavior, but the
claimed failure and cost metrics must come from real, identified executions.

## Concurrency, ownership, and learning checkpoints

```text
fixed-grid result
  -> human choice of next search/reducer boundary
      -> bundle schema + import validator
      -> Nemotron API/model feasibility (read-only, parallel)
      -> viewer journey sketch (parallel)
  -> integration and independent evidence review
  -> human decision on model, budget, import format and report claim
```

| Workstream | File ownership when planned for execution | Output |
| --- | --- | --- |
| Case contract/import | new case module and focused tests, no viewer files | Accepted manifest, safe validator, real-bundle compatibility check |
| Nemotron feasibility | research notes and isolated client prototype/tests, no import module | Available model/API/cost evidence and grounded-output evaluation |
| Viewer journey | existing viewer web files and viewer tests, no import module | Case-state and report design that reuses evidence panels |
| Integration owner | main plan, decision records, Git and cloud/Token Factory lifecycle | Combined review, cost accounting, and one coherent user journey |

Use parallel agents only for substantial independent work with nonoverlapping
files. One owner manages external resources and spending. At each red gate,
explain alternatives and evidence to Jethro: bundle vs MP4-only import,
supported fault family, reducer algorithm and cap, Nemotron model/input mode,
and external data rights. The code license is now settled. Green implementation may proceed after those decisions;
claims for the submission require a human interpretation checkpoint.

## Sources and claim limits

- [Hackathon requirements and judging criteria](https://nebiusglobalaihackathon.devpost.com/): NVIDIA open-source model on Nebius, open-source license, public repository, and a complete product experience.
- [Nebius Nemotron/Token Factory](https://nebius.com/services/token-factory/nemotron): available model family and compatible API; live account availability is a separate check.
- [Nebius Nemotron Nano 2 VL](https://nebius.com/blog/posts/nvidia-nemotron-nano-2-vl-in-ai-studio): published video-understanding capability, not proof of the exact current endpoint contract.
- [Apache-2.0](https://opensource.org/license/apache-2.0) and [MIT](https://opensource.org/license/mit): authoritative license texts and comparison points.

The product's measured claim remains narrow: for a named policy, task, initial
state, and approved perturbation family, find a failure within an explicit
compute budget, confirm it repeats, shrink its trigger, and save a replayable
case. Imported videos or Nemotron prose cannot establish those facts alone.
