# Robot policy debugging — Nebius × NVIDIA hackathon

Current direction: discover failures in simulated robot manipulation policies, reduce them into reproducible cases, and improve evaluation throughput through profiling and parallel execution.

This repository contains baseline preparation plus a small, tested core for
replayable experiment records. It does not yet run a robot model or provision
cloud compute.

Collaboration: cloud compute is an available main resource; architectural and design choices are discussed with Jethro before adoption, with explanations to support learning. Work is committed frequently using Conventional Commits. See [project instructions](AGENTS.md).

- [Startup plan](docs/superpowers/plans/2026-09-12-robot-debugging-startup.md): proposed stack, local hardware findings, first experiments, implementation milestones, HPC measurements, and submission checklist.
- [Technology learning guide](PROJECT-LEARNING-GUIDE.md): plain-language explanations of robot assurance and failure diagnosis. Failure diagnosis is the selected direction.
- [Baseline stack selection](docs/experiments/stack-selection.md): the pinned GR00T/LIBERO pairing and one-episode pilot scope.
- [Diagnostic trace decision](docs/decisions/0001-diagnostic-trace-and-first-fault.md): why the debugger preserves the upstream evaluator and starts with perception faults.
- [Attempt-record decision](docs/decisions/0002-attempt-record-boundary.md): the portable record shared by future runners, reducers, and reports.
- [Cloud-pilot preflight](docs/setup/cloud-pilot.md): credential-safe resource, cost, and cleanup checklist.

First milestone: one existing robot policy completes one simulated task and can be replayed. Model training and formal verification are outside the initial scope.

## Local checks

The current core uses only the Python standard library. From Ubuntu in WSL,
run:

```bash
cd /mnt/c/Users/Jethro/Documents/nebius-nvidia-hackathon
PYTHONPATH=src python3 -B -m unittest discover -s tests -v
```

This checks the portable attempt-record contract before it is connected to the
cloud evaluator.

## Viewer

The read-only viewer turns copied experiment artifacts into a paired demo of a
nominal robot-policy episode and a fault-injected episode. It never changes an
artifact and labels infrastructure errors separately from robot task failures.

Cloud evidence must first be copied or synchronized into the local `artifacts/`
directory. Then launch the viewer from PowerShell:

```powershell
$workspacePython = 'C:\Users\Jethro\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
& $workspacePython -m robot_debug.viewer.server --artifacts artifacts --port 8765
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). Select a nominal baseline
as the primary evidence and the global-occlusion episode as the comparison;
use the paired videos, conclusion line, and timeline to tell the failure
diagnosis story. An `INFRA ERROR` means the policy was not evaluated, rather
than that the robot failed the task.

The viewer binds only to loopback by default. Do not use `--host 0.0.0.0` on an
untrusted network.
