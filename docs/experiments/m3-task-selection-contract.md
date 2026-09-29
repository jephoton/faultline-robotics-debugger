# M3 multi-job task-selection contract

**Status:** Blocking compatibility finding for the portfolio runner, verified
against the pinned VLA evaluation harness source on 2026-09-30. No cloud run
or task screening was performed.

The pinned `LIBEROBenchmark` can enumerate LIBERO Object tasks internally: it
loops over task IDs from zero through the suite's `n_tasks - 1`, and its reset
method reads `task["task_id"]`. Its constructor, however, accepts suite and
environment settings only; it has no `task_id`, `task_ids`, or episode-index
selector. The pinned orchestrator receives the full task list, truncates it
with top-level `max_tasks`, and makes episode indices from
`range(episodes_per_task)`. Consequently, `max_tasks: 1` selects task 0 and
increasing it selects a *prefix* of tasks, not a particular requested task.

The current generated configuration therefore cannot safely create an
independent job for task 1 or task 2. `episode_indices` choose reset states for
the selected task; they do not select another LIBERO task.

The existing baseline identifies task 0 as `pick up the alphabet soup and
place it in the basket`. This environment does not contain the pinned LIBERO
runtime, so the remaining task-index-to-instruction catalog has not been
verified locally and is intentionally not invented here.

## Consequence

Pause dependent portfolio-runner work until Jethro chooses one of these
architecture options:

1. Add a narrow `task_ids`/single-task selector to the local
   `DiagnosticLIBEROBenchmark` adapter and test it against the pinned harness.
   This gives exact, frozen task jobs and is the recommended route.
2. Use top-level task prefixes only. This cannot support a clean task-level
   scheduler because a job would implicitly run several tasks.
3. Change the benchmark/evaluator integration. This has higher compatibility
   risk and is unnecessary unless the narrow adapter proves impossible.

Do not select three real task IDs, change to another suite, or start a VM from
this finding alone.
