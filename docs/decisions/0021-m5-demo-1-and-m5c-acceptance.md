# ADR 0021: Accept external demo_1 and the v2-06 Nemotron report

**Status:** Accepted by the project owner on October 11, 2026 ("try demo_1, accept v2-06").

## Context

ADR 0016 limited external restore to `demo_0`, state 0, of the acquired LIBERO
Object alphabet-soup file. From that start the M4 sensitive region (top-right)
failed only intermittently (4 of 9 episodes) and never met the 4-of-5
reproducibility bar, so no external case could be reduced. The same file holds
50 demonstrations of the same scene. `demo_1` uses the identical scene XML
(`203f7f01…`) with a different starting arrangement; its stored `init_state`
equals its first recorded state, hash
`39fcb000764607812d74c6fdbb92625f796370a5e1e6d3d76f6e4b86ba463722`.

For M5C, the iterated geometry-aware Nemotron report v2-06 (`58c2ad9f…`) had no
factual errors against the deterministic facts; later attempts were worse.

## Decision

- Accept `demo_1`, state 0, as a second external start, pinned to its own
  first-state hash. Every other demo stays rejected; nothing else in ADR 0016
  changes (asset resolution, fresh policy actions, private handling, licence
  caveat).
- Run the same `m5b-grid` workload (position grid from the external start, then
  reduction only of a confirmed failure) from `demo_1` under the usual US$2
  per-Job cap with no automatic retry.
- Accept Nemotron report v2-06 as the M5C demonstration interpretation, shown
  as human-review-required beside the deterministic facts.

## Consequences

Two external starts are now possible; this is still one task and one source
file, not general dataset import. A failure found from `demo_1` must still pass
the existing reproducibility and nominal-control gates before reduction.
