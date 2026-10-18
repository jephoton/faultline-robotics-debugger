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
