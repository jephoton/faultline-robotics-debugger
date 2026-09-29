# M3 multi-job task-selection contract

**Status:** Local adapter implemented and regression-tested on 2026-09-30.
Pinned-harness compatibility was checked in source, but no live LIBERO task
screening or cloud run was performed.

The pinned `LIBEROBenchmark` can enumerate LIBERO Object tasks internally: it
loops over task IDs from zero through the suite's `n_tasks - 1`, and its reset
method reads `task["task_id"]`. Its constructor, however, accepts suite and
environment settings only; it has no `task_id`, `task_ids`, or episode-index
selector. The pinned orchestrator receives the full task list, truncates it
with top-level `max_tasks`, and makes episode indices from
`range(episodes_per_task)`. Consequently, `max_tasks: 1` selects task 0 and
increasing it selects a *prefix* of tasks, not a particular requested task.

The local `DiagnosticLIBEROBenchmark` now filters the upstream `get_tasks()`
result by exact `task_id` without changing the retained task dictionary or
its original ID. The generated stage config writes `params.task_id` for
nonzero task IDs; task 0 retains the historical `max_tasks: 1` config.
`episode_indices` still choose reset states for the selected task, not the
task itself. Missing or invalid task IDs fail closed in the adapter.

The existing baseline identifies task 0 as `pick up the alphabet soup and
place it in the basket`. This environment does not contain the pinned LIBERO
runtime, so the remaining task-index-to-instruction catalog has not been
verified locally and is intentionally not invented here.

This resolves the local config-compatibility block for constructing distinct
portfolio jobs. Unit tests use a fake upstream task list; the exact selector
has not yet been exercised on the installed LIBERO runtime. Do not select
three real task IDs, change suites, or start a VM from this local proof alone.
