# One diagnosis pipeline: plan

Decision: [ADR 0035](../../decisions/0035-one-diagnosis-pipeline.md). Status:
**approved by the project owner on October 18** with the answers below.

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

**Additions from the project owner, October 18:**
- **Videos for disturbance and wording cases.** The Jobs already record and
  download them; only case building ignored them. Show the control, plus one
  clip per family at its threshold (or at the top severity when robust). The
  existing audit cases are re-registered to get theirs.
- **Pass/fail colours.** Every pass/fail outcome is green or red (icon and
  word kept), replacing "pass stays neutral". Record this in ADR 0033.
- **The UI runbook** is rewritten for the single pipeline, merging demos
  where the new flow makes them one.
- **Research context returns** as an optional step per case: Tavily finds
  public sources and Nemotron 3 Nano summarises them, shown as context, not
  evidence. A tickbox on New diagnosis, on by default when a Tavily key is
  present. Not yet in either builder's brief: add it at integration.


Reference (the pipeline, findings, replay per kind), UI runbook (the demos
rewritten around one entry point), README (what Faultline does), ADR 0035
implementation notes.

### 7. Validation run (paid; spend agreed at the time)

One pipeline run on a start expected to pass, with blur and noise probes
(LIBERO-Object task 0, start 0; the September experiments found thresholds
for both families there). It should produce a disturbance case, then one
replay of that case.

## Decisions (the project owner, October 18)

- **Q1. Default probes (revised October 19):** blur, noise, darken and
  contrast, no rewordings; cap US$2.50 and 1.5 hours.
  - These four are the only families where the policy has failed before.
  - The other six families and the rewordings stay one tick away.
  - Typical cost is about US$1.25 for a passing start and about US$1.15
    for the layout branch.
  - The first answer, everything ticked, would need a US$6–7, 4-hour cap,
    which the project owner judged too expensive in money and time.
- **Q2.** A flaky start (the stress test's control fails) skips the rewording
  probe too.
- **Q3.** A findings list at the top of the run, linking to each existing
  report-first case page.
- **Names** come after the build works.
- The project owner continues the UI runbook demos on the current UI meanwhile.

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


**Sequential, not parallel (the project owner asked, October 18):**
- The probe Jobs run one after another, as every Faultline run does.
- Running them at once would not save cost: each Job pays its own startup
  on its own GPU, and each is billed for its own container time.
- It would save wall-clock time (about 40 minutes instead of 1.5–2 hours),
  but needs three GPUs at once (more capacity waits), a cap covering three
  worst cases together, and reworked Stop, Resume and ledger handling
  (the orchestrator tracks one Job in flight).
- Kept as a later upgrade.

## Agents and order

- Build in two worktrees, in parallel against an agreed contract:
  - **backend:** steps 1–4;
  - **front end:** step 5, against fixtures.
- The coordinator integrates, updates the docs and runs a review.
- Then the validation run, with the project owner's go and cap.
- Estimate: 2 days of build and integration, plus the run.
- Conventional Commits, with no AI co-author trailers.

## Contract between the backend and front-end agents (API v1 additions)

The existing API (`docs/superpowers/plans/2026-10-17-control-panel-ui.md`)
stays valid; these are additions.

- **Spec mode `diagnose`:**

  ```yaml
  mode: diagnose
  diagnose:
    task: 0
    # exactly one of:
    start: 0
    screen: {starts: "10-49", confirm: 4}
    import: file.json
    probes:
      families: [blur, ...]   # [] for none
      rewordings: 10          # 0 for none
      enabled: true           # false = "don't probe"
    layout: true              # false = "probe only": skip the layout branch even if the start fails
  ```

  Plus the usual `policy`, `budget`, `nemotron` and `backend`. The template
  is `GET /api/specs/template?mode=diagnose`, with all ten families and
  `rewordings: 10` by default. Probes apply only with `start`; `screen` and
  `import` are layout-only, and validation says so.
- **Dry run** (`POST /api/specs/dry-run`):
  - each entry in `jobs[]` gains `"branch": "check" | "layout" | "probes"`;
  - a new `branches: [{"branch", "worst_case_usd", "typical_usd": number | null}]`;
  - `worst_case_total_usd` = check + the larger of layout and probes.
  - `typical_usd` comes from measured history: about 0.5 × worst case for a
    probe Job; null when unknown. The UI labels it as an estimate.
- **Progress:** gains `"route": "layout" | "probes" | "passes" | "flaky" | null`.
- **Detail:**
  - gains `"findings": [{"id", "fault_code", "kind", "verdict", "verdict_text"}]`:
    every library item registered by the same diagnosis run, in route order,
    this case included. The UI shows the list only when it has more than one
    entry, or when the run's route was "passes" or "flaky".
  - `replayable` can now be true for `audit` and `paraphrase` cases.
- **Replay:** `POST /api/library/{id}/replay` accepts audit and paraphrase
  cases. Replay verdict texts:
  - audit: "still fails at s = 0.50 (blur)" / "no longer fails";
  - wording: "the wording still fails" / "no longer fails".
- **Library ids** stay `d-<case_id>` and `r-<run>`. A pipeline run can
  register more than one case: an audit case and a wording case.

### Contract addition (October 19): measured typical cost and time

Each `branches[]` entry also has `typical_minutes`: end to end, excluding
GPU waits. Both typical figures come from measured runs.

Measured references (container minutes, cost):

| Job | Minutes | Cost |
| --- | --- | --- |
| Check (screen) | 10.6 | US$0.43 |
| Blur, noise, darken, contrast audit on LIBERO-Object | 20.4 (12.7 of testing) | US$0.59 |
| JPEG, colour cast, motion blur, dead pixels audit on LIBERO-Spatial | 24.3 | US$0.82 |
| Viewpoint and lighting | 9.6 | US$0.40 |
| Layout reduce | 18–21 | US$0.65–0.72 |
| Rewording screen | 7–8 | US$0.31–0.35 |
| Replay | 10.2 | US$0.41 |

The default diagnosis of a passing start (check plus the four default
families) is typically about 35–45 minutes and US$1.00–1.25. Task length
and finding a failure (the bisection steps) add time.
