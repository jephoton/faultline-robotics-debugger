# Serverless Job migration validation

## Scope and approval

One fresh nominal/reduced-mask episode pair on one GPU, not historical reruns.
The user approved US$3 incremental spend, at most one hour allocated, and private
output retention at most 24 hours, with at most 1 GiB evidence downloaded. The
original VM/disk are not cleanup targets. See
[ADR 0018](../decisions/0018-serverless-jobs-for-future-runs.md).
No billable resource was created during the following checks.

## October 6 read-only preflight

- WSL Ubuntu and Nebius CLI 0.12.275 work; local OAuth was renewed by Jethro.
- Existing eu-north1 project is active and original robot VM is STOPPED.
- Tenant L40S Compute quota limit is32. Exact `gpu-l40s-a`,
  `1gpu-16vcpu-64gb` resource advice returned19on-demand available/MEDIUM at
  the lookup; this is advice, not an allocation guarantee.
- Live calculator estimate for that one-GPU shape isUS$1.7468/hour before tax.
  A150GiBNetworkSSD quote isUS$0.0145833/hour. First GPU calculator lookup hit
  a connection deadline; the subsequent bounded lookup succeeded.
- Current CLI `ai job create --dry-run` accepted the shape, existing subnet,
  pinned public simulator image, restart-policy never,150GiBdisk and1htimeout.
  It explicitly reported validation success and no resource created. This is
  control/configuration validation, not simulator/model Job execution.
- Actual AI Cloud balance and expiry were not independently read. Jethro
  declined the console check, stated funds were adequate and asked to proceed.
  Token Factory's separately reported balance is not evidence for this account.
