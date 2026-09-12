# Cloud pilot preflight

**Status:** no Nebius resources have been created. The local CLI is authenticated
to the initial-balance account, but its projects were observed suspended on
September 13, 2026. Billing activation is therefore still required before any
VM can be created. Never record credentials here.

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

## Account-specific preflight

Record these values locally when cloud access is configured:

| Item | Required value |
| --- | --- |
| Nebius project | Initial-balance account authenticated; selected project is suspended. Main-account project pending. |
| Region and GPU platform/preset | Initial account observed in `eu-north1`; verify quota and availability after billing is active. |
| Credit expiry and spending ceiling | US$75 total project envelope; verify account-specific balances and expiry before each run. |
| VM disk size and price | Pending; account for model and container cache |
| Public access method | Pending; prefer SSH-key access and no public model-server port |
| Persistent artifact location | Pending; object storage or shared filesystem |
| Exact teardown command / console action | Pending |

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

At the last pricing check, an L40S with 16 vCPU and 64 GiB RAM in the target
region was approximately US$1.75 per hour before disk/storage charges. This is
only a planning estimate: retrieve the live price for the exact available
platform/preset immediately before provisioning. The US$75 envelope is roughly
43 such GPU-hours before storage, so avoid idle time and open-ended sweeps.

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
