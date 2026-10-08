# Faultline handoff context

> Generated project context. Keep credentials and large experiment artifacts out
> of this directory.

## Product

Faultline builds a compute-budgeted debugging loop for robot policies:
find a failure, verify that it repeats, reduce the triggering condition, and
save replayable regression evidence. The current validated stack is GR00T N1.7
with the LIBERO Object checkpoint, the AllenAI VLA evaluation harness, and
LIBERO/MuJoCo on Nebius GPU compute.

The name is final as of October 8 under ADR 0019. Further M3/HPC work is
optional stretch, not the core product; deeper HPC learning may move to another
project. Keep the measured fixed-replay throughput result. `robot_debug` imports,
artifact/schema identities, current folder and GitHub repository names remain
unchanged; `faultline-viewer` is the new branded command with the old alias retained.

## Approved future deployment

[ADR 0018](../decisions/0018-serverless-jobs-for-future-runs.md) moves future
evaluations to one finite single-GPU Serverless Job, containing a warm localhost
model server and one direct simulator evaluator in separate Python environments.
Closed local recordings are exported to private Object Storage and downloaded
for the same read-only viewer. Historical VM evidence is retained with its
original provenance, not rerun or relabeled. Local implementation and one US$3
validation allowance are approved; a real Job has not yet validated this backend.
Expanded M3 and external replay remain out of this migration's scope.

## Important components

- `scripts/run_failure_search.py`: bounded centered-severity session driver.
- `scripts/run_position_grid_search.py`: bounded fixed-area spatial search.
- `src/robot_debug/`: records, perturbation, runner, and reporting code.
- `src/robot_debug/viewer/`: read-only artifact catalog and local web viewer.
- `src/robot_debug/evidence_packet.py` and `explanation.py`: pure allowlisted
  packets, reported outcome counts and optional interpretation validation;
  no provider client, persistence or truth certification.
- `src/robot_debug/explanation_store.py`: reviewed immutable case/packet-bound
  sidecars, provenance validation and fresh-source checks. The local store is
  integrated with the guarded CLI and read-only viewer. The first real request
  yielded only factual fallback; one separately approved longer attempt now
  supplies a cautious but shallow interpretation, pending human review and
  actual viewport QA. M5C acceptance remains open.
- `src/robot_debug/token_factory.py`: reviewed fixed-model HTTPS transport,
  safe secret loading and exclusive conservative pilot reservation. Integrated
  through `8110001`; two generations attempted, second structurally valid.
  Both fixed reservations remain consumed. Only the guarded CLI
  may orchestrate paid requests after fresh evidence inspection/reservation.
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
