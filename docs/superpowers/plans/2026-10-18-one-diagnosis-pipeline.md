# One diagnosis pipeline: plan

Decision: [ADR 0035](../../decisions/0035-one-diagnosis-pipeline.md). Status:
**approved by Jethro on October 18** with the answers below.

## The flow

```text
New diagnosis: suite, task, and one of
  - a benchmark start   -> CHECK
  - a range of starts   -> layout branch only (search for a failure)
  - your own state file -> layout branch only (you bring a failure)

CHECK (the existing screen Job: the start plus a pool of nearby starts for a
reference; one attempt each, confirmation attempts for a start that fails)
  - the start fails reliably -> LAYOUT: reference, delta debugging, shrink
                                 (today's scenario reduction)
  - otherwise               -> PROBES, if any were chosen:
       stress test (chosen families) -> its control decides reliability;
                                        a failing control = "flaky start"
       rewordings (n)                -> control, screen, reduce a failure
  - otherwise, with no probes chosen -> "Passes untouched" (a finding)
```

Every branch ends with findings:
- **Layout:** one scenario case (replayable today).
- **Stress test:** one audit case listing every family; replay reruns each
  family that failed, at its threshold.
- **Rewordings:** one wording case; replay reruns the failing wording.
- **No failure:** "no failing condition in these ranges".

## Work

### 1. Spec and dry run (`spec.py`, `orchestrator.dry_run_lines`, `viewer/specs.py`)

- New `mode: diagnose` with `diagnose: {task, start | screen | import, probes:
  {families: [...], rewordings: n}, branches: {layout: true, probes: true}}`.
  Existing modes keep working for the CLI and older runs.
- The dry run lists both branches:

  ```text
  CHECK: screen
  IF IT FAILS: reduce (+continuations)
  IF IT PASSES: audit, paraphrase screen/reduce
  ```

  Each with its worst case. The total is the larger branch plus the check, not
  the sum, since only one branch runs. The cap rule is unchanged: the first
  Job must fit, and later Jobs that do not fit stop the run, which can be
  resumed.

### 2. Orchestrator (`orchestrator.py`)

- `_diagnose_pipeline`:
  - run the screen;
  - if `choose_start` confirms the start, continue as `_scenario` does;
  - otherwise run the chosen probes, the audit first, then the rewordings.
- Record the route in `steps.json` (`route: layout | probes | passes`) and in
  the report's Summary.
- **Probing a flaky start.** An audit whose control fails already stops with
  `nominal_controls_failed`. **Q2:** should the rewording probe then be
  skipped (recommended: yes, the same reason applies)?

### 3. Replay for audit and wording cases (`orchestrator._replay`, `job_runtime`, `m6_experiment`, `language_experiment`)

- **Audit case:** reuse the existing audit Job mode with each failing family's
  threshold as a one-level sweep, bisection off, 5 attempts, plus the
  5-attempt control. Verdict per family: still fails (4 of 5) or no longer.
- **Wording case:** reuse the rewording screen with only the failing wording
  and the original as control, confirmed by the 4-of-5 gate.
- Both reuse existing Job modes and workload fields. If a field the Job image
  does not accept turns out to be needed, that is a new image (v17), which is
  planned for the final runs anyway.
- `replay --expect` works for every case kind; the case page shows Replay for
  all three.

### 4. Cases and library (`case_register.py`, `viewer/library.py`, `export.py`)

- Audit and wording cases carry replay inputs. Wording cases are registered
  even when no failure was found ("passes these rewordings" is a finding).
- A diagnosis page per run lists its findings and links to each case.
- **Q3:** keep the current case pages and add a run-level "findings" list at
  the top, or make the findings list the page?

### 5. UI (`web/`)

- **New diagnosis**, one flow:
  1. What to check: a benchmark start, a range, or your own file.
  2. Settings: suite, task, start, and **If it passes, also probe**
     (disturbance families and rewordings, both optional). The scenario
     settings (reference pool, candidates) are kept as now.
  3. Review: both branches with costs, then Start.
- The run page shows the route once known.
- The case page's verdict sentence is phrased as a finding.

### 6. Docs

Reference (the pipeline, findings, replay per kind), UI runbook (the demos
rewritten around one entry point), README (what Faultline does), ADR 0035
implementation notes.

### 7. Validation run (paid; spend agreed at the time)

One pipeline run on a start expected to pass, with blur and noise probes
(LIBERO-Object task 0, start 0; the September experiments found thresholds
for both families there). It should produce a disturbance case, then one
replay of that case.

## Decisions (Jethro, October 18)

- **Q1. Default probes: everything.** All ten families plus 10 rewordings are
  ticked by default. Jethro noted the worst case is expensive, so the review
  step must show both the worst case and a typical cost.
- **Q2.** A flaky start (the stress test's control fails) skips the rewording
  probe too.
- **Q3.** A findings list at the top of the run, linking to each existing
  report-first case page.
- **Names** come after the build works.
- Jethro continues the UI runbook demos on the current UI meanwhile.

### Consequence of Q1: probes split across Jobs

One audit Job is limited to 40 minutes (2400 s). Ten families do not fit;
found October 18 when a ten-family dry run failed, which now returns a clear
field error. The pipeline therefore splits the probes:

- image families in two Jobs (four and four);
- scene families (viewpoint, lighting) in a third;
- rewordings in the usual screen Job, plus a reduce Job only when a wording
  fails.

Each Job reserves about US$1.2–1.4 worst case. Measured Jobs of this size
cost about US$0.4–0.9, so a full probe of a passing start should typically
cost about US$2–2.5, against reservations of about US$4.5. The dry run lists
every probe Job, and the cap rule (the first Job must fit) is unchanged.

## Agents and order

- Build in two worktrees, in parallel against an agreed contract:
  - **backend:** steps 1–4;
  - **front end:** step 5, against fixtures.
- The coordinator integrates, updates the docs and runs a review.
- Then the validation run, with Jethro's go and cap.
- Estimate: 2 days of build and integration, plus the run.
- Conventional Commits, with no AI co-author trailers.
