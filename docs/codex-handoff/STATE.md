# Current project state

> Generated current-state context. Update after material implementation,
> architecture, workflow, or risk changes.

## Completed evidence

- The nominal baseline passed 20/20 episodes.
- Centered opaque-square occlusions through 25% image area succeeded.
- The fixed-area position grid found a reproducible failure at normalized
  `x=0.50, y=0.00`: discovery plus 5/5 replays failed, while the nominal
  sentinel and 5/5 fresh nominal controls succeeded.
- The ignored local artifact tree contains 45 recorded episode videos.

## Current implementation

- The read-only viewer runs from `src/robot_debug/viewer/` and scans artifacts
  on each catalog request.
- Commit `3791fa7` deduplicates copied aggregate records by logical evaluation
  identity, prefers the copy with attached media, and supports early flat media
  layouts. The real catalog now exposes 45 unique episodes with zero missing
  video paths.
- The main branch is ahead of the configured remote; publishing remains a
  separate user-controlled action.

## Next material decision

Design M4 failure reduction for the proven upper-right occlusion. Jethro must
choose the reduction objective, algorithm, retry budget, confirmation seeds,
and any fresh cloud cap before dependent execution. The current recommendation
is a bounded nested rectangle reducer, followed by an equal-work 1/2/4-worker
HPC comparison using the resulting diagnostic workload.

## Known limitations and risks

- The current WSL `.venv` may lack NumPy for the complete suite; the focused
  viewer tests are independently runnable.
- Experiment evidence is ignored and local; do not infer that it is published
  or durable off-machine.
- The position failure is empirical and spatially specific, not a causal or
  universal robustness claim.

