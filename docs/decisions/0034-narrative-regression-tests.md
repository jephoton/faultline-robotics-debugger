# ADR 0034: Narrative — the minimal trigger, kept as a regression test

**Status:** Accepted by Jethro on October 18, 2026.

## Context

By October 18 the product worked end to end, but its story was unsettled:
it read in places as a debugger that explains why a policy fails, and in
others as a robustness audit. Jethro has no robotics background to judge
which a robotics team would value, so the options were compared against
published accounts of how teams work and against the four equally weighted
judging criteria (technological implementation, design, potential impact,
quality of idea).

## Options considered

- **A. Regression tests for policies:** find the minimal trigger of a
  failure, confirm it, keep it as a test, and rerun it on every checkpoint.
- **B. Debugger:** explain why the policy fails. The minimal trigger is
  measured, but the mechanism inside the network is not. Delivering it would
  lean on traces (not built) and Nemotron's reading (interpretation), which
  risks overpromising.
- **C. Robustness audit:** severity thresholds per disturbance family. Our
  audits mostly found robustness, and LIBERO-Plus already covers broad
  robustness sweeps.

## Decision

Tell story **A**:
- The minimal trigger is presented as the cause in the sense of *what*
  triggers the failure, and as the sharpest clue to *why*, which stays a
  person's job.
- Nemotron keeps both of its roles: ordering the search, and a labelled
  reading of the verified result shown beside the measurement.
- Mode 1 and Mode 2 are two ways to find cases for the suite.
- The README opens with the team workflow, the gap (average success rates
  hide failures; regression testing of policies is not systematic) and a
  plain explanation of regression testing.

## Consequences

- **Final runs:** Jethro's planned final round should produce one or two
  fresh reduced cases (ideally on another task), plus one replay of a case
  against a second checkpoint, so the regression loop is shown end to end.
  These need a new image with the October 18 fixes, and spend approval at
  the time.
- **Traces:** the trace feature stays paused, as a possible upgrade that
  makes the clue easier to read, revisited after the final runs.
- **Claims:** do not claim the product explains failures. The
  team-workflow description is supported by published accounts, but "a
  failure seen once may not repeat" is stated from our own runs, not as an
  industry finding.

## Amendment (October 19, 2026): scope stated up front

Jethro chose to state the scope right under the README's title, and in the
Reference's "Where it applies":
- what Faultline covers today: GR00T N1.7 on LIBERO;
- what an adapter for another simulator would need;
- that real robots are out of scope.

The general problem story stays. The 50 benchmark starts are LIBERO's, not a
robotics standard. A start file is a LIBERO state, not a different
environment. The Devpost text must carry the same scope line.
