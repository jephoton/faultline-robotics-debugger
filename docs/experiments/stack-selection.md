# Baseline stack selection

**Status:** accepted for the baseline; runtime reproduction is still pending a
bounded Nebius pilot.

## Chosen pairing

| Layer | Selection | Why it is here |
| --- | --- | --- |
| Policy | NVIDIA GR00T N1.7, LIBERO Object checkpoint | An NVIDIA policy specifically adapted to the selected task suite. |
| Model bridge | LeRobot adapter in AllenAI's VLA Evaluation Harness | It provides a ready model-server protocol and declares required cameras/state. |
| Simulator / benchmark | LIBERO Object on MuJoCo | A manipulation benchmark with replayable initial states and a supported harness adapter. |
| Execution location | Nebius GPU job | The local RTX 3050 has 4 GiB VRAM and limited disk capacity. |

The evaluated checkpoint is `nvidia/gr00t17-lerobot-libero_object-640`; its
base model is `nvidia/GR00T-N1.7-3B`. The checkpoint revision observed during
source discovery was `1499db357f6ca3762b56c2e8c00b530eb9a09444`; the base-model
revision was `2fc962b973bccdd5d8ce4f67cc63b264d6886495`.

The object checkpoint was publicly listed under Apache-2.0 during discovery.
The base model's licence and any Hugging Face access terms must be confirmed by
the account holder before download; no terms are accepted automatically.

## Harness evidence

The inspected, clean upstream checkout is:

```text
repository: https://github.com/allenai/vla-evaluation-harness.git
commit:     35f1200eb15608aa898f727a3722f7eef889c6cd
```

It includes both the LeRobot GR00T configuration and the LIBERO Object
configuration. The adapter requests two image views (`agentview` and `wrist`)
plus robot state; the harness passes those requirements to LIBERO through its
model-server handshake. They should not be manually omitted in our config.

LIBERO Object has ten tasks, up to 50 initial states per task, and a 280-step
horizon. The upstream Object YAML therefore schedules 500 episodes. Its smoke
test instead uses the `libero_spatial` suite, which does **not** match this
Object-trained checkpoint. Our first configuration runs one Object task and
one episode.

## Reproduction identity

The initial pilot uses the upstream `libero:latest` image only as a discovery
tag. Immediately after the first successful pull, record its immutable image
digest and replace the tag in the next experiment configuration. Do the same
for all model snapshot revisions. A floating container tag is not a stable
experiment identity.

For each attempt, retain the harness commit, checkpoint/base revisions,
container digest, task index/instruction, `seed`, `env_seed`, and
`episode_idx`. The last field matters: LIBERO selects an initial state by
episode index, so a seed alone is not enough to reproduce an episode.

## Commands to validate on the cloud host

Run these from the root of the pinned upstream harness checkout. The project
configurations are intentionally external to the upstream checkout, so the
server script path resolves correctly only from that root.

```bash
vla-eval serve --config /path/to/nebius-nvidia-hackathon/configs/model-server.yaml
vla-eval run --config /path/to/nebius-nvidia-hackathon/configs/baseline.yaml
```

Wait for the model server's health endpoint before starting the evaluation.
The first paid run is one clean, recorded episode; it is not a performance or
robustness result.
