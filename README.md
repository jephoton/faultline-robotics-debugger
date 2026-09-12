# Robot policy debugging — Nebius × NVIDIA hackathon

Current direction: discover failures in simulated robot manipulation policies, reduce them into reproducible cases, and improve evaluation throughput through profiling and parallel execution.

This repository currently contains planning documents, not a working implementation.

Collaboration: cloud compute is an available main resource; architectural and design choices are discussed with Jethro before adoption, with explanations to support learning. Work is committed frequently using Conventional Commits. See [project instructions](AGENTS.md).

- [Startup plan](docs/superpowers/plans/2026-09-12-robot-debugging-startup.md): proposed stack, local hardware findings, first experiments, implementation milestones, HPC measurements, and submission checklist.
- [Technology learning guide](PROJECT-LEARNING-GUIDE.md): plain-language explanations of robot assurance and failure diagnosis. Failure diagnosis is the selected direction.
- [Baseline stack selection](docs/experiments/stack-selection.md): the pinned GR00T/LIBERO pairing and one-episode pilot scope.
- [Diagnostic trace decision](docs/decisions/0001-diagnostic-trace-and-first-fault.md): why the debugger preserves the upstream evaluator and starts with perception faults.
- [Cloud-pilot preflight](docs/setup/cloud-pilot.md): credential-safe resource, cost, and cleanup checklist.

First milestone: one existing robot policy completes one simulated task and can be replayed. Model training and formal verification are outside the initial scope.
