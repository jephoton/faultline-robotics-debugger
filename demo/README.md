# Demo: one real Faultline diagnosis, viewable without a cloud account

This folder holds one finished mode 1 diagnosis from October 13, 2026, in the
same format `faultline diagnose` registers for the control panel, so you can see a
real result without a GPU, a Nebius account or any paid run.

**Case.** GR00T N1.7 (`nvidia/gr00t17-lerobot-libero_10-640`, pinned revision
`5ee08ab0`) on LIBERO-10 task 0, "put both the alphabet soup and the tomato
sauce in the basket". Benchmark start 14 fails reliably; the nearby start 28
passes. Faultline reduced the differences between them to an entity-minimal
set of five position shifts that are needed together (the soup, the orange
juice, the milk, the cream cheese and a small arm offset); no single shift
reproduces the failure. Three of the five were shrunk (each still needed at
least 87.5 % of its shift); milk and cream cheese were not shrunk before the
candidate budget ran out. Nemotron 3 Ultra had predicted the soup: the reruns
showed it is necessary but not sufficient. A `faultline replay` on October 15
still reproduced the failure. Full write-up:
[`docs/experiments/m7-scenario-reduction.md`](../docs/experiments/m7-scenario-reduction.md).

## View it

From the repository root (Python 3.10 or 3.11):

```bash
python -B -c "import sys; sys.path.insert(0, 'src'); from robot_debug.cli import main; sys.exit(main(['ui', '--artifacts', 'demo/root']))"
```

Open <http://127.0.0.1:8765> and select **soup-start14-demo** in the sidebar.
The control panel's New diagnosis and Setup pages need a cloud account; the
case page does not.

## What is inside `root/diagnoses/<case id>/`

| File | Content |
| --- | --- |
| `report.md` | The reduction report: differences, every rerun with its outcomes, the minimal cause, Nemotron's hypothesis and the measured check |
| `case.json` | The case record (suite, task, starts, minimal selection, replay recipe, videos, checkpoint) |
| `explanation.json` | Nemotron 3 Ultra's explanation of the verified result (model output, reviewed: not evidence) |
| `minimal-candidate.json`, `replay-inputs.json` | What `faultline replay` needs to re-run the case |
| `videos/original.mp4` | Start 14, the failing start |
| `videos/minimal.mp4` | Start 28 with only the five minimal shifts applied: fails |
| `videos/reference.mp4` | Start 28 unchanged: succeeds |

The videos are LIBERO simulator renders recorded during the Nebius Serverless
runs. Evidence is limited to this task, these starts and one policy
checkpoint; it is not a general claim about GR00T.
