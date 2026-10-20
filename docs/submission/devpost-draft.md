# HUMAN REVIEW DRAFT — Devpost submission

Nothing in this draft has been submitted. Tool feedback is approved; supplied billing-period totals are recorded, not matched to individual runs or lifetime spend. The publication gate at the end is internal review text, not submission copy.

## Project title

**Faultline: turn robot-policy failures into replayable tests**

## Tagline

A debugging workbench for robot foundation models: find repeatable failures, reduce their triggers, and keep replayable regression tests.

## What if a robot fails on one exact start?

A robot foundation model can score well on a benchmark and still fail on one scene. Robotics engineers need to reproduce that rollout, isolate a reproducible triggering condition, and save a regression test for future policy changes.

Faultline is a debugging workbench for robot foundation models. Within a configured compute budget, it checks a LIBERO start, probes selected image, scene or instruction changes when it passes, or reduces a failing scene against a passing reference. Repeated runs separate reliable findings from flaky outcomes. Confirmed cases keep inputs, evidence, and a replay path together.

The contribution is that integrated debugging workflow, not a new robot policy or reduction algorithm. It gives an evaluation engineer a concrete case to investigate and replay, rather than only an aggregate score.

## The cases

In the layout case, GR00T N1.7 failed 4 of 5 attempts on LIBERO-10 task 0, start 14. Against passing reference start 4, four shifts reproduced the failure together: basket, milk, orange juice, and robot arm. Removing any one lost the failure gate in those tests. The reduced scene failed on replay; the reference passed 5 of 5. Budget limits and non-monotone results mean these are not proven to be the smallest shift sizes. [FL-S-8E0D showcase record](../experiments/m7-final-showcase.md)

In the image-probe case, LIBERO-Object task 0, start 0 passed untouched. Gaussian blur at severity 0.4625 (sigma 3.7 pixels) failed 5 of 5 search attempts and 4 of 5 replay attempts, meeting the repeatability gate. Noise was borderline: 4 of 5 in search, 3 of 5 on replay, below the gate. Blur is confirmed; noise is not. [FL-A-D582 showcase record](../experiments/m7-final-showcase.md)

In the third case, no tested probe met the failure gate. LIBERO-Spatial task 0, start 0 passed untouched; JPEG, colour-cast and dead-pixel probes did not trigger reliable failures. Motion blur caused one failure in five attempts at maximum tested strength, below the gate. This is a bounded result, not a general robustness guarantee. [FL-A-F526 breadth-pack measurements](../experiments/m7-breadth-pack.md)

## How the workbench runs

Faultline is a Physical AI simulation and policy-evaluation tool built around LIBERO, the AllenAI VLA evaluation harness, robosuite, and MuJoCo. GR00T N1.7 is the closed-loop policy under test; diagnosis and replay jobs ran on Nebius AI Cloud Serverless Jobs, using one L40S GPU per job. Run evidence is stored in Nebius Object Storage.

NVIDIA Nemotron on **Nebius Token Factory** assists the workflow: Ultra ranks layout hypotheses before reruns, writes scenario explanations and suggests next steps using optional Tavily research; Super generates instruction variations. Earlier research summaries used Nano. Programmed gates and simulator reruns decide whether a failure repeats or a reduced case reproduces; generated text is not proof of cause. [Model comparison](../decisions/0030-nemotron-model-per-task.md)

All four LIBERO suite paths—Object, 10, Spatial, and Goal—run end to end through `faultline diagnose`. That is path support, not testing all 40 tasks: the results above are three showcase cases on specific starts. [Workflow evidence](../experiments/m7-workflow-evidence.md)

## What we learned and what’s next

GPU capacity waits sometimes stretched short jobs. Two interrupted layout-evidence downloads were traced to workstation networking, then addressed with retries and resumable downloads. [Showcase record](../experiments/m7-final-showcase.md) [Tool feedback](../../FEEDBACK.md)

Model errors also reinforced a design boundary: give Nemotron computed facts to interpret, but keep outcome checks in code. Its assistance is demonstrated; an improvement in diagnostic speed or cost is not.

The next evaluation step is to compare the integrated loop with explicit search baselines and measure time to first apparent failure, reproducible failure, and reduced failure. Broader task and start coverage would show how often the current results generalize. Neither comparison nor broad coverage is established by these three cases.

The [billing worksheet](billing-reconciliation.md) records the supplied reporting window separately from estimated per-run costs; it is not a lifetime project total.

## Built with

Python, React, LIBERO, robosuite, MuJoCo, AllenAI VLA Evaluation Harness, NVIDIA GR00T N1.7, NVIDIA Nemotron 3 Nano/Super/Ultra, Nebius AI Cloud Serverless Jobs, Nebius Token Factory, Nebius Object Storage, Tavily, and Vercel static hosting.

## Try it and inspect the evidence

- [Public case gallery](https://faultline-robotics-debugger.vercel.app) — read-only reports and recordings for the three showcase cases; it does not run diagnoses or replays.
- [Repository and local setup](https://github.com/jephoton/faultline-robotics-debugger) — the bundled offline case viewer needs no cloud account. New diagnoses and replays require the operator’s own configured Nebius account, model access, and paid compute; the public gallery cannot launch them.
- [UI runbook](../ui-runbook.md) and [diagnosis quickstart](../setup/diagnose.md).

## Limitations

The results apply to the named checkpoint, simulator/reset setup, starts, and tested ranges. Reduction does not establish a global minimum or causal proof. The public evaluation evidence for start 14 concerns a different GR00T checkpoint and does not show the same cause. Suggested remedies, physical-robot behavior, universal checkpoint compatibility and cost savings have not been established.

**Internal publication gate — exclude from submission copy:** final wording, entrant/media rights and judge access require review before submission. Free gallery/offline-demo access is not free hosted GPU execution; see the [readiness audit](readiness-audit.md#remaining-gates). No upload or submission is authorized by this draft.
