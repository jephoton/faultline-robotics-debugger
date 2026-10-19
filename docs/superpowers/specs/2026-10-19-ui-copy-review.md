# UI copy review: proposed removals and trims (October 19, 2026)

**Status:** proposed. Jethro selects items by number; nothing has been changed
yet.

**Paths** are under `web/src/`.

**Legacy sections:** `ScenarioSection`, `AuditSection` and
`OcclusionSection` render only for cases without a stored report. Their items
are marked "(legacy)".

**Actions:**
- **REMOVE:** adds nothing.
- **SHORTEN:** keep a shorter version.
- **MOVE:** belongs in the Reference or the Guide.
- **FIX:** inaccurate.

## Home (`pages/HomePage.tsx`)

1. `:21-23`, intro lede: "Faultline finds a failure of a robot policy,
   confirms that it repeats, reduces it to its cause and saves it as a
   replayable case."
   - **REMOVE.** The four-step list below says the same.
2. `:101`, local-mode lede: "Find a robot-policy failure, confirm it repeats,
   reduce it to its cause and keep it as a replayable test."
   - **REMOVE.** It is the same as the Find, Confirm, Reduce, Replay list.
     Keep the static-gallery lede at `:73`.
3. `:34-38`: "Each case below was made by one diagnosis of a GR00T policy on
   LIBERO tasks. It describes the disturbances that were tested and the
   reruns that were made; it does not claim every failure mode, and a reduced
   cause is the smallest one found, not proof of causation."
   - **SHORTEN** to: "Cases cover the disturbances tested and the reruns
     made, not every failure mode. A reduced cause is the smallest one found,
     not proof of causation."
   - The cards already show the suite and task, and "below" is wrong on the
     local home page. The claim boundary stays.
4. `:143-145`: "Made {date}. Every case is listed in the sidebar."
   - **REMOVE.** The date is on the case page, and the sidebar is
     self-evident.
5. `:133-135`: "No cases yet. Start a diagnosis to make the first one."
   - **SHORTEN** to "No cases yet." The New diagnosis button is right there.
6. `:91-93` (static gallery): "Want to run one yourself? Read how to run your
   own."
   - **REMOVE.** The sidebar already links Run your own. Optional: keep it as
     the one call to action for judges.

## Sidebar (`components/Sidebar.tsx`)

7. `:102` and `:104`: "Loading cases." and "No cases yet."
   - **REMOVE.** Home shows the same messages at the same moment. Keep the
     error message and "Nothing running."

## New diagnosis, step 1

8. `NewDiagnosisPage.tsx:127`: "Nothing is created or charged until you
   confirm on the review step."
   - **REMOVE.** The step bar shows Review, and the cost warning sits above
     Start.
9. `StepChoose.tsx:65`, lede `PIPELINE_PROMISE`.
   - **REMOVE.** Option 1's route line says it more precisely.
10. `StepReview.tsx:126`: the same `PIPELINE_PROMISE` on the Review step.
    - **REMOVE.** The Dry run headings (First / If it fails / If it passes)
      cover it.
11. `StepChoose.tsx:9-10`: "A start is one of the benchmark's 50 fixed
    starting layouts for a task: where the objects and the arm begin."
    - **SHORTEN** to "A start is one of a task's 50 fixed starting layouts."
12. `StepChoose.tsx:25-26`, option 1 text.
    - **SHORTEN** to: "The usual choice. Give the task and start of a failure
      from your own LIBERO evaluation (episode n is start n, counted from 0;
      other tools may count differently)."
13. `StepChoose.tsx:38`, option 3 text.
    - **SHORTEN** to: "Upload a saved start-state JSON file for a scene
      outside the 50 benchmark starts."

## New diagnosis, step 2 (`components/new/StepSettings.tsx`)

14. `:115`, Name hint: "Used for the run folder and the case."
    - **REMOVE.**
15. `:141`, Task hint: "Instruction: …"
    - **REMOVE.** The selected option already shows the instruction. Check
      that the select does not truncate at phone width.
16. `:159`, Start hint: "The benchmark start, 0 to 49."
    - **SHORTEN** to "0 to 49."
17. `:184`, Confirm hint.
    - **SHORTEN** to: "Extra attempts after a first failure, 4 to 8. The
      default 4 means a start must fail 4 of 5."
18. `:201`, Start-file hint.
    - **SHORTEN** to: "A JSON start-state file for the suite and task
      above."
19. `:230-232`, Probes hint.
    - **SHORTEN** to: "Off: if the start passes, nothing more runs."
20. `:236-238`, families intro.
    - **SHORTEN:** drop "More families cost more time." Item 21's kept cost
      hint covers it.
21. `:276`, Rewordings hint.
    - **SHORTEN** to: "0 skips rewordings; 1 to 12 are written by Nemotron."
22. `:294`, Spend cap hint.
    - **SHORTEN** to: "The run stops before a Job could take it over."
23. `:305`, Hour limit hint.
    - **REMOVE.** It restates the label.
