# ADR 0035: One diagnosis pipeline that routes on the untouched result

**Status:** Direction accepted by Jethro on October 18, 2026. The
implementation plan
(`docs/superpowers/plans/2026-10-18-one-diagnosis-pipeline.md`) is for his
review before building. Names for the entry point and the kinds of finding are
not yet chosen.

## Context

ADR 0034 settled the story: the minimal trigger, kept as a regression test.
The tool still had separate modes:
- layout diagnosis of a failing start (replayable);
- stress tests and rewordings of a passing start (not replayable).

Only the first produced regression tests, and a user had to know in advance
which mode their start needed.

## Decision

One **New diagnosis** promises: *find the smallest condition under which the
policy fails here.* Every result has the same shape (a condition, its smallest
version, a replayable test) or is an empty list, which is a valid answer.

1. The start is run untouched (the existing screen, with its confirmation
   attempts).
2. **If it fails reliably:** layout diagnosis (nearest passing reference,
   shrink the differences), as today.
3. **If it does not:** the probes the user chose:
   - disturbance families, with their thresholds;
   - rewordings, reduced to the smallest word change.

   Their own control decides whether the start is reliable. A flaky start is
   reported as a finding, and nothing is blamed on a disturbance.
4. **Every failure becomes a replayable case:**
   - a layout trigger (today);
   - "start *n* + family at severity *s*";
   - "start *n* + this wording".

Imported start files and range searches stay on the layout branch: you bring,
or search for, a failure.

## Alternatives considered

- **Two separate jobs** ("debug and pin" plus "probe"), with a hand-off from a
  failing control. Lower risk; only layout failures become tests.
- **Two jobs now, the pipeline after submission.**

Jethro chose the pipeline for the submission, accepting the build and
validation risk before October 29.

## Consequences

- The review step must show both branches and their worst-case costs before
  Start, and allow "don't probe" or "probe only".
- Disturbance and wording cases get replay. Fault codes, the case page, the
  Reference, the runbook, the README and the video follow the single entry
  point.
- One validation run, with spend approved at the time, should produce at
  least one disturbance case. Blur and noise thresholds were found in the
  September experiments on LIBERO-Object, so a blur or noise probe there is
  the likeliest to produce one.

## Implementation notes (October 19, 2026)

- **How it was built.** Backend and front end were built in parallel against
  the plan's contract, then integrated. A `mode: diagnose` spec and
  template:
  - defaults: blur, noise, darken and contrast; no rewordings; research on;
    a US$2.50 cap and 1.5 hours (Jethro revised the defaults down from
    "everything", which needed a US$6–7, 4-hour cap);
  - other modes still work from the CLI.
- **Routing.** The check reuses the layout screen Job. Routes are layout,
  probes, flaky and passes. A failing audit control (flaky) skips the
  rewordings.
- **Probe Jobs.** Each audit Job is capped at 40 minutes, so families are
  grouped (image 4+4, scene together). Jobs run one after another; parallel
  Jobs would save wall-clock time but not cost, and are deferred.
- **Review.** The dry run lists the branches with their worst cases (check
  plus the larger branch) and typical figures modelled on measured runs:
  check about 16 minutes and US$0.43; four families about 29 minutes and
  US$0.82; layout about 25 minutes and US$0.68.
- **Cases.** A run can register several cases: an audit case and a wording
  case. Audit and wording cases carry videos (the control, and each family at
  its threshold or top severity) and replay inputs. Replay reuses the
  existing Job types, so no simulator image change was needed. The three
  existing audit cases were re-registered locally to gain their videos (case
  ids unchanged).
- **Research.** An optional research step (Tavily sources, a Nemotron 3 Nano
  summary) attaches context to each new case when a Tavily key is present.
- **Default cap kept at US$2.50** (Jethro, October 19). The runtime reserves
  each Job's worst case only when it submits it, and charges the measured
  time. A typical check (about US$0.43) therefore leaves room for either
  branch's first Job. Review names the Job that would be refused only if the
  Jobs before it cost their worst case.
- **Occlusion stays out of the New diagnosis** (Jethro, October 19). The ten
  probe families each have a single severity. The September occlusion
  rectangle is a 2D shape with its own edge-trimming reducer. Adding it, as a
  scalar family or as its own probe kind, would need image work and a paid
  validation run before the deadline. Its results (the 14% rectangle, and
  the camera-roles hypothesis) stay in the README as earlier results, with no
  gallery case.
