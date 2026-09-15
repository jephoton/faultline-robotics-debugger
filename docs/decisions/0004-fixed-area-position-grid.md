# ADR 0004: Search occlusion position at fixed area

**Status:** accepted on September 15, 2026

## Context

The first bounded search produced 20/20 nominal successes and no failure while
increasing a centered opaque square from 6.25% to 25% image area. Increasing the
centered square further would probably find a threshold eventually, but a
failure caused by hiding most of the frame would be weak diagnostic evidence.

## Decision

Keep the accepted model, simulator, task, episode, seeds, occlusion appearance,
and 25% area fixed. Search the eight previously untested placements in the 3x3
top-left-coordinate grid whose `x` and `y` values are each `0.00`, `0.25`, or
`0.50`; the prior center result at `(0.25, 0.25)` completes the ninth cell.

Run one fresh unoccluded episode-0 sentinel first. Search the eight positions in
a preregistered order. Stop at the first completed task failure, replay its
exact configuration five times, and retain the accepted 4/5 repeatability gate.
If it repeats, run five matched unoccluded episode-0 controls and require at
least 4/5 successes before describing the result as perturbation-associated.

## Rationale

This changes only position, so an observed difference is easier to interpret
than a simultaneous change in area or perturbation family. The fixed order
makes time and cost to first failure reproducible. The fresh sentinel cheaply
detects session drift, while conditional matched controls strengthen a positive
claim without paying for them when no candidate exists.

## Consequences and limits

- The hard maximum is 19 episodes: one sentinel, eight grid cells, five failure
  replays, and five matched nominal controls.
- The grid is coarse and overlapping. It does not prove spatial robustness or
  locate an object causally.
- Coordinates name image-array positions, not robot-world directions.
- Search order affects time to first failure and must be recorded.
- A new cloud cap remains a separate red decision after local implementation.

## Alternatives considered

- **Increase centered severity:** cheaper and likely to find a threshold, but
  risks producing a trivial near-total-obstruction failure.
- **Change perturbation family:** broadens coverage but abandons the controlled
  single-variable progression before spatial sensitivity is understood.

