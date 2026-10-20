# HUMAN REVIEW DRAFT — Devpost submission

Nothing in this draft has been submitted. The sections below map to the form supplied by the project owner on October 21. Copy only the story between its markers into **About the project**; tags, links, media notes and internal checks belong outside that field.

## Project title

**Faultline: turn robot-policy failures into replayable tests**

## Tagline

A debugging workbench for robot foundation models: find repeatable failures, reduce their triggers, and keep replayable regression tests.

## Project Story → About the project

<!-- BEGIN ABOUT THE PROJECT: copy from the following heading through Limitations. -->

## Inspiration

A robot foundation model can score well on a benchmark and still fail on one scene. What does an engineer do with that one failure? Reproduce the rollout, isolate a reproducible triggering condition, and save a regression test for future policy changes.

Faultline grew from an interest in robotics and reproducible debugging: moving beyond an average success rate to a concrete case someone can investigate. The guiding idea is to make a robot-policy failure as inspectable and replayable as a software bug.

## What it does

Faultline is a debugging workbench for robot foundation models. Within a configured compute budget, it checks a LIBERO start, probes selected image, scene or instruction changes when it passes, or reduces a failing scene against a passing reference. Repeated runs separate reliable findings from flaky outcomes. Confirmed cases keep inputs, evidence, and a replay path together.

The contribution is that integrated debugging workflow, not a new robot policy or reduction algorithm. It gives an evaluation engineer a concrete case to investigate and replay, rather than only an aggregate score.

## What we demonstrated

In the layout case, GR00T N1.7 failed 4 of 5 attempts on LIBERO-10 task 0, start 14. Against passing reference start 4, four shifts reproduced the failure together: basket, milk, orange juice, and robot arm. Removing any one lost the failure gate in those tests. The reduced scene failed on replay; the reference passed 5 of 5. Budget limits and non-monotone results mean these are not proven to be the smallest shift sizes.

In the image-probe case, LIBERO-Object task 0, start 0 passed untouched. Gaussian blur at severity 0.4625 (sigma 3.7 pixels) failed 5 of 5 search attempts and 4 of 5 replay attempts, meeting the repeatability gate. Noise was borderline: 4 of 5 in search, 3 of 5 on replay, below the gate. Blur is confirmed; noise is not.

In the third case, no tested probe met the failure gate. LIBERO-Spatial task 0, start 0 passed untouched; JPEG, colour-cast and dead-pixel probes did not trigger reliable failures. Motion blur caused one failure in five attempts at maximum tested strength, below the gate. This is a bounded result, not a general robustness guarantee.

