# Project handoff context

> Generated project context. Keep credentials and large experiment artifacts out
> of this directory.

## Product

This repository builds a compute-budgeted debugging loop for robot policies:
find a failure, verify that it repeats, reduce the triggering condition, and
save replayable regression evidence. The current validated stack is GR00T N1.7
with the LIBERO Object checkpoint, the AllenAI VLA evaluation harness, and
LIBERO/MuJoCo on Nebius GPU compute.

## Important components

- `scripts/run_failure_search.py`: bounded centered-severity session driver.
- `scripts/run_position_grid_search.py`: bounded fixed-area spatial search.
- `src/robot_debug/`: records, perturbation, runner, and reporting code.
- `src/robot_debug/viewer/`: read-only artifact catalog and local web viewer.
- `src/robot_debug/evidence_packet.py` and `explanation.py`: pure allowlisted
  packets, reported outcome counts and optional interpretation validation;
  no provider client, persistence or truth certification.
- `configs/`: validated experiment configuration.
- `docs/decisions/`: accepted architecture and experiment decisions.
- `PROJECT_PLAN.md`: milestone roadmap and current project position.
- `artifacts/`: ignored local evidence; never commit large recordings.

## Boundaries

- The demonstrated claim is limited to the named policy, task, seeds, and
  perturbation space. Do not claim universal failure coverage or causal proof.
- Preserve the integrated differentiator: budgeted search, repeatability,
  reduction, replay, and GPU time/cost measurement.
- Cloud spending, model/simulator changes, failure definitions, search or
  reduction algorithms, publication, and submission claims require Jethro's
  decision.
- Never commit credentials, tokens, private keys, model weights, or
  secret-bearing logs.
- Use one owner for stateful Nebius execution and spending.
