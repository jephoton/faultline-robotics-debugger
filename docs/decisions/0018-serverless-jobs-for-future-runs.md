# ADR 0018: Serverless Jobs for future robot evaluations

Status: accepted topology and output-storage direction, October 6, 2026.
Paid execution: not yet approved; read-only preflight is authorized.

Jethro approved migrating future evaluations to one finite, single-GPU Nebius
Serverless Job. Keep the model server and one simulator evaluator in the same
container, communicating over localhost. Endpoints and Devlabs are not needed
for this first migration. Preserve existing VM videos, traces and conclusions
with their original provenance; do not rerun experiments merely to change the
deployment label. Expanded M3 stays frozen and external-state replay deferred.

Jethro also approved private Object Storage for Job outputs. Write live
SQLite/JSONL/MP4 evidence to the container's local disk. Copy closed output
files into a unique run prefix and publish a checksum manifest last. A bucket
mount is an export destination, not a transactional experiment filesystem.
Storage provisioning and retention belong in the later explicit spending cap.

The migration is deployment work, not an algorithm or policy change. Retain
the existing LIBERO image digest and separate simulator/model environments;
the historical simulator harness is 0.5.0, not the host's 0.5.1.dev5. Inspect
the actual image before relying on its direct CLI. Do not replace its source
with the model-server checkout or resolve a new robot policy implicitly.

Validate a fresh nominal/reduced-mask episode pair with fresh policy actions,
complete media and traces, and actual runtime provenance. A valid run is not
required to reproduce historical outcomes: disagreement must be reported.
Only this new validation evidence may be described as Serverless execution.
Existing search/grid/reduction drivers should remain configurable through
their command-runner seams, without changing their algorithms or evidence.

References: [design](../superpowers/specs/2026-10-06-serverless-job-migration-design.md),
[implementation plan](../superpowers/plans/2026-10-06-serverless-job-migration.md),
[official Job configuration](https://docs.nebius.com/serverless/jobs/manage).
