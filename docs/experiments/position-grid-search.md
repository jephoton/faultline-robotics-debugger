# Fixed-area position-grid search

**Status:** local implementation ready; cloud execution not authorized.

This is a preregistered, single-worker session plan. It has no cloud outcomes,
artifacts, or cost charge. The frozen GR00T N1.7 / LIBERO checkpoint is
`nvidia/gr00t17-lerobot-libero_object-640`, as recorded in the
[first-failure experiment](first-failure-search.md); this record does not
introduce a different checkpoint or revision.

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

Only after authorization, each launch must atomically preserve its summary,
all generated YAML, aggregate output, JSONL, SQLite data, and MP4 media under
the ignored `artifacts/position-grid-search-1/` root. No credentials belong in
Git.

The historical planning estimate is about US$0.834 including GST. It is not a
quote, authorization, or measured charge. Before any cloud launch, perform a
fresh live preflight of the account, balance and expiry, GPU quota and capacity,
selected-resource and storage rates, and run-specific cap; Jethro must then
approve that cap explicitly.
