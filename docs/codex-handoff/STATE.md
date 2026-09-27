# Current project state

> Generated current-state context. Update after material implementation,
> architecture, workflow, or risk changes.

## Completed evidence

- The nominal baseline passed 20/20 episodes.
- Centered opaque-square occlusions through 25% image area succeeded.
- The fixed-area position grid found a reproducible failure at normalized
  `x=0.50, y=0.00`: discovery plus 5/5 replays failed, while the nominal
  sentinel and 5/5 fresh nominal controls succeeded.
- The September 27 M4 session reduced the 25%-area parent to a certified
  14.0625%-area rectangle at `x=0.625, y=0, width=0.375, height=0.375`.
  Its accepted cases failed 4/4, while five fresh nominal controls succeeded.
  The 12-candidate-attempt budget ended before proving a minimum.
- The ignored local M4 artifact tree contains 22 aggregates, traces, MP4s,
  SQLite recordings, the summary, and the replay manifest.

## Current implementation

- The read-only viewer runs from `src/robot_debug/viewer/` and scans artifacts
  on each catalog request.
- The viewer deduplicates copied aggregates, prefers media-bearing records,
  and displays accepted reduction lineage. Its M4 catalog indexes all 22
  episodes with no missing media or warnings.
- The main branch was synced with the private remote before this documentation
  update. Public release remains a separate user-controlled action.

## Next material decision

M4's bounded live run and evidence validation are complete; details are in
`docs/experiments/m4-reducer.md`. The next material step is to design M3's
equal-work 1/2/4-worker comparison around the real reduction workload.
Worker topology, valid outcome-drift rules, and any paid run cap remain Jethro
decisions. The root `FEEDBACK.md` tracks submission feedback by actual tool.

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
- The retained 200 GiB boot disk continues to accrue storage cost while the VM
  is stopped. A future storage/teardown decision should preserve any needed
  model cache and copied evidence explicitly.
- The position failure is empirical and spatially specific, not a causal or
  universal robustness claim.
