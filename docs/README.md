# Where to look

A short index for judges and new readers. Each result note states its tested
suite, task, start and perturbation family; none is a general claim.

## Start here

- [Project README](../README.md): what Faultline does, what it has found, how
  NVIDIA and Nebius are used.
- [Quickstart: run a diagnosis](setup/diagnose.md): setup, specs, dry run,
  resume, replay.
- [Hackathon tool feedback](../FEEDBACK.md) and
  [third-party notices](../NOTICE.md).
- [Learning guide](../PROJECT-LEARNING-GUIDE.md) in plain language, and the
  [project plan](../PROJECT_PLAN.md) with the current status table.

## Results

The three M7 notes are the newest and use the `faultline` tooling:

- [M7 mode 1: scenario reduction](experiments/m7-scenario-reduction.md):
  LIBERO-10 task 0, start 14 against start 28, reduced to five shifts needed
  together; includes the Nemotron model comparison and the regression replay.
- [M7 breadth pack](experiments/m7-breadth-pack.md): four suites; image
  catalog, lighting, viewpoint and paraphrases, one task and start per family.
- [M6: camera roles and scalar families](experiments/m6-camera-and-scalar-families.md):
  wrist versus third-person camera; blur, noise, darkening and contrast
  thresholds.
- [M4: the occlusion reducer](experiments/m4-reducer.md) and
  [M5B: external-start replay](experiments/m5b-external-replay.md).
- [M3 batched inference](experiments/m3-batched-inference.md) and
  [M3 parallel replay](experiments/m3-parallel.md): throughput measurements.
- [M5D: Tavily research context](experiments/m5d-tavily-research.md) and
  [M5 Nemotron pilot](experiments/m5-nemotron-pilot.md).

Earlier setup and baseline notes are in [experiments/](experiments/).

## Setup notes

[setup/](setup/): [diagnose quickstart](setup/diagnose.md),
[model access](setup/model-access.md), [Serverless Jobs](setup/serverless-jobs.md),
[case workbench](setup/case-workbench.md). The
[local environment](setup/local-environment.md) and
[cloud pilot](setup/cloud-pilot.md) notes describe the earlier VM-based work.

## Design decisions (ADRs)

All in [decisions/](decisions/). The ones that shape the product:

| ADR | Decision |
| --- | --- |
| [0027](decisions/0027-m7-product-consolidation-and-access.md) | M7 product direction: two modes, `faultline diagnose`, breadth pack, access options |
| [0028](decisions/0028-m7-scenario-reduction-design.md) | How mode 1 reduces a failing start to the shifts that matter |
| [0029](decisions/0029-m3-latency-startup-and-early-decided-gates.md) | Early-decided repeatability gates; the startup cut and warm Endpoint |
| [0030](decisions/0030-nemotron-model-per-task.md) | Which Nemotron model does which job, chosen by measurement |
| [0031](decisions/0031-faultline-diagnose.md) | One command that owns the whole cloud lifecycle and spend cap |
| [0032](decisions/0032-breadth-pack.md) | Four suites, image catalog, paraphrase and scene families |
| [0026](decisions/0026-m6-camera-reliance-and-scalar-families.md) | Camera reliance and scalar image families (M6) |
| [0025](decisions/0025-m3-batched-inference-experiment.md) | The batched-inference experiment |
| [0024](decisions/0024-m5d-tavily-research-context.md) | Tavily research context |
| [0018](decisions/0018-serverless-jobs-for-future-runs.md) | Serverless Jobs for future runs |
| [0020](decisions/0020-mit-code-license.md) | MIT licence for original code |

The earlier ADRs, in order:
[0001](decisions/0001-diagnostic-trace-and-first-fault.md) diagnostic trace and
first fault;
[0002](decisions/0002-attempt-record-boundary.md) the immutable attempt record;
[0003](decisions/0003-temporary-public-ssh-for-cloud-pilot.md) temporary SSH for the first VM pilot;
[0004](decisions/0004-fixed-area-position-grid.md) occlusion position search at fixed area;
[0005](decisions/0005-bounded-failure-reduction.md) bounded nested-rectangle reduction;
[0006](decisions/0006-single-vm-parallel-replay.md) single-VM parallel replay;
[0007](decisions/0007-separate-two-episode-m3-pilot.md) the two-episode M3 pilot;
[0008](decisions/0008-exact-vm-workstation-watchdog.md) the exact-VM watchdog;
[0009](decisions/0009-portfolio-first-hpc.md) portfolio-first HPC;
[0010](decisions/0010-h100-snapshot-migration.md) the H100 snapshot clone;
[0011](decisions/0011-freeze-expanded-m3.md) freezing expanded M3;
[0012](decisions/0012-m5-cli-first-workbench.md) CLI-first case workbench;
[0013](decisions/0013-m5-independent-case-capabilities.md) independent case capabilities;
[0014](decisions/0014-m5-bounded-sample-and-nemotron-pilot.md) external sample and Nemotron pilot;
[0015](decisions/0015-m5-evidence-bound-interpretations.md) evidence-bound interpretations;
[0016](decisions/0016-m5-narrow-external-state-restore.md) narrow external state restore;
[0017](decisions/0017-m5-bounded-nemotron-repair.md) the longer Nemotron attempt;
[0019](decisions/0019-faultline-name-and-hpc-scope.md) the Faultline name and optional HPC scope;
[0021](decisions/0021-m5-demo-1-and-m5c-acceptance.md) accepting external demo_1;
[0022](decisions/0022-grid-continues-after-unreproducible-failures.md) the position grid keeps searching;
[0023](decisions/0023-post-m5-roadmap-order.md) post-M5 roadmap order.

## History and internal working notes

These record how the project was built, including superseded plans, working
logs and VM-era tooling. They are kept for transparency and are **not needed
to use Faultline**; some describe approaches since replaced by Serverless Jobs
and `faultline diagnose`.

- `superpowers/`: implementation plans and specs written before each step.
- `codex-handoff/`: handoff documents from earlier agent sessions (state,
  runbook, task briefs).
- [dev-log.md](dev-log.md): engineering issues, kept apart from provider
  feedback; [history-rewrite-2026-10-11.md](history-rewrite-2026-10-11.md) and
  [milestone-commit-audit.md](milestone-commit-audit.md): repository history.
- `research/`: feasibility and access research notes.
- VM-era scripts: `scripts/cloud_guest/`, `scripts/run_vm_watchdog.py`,
  `scripts/run_diagnostic_portfolio.py` and `scripts/run_parallel_eval.py`
  drove the single-VM pilots (ADRs 0003 to 0011), before Serverless Jobs.