24. `:323-326`, Nemotron hint.
    - **SHORTEN** to: "Nemotron only proposes an order and a reading; the
      reruns decide the result. It also writes any rewordings, whatever you
      choose here." The key requirement is checked on Review and on Setup.
25. `:339-341`, Research hint.
    - **SHORTEN** to: "Public sources found with Tavily and summarised by
      Nemotron 3 Nano. Context, not evidence."
    - Its wording also needs updating for next steps: "Public sources found
      with Tavily; Nemotron cites them in suggested next steps. Context, not
      evidence."
26. `:351-354`, YAML intro.
    - **SHORTEN:** drop "Once you edit it, the YAML is the source of truth."
      The notice below says it.

## New diagnosis, step 3 and the plan

27. `Review.tsx:119, :206`: the captions "Planned Jobs. … Nothing has been
    created yet."
    - **SHORTEN** to "Planned Jobs", and make the branch caption
      screen-reader-only.
28. `Review.tsx:181`, `TYPICAL_NOTE` (shown up to four times).
    - **REMOVE**, and label the row "Typical (estimate)".
29. `StepReview.tsx:43`: "… You can stop a run at any time."
    - **SHORTEN:** drop that sentence and keep the cost warning.
30. `StepReview.tsx:184-188`, the no-Tavily note.
    - **SHORTEN** to: "Related research will be skipped (no Tavily key). The
      diagnosis is not affected."
31. `StepReview.tsx:190-192`: "Open Setup for how to fix anything above."
    - **REMOVE**, or show it only when a check fails.
32. `StepReview.tsx:213`: "Start is off on this page for safety. Open Running
    in the sidebar to follow the run."
    - **SHORTEN** to "Start is off on this page for safety."
33. `Review.tsx:148`, check text.
    - **SHORTEN** to "With confirmation attempts if it fails."
34. `Review.tsx:150`, layout text.
    - **SHORTEN** to: "Takes the nearest passing start as a reference and
      shrinks the differences to the shifts that cause the failure."
35. `Review.tsx:152`, the probe text's two stop-condition sentences.
    - **MOVE** them to Reference §5.
36. `Review.tsx:225`: "(the check plus the larger of the two branches,
    because only one of them runs)"
    - **SHORTEN** to "(the check plus the larger branch; only one runs)".
37. `Review.tsx:97-103`, the over-cap warning.
    - **SHORTEN** to: "The first Job fits, but not all of them. If earlier
      Jobs cost their worst case, the run stops at X; raise the cap and
      resume."

## Run page

38. `RunPage.tsx:157`: "Fault code (assigned when the case is saved)"
    - **SHORTEN** to "Fault code (pending)".
39. `RunPage.tsx:200`: the interrupted text.
    - **SHORTEN** to: "Resume continues from the last finished step."
40. `RunPage.tsx:209`: the stopping text.
    - **SHORTEN** to: "Waiting for the provider to confirm the cancel; the
      cost is settled then."
41. `RunPage.tsx:221-223`: "The case is saved. Opening it in N seconds."
    - **SHORTEN:** show only the countdown.
42. `RunPage.tsx:237`, the no-case text.
    - **SHORTEN** to: "No case was saved; the log below says why."
43. `lib/runs.ts:87`, the passes detail.
    - **REMOVE.** The title is "Passes untouched".
44. `lib/runs.ts:84`, the flaky detail.
    - **SHORTEN** to: "No disturbance or wording is blamed, and the
      remaining probes are skipped."
45. `RaiseLimits.tsx:62-66`.
    - **SHORTEN** to: "Limits can be raised, never lowered."
46. `RunParts.tsx:60-64`: the last sentence of the waiting text.
    - **REMOVE.** The meter legend covers it.
47. `RunParts.tsx:102`, the meter legend.
    - **SHORTEN** to: "Hatched: worst case held for the running Job."
48. `RunParts.tsx:135`: "Run log (last N lines)"
    - **SHORTEN** to "Last N lines".

## Case page

49. `CommonSections.tsx:297-303`, the Videos hints.
    - **REMOVE.** The clip captions already label each clip.
    - The audit hint is also **inaccurate**: families that never failed are
      shown at their highest severity tried. If a hint is kept, **FIX** it to:
      "The control first, then each tested family at its failure threshold,
      or at the highest severity tried if it never failed."
    - Paraphrase: "The original wording first, then one rewording (a failing
      one if any)."
50. `ScenarioSection.tsx:97` (legacy), the same Videos hint.
    - **REMOVE.**
51. `TeamSections.tsx:18-22`, the trust hints.
    - Scenario: **SHORTEN** to "Counts from the saved reruns; row numbers
      match the # column of the Candidates table under Full evidence."
    - Audit: **REMOVE.**
52. `TeamSections.tsx:67`.
    - **SHORTEN** to "Ranked by Nemotron before any rerun."
53. `CommonSections.tsx:160`, the reading hint.
    - **REMOVE.** The summary, badge and disclaimer already say
      "interpretation, not evidence".
