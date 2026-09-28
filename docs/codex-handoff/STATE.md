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
- M3 local work is isolated on `codex/m3-parallel-replay`, not merged into
  `main`. The fixed 16-item manifest, bounded 1/2/4-worker scheduler, evidence
  validation, fail-closed comparison reporter, process-group containment, and
  durable per-case attempt ledger are implemented. Windows Python 3.11 passed
  199 tests (2 POSIX-only skips); the focused WSL signal/driver suites passed
  45 tests. No M3 Nebius run exists.

## Next material decision

M4's bounded live run and evidence validation are complete; details are in
`docs/experiments/m4-reducer.md`. Jethro accepted the M3 equal-work
1/2/4-worker design on one GPU VM with a shared GR00T server, using fixed
repeats of the real M4 case. The M3 local implementation now uses the accepted
durable attempt-ownership design; final whole-branch review and integration
are next. The 2-worker live pilot and subsequent 1/2/4 comparison remain
separate paid work. Cloud preflight, an external exact-VM stop watchdog, and a
calculated run-specific cap still need explicit approval. The root
`FEEDBACK.md` tracks submission feedback by actual tool.

The M4 reducer kernel's September 21 external-provider handoff is historical
provenance only. Jethro has retired that provider from future routing after
integration issues. See the archived handoff under `docs/codex-handoff/tasks/`
only when investigating M4 history; do not treat it as an active instruction.

## Known limitations and risks

- The WSL `.venv` may lack NumPy for the complete suite. The focused WSL
  lifecycle and driver tests, including real process signals, have passed;
  the complete suite passes with Windows Python 3.11.
- Experiment evidence is ignored and local; do not infer that it is published
  or durable off-machine.
- The retained 200 GiB boot disk continues to accrue storage cost while the VM
  is stopped. A future storage/teardown decision should preserve any needed
  model cache and copied evidence explicitly.
- The position failure is empirical and spatially specific, not a causal or
  universal robustness claim.
- The M3 ledger persists `prepared`, `submitting_unknown`, `active`,
  `completing_pending`, and `terminal` per case; results and counts are derived
  from that authority. An interrupted or late completion is not counted as a
  valid replay. Process-group containment was tested with a delayed POSIX
  child, but local tests cannot prove a Docker daemon has no outstanding
  request. An absent-container check is only a local observation. After any
  uncertainty, stop and verify the exact VM before another mode. A stuck
  thread can outlive the CLI's partial-summary deadline; the independent VM
  watchdog is still the cost boundary.
