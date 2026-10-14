# M7a step 2: `faultline diagnose`, replay and image commands

**Goal:** a user with a Nebius project (or, untested, a local NVIDIA GPU)
writes one spec file and runs `faultline diagnose SPEC.yaml`; Faultline runs
the whole mode 1 or mode 2 pipeline, enforces the spend cap, and leaves a
report, a viewer case and an explanation. `faultline replay CASE` re-runs a
saved case.

**Design:** ADR 0031 (scope, CLI wrapping, image distribution, startup cut
skipped), ADR 0027, ADR 0028–0030. No paid run before Jethro approves this
plan; the live check at the end has its own cap.

## Spec (YAML, validated fail-closed)

```yaml
faultline: 1
name: soup-start14                 # run folder and Job name prefix
mode: scenario                     # scenario (mode 1) | audit (mode 2)
policy: {suite: libero_10}         # checkpoint follows the suite (pinned)
scenario:                          # mode 1: one of start / screen / import
  task: 0
  start: 14                        # or: screen: {starts: "10-49", confirm: 4}
  # import: path/to/candidate.json (validated scenario candidate)
  reference: auto                  # nearest passing start, or an index
audit:                             # mode 2
  task: 0
  start: 0
  families: [blur, noise, darken, contrast]
budget:
  max_spend_usd: 3.0               # required; hard cap across all Jobs
  max_hours: 2                     # required; hard wall-clock cap
  max_candidates: 36
nemotron: {hypothesis: true, explain: true}   # needs NEBIUS_API_KEY / --env-file
backend:
  kind: nebius                     # nebius | local
  project: from-cli-profile        # or an explicit project id
  platform: gpu-l40s-a
  preset: 1gpu-16vcpu-64gb
  image: cr.eu-north1.nebius.cloud/REGISTRY/faultline-serverless@sha256:...
  hf_token_secret: faultline-hf-token   # MysteryBox secret name
  hourly_usd: 1.7468               # used for cap arithmetic; checked against live price if available
```

## Components and ownership

| Unit | Files | Owner |
| --- | --- | --- |
| A. CLI, spec, orchestrator | new `src/robot_debug/cli.py`, `spec.py`, `orchestrator.py`, `pyproject.toml` (`faultline` script), tests | agent O |
| B. Backends | new `src/robot_debug/backends/{__init__,nebius,local}.py`, tests with a fake `nebius` executable | agent B |
| C. Cases, replay, image commands | `src/robot_debug/case_store.py`/viewer catalog (register scenario and audit cases), new `replay` and `image` subcommands, generalise the M6 audit runner to any supported suite/task/start, tests | agent C |
| D. Docs, live check | README quickstart, `docs/setup/diagnose.md`, example specs in `configs/specs/`, experiment note | coordinator |

A and B share only the backend Protocol below (agent B owns it); C uses A's
run folder layout. Smaller model (Sonnet) for A–C; coordinator integrates,
reviews and runs the live check. No AI co-author trailers.

## A. Orchestrator (amber)

- **Backend Protocol** (`backends/__init__.py`): `prepare(run) -> Context`,
  `submit(ctx, job_name, workload: dict) -> handle`, `wait(ctx, handle,
  *, deadline) -> JobResult` (terminal state, started/finished times, reason
  such as `NotEnoughResources`), `download(ctx, handle, dest) -> Path`
  (only that Job's prefix), `cancel(ctx, handle)`, `finish(ctx)` (delete
  per-run keys; bucket left to expire), `price_per_hour(ctx) -> float`.
- **Spend ledger:** before each Job, estimate its worst case (deadline x
  rate + 4 min start) and refuse if spent + worst case would exceed
  `max_spend_usd`; after each Job, add the measured cost (container time +
  start allowance). The ledger is written to the run folder after every step.
- **Capacity:** on `NotEnoughResources` resubmit the identical workload under
  a new Job name, up to 6 attempts with a 5-minute pause, inside `max_hours`.
