# M7 breadth pack: four suites, new image, scene and language families

October 15–16, 2026. GR00T N1.7 (suite checkpoints
`nvidia/gr00t17-lerobot-libero_{object,10,spatial,goal}-640`, pinned), one
L40S per Nebius Serverless Job, image v15, every run driven by
`faultline diagnose`. Design: ADR 0032; plan:
`docs/superpowers/plans/2026-10-15-breadth-pack.md`. Spend cap US$6.00
(raised from US$4.00 by Jethro).

## Local verification

- Real-simulator CPU calibration of the scene families
  (`assets/scene-family-calibration.png`: rows are LIBERO-Object viewpoint,
  LIBERO-Object lighting, LIBERO-10 viewpoint, LIBERO-10 lighting; columns are
  severity 0, 0.5, 1). At s = 1 the camera is moved 10 cm and turned 10 degrees
  with the table and objects still in view; lighting at s = 1 leaves the scene
  very dark but visible (mean brightness 139 -> 77 -> 16).
- Calibration found a real defect: MuJoCo keeps light colours in float32, and
  the write check used a float64 tolerance, so every lighting write was
  rejected (`0acda6c`).
- The pure-NumPy JPEG codec took about 33 ms per frame in the simulator image;
  the Job now uses the image's Pillow (about 2.4 ms) with NumPy as fallback.
- Paraphrase-model comparison chose Nemotron 3 Super (ADR 0030).

## Live runs

| Run | Suite, task, start | Result | Cost |
| --- | --- | --- | ---: |
| Image catalog audit | LIBERO-Spatial 0, start 0 | nominal 5/5; jpeg, colour cast, dead pixels 0/5 at every level to s = 1; motion blur 1/5 only at s = 1 | US$0.82 |
| Scene audit | LIBERO-Goal 0, start 0 | stopped `nominal_controls_failed`: unperturbed GR00T 2/5 (S F F F S) | US$0.34 |
| Scene audit | LIBERO-Object 0, start 0 | lighting 0/5 at every level (lights down to 10 %); viewpoint 0/5 to s = 0.6, 1/5 at s = 0.8 and 1.0 | US$0.40 |
| Paraphrase diagnosis | LIBERO-Object 0, start 0 | control S S, matches the task wording; all 10 paraphrases succeeded | US$0.34 |
| Paraphrase diagnosis | LIBERO-10 0, start 7 | control S S, matches the task wording; all 10 paraphrases succeeded | US$0.35 |
| **Total** | | | **US$2.25** |

Costs are measured container time plus a 4-minute start allowance at
US$1.7468/h, as recorded by each run's spend ledger; reconcile with billing.

## Reading

- All four LIBERO suites now run end to end through `faultline diagnose`.
- Within the tested ranges GR00T is robust to JPEG compression down to quality
  5, a strong warm colour cast, 20 % dead pixels, scene lighting down to 10 %,
  and everyday rewording of its instruction (20 paraphrases across two
  suites). Motion blur and camera viewpoint show isolated failures only at the
  top of their ranges: candidate boundaries just beyond what was tested.
- The failures Faultline has found are therefore image corruption (Gaussian
  blur and noise, M6) and object arrangement (the mode 1 conjunction,
  `m7-scenario-reduction.md`). Robustness results are reported per family,
  task and start; they are not general claims.
- LIBERO-Goal task 0 start 0 is a natural weak start for GR00T (2/5
  unperturbed): a candidate for mode 1, not for an audit.

## Operational lessons

- The Nebius CLI sign-in expired mid-run on October 15; it looked transient,
  so waiting polled for an hour and wrote the finished screen Job off at its
  worst case. Fixed in `4462bff`: sign-in errors stop at once with a resume
  hint, the attempt stays re-attachable, and `--resume` replaced the US$1.31
  worst case with the measured US$0.34 without resubmitting.
- Python output to a pipe is block-buffered; long runs now use `python -u` so
  progress is visible.

## Evidence

Run folders (ignored): `artifacts/runs/{catalog-spatial,scene-goal,scene-object,paraphrase-task0,paraphrase-l10}-*`,
each with spec, ledger, steps, Job evidence, report and case; private specs
with real ids in `artifacts/specs-local/`.
