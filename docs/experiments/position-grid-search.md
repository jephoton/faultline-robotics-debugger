# Fixed-area position-grid search

**Status:** bounded cloud session complete; reproducible spatial failure found
and validated against fresh nominal controls.

This was a preregistered, single-worker session. The frozen GR00T N1.7 / LIBERO checkpoint is
`nvidia/gr00t17-lerobot-libero_object-640`, as recorded in the
[first-failure experiment](first-failure-search.md); this record does not
introduce a different checkpoint or revision.

## September 16 cloud result

The corrected `5-series` session ran frozen source commit `c4ec448` on the
existing Nebius L40S VM. The nominal sentinel succeeded. The first three cells
in the fixed order succeeded, while the fourth cell, `x=0.50, y=0.00`, failed.
All five exact replays of that cell failed, and all five fresh unoccluded
controls succeeded. The terminal classification was
`reproducible_failure_with_nominal_controls`.

Coordinates are normalized image coordinates with the origin at the top left,
so this cell occludes the upper-right quarter of the global agent view. The
evidence supports a spatially specific failure under this exact task, initial
state, policy, checkpoint, and occlusion contract. It does not show that every
25%-area occlusion fails, identify a causal visual feature, or establish
robustness outside the tested cells.

| Stage | Geometry | Outcome | Steps |
| --- | --- | --- | ---: |
| `nominal-sentinel` | none | success | 140 |
| `grid-x000-y050` | x=0.00, y=0.50 | success | 139 |
| `grid-x050-y050` | x=0.50, y=0.50 | success | 137 |
| `grid-x000-y000` | x=0.00, y=0.00 | success | 124 |
| `grid-x050-y000` | x=0.50, y=0.00 | policy failure | 280 |
| five exact replays | x=0.50, y=0.00 | 5/5 policy failures | 280 each |
| five nominal controls | none | 5/5 successes | 137--142 |

The driver recorded 15 episodes in 543.26 seconds. Local evidence contains 15
aggregate JSON files, 15 JSONL traces, 15 MP4 videos, and 15 SQLite recordings
under ignored `artifacts/position-grid-search-1/session-5-20260916/`. The
viewer indexes the copied evidence and exposes the failing coordinate label.

The VM was active from `2026-09-16T11:07:46Z` until
`2026-09-16T11:23:43Z` (957 seconds). At the refreshed official rate of
US$1.7468/hour plus US$0.01945/hour for the 200 GiB Network SSD, the bounded
session is estimated at US$0.4695 before tax or US$0.5118 including the 9% GST
assumption. The console balance was US$19.66 immediately before launch; billing
posting may lag. After evidence copy, an independent provider query confirmed
the VM `STOPPED` and no matching temporary SSH rule.

## Local verification

On September 15, local unit discovery completed successfully: 68 tests passed.
Both credential-free CLIs completed `--help` successfully:
`scripts/run_failure_search.py` and `scripts/run_position_grid_search.py`.
`git diff --check` also completed with no whitespace errors. The position-grid
contract tests cover the sentinel plus eight ordered cells, exact discovery and
replay geometry, and five unoccluded controls using temporary fixtures; those
fixtures are not cloud evidence and no real `artifacts/` files were created.

## Fixed contract

The session targets LIBERO Object task 0, episode 0, with `seed=7` and
`env_seed=7`. It changes only the `agentview` policy image: an opaque black
`0.5 x 0.5` square. Wrist input, robot state, instruction, physics, and the
success predicate remain unchanged. The earlier centered `x=0.25, y=0.25`
square succeeded and is context only; it is not rerun here.

The ordered, previously untested cells are:

| Stage | x | y |
| --- | ---: | ---: |
| `x000-y050` | 0 | 0.5 |
| `x050-y050` | 0.5 | 0.5 |
| `x000-y000` | 0 | 0 |
| `x050-y000` | 0.5 | 0 |
| `x025-y050` | 0.25 | 0.5 |
| `x000-y025` | 0 | 0.25 |
| `x050-y025` | 0.5 | 0.25 |
| `x025-y000` | 0.25 | 0 |

Launch one fresh nominal sentinel first. If it succeeds, run the cells in that
order and stop discovery at the first apparent policy failure. Run five exact
replays of that cell; at least 4/5 failures establish the session's
reproducibility screen. Only then run five unoccluded matched nominal controls;
at least 4/5 successes pass the control screen. One sequential worker may
launch at most 19 episodes: 1 sentinel + 8 cells + 5 replays + 5 controls.

## Terminal classifications

The driver stops durably for sentinel, grid, replay, or control infrastructure
errors and for their invalid evidence; it also stops for nominal sentinel
failure, no policy failure in the grid, a nonreproducible candidate, failed or
passed nominal controls, and the launch cutoff. Infrastructure and invalid
evidence never count toward either 4/5 threshold.

## Evidence and authorization gate

The authorized launch atomically preserved its summary,
all generated YAML, aggregate output, JSONL, SQLite data, and MP4 media under
the ignored `artifacts/position-grid-search-1/` root. No credentials belong in
Git.

The live preflight found the exact VM stopped, no stale grid rule, 13 available
on-demand instances against a limit of 32, a US$19.66 balance, and a 26-minute
maximum of about US$0.835 including GST. Jethro's cumulative US$2 cap covered
this session. Any later cloud experiment requires its own scoped design and
fresh preflight; this completion is not authorization for reduction or scaling.
