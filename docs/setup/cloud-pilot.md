# Cloud pilot preflight

**Status:** one bounded initial-account VM was provisioned on September 13,
2026. The local CLI is authenticated to that account. Never record credentials
here. Its managed boot disk must be deleted with the VM after artifacts are
copied.

## Provisioned pilot state

The running VM is named `robot-debug-pilot`; identifiers and IP addresses are
kept out of committed files. It has the selected `gpu-l40s-a` /
`1gpu-16vcpu-64gb` resources, a 200 GiB managed Network SSD boot disk, and the
`ubuntu24.04-cuda13.0` image family. A guest-side eight-hour shutdown guard was
set at creation.

Verification over the restricted SSH path found:

| Item | Observed value |
| --- | --- |
| GPU | NVIDIA L40S, 46,068 MiB; driver 580.173.02 |
| Docker | Docker Engine 29.8.0, usable by the dedicated `robot` user |
| Root disk after setup | 175 GiB available |
| Harness | pinned checkout `35f1200eb15608aa898f727a3722f7eef889c6cd`; isolated `vla-eval` CLI installed |
| LIBERO container | Cached at `ghcr.io/allenai/vla-evaluation-harness/libero@sha256:d0c45bc5a3720d569180e6b8dd92510da895f16c3cc509ccc76e4b4ffbb9e0f0` (5.99 GB) |

The upstream checkout, Python environment, container cache, model cache, logs,
and recordings live only on this managed disk. No model weights have been
downloaded. The selected GR00T repositories are public and not gated, so a
Hugging Face token is optional rather than a prerequisite. See
[model-access.md](model-access.md).

The cached LIBERO image was started with Docker's GPU runtime and independently
reported the same L40S, 46,068 MiB GPU memory, and 580.173.02 driver as the
host. This passes the container-GPU compatibility gate without downloading or
starting a policy.

## Recommended pilot topology

Use one regular Nebius GPU virtual machine for the first evaluation, with the
model server and LIBERO evaluator on the same host.

This is deliberately more conservative than starting with a Serverless AI job.
The selected VLA Evaluation Harness starts the LIBERO benchmark in a Docker
container, while the GR00T model server runs on the host. A VM gives us a normal
Docker daemon and direct access to the resulting recordings. A Serverless job
is a good later option only after we build a single self-contained image or
explicitly verify nested Docker support.

Use an Ubuntu 24.04 CUDA image, one GPU, and enough local disk for the model,
the roughly 6 GB LIBERO image, Python/uv caches, and recordings. Select the
actual platform, preset, region, disk size, and maximum price only after
checking the signed-in account. One worker is sufficient for the pilot.

### Current read-only evidence (September 13)

The authenticated initial account has active projects in `eu-north1`. The
capacity service reported 31 on-demand slots for the following candidate at the
time of the check:

| Candidate | GPU memory | Host resources | Availability |
| --- | ---: | --- | --- |
| `gpu-l40s-a` / `1gpu-16vcpu-64gb` | 48 GB | 16 vCPU, 64 GiB RAM | 31 of 32 on-demand slots available |

The corresponding official L40S Intel rates at that check were US$1.35 per GPU
hour, US$0.012 per vCPU hour, and US$0.0032 per GiB-hour. The resulting compute
estimate is **US$1.7468 per running hour**:

```text
1 × 1.35 + 16 × 0.012 + 64 × 0.0032 = 1.7468 USD/hour
```

