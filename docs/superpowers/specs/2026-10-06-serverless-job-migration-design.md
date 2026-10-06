# Single-GPU Serverless Job migration

## Accepted scope

Jethro approved the recommended single-Job topology and private Object Storage
export. Implement and locally validate it, then seek a fresh numeric spending
cap after read-only cloud preflight. Historical VM evidence stays untouched.
This does not resume expanded M3, external replay, Nemotron retries, a model
change, public publication, or benchmark reruns.

## Runtime and boundaries

One finite GPU Job owns one warm GR00T server and at most one active evaluator.
The server URL remains `ws://localhost:8000`. Model and simulator run in
separate Python environments in one outer container; there is no nested Docker,
VM systemd, SSH port, or separate Endpoint. The outer image derives from the
existing immutable LIBERO image. `/workspace` and its simulator environment
remain intact; the pinned model bridge lives separately at `/opt/upstream`.
Use process-specific source paths, never a global path replacing the simulator
harness. Inspect the installed evaluator's direct execution support in the image.

Pinned inputs:

- LIBERO image: `ghcr.io/allenai/vla-evaluation-harness/libero@sha256:d0c45bc5a3720d569180e6b8dd92510da895f16c3cc509ccc76e4b4ffbb9e0f0`.
- Model bridge checkout: `35f1200eb15608aa898f727a3722f7eef889c6cd`.
- Checkpoint: `nvidia/gr00t17-lerobot-libero_object-640`, revision `1499db357f6ca3762b56c2e8c00b530eb9a09444`.
- Base model: `nvidia/GR00T-N1.7-3B`, revision `2fc962b973bccdd5d8ce4f67cc63b264d6886495`.

No weights, credentials or historical artifacts enter an image build context.
Use runtime SecretStash injection for required gated-model access. Resolve and
record all transitive model dependencies; main checkpoint caching alone is not
proof of offline readiness. Actual installed versions and image digest belong
in new provenance. Dependency drift is a validation risk, not permission to
rewrite older results as comparable.

## Configuration and stable launch contract

A checked JSON configuration chooses `pilot`, `search`, `grid`, or `reduce`.
These modes invoke existing sequential drivers via their command-runner seams;
no worker scheduler or reduction algorithm changes. Pilot runs only task 0,
initial state 0, seed 7, once nominal and once with the known reduced rectangle
`x=.5, y=0, width=.375, height=.375`. Both record steps and video.

Configuration includes a safe unique run ID, immutable outer image reference,
one-GPU platform/preset, subnet, private output bucket, and secret selectors
(not values). Prepare-only tooling emits CLI arguments and never calls Nebius.
Actual submission is owned by root after account/quota/price/balance/cap checks.
Use the same configuration and durable Job identity when recovering observation;
an interrupted local command must not silently submit another Job.

Use restart policy `never`, a provider timeout of one hour (documented minimum),
and a shorter container deadline no greater than 50 minutes. This is a planning
limit, not a paid allowance. Readiness has a bounded wait and requires a live
model process plus successful WebSocket handshake, not just an open port.
Evaluator commands have bounded deadlines within the remaining Job budget.
No queued stage starts after the cutoff. SIGTERM/interrupts stop owned process
groups; reap leaders and verify group absence. Uncertain cleanup terminates the
Job path rather than launching another evaluator. Treat startup, timeout,
missing/invalid aggregate, or incomplete recording as infrastructure evidence,
never a robot-policy failure. Keep the old M3 Docker containment unchanged.

## Evidence durability

Every run uses fresh local and remote directories. SQLite is written locally;
copy only after evaluator closure. After each stage and on safe failure cleanup,
export closed files and hashes, then a manifest. Do not copy open SQLite/WAL
files as if they were a valid replay bundle. Copy failures keep the Job failed
and must not emit a successful completion manifest. Never overwrite a previous
run or publish a completion marker ahead of its media. A checksum manifest is
checked again after downloading to a fresh ignored artifacts directory.

Logs and provenance contain no tokens or secret environment dumps. Image
builds are private; registry/bucket writes and retention costs need the cloud
cap. Downloaded new runs retain formats usable by the existing read-only viewer.
No automatic import rewrites of old cases or interpretation sidecars.

## Acceptance

Local fixtures cover direct argv, process isolation, readiness failure, timeout,
orphan-child cleanup, unique run paths, export error, manifest ordering,
configuration rejection, and zero cloud calls from prepare-only tooling.
Run actual POSIX child tests under WSL, not only mocked Windows tests.
Build/probe the actual container environments without GPU before spending.

Live acceptance requires one real single-GPU Job, fresh nominal and masked
GR00T episodes, readable aggregates/JSONL/MP4s, recovered checksummed artifacts,
honest outcomes, new backend provenance, and observed terminal Job state.
Report estimated versus posted billing separately. Unit tests, an image build,
or a successful `nvidia-smi` alone do not complete the migration.

## Gates and learning checkpoint

Green: local fixtures, packaging, preparation, documentation, existing evidence
inspection. Amber: deadline allocation and dependency/environment packaging
within the pinned policy/simulator boundary. Red: numeric spend, resources or
retention beyond a cap, policy/image changes, additional experiments, and public
publication. Root remains sole cloud lifecycle and Git integration owner.

Explain whether the Job validated deployment, not whether it reproduced every
research claim; show where its costs arose and what failed if it did not finish.
