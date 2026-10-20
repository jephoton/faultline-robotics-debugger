# Faultline documentation

## Use Faultline

- [Project overview](../README.md) — product, setup, results and model roles.
- [Public gallery](https://faultline-robotics-debugger.vercel.app/) — four
  recorded examples; no cloud account or installation needed.
- [Run your own](setup/diagnose.md) — installation, model access, image,
  specs, budgets, dry run and recovery.
- [UI walkthrough](ui-runbook.md) — exact clicks and demonstration scenarios.
- [Reference](reference.md) — gates, perturbation levels, report columns
  and stop reasons.
- [Bundled offline case](../demo/README.md) — inspect one layout failure locally.
- [Architecture](architecture.md) — components, data flow and system boundaries.
- [Learning guide](../PROJECT-LEARNING-GUIDE.md) — plain-language explanations.

The public gallery only displays saved evidence. New diagnoses and replays
need local setup and the operator's own paid cloud account.

## Results

- [Final showcase](experiments/m7-final-showcase.md) — the retained layout
  failure, blur/noise results and recorded regression replays.
- [Breadth measurements](experiments/m7-breadth-pack.md) — tested suite/task
  combinations and image, scene and language families.
- [Gallery publication](experiments/m7-public-gallery.md) — four-case export,
  privacy checks, deployment verification and regeneration.
- [Earlier occlusion reduction](experiments/m4-reducer.md) and
  [external-state replay](experiments/m5b-external-replay.md).
- [Camera/visual perturbation experiments](experiments/m6-camera-and-scalar-families.md).
- [Parallel replay](experiments/m3-parallel.md) and
  [batched inference](experiments/m3-batched-inference.md) — supporting
  throughput measurements, not proof of cheaper diagnosis.

Each experiment states its tested conditions and limits. Earlier notes may
describe interfaces or methods superseded by the current diagnosis workflow.
The full record remains under [experiments/](experiments/).

## Feedback, license and submission records

- [Tool feedback](../FEEDBACK.md) — observed strengths, problems and reuse decisions.
- [MIT license](../LICENSE) and [third-party notices](../NOTICE.md).
- [Submission records](submission/README.md) — drafts, audit and billing scope;
  the owner reports submission completed.

## Maintainer references

These are not required to use the app:

- [Operator runbook](codex-handoff/RUNBOOK.md) — recovery, verification and
  local test commands.
- [Current handoff](codex-handoff/STATE.md) — latest verified state and caveats.
- [Project roadmap](../PROJECT_PLAN.md) — milestone history and stretch work.
- [Decision records](decisions/) — accepted choices and their rationale.
- [Development log](dev-log.md) — engineering issues, separate from provider feedback.
- [Setup notes](setup/) — additional access and infrastructure detail.
- [Plans and specs](superpowers/) and [research](research/) — development history,
  including superseded VM-era approaches.
