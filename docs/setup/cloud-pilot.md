# Cloud pilot preflight

**Status:** no Nebius resources have been created. Complete the account-specific
fields with Jethro after local sign-in; never record credentials here.

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
| Nebius project | Pending |
| Region and GPU platform/preset | Pending; verify quota and availability |
| Credit expiry and spending ceiling | Pending; user chooses a maximum |
| VM disk size and price | Pending; account for model and container cache |
| Public access method | Pending; prefer SSH-key access and no public model-server port |
| Persistent artifact location | Pending; object storage or shared filesystem |
| Exact teardown command / console action | Pending |

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
charges. Set a VM auto-stop/explicit shutdown reminder appropriate to the
service's actual options; do not invent a short timeout.

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

