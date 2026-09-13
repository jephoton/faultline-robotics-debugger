# First global scene occlusion episode

**Status:** the first bounded global-agent-view perturbation completed as a
valid policy episode on September 13, 2026. It succeeded, so this is an
integration result rather than a discovered failure.

## Valid result

The run reused the nominal task and seeds while covering the centered 25% of
the image width and height. That rectangle occupies 6.25% of the full image
area.

| Field | Observed value |
| --- | --- |
| Task | `pick up the alphabet soup and place it in the basket` |
| Suite / task / episode | `libero_object` / 0 / 0 |
| Seed / environment seed | 7 / 7 |
| Outcome | success |
| Control steps | 129 |
| Episode elapsed time | 23.782 seconds |
| Video | 130 frames at 20 fps |
| Rectangle | `x=0.375, y=0.375, width=0.25, height=0.25` |
| Appearance | opaque black, RGB `[0, 0, 0]` |

One success is not evidence that the model is robust to occlusion. It proves
that the perturbation reaches the policy through the pinned evaluator without
changing the task, physics, wrist camera, robot state, or success predicate.
The next experiment should use a fixed, budgeted sweep rather than drawing a
performance conclusion from this compatibility check.

## Compatibility evidence

The repository source was mounted read-only into the pinned simulator image.
The adapter import and all 15 unit tests passed in the image's actual
Python 3.8.20 / NumPy 1.24.4 `libero` Conda environment. The valid run log
confirmed that the model server auto-configured both `send_state=True` and
`send_wrist_image=True`.

The image's bare default `python` is not the evaluator environment. Import
checks must use `conda run --no-capture-output -n libero python`; bypassing
Conda produces a misleading missing-NumPy error.

| Item | Value |
| --- | --- |
| Host harness | `35f1200eb15608aa898f727a3722f7eef889c6cd` (`0.5.1.dev5`) |
| Simulator harness | `0.5.0` |
| Simulator image | `ghcr.io/allenai/vla-evaluation-harness/libero@sha256:d0c45bc5a3720d569180e6b8dd92510da895f16c3cc509ccc76e4b4ffbb9e0f0` |
| Policy checkpoint | `nvidia/gr00t17-lerobot-libero_object-640` at `1499db357f6ca3762b56c2e8c00b530eb9a09444` |
| Base model | `nvidia/GR00T-N1.7-3B` at `2fc962b973bccdd5d8ce4f67cc63b264d6886495` |

The host and simulator harness versions differ despite the pinned image. That
matters because simulator harness 0.5.0 only inspects parameters directly on a
benchmark subclass constructor when forwarding model observation
requirements. The adapter therefore exposes `send_state` and
`send_wrist_image` explicitly instead of relying only on `**kwargs`.

## Preserved infrastructure error

The first transformed launch ended before step zero with
`observation_failed: AttributeError`. Its server trace showed that the policy
received neither wrist image nor robot state. This was an evaluator
compatibility error, not a task failure, and it is excluded from policy
metrics. A regression test now protects the explicit constructor contract.

The error aggregate, one-frame video, SQLite file, and run log are retained in
the ignored local directory
`artifacts/2026-09-13-global-occlusion-infra-error/`.

## Visual review and artifacts

A representative 256×256 frame was extracted at two seconds. The intended
center region spans pixels `[96:160, 96:160]`; its decoded pixel range is 0–1
because of video compression, confirming the opaque mask is present. The
scene outside the rectangle remains visible. Full semantic review of the
entire motion is still useful before choosing demo footage.

The valid aggregate JSON, per-step JSONL, SQLite recording, full MP4, run log,
and representative frame are retained in the ignored local directory
`artifacts/2026-09-13-global-occlusion-valid/` and on the managed VM disk.

The L40S VM was stopped immediately after evidence collection. This session
used roughly fifteen running minutes, approximately US$0.44 of compute at the
recorded US$1.7468/hour estimate; the Nebius billing view remains authoritative.
The stopped 200 GiB disk continues to cost approximately US$0.47/day.
