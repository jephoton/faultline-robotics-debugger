# Report-first case page and per-step traces: plan

Decisions by Jethro, October 18, 2026:

- **Case page:** report-first. The readout header and the linked videos, then
  the rendered report (opening with a bullet summary, long tables
  collapsible), then Replay with a one-line purpose, then the files.
- **Trace feature:** plan it now. Jethro intends a final round of fresh runs
  once the product is settled, and wants those runs to carry traces. The data
  set and the validation run are decided at this plan's review (below). No
  paid run or image push is approved by this plan.

## Part A: report-first case page (green/amber, approved)

### Why

The case page repeats the report in pieces (minimal cause, reruns, history,
hypothesis) and shows only the reruns Nemotron cited (8 of 26 for
`FL-S-AFB5`). The report holds the whole story in order. Make it the body.

### Changes

1. **Report generator** (`scripts/report_scenario_reduction.py`): add
   `## Summary` at the top, as bullets:
   - the verdict;
   - the failing start (benchmark start or imported file) and the reference;
   - each kept shift with its size and share;
   - the stop status in plain words.

   Keep the Candidates legend (added October 18). The audit and paraphrase
   reports (`report_m6_experiment.py`, `report_paraphrase.py`) get the same
   kind of summary.
2. **Honest result sentence** (`src/robot_debug/scenario_experiment.py` ~1719):
   state "sizes resolved to within 1/16" only when the shrink step completed
   for every part; otherwise "sizes not fully shrunk". This file runs inside
   the Job, so new runs need the next image. The library also derives the
   page's summary from structured data (`minimal_cause`), so existing cases
   read correctly without the sentence.
3. **Case page** (`web/src/pages/CasePage.tsx` and `components/case/*`):
   1. readout header;
   2. linked videos;
   3. the rendered report:
      - tables over 12 rows collapsed behind "Show all *n* rows";
      - headings get anchors;
      - Nemotron's reading as a labelled, collapsed section after the report
        (interpretation, not evidence);
   4. **Replay** for scenario cases, with "Replay re-runs the minimal scene and
      its reference to check whether the failure still reproduces, for
      example after you change the policy.";
   5. a collapsed **Run details** (steps, Jobs, cost, time);
   6. files.

   Cases with no report (the September occlusion case) keep their current
   structured view. Remove the now-duplicated sections; keep their components
   only where the fallback still uses them.
4. **Regenerate stored reports** locally (ignored `artifacts/`) for every
   registered case. Regenerate the committed demo case
   (`demo/root/diagnoses/…/report.md`) and commit it, so existing cases show
   the summary and legend. No new compute.
5. **Docs:** update `docs/ui-runbook.md` (Demos 1–5 describe the new page),
   `docs/architecture.md` (UI reference) and ADR 0033 implementation notes.
6. **Gallery:** re-export and redeploy only with Jethro's go at the time.

### Tests

- Report summary for an imported start, a benchmark start, an incomplete
  shrink and a completed shrink.
- The sentence rule.
- The case page renders the report body, collapses long tables, keeps
  Replay and run details, and falls back for a case without a report.
- Static mode.

## Part B: per-step traces (PAUSED)

**Paused by Jethro on October 18:** do not implement. First decide whether it is
worth doing once the project narrative and target use cases are scoped. The
design below is kept for that discussion only.

### Why

Robotics engineers debug by scrubbing a recorded timeline (arm path, gripper,
commanded actions, object positions) in tools such as rerun.io or Foxglove.
Faultline has videos only, so it cannot show where the minimal scene and the
reference first behave differently. This is the largest usefulness gap
recorded on October 18.

### Proposed design

- **Recording** (inside the Job, in our LIBERO adapter
  `src/robot_debug/libero.py`, which steps the simulator; the harness's own
  per-step file, which holds only step, reward, done and success, stays as it
  is). Each episode writes `trace.jsonl` beside its video, one line per
  policy step:
  - end-effector position (x, y, z) and gripper opening;
  - the 7 action values the policy sent;
  - the positions of the objects the task names (for example the soup, the
    sauce and the basket).

  About 20 numbers per step, roughly 100 KB per 500-step episode. It is on
  for every episode a Job saves a video for, and capped in size.
- **Export and case:** the Job's downloader and `case_register` copy the
  traces for the original, minimal and reference episodes into the case, as
  with videos. The export copies them to the gallery.
- **Read model:** `Detail.videos[].trace_url`, and a small
  `/api/library/{id}/trace/{role}` returning the downsampled series.
- **Case page:** under the videos, a **Trace** panel:
  - the end-effector height and gripper opening over time for the three
    episodes;
  - a top-down path plot;
  - markers where the gripper closes and opens;
  - the first step where the minimal and reference paths differ by more than
    2 cm.

  A shared cursor follows the linked videos' timeline.
- **Replays** record traces too, so a replayed case can be compared with the
  saved one.

### Decisions for Jethro at plan review

1. **What to record:**
   - **(a) arm, gripper, actions and task objects** (recommended);
   - (b) arm and gripper only;
   - (c) everything the simulator exposes.
2. **Validation run** after the image build:
   - **(a) one replay** of `FL-S-AFB5` (measured US$0.41 last time, worst case
     about US$1.08);
   - (b) one small new diagnosis (worst case about US$3);
   - (c) fold it into the final round of fresh runs.
3. **Image:** rebuild and push a new simulator image (v17) containing the
   trace recorder, the reduction fix of October 18 and the honest sentence.
   Building is free locally; pushing to the private registry stores about
   20 GB.

### Order

Part A first (no compute). Part B implementation after the decisions above;
its image build waits for B's code and A's sentence fix so one new image
carries all three Job-side changes.

## Agents and ownership

- **Part A:** one implementation agent (smaller model) in a worktree, owning
  the scripts, `scenario_experiment.py` (sentence only),
  `src/robot_debug/viewer/library.py`, `web/` and tests.
- **Coordinator:** regenerates the stored reports, updates the docs, does
  browser verification and integration.
- **Part B:** a second agent after Jethro's decisions.
- Commits follow Conventional Commits, with no AI co-author trailers. Agents
  never push.
