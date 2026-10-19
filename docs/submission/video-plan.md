# Faultline pitch video — review draft

Target **2 minutes 40 seconds**, leaving margin below three minutes. This is
a shot list and narration draft, not a rendered video. Use existing recordings
and the gallery/local panel; do not launch a paid run to obtain footage.

Audience: engineers evaluating or fine-tuning robot manipulation policies.
Lead with the debugging problem and one real case, not setup instructions.

## Timed route and narration

| Time | Screen/shot | Spoken draft |
| --- | --- | --- |
| 0:00–0:15 | Faultline title, then failing robot clip | “A robot benchmark tells you how often a policy fails. It doesn't give you a small test that reproduces one failure. Faultline turns those failures into replayable regression tests.” |
| 0:15–0:30 | Local New diagnosis Review: untouched check and two branches; never press Start | “Choose a task and start, then review the compute budget. Faultline checks the policy untouched. A reliable failure goes to layout reduction; a passing start goes to controlled probes.” |
| 0:30–1:05 | FL-S-8E0D, original/minimal/reference clips; Summary and Candidates | “Here, NVIDIA GR00T N1.7 fails from a LIBERO start. Faultline compares a passing layout and reruns smaller combinations. These four shifts reproduce the failure together. Remove any one and it no longer meets our failure gate. The retained sizes aren't a global minimum; the report keeps that limitation visible.” |
| 1:05–1:25 | FL-A-D582 videos and levels table | “From another untouched passing start, blur repeatedly breaks the task. The saved threshold also failed four out of five replay attempts. Noise was borderline on replay, so it isn't the headline result.” |
| 1:25–1:40 | Regression test history and saved replay inputs, no new Replay action | “Keep the inputs, videos and report as a regression case. The recorded replay still fails on the original policy. A compatible updated checkpoint can be tested against the same saved condition.” |
| 1:40–2:05 | Nemotron ranking versus actual candidates; labeled Next steps/source links | “Nebius AI Cloud Serverless Jobs run the GPU simulations and GR00T policy. NVIDIA Nemotron on Nebius Token Factory ranks what to test and interprets recorded evidence. Tavily supplies research context for suggested next steps. The model proposes; simulator reruns decide. Suggestions aren't proven fixes.” |
| 2:05–2:25 | FL-A-F526 no-failure result, tested ranges; compact architecture view | “No failure found is useful too: this start survived these tested ranges. These are bounded results in simulation, not real-robot safety guarantees. Faultline joins discovery, confirmation, reduction and replay in one inspectable workflow.” |
| 2:25–2:40 | Gallery URL and repository, title/closing frame | “Explore three recorded cases free in the public gallery. Install Faultline to run your own diagnoses. The goal is a smaller, repeatable debugging case—not another average success rate.” |

## Footage and truth checks

- Keep **at least 75 seconds of legible application modules operating** in
  the final cut: the continuous 0:15–1:40 route already allocates 85 seconds
  before any slides. Exclude title/slides from that count and verify the
  actual edit. Follow the current Physical AI no-hardware alternative in
  [the readiness audit](readiness-audit.md#current-rules-check).
- Label saved results “Recorded Nebius run”; label Review “Budget preview —
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
- Hide address-bar private paths, CLI IDs, keys, billing/account screens and
  unrelated tabs. Use only authorized footage/fonts/music; silence is better
  than unlicensed background music.

## Cover concept and production gate

A screenshot-derived cover: **Faultline** / “Turn robot failures into
replayable tests”, paired failing/passing robot frames and a small
“Find → Confirm → Reduce → Replay” line. Keep text readable at thumbnail size.
No new logo or brand direction is required.

The project owner reviews the story and chooses narration (own voice recommended for a
personal pitch; any alternative must be approved). Then record/edit the
existing UI, measure final duration and module-footage time, review the cover,
and obtain explicit approval before public YouTube upload and submission.
