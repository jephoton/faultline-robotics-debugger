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
place it in the basket`. Source inspection of the [harness-pinned LIBERO
revision](https://raw.githubusercontent.com/Lifelong-Robot-Learning/LIBERO/8f1084e3132a39270c3a13ebe37270a43ece2a01/libero/libero/benchmark/libero_suite_task_map.py)
gives provisional IDs 1 = cream cheese, 2 = salad dressing, and 3 = BBQ sauce,
each placed in the basket. The [pinned harness Dockerfile](https://raw.githubusercontent.com/allenai/vla-evaluation-harness/35f1200eb15608aa898f727a3722f7eef889c6cd/docker/Dockerfile.libero)
selects that LIBERO revision, and its benchmark enumerates IDs from zero.
This is pinned-source evidence, not runtime enumeration or GR00T baseline
success. IDs 1 and 2 are sensible screening candidates because they keep the
same single-object-to-basket task shape, but Jethro has not frozen the actual
three-job manifest.

This resolves the local config-compatibility block for constructing distinct
portfolio jobs. Unit tests use a fake upstream task list; the exact selector
has not yet been exercised on the installed LIBERO runtime. Verify the actual
image's task catalog and nominal outcomes before freezing three real task IDs.
Do not change suites or start a VM from this local proof alone.
