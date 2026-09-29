# M3 fixed replay workload contract

**Status:** September 29 live 1/2/4-worker comparison complete; billing reconciliation pending

**Harness:** `allenai/vla-evaluation-harness` commit `35f1200eb15608aa898f727a3722f7eef889c6cd`

**Design:** [M3 equal-work parallel evaluation](../superpowers/specs/2026-09-27-m3-equal-work-parallel-evaluation-design.md)

**Decision:** [ADR 0006](../decisions/0006-single-vm-parallel-replay.md)

## Pinned harness findings

Inspection used the immutable source revision linked below, not upstream
`main`:

| Source | Relevant behavior |
| --- | --- |
| [`orchestrator.py`](https://github.com/allenai/vla-evaluation-harness/blob/35f1200eb15608aa898f727a3722f7eef889c6cd/src/vla_eval/orchestrator.py) | Builds work as `(task_idx, task, ep)` for each configured task and `range(episodes_per_task)`. Fixed-seed sharding permutes this list and assigns its round-robin slices. There is no repeat field. Progress files use the shard stem; recording is in SQLite. |
| [`cli/main.py`](https://github.com/allenai/vla-evaluation-harness/blob/35f1200eb15608aa898f727a3722f7eef889c6cd/src/vla_eval/cli/main.py) | `run` accepts `--shard-id`/`--num-shards`, `--eval-id`, output-dir and Docker controls. Docker mode mounts the results directory and gives each process a PID-derived container name. Sharded processes can share one `recording-<eval-id>.sqlite` using WAL; merge materializes JSONL/aggregate files after all shards. |
| [`lerobot.py`](https://github.com/allenai/vla-evaluation-harness/blob/35f1200eb15608aa898f727a3722f7eef889c6cd/src/vla_eval/model_servers/lerobot.py) | GR00T uses the LeRobot policy server. Its comment describes inference as stateless per call and the policy resets at episode start; action chunks are managed per session by the base server. |
| [`predict.py`](https://github.com/allenai/vla-evaluation-harness/blob/35f1200eb15608aa898f727a3722f7eef889c6cd/src/vla_eval/model_servers/predict.py) | Default `max_batch_size=1`; a shared async lock and single-capacity inference limiter serialize non-batched `predict()` calls. Chunk buffers are keyed by session. Thus concurrent evaluator connections are supported, but this default path does not run model inference concurrently or batch it. |
| [`serve.py`](https://github.com/allenai/vla-evaluation-harness/blob/35f1200eb15608aa898f727a3722f7eef889c6cd/src/vla_eval/model_servers/serve.py) | WebSocket connections receive separate session IDs; the server handles multiple connections and reports shared backpressure. This supports request isolation, not an assertion of parallel GPU inference. |

The CLI's native shards divide configured task/episode pairs. Eight items
whose identity is the same task 0, episode index 0, with distinct repeat IDs
cannot be represented as eight explicit repeats by that work-list schema.
Using episode indices 0–7 would evaluate different episode indices and change
the experiment. M3 therefore uses the project-owned scheduler to launch one
existing one-episode run per manifest item. Every item gets a distinct config,
output directory, and evaluator process; no native shard flags are used. The
mode's worker count bounds active processes, while the shared server's default
inference lock serializes model calls. The concurrency pilot must still check
that multiple sessions preserve outcomes and request isolation.

Result naming is made collision-free at the project layer. The harness creates
`recording-<eval-id>.sqlite` in `output_dir`; per-episode materialized JSONL,
aggregate JSON, and recording files derive from benchmark/task/episode context
and configured filename stems. Each invocation therefore receives its own
output directory and eval ID rather than relying on shard suffixes to separate
repeated case artifacts.

## Frozen manifest identity

The manifest contains 16 entries in this stable order. The table explicitly
maps every case ID to its repeat; all rows have `task_id: 0`,
`episode_index: 0`, `seed: 7`, and `env_seed: 7`. Nominal entries have
`rectangle: null`. Mask entries use the M4 accepted reduced rectangle.

| Order | `case_id` | `kind` | `repeat` | `rectangle` |
| ---: | --- | --- | ---: | --- |
| 1 | `nominal-01` | nominal | 1 | null |
| 2 | `nominal-02` | nominal | 2 | null |
| 3 | `nominal-03` | nominal | 3 | null |
| 4 | `nominal-04` | nominal | 4 | null |
| 5 | `nominal-05` | nominal | 5 | null |
| 6 | `nominal-06` | nominal | 6 | null |
| 7 | `nominal-07` | nominal | 7 | null |
| 8 | `nominal-08` | nominal | 8 | null |
| 9 | `mask-01` | mask | 1 | `(0.625, 0, 0.375, 0.375)` |
| 10 | `mask-02` | mask | 2 | `(0.625, 0, 0.375, 0.375)` |
| 11 | `mask-03` | mask | 3 | `(0.625, 0, 0.375, 0.375)` |
| 12 | `mask-04` | mask | 4 | `(0.625, 0, 0.375, 0.375)` |
| 13 | `mask-05` | mask | 5 | `(0.625, 0, 0.375, 0.375)` |
| 14 | `mask-06` | mask | 6 | `(0.625, 0, 0.375, 0.375)` |
| 15 | `mask-07` | mask | 7 | `(0.625, 0, 0.375, 0.375)` |
| 16 | `mask-08` | mask | 8 | `(0.625, 0, 0.375, 0.375)` |

```json
{
  "case_id": "nominal-01",
  "kind": "nominal",
  "repeat": 1,
  "task_id": 0,
  "episode_index": 0,
  "seed": 7,
  "env_seed": 7,
  "rectangle": null
}
```

Each mask row has the same fields, with `case_id` `mask-01` through
`mask-08`, `kind` `mask`, and:

```json
{"x":0.625,"y":0,"width":0.375,"height":0.375}
```

Serialize the whole ordered array as UTF-8 JSON with sorted object keys,
compact separators `(',', ':')`, and non-finite numbers disallowed. Hash those
exact bytes with SHA-256. With the table and shared fields above, the canonical
serialization is 2,257 bytes and its SHA-256 is
`2c815047f734a691b8b55db0dc15521afd175962d7483a7a9f8f06463cd0338a`.
Each 1-, 2-, and 4-worker mode record must contain
the same serialized manifest and digest; mode, worker assignment, host paths,
and timestamps are metadata outside the manifest. Validate digest equality
and the full case-ID multiset before comparing results.

M4 provenance: [bounded reducer result](m4-reducer.md) records task 0, episode
0, seed 7. The all-visible nominal controls succeeded; the parent upper-right
mask failed 4/4, and the accepted reduced rectangle
`(x=0.625, y=0, width=0.375, height=0.375)` failed 4/4. M3 repeats that
known matched pair eight times each to create equal finite work for 1/2/4
workers. This is a systems workload for repeatability, throughput, and cost;
the repeats are not new initial states or independent evidence of
generalization. Assigning distinct episode indices would change the initial
conditions and cease to reproduce the M4 case.

No harness inspection or this contract authorizes Nebius provisioning,
spending, or a live run. Those remain behind the separate resource preflight
and run-cap approval gate in the accepted design.

## Local comparison report

After three complete local or copied mode summaries exist, produce a
fail-closed comparison from the explicit source files. The reporter recomputes
the manifest digest from each sibling `manifest.json`, requires identical item
IDs and complete valid terminal results, and refuses partial or invalid modes.

```powershell
$env:PYTHONPATH = 'src'
& 'C:\Windows\py.exe' -3.11 scripts/run_parallel_eval.py report `
  --mode-summary artifacts/m3-workers-1/session_summary.json `
  --mode-summary artifacts/m3-workers-2/session_summary.json `
  --mode-summary artifacts/m3-workers-4/session_summary.json `
  --output-dir artifacts
```

This writes `m3_comparison.json` and `m3_comparison.md`. Without pricing
inputs, their cost fields are `null` and the table labels cost as unavailable.
Only after a separately approved live run has reconciled billing, provide all
four values together: one verified full-resource `--hourly-rate-usd` and one
`--billable-seconds WORKERS=SECONDS` value for each of 1, 2, and 4 workers.
Cost is rate times measured billable VM seconds divided by 3,600; it is never
multiplied by the number of evaluator workers.

Each source summary and its per-item `runs/<case-id>/` directory remain the
audit trail. Copy those artifacts under the local ignored `artifacts/`
directory, start the existing read-only viewer as documented in `README.md`,
and select the episode entries to inspect their recorded videos. A missing
video is not evidence of a replayable result.

## How to interpret an M3 result

The `elapsed_seconds` recorded by a mode is the warm evaluation clock for that
mode. Keep VM boot, model download/server readiness, setup, teardown, and
other shared overhead in a separate end-to-end clock and allocate its billing
explicitly; do not silently treat simulator runtime as billable time.

M3 measures fixed-repeat confirmation and replay throughput for the same known
M4 case on one shared server. It does **not** measure adaptive reducer speedup,
failure discovery speedup, or generalization to new initial states. Any outcome
drift across worker counts prevents an equivalent-work performance claim until
it is investigated.

## Current live-run status

### Equal-work comparison (September 29)

The approved US$5/two-hour comparison completed on the existing one-L40S VM,
with one shared GR00T server. Each mode used the identical frozen 16-item
manifest (`2c815047f734a691b8b55db0dc15521afd175962d7483a7a9f8f06463cd0338a`):

| Evaluator workers | Valid | Nominal success | Mask policy failure | Warm elapsed | Speedup vs 1 | Efficiency |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 16/16 | 8/8 | 8/8 | 610.247 s | 1.000× | 1.000 |
| 2 | 16/16 | 8/8 | 8/8 | 310.472 s | 1.966× | 0.983 |
| 4 | 16/16 | 8/8 | 8/8 | 164.256 s | 3.715× | 0.929 |

The fail-closed reporter accepted all three fresh, complete summaries and
found no outcome drift. The local ignored tree
`artifacts/m3-comparison-20260929/` contains all 48 non-empty MP4s and
48 non-empty JSONL traces, plus the manifests, per-case configs/results,
and `evaluation/m3_comparison.json`/`.md`. The running viewer indexes these
episodes. The archive `artifacts/m3-comparison-20260929.tar.gz` is another
local copy; none of this evidence is in Git or off-machine backup.

The CLI calculator's full VM rate was US$1.7468/hour before tax. Allocating
only each mode's warm elapsed seconds gives **compute-only estimates** of
US$0.2961, US$0.1506, and US$0.0797 for 1/2/4 workers respectively
(US$0.01851, US$0.00942, and US$0.00498 per valid episode). These are shown
in `warm-cost-report/`; they exclude shared setup and teardown, disk, and
tax, and are **not** provider-billed per-mode costs. The mode time saved on
one VM should reduce marginal compute cost when the overhead is held fixed.

There were two VM-on intervals: a short 229-second start aborted when CLI
authentication expired, and the main 1,858-second session. Using the
operation creation-to-finish bounds (2,087 seconds total) gives a
conservative US$1.0127 compute estimate before tax, or US$1.1038 with an
assumed 9% tax; approximately 1,002 seconds of those bounds were outside
the three warm mode clocks. This is **not an invoice**. Posted billing may
lag, and the retained 200 GiB boot disk accrues separately while stopped.
The VM was verified `STOPPED` after evidence copy and the temporary
workstation-only SSH ingress rule was removed. An OS-managed Windows task
kept the exact-VM guard running during the comparison; it was removed only
after independent stop verification. Guest shutdown was backup. The first
plain detached guard disappeared without a terminal log event, so it was
not trusted for the run. No further paid mode is required for M3.

This supports a narrow systems claim: on this pinned task/policy, overlapping
simulator/evaluator processes improved fixed-work replay throughput on one
shared-server VM without changing these observed outcomes. It does not prove
concurrent model inference, generalization, adaptive search acceleration,
or a universal cloud-cost optimum. The next product work is a separately
designed import/Nemotron flow, not an automatic extension of M3.

### Two-episode pilot

The separately labeled two-episode Nebius pilot ran on September 29 within
Jethro's US$4/90-minute cap. Both evaluators ran concurrently on one L40S VM
against the pinned harness and shared GR00T server. `nominal-01` succeeded
(138 steps, 41.8 seconds) and `mask-01` failed (280 steps, 53.4 seconds).
Both were terminal-valid, replayable, and have non-empty JSONL traces and
MP4s. The warm two-worker evaluation elapsed 53.4 seconds. Local ignored
evidence is in `artifacts/m3-pilot-live-20260929/` and is visible in the
viewer. This is a concurrency/outcome-isolation smoke test, **not** a
1/2/4-worker performance or cost comparison. The summary's `cost_usd` is
null; billable end-to-end cost awaits provider reconciliation.

The VM was stopped promptly after evidence copy, and the temporary SSH
ingress rule was removed. Its retained 200 GiB boot disk still incurs storage
charges; decide retention or teardown within the approved 24-hour window.
At that point the pilot did not authorize the later comparison; Jethro
subsequently approved its separate US$5/two-hour cap.

The local runner uses a durable per-case
attempt ledger: it persists uncertain submission before enqueueing, captures
the full pending result before releasing Future ownership, and derives counts
and visible results from terminal ledger records. On interruption, a late
completion is nonvalid; a possibly submitted case is never silently treated
as untouched. See the [accepted attempt-ownership design](../superpowers/specs/2026-09-28-m3-attempt-ownership-design.md).

The production launcher atomically records each evaluator's exact PID and
expected container name before waiting. An explicit resume path accepts only
a validated partial session with terminal-valid and proven-prepared cases;
uncertain attempts, stale prepared-case outputs/launch sidecars, symlinked
paths, and concurrent resumes fail closed. A matching pre-submit config may
be reused. Resumed runs retain terminal evidence once but are excluded from
throughput comparison, so the benchmark remains based on fresh uninterrupted
modes. See the [recovery plan](../superpowers/plans/2026-09-28-m3-launch-identity-and-resume.md).

Local verification passed 242 Windows tests (3 POSIX-only skips) and 66
focused WSL lifecycle/driver tests, including actual process signals and a
delayed-child containment case. This does not prove daemon-level Docker
containment: the pinned harness can spawn `docker run`, and a daemon request
may remain in flight even after local process-group termination and an
absent-container observation. A stuck thread can also outlive the CLI's
partial-summary deadline. The runner's cleanup observation is not permission
to resume after uncertainty. The independent exact-VM stop guard and guest
shutdown remained the cost boundary for the later comparison, together with
refreshed resource preflight and its separately approved cap.

The separately labeled `pilot` command now runs only `build_manifest(1)` with
two workers in `m3-pilot-workers-2/`. It requires nominal success and reduced
mask failure, plus non-empty trace and MP4 evidence per case; incomplete or
drifted results are non-comparable. The reporter refuses pilot summaries.
The detached Windows exact-VM watchdog passed a real read-only `check` and
was armed before the VM start, with guest shutdown as backup. The pilot
completed and the VM was independently confirmed stopped before the guard's
deadline. Pilot success alone did not authorize the later 48-episode
comparison.