- **Mode 1 pipeline:** start given -> (if `screen`) screen Job, pick the start
  with the most policy failures among those meeting 4-of-5 (ties: lowest
  index; none: stop with `no_reproducible_failure` and print the screen
  table) -> plan (reuse `plan_scenario_reduction.build_plan`; Nemotron via
  the existing Token Factory path; `--no-llm` falls back) -> reduce Job ->
  while not entity-minimal and cap allows: continuation from the best
  reproducing selection (the October 13 manual step, now code) -> report,
  case, measured hypothesis, Ultra explanation.
- **Mode 2 pipeline:** one audit Job (generalised M6 threshold mode) ->
  report, case, explanation.
- **Run folder** `artifacts/runs/<name>-<UTC stamp>/`: spec copy, ledger,
  per-Job folders (workload, Job id, logs tail, evidence), report, case.
  Resumable: `faultline diagnose --resume RUN_DIR` continues after the last
  completed step without repeating paid Jobs.
- Output to the terminal: one line per step with time and spend.

## B. Backends (amber)

- **Nebius** wraps the CLI exactly as the October 13 scratchpad did:
  resolve the executable (`nebius` on PATH, else `wsl -e ~/.nebius/bin/nebius`
  on Windows); project from the CLI profile unless given; **one** bucket per
  diagnosis with a 1-day expiry lifecycle and a storage.viewer policy for a
  **reusable** read group and service account per project (created once,
  found by name afterwards); one access key per diagnosis, deleted in
  `finish`. Submit via `scripts/prepare_serverless_job.py` argv (keeps the
  dry-run and deadline guards), dry-run first, then real submit; recover the
  Job id by name when the create response is not JSON. Poll status with
  timeouts and retries for transient API errors. Download with boto3 (an
  optional `cloud` extra) restricted to the Job's prefix. Never print or log
  secrets; IDs are redacted in terminal output.
- **Local** runs the same image with Docker (`--gpus all`, the workload file
  mounted, output to the run folder). Refuses if no NVIDIA runtime is found.
  Unit-tested with a fake docker; labelled untested on a real GPU.

## C. Cases, replay, image (amber)

- Register each finished diagnosis as a viewer case (scenario and audit
  kinds) with its videos, report and explanation; the existing viewer at
  least lists them (the UI overhaul comes later).
- `faultline replay CASE --spec SPEC.yaml`: one small Job running the case's
  minimal scene and its reference 5 times each; prints whether the failure
  still reproduces (the regression-test use).
- `faultline image build [--push REGISTRY]` wraps the Dockerfile build and
  push and prints the digest to put in the spec. GHCR publication is
  documented but not performed (licence check plus Jethro's go first).
- Generalise the M6 threshold mode's fixed suite/task/start to spec values
  (defaults byte-identical for recorded evidence).

## Tests, commits and gates

TDD with fakes (fake `nebius`, fake docker, fake Token Factory); full suite
green before each commit; Python 3.8 compatibility for anything imported in
the Job. Commits by unit, e.g. `feat(cli): add faultline diagnose spec and
orchestrator`, `feat(cloud): drive Nebius Jobs from the faultline CLI`,
`feat(cli): register diagnosis cases and add faultline replay`.

1. Independent review of A–C (cap arithmetic, resubmission, cleanup on
   every exit path including Ctrl-C, secret handling, resume).
2. Dry-run check: `faultline diagnose --dry-run` on the example specs prints
   the Job plan and worst-case spend without creating anything.
3. **Live check (needs Jethro's go and a top-up; cap US$1.00):** `faultline
   replay` on the October 13 case (minimal scene and reference, 5 each) —
   one Job, exercises the whole backend path, and is itself the first
   regression-test result.

## What would change direction

- The CLI wrapper proves too brittle across environments: revisit the SDK.
- Capacity failures dominate: offer a second platform in the spec (a red
  cost decision for Jethro).