54. `TeamSections.tsx:175`, the full-reading line.
    - **REMOVE**, for the same reason.
55. `CommonSections.tsx:194-195`, `RESEARCH_HINT`.
    - **SHORTEN** to "Context, not evidence."
56. `ReplaySection.tsx:14-21`, the purpose lines ("Run it after you change
    the policy." three times).
    - **SHORTEN:**
      - scenario: "Reruns the minimal scene and its passing reference, five
        attempts each, to check the failure still happens."
      - audit: "Reruns each disturbance that broke the policy at its
        threshold, five attempts each, with the unchanged start as
        control."
      - paraphrase: "Reruns the failing wording, five attempts, with the
        original wording as control."
57. `ReplaySection.tsx:69`, legend "Which policy do you want to test?"
    - **REMOVE** visually (screen-reader only). It repeats "Test a policy".
58. `ReplaySection.tsx:83`, the new-checkpoint card text.
    - **SHORTEN** to "For example a retrained policy."
59. `ReplaySection.tsx:88-91`.
    - **KEEP**, tightened: "A GR00T N1.7 checkpoint in LeRobot format,
      trained for this LIBERO suite. A private repository needs read access
      for the Hugging Face token in your Nebius project."
60. `ReplaySection.tsx:105`, the model id hint.
    - **SHORTEN** to "e.g. the one this case used: X".
61. `ReplaySection.tsx:121`, the revision hint.
    - **SHORTEN** to: "From the model repository's history on Hugging Face;
      it pins exactly which version ran."
62. `ReplaySection.tsx:172-176`, the "In a script: faultline replay …" line.
    - **REMOVE.** Guide §6 already documents `--expect` and
      `policy.checkpoint`.
63. `ReplaySection.tsx:134`.
    - **SHORTEN** to "Planning the test." Optional.
64. `Findings.tsx:34-39`.
    - **REMOVE** the passes and flaky hints.
    - **SHORTEN** the default to: "Each finding is its own case with its own
      report and replay."
65. `ParaphraseSection.tsx:13`.
    - **SHORTEN** to: "A rewording that changes the task's meaning is
      discarded, not counted as a policy failure."
66. `OcclusionSection.tsx:59` (legacy).
    - **REMOVE.**
67. `ScenarioSection.tsx:65-67` (legacy).
    - **SHORTEN** to: "Share is how far each shift moves toward its failing
      value."
68. `ScenarioSection.tsx:115` (legacy).
    - **SHORTEN** to "Ranked before any rerun."
69. `AuditSection.tsx:85` (legacy).
    - **SHORTEN** to: "Severity runs from 0 (no change) to 1 (the
      strongest)."

## Setup (`pages/SetupPage.tsx`)

70. `:64`.
    - **SHORTEN:** drop "Nothing here creates or changes anything."
71. `:13`, the Nebius text.
    - **SHORTEN** to "The sign-in expires after about a day."
72. `:16`, the Docker text.
    - **REMOVE**, keeping the guide link. The title already says "only for
      building the image".
73. `:18`, the Token Factory text.
    - **SHORTEN** to: "Used for Nemotron hypotheses, explanations and
      rewordings. It stays on this machine and never enters a Job."
74. `:22`, the backend text.
    - **SHORTEN** to: "New diagnoses reuse the backend block (image and
      secret name) of a local spec."
75. `:103-105`, the bottom "Open the guide" button.
    - **REMOVE.** Each card links the guide.

## Reference, Guide and other pages

76. `ReferencePage.tsx:44-47`, the lede listing every section.
    - **SHORTEN** to: "What Faultline does and what everything it shows
      means."
77. `GuidePage.tsx:23-26`.
    - **SHORTEN** to: "Run a diagnosis on your own Nebius account, from the
      control panel or a terminal."
78. `content/guide.tsx:190-191`.
    - **REMOVE** the duplicate "resubmitted automatically" sentence.
79. `content/guide.tsx:248-250`.
    - **REMOVE** the duplicate reconciliation sentence.
80. `content/guide.tsx:216-222`.
    - **MOVE/trim**, optional: keep the `--expect` and `policy.checkpoint`
      sentences.
81. `NotFoundPage.tsx:9`: "There is nothing at this address."
    - **REMOVE.**
82. `EvidencePage.tsx:96`.
    - **SHORTEN** to "Raw recorded episodes, not a diagnosis."

## Kept on purpose

These stay because each is a spend warning, a claim boundary, or information
shown nowhere else:
- the Review and replay cost warnings;
- "each extra family adds about half an hour";
- "the reruns decide the result";
- "Resume … never pays twice";
- the stop confirmation;
- the polling-failure notices;
- "reduction cut short, may not be the smallest cause";
- "Suggestions from {model}, not evidence";
- the wording meaning-change sentence;
- the disabled and not-replayable explanations;
- the static-gallery lede;
- "Nothing running.";
- the worst-case-under-cap note.

## Suggested first batch

The most visible redundancy: items 1–4, 8–10, 28, 49, 53–55, 62.
