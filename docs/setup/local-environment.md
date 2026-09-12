# Local environment discovery

**Status:** observed on September 12, 2026. This is a development machine, not
the target for the first GR00T/LIBERO run.

## What is available

| Component | Observed state | Consequence |
| --- | --- | --- |
| Windows GPU | NVIDIA GeForce RTX 3050 Laptop GPU, 4,096 MiB VRAM, driver 591.59 | Insufficient headroom should be assumed for the selected policy and simulator together. |
| System memory | About 15.36 GiB | Suitable for editing and small checks, not many heavy simulator workers. |
| Windows system disk | About 8 GiB free | Do not download model weights, datasets, or Docker images locally. |
| WSL | Ubuntu 24.04.3 LTS on WSL2 | Useable for lightweight Linux inspection. |
| WSL Python | Python 3.12.3; PyYAML 6.0.1 | Enough to validate YAML, but not treated as the experiment runtime. |
| WSL GPU visibility | Same RTX 3050 is visible to `nvidia-smi` | GPU passthrough to WSL exists; this does not establish Docker GPU support. |
| Docker in WSL | Docker CLI unavailable; Docker Desktop was not running | Local container evaluation is currently unavailable. |
| `uv` / Nebius CLI | Not found in WSL PATH | Install or use a cloud job image only when preparing the cloud pilot. |

The WSL virtual disk reports substantial logical free space, but its backing
Windows drive is nearly full. Treat the Windows free-space figure as the
practical limit.

## Development / execution split

The authoritative Git checkout remains the Windows checkout at
`C:\Users\Jethro\Documents\nebius-nvidia-hackathon`. The laptop is used for
source edits, documentation, and light validation. The first real evaluation
will run on Nebius with model inference and simulation colocated on the same
GPU host.

This avoids two avoidable problems: a 4 GiB local GPU is unlikely to fit the
policy with rendering overhead, and streaming camera observations over the
internet would change the timing experiment.

## Before a cloud run

1. Sign in to Nebius locally and select the project; never place credentials in
   this repository or chat.
2. Confirm available regions, GPU quota, credit expiry, price, and a user-set
   spending ceiling.
3. Confirm the selected NVIDIA GPU has enough VRAM for the model plus a LIBERO
   worker, then use one worker for the first pilot.
4. Download the model and container only into cloud-attached storage or the
   cloud job's local cache.
5. Record the explicit job-stop and resource-cleanup procedure in
   `docs/setup/cloud-pilot.md` before creating billable compute.