- [Registry pricing](https://docs.nebius.com/container-registry/resources/pricing)
  states the service is free. [Object Storage pricing](https://docs.nebius.com/object-storage/resources/pricing)
  listsStandardUS$0.0147/GiB/730hours,US$0.015/GiBinternet egress, plus
  request charges. Prices exclude tax. Under the one-hour limit the quoted
  GPU/disk subtotal isUS$1.7613833; applying the planning9%tax assumption gives
  US$1.919907797before small output/request costs. This is not posted billing.

## Local verification and blocker

Clean isolated runtime checkout's fullWindowsPython3.11suite:581testsOK,
fourPOSIX-only skips,128.322seconds. Lifecycle-failure fixture diagnostics in
that suite do not indicate an actual VM stop failure.

Docker Desktop4.43.2 failed before creating its Linux engine pipe. Its backend
identified failure removing the zero-byte `dockerInference` runtime reparse
point. A narrowly targeted single-socket quarantine move also failed with
Windows's inaccessible-file error; nothing was moved/deleted. A reversible
runtime-folder repair is awaiting permission. No factory reset, image/volume
deletion, settings change, WSL shutdown or reboot occurred.
Similar error reports exist in [Docker's tracker](https://github.com/docker/desktop-feedback/issues/531);
this corroborates the failure class, not proof of its exact kernel cause here.

## Live evidence status

### October 10 first Job: inference observed, export failed

This supersedes older "not started" statements below. Claude submitted the
single approved L40S pilot on image23d07cd. Fresh exact-ID lookup confirms
FAILED / ContainerFailed, running from 03:56:37 to 04:03:38 UTC. The final
container diagnostic was "source evidence changed during open" (incorrectly
classified rejected by the old entrypoint).

Read-only recovery from the existing private bucket downloaded two objects,
3,133 bytes total: a staging model stderr log and a zero-byte final log. Their
local recovery index records hashes but is **not** a valid export manifest.
The log establishes successful GR00T loading, WebSocket serving, and two
episode start/end pairs. It does not establish the episodes' success/failure,
EGL correctness, or available videos/traces. No robot outcome is accepted.

Claude's destination-mount repair avoids rename and inode identity assumptions,
retains stable source/content checks, and publishes a manifest only after
copy verification. Imagec91383c was pushed successfully; the current registry
tag resolves to
`sha256:19c9bacae24f74e71ae5df048df37da3b40180b4f2070a1fa5e3824f5fd1aa0b`.
Independent review then found the preflight/deadline regressions described in
the [repair plan](../superpowers/plans/2026-10-10-serverless-preflight-deadline-repair.md).
The image must be rebuilt after that repair; c91383c is not the final retry
candidate. No additional Job was submitted during Codex recovery. A new paid
attempt needs a new explicit allowance and live resource/balance checks.

### October 9 local recovery and pinned-image probe

The user approved moving only Docker's stopped runtime `run` directory to a
recoverable sibling backup. The move and hidden restart succeeded; the engine
is healthy. Backup: `run.faultline-backup-20261009-9cb87fb7` beside the recreated
runtime directory. No images, volumes, settings or unrelated files were removed.
This fixes the observed startup symptom without establishing the Windows
kernel cause. It is workstation friction, not a Nebius service failure.
The same socket error recurred after an engine exit; a subsequent normal
hidden restart recovered Engine 28.3.2 without another folder move. Long-term
startup reliability is not established, and no broad repair is authorized.

The immutable LIBERO image was pulled successfully. Read-only CPU containers
with networking disabled verified Python 3.8.20, vla-eval 0.5.0, NumPy 1.24.4,
MuJoCo 3.2.3 and robosuite 1.4.0. Faultline's process adapter imports with only
project source mounted read-only, and actual CLI help exposes `--no-docker`.
The installed image versions, not a different upstream Dockerfile, are the
provenance facts for this pin. No policy dependency or simulator pin changed.
The final GR00T environment, EGL rendering and inference are still untested.
After the pull, local free disk space was about 9.4 GiB, making the larger
model-environment build a space-risk gate rather than permission to delete data.

Reviewed local containment and prepare-only configuration are integrated.
No Job submission, private registry publication or bucket provisioning occurred.
Historical October 6 prices/capacity above are not fresh October 9 quotes.

Not started. No real Serverless GR00T action, EGL render, video/trace recovery,
Job terminal-state proof, incurred charge or useful outcome comparison exists
yet. Local process/config kernels and actual image validation precede the pilot.

### October 9–10 full image build, probes and private push

The complete Serverless image (`deploy/serverless/Dockerfile`, application
code at `23d07cd`) was built locally after workstation disk cleanup. A planned
Nebius CPU builder VM was refused because the tenant's non-GPU vCPU quota is 0;
nothing was provisioned. Two local build failures were workstation/network
issues, not packaging defects: AVG antivirus HTTPS scanning replaced GitHub's
certificate (diagnosed with `openssl s_client`; Jethro disabled scanning during
the build), then one transient `pypi.org` connect timeout; a plain retry passed.

Local image ID and pushed digest:
`sha256:34b5d399f82c95e94116e0c539ee90e9fd4e8ed266fffe8ba3a2fae9b3ae9825`
(21.7 GB uncompressed; push took 21 minutes) in the private registry
`faultline-serverless` (eu-north1, same project; the service is free).

Network-disabled CPU probes inside the image passed:

| Check | Result |
| --- | --- |
| Model env imports (torch, torchcodec, LeRobot GrootPolicy, model bridge) | Python 3.12.13, torch 2.11.0+cu128, lerobot 0.6.0, huggingface_hub 1.22.0 |
| Simulator env imports `robot_debug.job_entry` / `job_workload` | Python 3.8.20 |
| `vla-eval run --help` lists `--no-docker` | yes |
| Model bridge checkout | pinned `35f1200…` |
| Baked Hugging Face cache or secret-like env | none |
| Entrypoint with missing workload file | JSON `rejected`, exit 2 |
| Prefetch pinning tests with the image's real `huggingface_hub` | 3/3 pass |

GPU, EGL rendering, model download/inference, bucket export and the Job
lifecycle remain unverified until the paid pilot.
