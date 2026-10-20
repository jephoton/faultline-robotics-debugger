# Faultline pitch video — review draft

Target **2 minutes 45 seconds**, leaving 15 seconds below three minutes. This is
a shot list and narration draft, not a rendered video. Use existing recordings
and the gallery/local panel; do not launch a paid run to obtain footage.

Audience: engineers evaluating or fine-tuning robot manipulation policies.
Positioning: **a debugging workbench for robot foundation models**. GR00T is
the policy under test; Nemotron assists experiments and interpretation. The
program's repetition/reduction rules and simulator outcomes establish the
measured findings, not an LLM's diagnosis. Follow the same story as the
[Devpost draft](devpost-draft.md), using one real case rather than setup steps.

## Timed route and narration

| Time | Screen/shot | Spoken draft |
| --- | --- | --- |
| 0:00–0:15 | Failing robot clip in the app; Faultline name visible | “A robot's success rate doesn't tell you how to reproduce one failure. Faultline is a debugging workbench for robot foundation models: find a failure, confirm it, reduce its trigger, and save a replayable test.” |
| 0:15–0:35 | Local New diagnosis Review: task/start, budget and two branches; never press Start | “Choose a task, starting state and budget. Faultline tests the policy unchanged. A repeatable failure goes to layout reduction. A passing start goes to image, scene or instruction tests.” |
| 0:35–1:15 | FL-S-8E0D: original/reduced/reference videos, then Summary/Candidates showing basket, milk, orange juice and arm | “Here, NVIDIA GR00T fails four out of five attempts in LIBERO simulation. Faultline compares a passing layout and tests smaller combinations of changes. Four shifts are needed together: the basket, milk, orange juice and robot arm. Remove any one and the result no longer meets the failure threshold in these tests. The sizes aren't proven smallest.” |
| 1:15–1:35 | Same case: recorded regression result and saved replay inputs; no Replay action | “The case keeps the inputs, videos and report. A recorded replay still fails on the original policy. An engineer can test a compatible updated checkpoint against the same saved condition.” |
| 1:35–1:55 | FL-A-D582: paired blur video, levels and replay result | “On another starting state, blur causes a repeatable failure, including four out of five replay attempts. Noise falls below the threshold on replay, so the report treats it as borderline.” |
| 1:55–2:20 | Existing Nemotron ranking/next steps; simple on-screen labels for Jobs/GR00T and Token Factory/Nemotron | “Nebius AI Cloud Serverless Jobs run GR00T and the simulations. NVIDIA Nemotron on Nebius Token Factory ranks layout hypotheses, generates instruction rewordings and explains results. Tavily finds research for suggested next steps. Simulator reruns decide the outcomes, not the model's explanation.” |
| 2:20–2:35 | FL-A-F526: no-failure finding and tested ranges | “This third case found no reliable failure within the tested ranges. Faultline reports that too. These are simulation results, not real-robot safety guarantees.” |
| 2:35–2:45 | Gallery and repository links; hold closing frame | “Explore three recorded cases in the free gallery. Install Faultline to run your own diagnoses.” |

Read only the spoken column. Do not narrate case IDs, headings or every table
row. Finish each line, then let the evidence stay visible for the rest of its
slot. Pre-open the pages; cut between them rather than recording navigation
delays. If a take runs long, shorten transitions—not playback by speeding up
the robot clips. No architecture walkthrough or setup tutorial is needed.

## Footage and truth checks

- For the layout narration, show all four retained shifts clearly in Summary:
  basket, milk, orange juice and robot arm. Do not leave “these four shifts”
  dependent on an unlabeled video alone.

- Keep **at least 75 seconds of legible application modules operating** in
  the final cut: 0:15–1:55 allocates 100 seconds of setup preview, evidence,
  tables and replay history. Include robot-video playback and actual UI
  interactions, not only still screenshots. Exclude title/slides and verify the
  actual edit. Follow the current Physical AI no-hardware alternative in
  [the readiness audit](readiness-audit.md#current-rules-check).
- Label saved results “Recorded Nebius simulation”; label Review “Budget preview —
  no run started”. Do not fake live progress or imply public execution.
- Case IDs: layout `FL-S-8E0D`; blur `FL-A-D582`; bounded pass `FL-A-F526`.
  [Layout/blur evidence](../experiments/m7-final-showcase.md),
  [F526 measurements](../experiments/m7-breadth-pack.md),
  [click route](../ui-runbook.md).
- Use the paired videos at a readable speed, not a rapidly scrolled terminal.
  Verify final spoken numbers against the report; do not say blur fails
  “every time,” since replay was four of five.
- Show actual Nebius/NVIDIA names with spoken attribution, not a logo-only
  slide. No invented customer quote, causal proof, automatic CI deployment,
  globally minimum layout or measured diagnostic cost saving.
- Do not call Faultline an autonomous AI scientist, a new embodied agent or
  an LLM-powered reducer. GR00T is central as the robot policy being tested;
  Nemotron's assistance is real, but its effect on search efficiency has not
  been measured. Model ranking must remain visibly distinct from rerun results.
- Hide address-bar private paths, CLI IDs, keys, billing/account screens and
  unrelated tabs. Use only authorized footage/fonts/music; silence is better
  than unlicensed background music.

## Recording and publication

The project owner has completed screenshots and cover and is producing the
video; no further agent media review is requested. Record from existing
evidence only. Check the final exported duration, module-footage time and
private information yourself. Use public YouTube under the current specific
hackathon rules. A word-count/timing plan does not certify a finished recording.
No upload or submission is performed by editing this script.
