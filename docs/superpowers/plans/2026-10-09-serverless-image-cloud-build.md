# Serverless Image Cloud Build Plan

**Goal:** Build `deploy/serverless/Dockerfile` in Nebius, probe it without a GPU,
push it to a private registry and record its immutable digest for the approved
L40S pilot Job. The workstation disk could not hold the build.

**Approval (October 9, Jethro):** option A, all-in builder cap **US$1.50**,
separate from the US$3 L40S Job cap. AI Cloud top-up confirmed by Jethro;
amount not stated. The US$25 promo credit is Token Factory only. Keep the
stopped `robot-debug-pilot` VM/disk until the pilot succeeds or October 16,
whichever is first, then delete with explicit approval.

## Resources and prices (read-only checked October 9)

| Resource | Shape | Rate (pre-tax) |
| --- | --- | --- |
| Private container registry | one, in `default-project-eu-north1` | service free of charge |
| Builder VM | `cpu-d3` / `8vcpu-32gb`, public IP | US$0.264/h |
| Builder boot disk | managed 150 GiB network SSD, `ubuntu24.04-driverless` | US$0.0146/h |

Maximum builder lifetime 90 minutes, about US$0.42. Guest `shutdown -h +100`
and a workstation watchdog that deletes the exact instance at 95 minutes are
backups. The managed disk is deleted with the instance.

## Access

Reuse security group `robot-debug-pilot-ssh` (egress only). Add one stateful
TCP/22 ingress rule from the workstation's current `/32`; delete it after.
Reuse the existing untracked project SSH key. Source reaches the VM as a
`git archive HEAD` tarball: no GitHub credentials on the VM. Docker logs in to
`cr.eu-north1.nebius.cloud` with a short-lived `nebius iam get-access-token`
piped over SSH stdin; never printed or stored in the repository.

## Steps (root-owned; one execution owner)

1. Create the registry; record its ID in an ignored run directory
   `artifacts/serverless-builder-20261009/`.
2. Add the SSH rule; create the builder VM; arm the watchdog.
3. Wait for cloud-init (Docker installed), copy the tarball, `docker build`.
4. Probe without GPU: both Python environments import, `vla-eval run --help`
   supports `--no-docker`, `robot_debug.job_entry` imports under the simulator
   Python 3.8, no baked secrets/weights, image size.
5. Push; record the `@sha256` digest.
6. Delete the instance and SSH rule; verify only the stopped pilot VM/disk,
   network, security groups and the registry remain.
7. Record results in `FEEDBACK.md`, the experiment note and handoff.

Any build or probe failure stops the run: copy logs, tear down, report.
GPU/renderer/inference remain unverified until the Job.
