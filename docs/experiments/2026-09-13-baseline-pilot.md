# Baseline pilot: pre-score infrastructure result

**Status:** blocked on an account-holder Hugging Face authorization; not a
robot-policy result.

## Fixed experiment identity

| Item | Value |
| --- | --- |
| Harness | `allenai/vla-evaluation-harness` at `35f1200eb15608aa898f727a3722f7eef889c6cd` |
| Simulator image | `ghcr.io/allenai/vla-evaluation-harness/libero@sha256:d0c45bc5a3720d569180e6b8dd92510da895f16c3cc509ccc76e4b4ffbb9e0f0` |
| Policy checkpoint | `nvidia/gr00t17-lerobot-libero_object-640` at `1499db357f6ca3762b56c2e8c00b530eb9a09444` |
| Base model | `nvidia/GR00T-N1.7-3B` at `2fc962b973bccdd5d8ce4f67cc63b264d6886495` |
| Suite | `libero_object` |
| Work | task 0, episode 0, `seed=7`, `env_seed=7` |
| Recording | video plus per-step SQLite rows enabled |

## What ran

The model service became healthy, declared the expected agent-view and wrist
camera inputs plus robot state, and the evaluator connected successfully. The
first task instruction was:

> Pick up the alphabet soup and place it in the basket.

The evaluator created a SQLite recording, aggregate JSON, and a one-frame
error video. It did not generate a usable action. Consequently, the reported
`0.0%` is **not** a baseline success rate and must not be compared with later
runs.

## Failure evidence and diagnosis

The model server returned a `403` while processing the first observation. Its
runtime attempted to retrieve the gated `nvidia/Cosmos-Reason2-2B` repository.
The public GR00T base and LIBERO policy checkpoint are available anonymously,
but this transitive dependency is not.

An earlier container startup also exposed an upstream image packaging issue:
`/workspace/src/vla_eval/watchdog.py` is root-only inside the pinned image.
The pilot configuration therefore uses `docker.user: root`; this is required
for the image to import its own evaluator. Artifact ownership is normalized
after cloud runs if files must be copied as the non-root VM user.

## Resume condition

After the account holder accepts Cosmos access and enters a Hugging Face read
token interactively on the VM, restart the model server and run this identical
configuration once. Keep this pre-score attempt as provenance, but do not use
it in aggregate success metrics or failure-reduction claims.
