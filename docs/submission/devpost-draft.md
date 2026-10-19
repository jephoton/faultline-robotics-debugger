# HUMAN REVIEW DRAFT — Devpost submission

No claims in this draft have been submitted. Review the wording, first-hand tool feedback, and billing before submission.

## Project title

**Faultline: turn robot-policy failures into replayable tests**

## Tagline

Find a failure, check that it repeats, reduce its trigger, and keep it as a regression test.

## The problem

A benchmark success rate tells a robotics engineer how often a policy succeeds. It does not point to the conditions behind one failure. Engineers still need to locate a failed rollout, reproduce it despite policy and simulator variability, work out which conditions matter, and check whether the failure returns after a model update.

Faultline takes a failing or passing LIBERO start and runs a diagnosis workflow. It first checks the untouched start. A reliable failure goes through layout reduction against a passing reference. A passing start can be tested against selected image, scene, and instruction disturbances. A flaky start is reported as flaky rather than blamed on a probe. Confirmed findings are saved with their inputs, evidence, and replay path.

## What we built

The contribution is the integrated diagnostic loop for modern vision-language-action manipulation policies: search, repeatability control, counterexample reduction, inspection, replay, and GPU time/cost measurement. Evaluation harnesses, perturbation tests, simulation search, and parallel execution already exist; Faultline does not claim any one of those primitives as its novelty.

In the October 19 showcase, the layout case began with LIBERO-10 task 0, start 14, which failed 4 of 5 attempts. Faultline compared it with passing start 4 and identified four entity shifts needed together: basket, milk, orange juice, and the robot arm. The saved case replayed with the minimal scene failing again and the reference passing 5 of 5. The record explicitly warns that the retained shifts are verified to reproduce, but are not proven to be the smallest possible sizes; the size search was budget-limited and showed non-monotone outcomes. [M7 showcase record](../experiments/m7-final-showcase.md)

In the probe case, LIBERO-Object task 0, start 0 passed untouched. Blur at severity 0.4625 (sigma 3.70 pixels) failed 5 of 5 attempts in the search and 4 of 5 on replay, meeting the repeatability gate both times. Noise was borderline: 4 of 5 at full strength in the search but 3 of 5 on replay. Darkening and contrast did not trigger failures at the tested levels. This makes blur the robust finding; noise is not presented as confirmed. [M7 showcase record](../experiments/m7-final-showcase.md)

The third case, LIBERO-Spatial task 0, start 0, kept succeeding through its tested image probes. At full tested strength, that included JPEG quality 5, a strong colour cast, 20% dead pixels, and motion blur; motion blur failed once in five attempts, below the gate. This is a bounded “nothing broke it in these ranges” result, not a robustness guarantee. [Breadth-pack measurements](../experiments/m7-breadth-pack.md)

## How it works and what we used

Faultline runs LIBERO through the AllenAI VLA evaluation harness, robosuite/MuJoCo, and NVIDIA GR00T N1.7 checkpoints. Nebius AI Cloud Serverless Jobs run the diagnoses and replays on one L40S GPU per job; private Object Storage holds run evidence. Nebius Token Factory serves NVIDIA Nemotron models for limited text tasks: Ultra proposes scenario-difference ranking and writes case explanations or suggested next steps, while Super generates instruction paraphrases. The simulator reruns determine measured outcomes; model prose is shown as interpretation, not evidence. Tavily supplies optional public-source context for suggested next steps.

All four LIBERO suites (Object, 10, Spatial, Goal) have run end to end through `faultline diagnose`. That establishes suite-path support, not evaluation of every one of the 40 tasks. The numeric results above come from three showcase cases on specific starts, including a layout comparison between starts 14 and 4. [README scope and results](../../README.md) [workflow evidence](../experiments/m7-workflow-evidence.md)

## Challenges and what we learned

GPU capacity waits sometimes stretched short jobs: in one earlier session, four of nine L40S submissions found no machine after about 27 minutes of retries, with no charge while waiting. Separately, an interrupted evidence download during the layout showcase was traced to unstable workstation networking; it was an operator/network recovery issue, not a Nebius service failure. Retries and resumable downloads were added to the workflow. [FEEDBACK.md](../../FEEDBACK.md) [M7 showcase record](../experiments/m7-final-showcase.md)

The model comparison also changed how the system uses generated text. Different Nemotron variants made factual or formatting errors, while Ultra passed the checked scenario-explanation facts in the comparison. The practical lesson is to give the model computed measurements and ask it to interpret them; reruns and validators remain authoritative. [ADR 0030](../decisions/0030-nemotron-model-per-task.md)

## What’s next

Next is a judge-ready walkthrough, broader task/start evaluation, and a comparison against explicit search baselines using time to first apparent failure, reproducible failure, and reduced failure. Broader perturbation and simulator coverage would be needed before extending the claims. Billing estimates also need reconciliation against posted Nebius charges. The showcase ledger currently estimates US$3.87 total; it is not a finalized billed cost. [M7 showcase record](../experiments/m7-final-showcase.md) [public gallery record](../experiments/m7-public-gallery.md)

## Built with

Python, React, LIBERO, robosuite, MuJoCo, AllenAI VLA Evaluation Harness, NVIDIA GR00T N1.7, NVIDIA Nemotron 3 Nano/Super/Ultra, Nebius AI Cloud Serverless Jobs, Nebius Token Factory, Nebius Object Storage, Tavily, and Vercel (static gallery hosting).

## Try it and inspect the evidence

- [Public case gallery](https://faultline-robotics-debugger.vercel.app) — read-only reports and recordings for the three showcase cases; it does not run diagnoses or replays.
- [Repository and local setup](https://github.com/jephoton/faultline-robotics-debugger) — the bundled offline case viewer needs no cloud account. New diagnoses/replays require a configured Nebius account, model access and paid compute; the public static gallery cannot launch them. The installed control panel and CLI share that execution path.
- [UI runbook](../ui-runbook.md) and [diagnosis quickstart](../setup/diagnose.md).
- [Test commands and scope](../../README.md#local-checks) — Python unit suite and web front-end checks use fakes/CPU-only paths and do not start paid jobs.

## Limitations

Results cover the named checkpoint, simulator/reset setup, starts, and tested perturbation ranges only. The four-suite path does not mean all 40 tasks were tested. Reduction does not establish a global minimum or causal proof; the layout size search can retain a verified trigger that may not be the smallest. The public evaluation evidence for start 14 concerns a different GR00T checkpoint and does not show the same cause. The system does not validate whether suggested remedies work. Cross-simulator compatibility, physical-robot behavior, universal checkpoint compatibility, and cost savings have not been established. Showcase cost figures are estimates pending billing reconciliation.

**Pre-submit review gate (not submission prose):** the gallery and offline build are free to inspect, but new GPU work is not free hosted execution. Review the rules' testing-access requirement and obtain organizer clarification if that account-free test build is insufficient; do not promise sponsor-paid experiments without authorization.
