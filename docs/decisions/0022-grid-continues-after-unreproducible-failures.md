# ADR 0022: Position grid keeps searching after unreproducible failures

**Status:** Accepted by the project owner on October 11, 2026.

## Context

The position grid (`scripts/run_position_grid_search.py`) tried its eight
0.5×0.5 positions in a fixed order, replayed the **first** apparent failure five
times and, if that failure was not reproducible (fewer than 4 of 5 replays
failing), stopped the whole session. From the benchmark start failures were
reliable, so this was cheap and sufficient. From external starts the policy's
failures are intermittent: on demo_1 a one-off top-left failure (0/5 replays)
ended the session before the top-right position — the region implicated by M4
and demo_0 — was ever tried.

## Decision

- After an unreproducible apparent failure, record it in `rejected_failures`
  (with its replay outcomes) and continue with the next grid position.
- Stop at the first **confirmed** failure (`confirmed_failure`), then run the
  unchanged five nominal controls.
- Cap every grid session at **30 episodes** (`MAX_EPISODES`). Before each
  position and before each replay round, the driver checks that the round plus
  the nominal controls still fits; otherwise it stops with
  `episode_cap_reached`.
- Replays use one global counter (`replay-1`… then `replay-6`…), so earlier
  evidence names are unchanged and later rounds never collide.
- `m5b-grid` reduces only `confirmed_failure`, never a rejected fluke.
- The reproducibility rule (4 of 5), grid positions, replay count and
  nominal-control gate are unchanged.

## Consequences

Noisy starts can no longer end a search on a single fluke; worst case a session
costs 30 episodes (about 12–15 minutes of evaluation) instead of 19. Searching
more positions slightly raises the chance of confirming a rare failure, so
confirmed failures are still reported with their replay counts and the rejected
flukes alongside them.