Source: [Nebius Compute pricing](https://docs.nebius.com/compute/resources/pricing).

For a 200 GiB Network SSD boot disk, the listed US$0.071/GiB-month rate is
approximately US$0.0195/hour (US$0.47/day) while the disk exists, including
when the VM is stopped. A proposed first-run limit is **8 hours**: about
US$13.97 of running compute plus at most one day of disk, leaving meaningful
room inside the initial account's US$20--25 allocation. This is a proposed
run-specific cap, not permission to create the VM. Recheck capacity and pricing
immediately before provisioning.

The public image listing contains the Ubuntu 24.04 CUDA 13.0 image family
(`ubuntu24.04-cuda13.0`) for this region. Use the family name for creation and
record the resolved image ID in the ignored run log; that preserves both an
up-to-date security image at launch and experiment reproducibility.

## Account-specific preflight

Record these values locally when cloud access is configured:

| Item | Required value |
| --- | --- |
| Nebius project | Initial-balance account authenticated and active. Main-account project pending. |
| Region and GPU platform/preset | `eu-north1`, candidate `gpu-l40s-a` / `1gpu-16vcpu-64gb`; read-only capacity check reported 31 on-demand slots available. |
| Credit expiry and spending ceiling | US$75 total project envelope; verify account-specific balances and expiry before each run. |
| VM disk size and price | Pending; account for model and container cache |
| Public access method | Pending; prefer SSH-key access and no public model-server port |
| Persistent artifact location | Pending; object storage or shared filesystem |
| Exact teardown command / console action | Pending |

The account's VM, L40S-GPU, and network-SSD quota records are present and
unused. Capacity availability is dynamic, so repeat the check just before VM
creation; it is evidence of feasibility, not a reservation.

The default project subnet is ready. There are currently no VMs or disks in the
project. Do not rely on a blank-list response as a numeric count without first
checking that it contains an `items` array.

## Proposed execution and teardown sequence

For the initial account, use one VM with a **managed** 200 GiB boot disk. The
model cache, upstream checkout, recordings, and logs live on that disk for at
most 24 hours. Copy selected artifacts back to the workstation before teardown;
do not create a long-lived object-store or filesystem dependency for this first
episode. Managed disks are deleted together with the VM, which eliminates the
most likely forgotten-storage charge.

The workstation had no existing default WSL SSH public key, so a dedicated
project key was created locally with restrictive file permissions. It is not
tracked and its private material is never printed or copied to the VM.

Jethro selected a temporary public IP for the pilot. The provider's default
security group allows all ingress, so the VM will instead use a dedicated
security group with only stateful TCP/22 ingress from the workstation's current
public IPv4 `/32` and stateful outbound access for package/model downloads. No
model, notebook, simulator, or other application port is public. If the
workstation's public IP changes, update the SSH rule before attempting to
reconnect.

After artifacts are copied, delete the VM and verify no unmanaged disk remains:

```bash
nebius compute instance delete <instance-id>
nebius compute disk list --parent-id <project-id> --all
```

The first command also deletes managed disks declared in the VM specification.
If an unmanaged disk was created separately, explicitly delete it only after
checking its ID and confirming its contents have been copied.

## Budget and account sequence

The project has a confirmed **US$75** overall Nebius-credit plan:

| Account role | Planned credit | Intended work |
| --- | ---: | --- |
| Initial-balance account | US$25 | First clean baseline, integration, and limited repeat runs |
| Main account | US$50 (US$25 initial balance + US$25 hackathon promo) | Perturbation search, reduction, parallel measurements, and demo capture |

Do not intentionally waste the initial US$25 balance. It is a constrained but
useful first execution budget. The main account must have payment details in
place before the promo code can be applied.

Nebius does not support moving a project between tenants or regions. The
account handoff therefore means selecting or creating a separate project and a
separate local CLI profile, while continuing from the same Git repository and
recording the account role in local run evidence. It is not a project migration.

At the last pricing check, the candidate L40S with 16 vCPU and 64 GiB RAM in
the target region was US$1.7468 per running hour before disk/storage charges.
This is only a planning estimate: retrieve the live price for the exact
available platform/preset immediately before provisioning. The US$75 envelope
is roughly 43 such GPU-hours before storage, so avoid idle time and open-ended
sweeps.

## Credentials and model access

Sign in through the Nebius console or CLI on the local machine. Store any
Hugging Face token only in the cloud secret mechanism or the VM's local
environment; do not put it in a YAML file, shell history, Git, or chat. The
policy/base-model terms must be accepted by the account holder if access
requires it.

The model server should listen only on the VM loopback interface. The evaluator
then connects to `ws://localhost:8000`; no public inference endpoint is needed
for this colocated pilot.

## Cost and cleanup guardrails

Before creation, calculate the maximum cost as the selected hourly GPU/preset
rate multiplied by an agreed maximum runtime, plus disk and persistent-storage
charges. For this project, keep the initial-account baseline/integration work
within US$20--25, reserve US$40--45 of the main account for experiments and
demo capture, and keep US$5--10 of the overall envelope unallocated until the
end. Set a VM auto-stop/explicit shutdown reminder appropriate to the service's
actual options; do not invent a short timeout.

After a pilot:

1. Copy recordings, logs, resolved configuration, and image/model revision
   evidence to persistent storage.
2. Stop or delete the VM using the recorded command or console action.
3. Check for billable disks, public IPs, snapshots, and object-storage data
   that remain after compute stops.
4. Record the run's wall-clock duration, GPU type, and actual resource IDs in
   an ignored local run log, not in a committed credential file.

Nebius Serverless AI jobs have a minimum one-hour timeout and can mount
persistent storage, so they remain attractive once the workload is packaged as
a single container. This is a deployment optimisation, not a baseline
requirement.