The [public case gallery](https://faultline-robotics-debugger.vercel.app) also includes a rewording screen: the original instruction succeeded twice, and four Nemotron-written variations each succeeded once and passed the mechanical meaning check. No wording failure was found in that screen. The gallery has four examples; videos accompany the three original showcase cases, not the rewording screen.

## How we built it

Faultline is a Physical AI simulation and policy-evaluation tool built around LIBERO, the AllenAI VLA evaluation harness, robosuite, and MuJoCo. GR00T N1.7 is the closed-loop policy under test; diagnosis and replay jobs ran on Nebius AI Cloud Serverless Jobs, using one L40S GPU per job. Run evidence is stored in Nebius Object Storage.

NVIDIA Nemotron on **Nebius Token Factory** assists the workflow: Ultra ranks layout hypotheses before reruns, writes scenario explanations and suggests next steps using optional Tavily research; Super generates instruction variations. Earlier research summaries used Nano. Programmed gates and simulator reruns decide whether a failure repeats or a reduced case reproduces; generated text is not proof of cause.

A Python backend connects the experiments to a React workbench for reviewing a run, comparing videos, inspecting tested conditions, and replaying saved cases. A separate static gallery shares recorded evidence without exposing cloud controls. All four LIBERO suite paths—Object, 10, Spatial, and Goal—run end to end through `faultline diagnose`. That is path support, not testing all 40 tasks.

## Challenges and what we learned

GPU capacity waits sometimes stretched short jobs. Two interrupted layout-evidence downloads were traced to workstation networking, then addressed with retries and resumable downloads. Recovering a run should mean retrieving the evidence, not paying to repeat an experiment that already finished.

Robotics outcomes were not always consistent. The noise result looked convincing during search, then fell below the repeatability gate on replay. That made confirmation a product requirement rather than an optional chart.

Model errors reinforced another boundary: give Nemotron computed facts to interpret, but keep outcome checks in code. Its assistance is demonstrated; an improvement in diagnostic speed or cost is not. The work also taught us that a useful robotics debugging interface must make uncertain and negative results as visible as a successful reduction.

Specific onboarding notes, strengths and friction for Nebius AI Cloud, Token Factory and the NVIDIA models are recorded in the repository's [tool feedback](https://github.com/jephoton/faultline-robotics-debugger/blob/main/FEEDBACK.md).

## What's next

With the working diagnosis, inspection and replay workflow in place, the next step is broader validation. We want to compare Faultline with simpler grid and random searches, measuring the time and compute cost needed to find a repeatable failure and reduce its triggering condition. Testing more robot tasks and starting states would also show how broadly the current findings generalize. These are future experiments, not results claimed by this submission.

## Limitations

The demonstrated results cover specific GR00T checkpoint, simulator, task and starting-state configurations within the tested perturbation ranges. A reduced case preserves a repeatable failure, but is not necessarily the smallest possible trigger or proof of the underlying cause. We have not established the same behavior on arbitrary robot policies or physical robots. Nemotron's explanations and suggested next steps remain hypotheses, not verified fixes, and we have not yet shown that the diagnostic workflow saves time or money compared with simpler searches.

<!-- END ABOUT THE PROJECT -->

## Built with → tags

Enter these separately, using the closest available tag spelling. **16 suggested tags**, within the supplied 25-tag limit:

- Python
- TypeScript
- React
- LIBERO
- robosuite
- MuJoCo
- AllenAI VLA Evaluation Harness
- NVIDIA GR00T N1.7
- NVIDIA Nemotron 3 Ultra
- NVIDIA Nemotron 3 Super
- NVIDIA Nemotron 3 Nano
- Nebius Token Factory
- Nebius AI Cloud
- Nebius Serverless Jobs
- Tavily
- Vercel

Object Storage is named in the story; tags need not enumerate every dependency. Nano reflects earlier model use, not the default for current next-step generation.

## Try it out → links

| Link label | URL |
| --- | --- |
| Explore recorded cases — read-only demo | https://faultline-robotics-debugger.vercel.app/ |
| Source code and local setup | https://github.com/jephoton/faultline-robotics-debugger |

The bundled offline viewer needs no cloud account. New diagnoses and replays require the operator's own configured Nebius account, model access and paid compute; the public gallery cannot launch them.

## Project Media → image gallery

No image files have been produced by this draft. Suggested initial set:

1. Cover: Faultline name, failing/passing robot frames, and “Find → Confirm → Reduce → Replay.”
2. Layout case: paired evidence and the four retained shifts, with its reduction limitation visible.
3. Image-probe case: blur evidence and the levels/repeatability table.
4. System overview: a legible diagram of local workbench → Nebius Jobs/GR00T → saved evidence, with Token Factory/Nemotron shown separately.

Use JPG, PNG or GIF, each at most 5 MB; prefer 3:2. The supplied form permits up to 15, but there is no need to fill every slot. Hide private paths, cloud identifiers and unrelated tabs.

## Project Media → demo video URL

**Pending: insert the actual reviewed video URL.** Do not use the gallery URL here.

The supplied form accepts YouTube or Vimeo and public or unlisted access without a password. The hackathon requirements supplied earlier specifically request a public YouTube video; use that stricter option unless a final rules check confirms otherwise. Keep the finished video under three minutes, with at least one minute of key application modules operating for the Physical AI no-hardware alternative. The [video plan](video-plan.md) targets 2:45; no video has been rendered or uploaded by this drafting step.

## Internal review — do not paste into Devpost

- Final story, entrant/media rights, judge access and publication still require approval. This draft authorizes no upload or submission.
- [Layout/blur source](../experiments/m7-final-showcase.md), [F526 source](../experiments/m7-breadth-pack.md), [model roles](../decisions/0030-nemotron-model-per-task.md) and [workflow evidence](../experiments/m7-workflow-evidence.md) support the story. Local relative links stay here, outside the paste-ready text.
- Tool feedback is approved. The [billing worksheet](billing-reconciliation.md) covers the supplied reporting window, not lifetime or matched per-run costs.
- Audit/draft work remains local on `codex/submission-readiness`. Before final submission, integrate approved repository changes and verify public links and contents; a syntactically valid link is not verification that pending branch changes are publicly available.
- See the [readiness audit](readiness-audit.md#remaining-gates) for remaining gates. Free gallery/offline access is not free hosted GPU execution.
