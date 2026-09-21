# ADR 0005: Bounded nested-rectangle failure reduction

**Status:** Accepted  
**Date:** 2026-09-21

## Context

The position-grid experiment found a repeatable policy failure under an opaque
upper-right rectangle covering 25% of the agent-view image. M4 must shrink that
condition without assuming the failure is monotonic and without allowing an
open-ended cloud search.

## Decision

Use deterministic greedy edge stripping with deltas `0.125` then `0.0625`.
Candidate order is `left`, `bottom`, `right`, `top`. A candidate passes after
four `policy_failure` outcomes and is rejected after two valid non-failures,
with at most five valid attempts. The first live session stops after 12
candidate attempts and has a proposed total ceiling of 23 valid episodes.

Infrastructure and invalid-evidence results abort the session and never enter
the repeatability gate. M4 minimizes the known seed-7 case; fresh-state
generalization remains M6 work.

## Alternatives

- Binary-searching square size is cheaper but assumes monotonicity and cannot
  distinguish which edge matters.
- Exhaustively searching rectangles provides broader coverage but consumes the
  bounded M4 budget before producing one useful regression case.

## Consequences

The result is interpretable and supplies a real workload for the later M3
parallelism experiment. It is only a local minimum relative to the tested
moves and budget. It does not establish global minimality, causality, or
coverage of other tasks, seeds, or failure families.
