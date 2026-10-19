# Demo: one real Faultline diagnosis, viewable without a cloud account

This folder holds one finished diagnosis from October 19, 2026, in the same
format `faultline diagnose` registers for the control panel, so you can see a
real result without a GPU, a Nebius account or any paid run. It is the
gallery's layout case `FL-S-8E0D`.

**Case.** GR00T N1.7 (`nvidia/gr00t17-lerobot-libero_10-640`, pinned revision
`5ee08ab`) on LIBERO-10 task 0, "put both the alphabet soup and the tomato
sauce in the basket".
- Benchmark start 14 fails reliably; the nearby start 4 passes.
- The two differ in five entities. Faultline reduced them to an
  entity-minimal set of four shifts that are needed together: the basket,
  the milk, the orange juice and a small arm offset. No single shift
  reproduces the failure.
- Three shifts were shrunk:
  - basket to 93.8% of its shift;
  - milk to 87.5%;
  - arm to 93.8%.

  The candidate budget ran out before the orange juice was shrunk.
- Nemotron 3 Ultra ranked the arm first and the soup second. The reruns
  showed the arm is necessary but not sufficient, and the soup is not needed.

Write-up: [`docs/experiments/m7-final-showcase.md`](../docs/experiments/m7-final-showcase.md).

## View it

From the repository root (Python 3.10 or 3.11):

```bash
python -B -c "import sys; sys.path.insert(0, 'src'); from robot_debug.cli import main; sys.exit(main(['ui', '--artifacts', 'demo/root']))"
```

Open <http://127.0.0.1:8765> and select **l10-start14** in the sidebar.
The control panel's New diagnosis and Setup pages need a cloud account; the
case page does not.

## What is inside `root/diagnoses/<case id>/`

| File | Content |
| --- | --- |
| `report.md` | The reduction report: differences, every rerun with its outcomes, the minimal cause, Nemotron's hypothesis and the measured check |
| `case.json` | The case record (suite, task, starts, minimal selection, replay recipe, videos, checkpoint) |
| `explanation.json` | Nemotron 3 Ultra's explanation of the verified result (model output, reviewed: not evidence) |
| `research.json` | Accepted next-step suggestions and source titles/links; retrieved third-party snippets and search text are excluded |
| `minimal-candidate.json`, `replay-inputs.json` | What `faultline replay` needs to re-run the case |
| `videos/original.mp4` | Start 14, the failing start |
| `videos/minimal.mp4` | Start 4 with only the four minimal shifts applied: fails |
| `videos/reference.mp4` | Start 4 unchanged: succeeds |

The videos are LIBERO simulator renders recorded during the Nebius Serverless
runs. Evidence is limited to this task, these starts and one policy
checkpoint; it is not a general claim about GR00T.
