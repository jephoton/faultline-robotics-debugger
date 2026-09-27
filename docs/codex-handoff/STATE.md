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

M4 has an accepted design and implementation plan at
`docs/superpowers/plans/2026-09-21-m4-bounded-failure-reducer.md`. Tasks 1--6
are complete locally: pure reducer, rectangular config support, resumable
session driver, replay manifest, validated viewer lineage, fake-evaluator
resume/idempotence checks, a 126-test Python 3.11 suite, and browser smoke
testing. No live M4 episode has run and no reduced rectangle is claimed.

The next step is the read-only Nebius preflight in Task 7. Before provisioning
or running an episode, Jethro must approve a fresh dollar cap after current
price, balance, quota, capacity, instance, disk, and firewall state are
verified. M3's equal-work 1/2/4-worker comparison follows the M4 evidence.

Jethro explicitly authorized DeepSeek Flash for the isolated pure reducer
kernel on September 21. Its durable task handoff is
`docs/codex-handoff/tasks/2026-09-21-reducer-kernel.md`; this authorization
does not include other files, models, providers, or external systems.
The initial handoff exposed a Windows ACL mismatch between sandbox identities.
Jethro authorized a fresh retry after a scoped permission repair; partial files
were removed before retrying, and independent Python 3.11 verification remains
the coordinator's responsibility.

## Known limitations and risks

- The current WSL `.venv` may lack NumPy for the complete suite; the focused
  viewer tests are independently runnable.
- Experiment evidence is ignored and local; do not infer that it is published
  or durable off-machine.
- The position failure is empirical and spatially specific, not a causal or
  universal robustness claim.
