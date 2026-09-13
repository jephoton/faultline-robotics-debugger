# First valid baseline

**Status:** one successful compatibility episode; exact replay still pending.

## Result

On September 13, 2026, the pinned GR00T/LIBERO pairing completed the first
valid baseline episode:

| Field | Observed value |
| --- | --- |
| Task | `pick up the alphabet soup and place it in the basket` |
| Suite / task / episode | `libero_object` / 0 / 0 |
| Seed / environment seed | 7 / 7 |
| Outcome | success |
| Control steps | 137 |
| Episode elapsed time | 33.718 seconds |
| Video | 138 frames at 20 fps |

This is a compatibility result, not a success-rate estimate: one of one is
not evidence of robustness or general performance.

## Reproduction identity

| Item | Value |
| --- | --- |
| Harness checkout | `35f1200eb15608aa898f727a3722f7eef889c6cd` |
| Simulator image | `ghcr.io/allenai/vla-evaluation-harness/libero@sha256:d0c45bc5a3720d569180e6b8dd92510da895f16c3cc509ccc76e4b4ffbb9e0f0` |
| Policy checkpoint | `nvidia/gr00t17-lerobot-libero_object-640` at `1499db357f6ca3762b56c2e8c00b530eb9a09444` |
| Base model | `nvidia/GR00T-N1.7-3B` at `2fc962b973bccdd5d8ce4f67cc63b264d6886495` |
| Model inputs | agent-view image, wrist image, robot state |
| Action chunk | 16 |

The harness connected to the local model server and auto-enabled the wrist
image and state. It issued generic schema warnings, but the episode completed
and the recorded success check passed. Keep those warnings in view during
replay; they are not by themselves evidence of an invalid result.

## Artifacts

The following are copied to the ignored local directory
`artifacts/2026-09-13-baseline-authorized/` and remain on the managed VM disk:

- `libero-object-pilot_aggregate.json`
- `task0000_ep0000_success.jsonl`
- `task0000_ep0000_success.mp4`
- the SQLite recording for the attempt

The earlier one-frame authorization-error recording is deliberately retained
in a different result directory and excluded from policy metrics.

## Next gate

Repeat this exact nominal configuration once, retaining a separate recording.
Compare task, seeds, step count, outcome, and video before choosing any
perturbation family. The first perturbation choice remains a user-led design
decision after that replay.
