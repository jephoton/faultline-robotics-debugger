# Disturbance families and severity levels

The reference for Mode 2 stress tests (audits): what each disturbance family
changes, and what every severity level means physically. The code is
`src/robot_debug/image_perturbation.py` (image families) and
`src/robot_debug/scene_perturbation.py` (scene families). Design:
[ADR 0026](decisions/0026-m6-camera-reliance-and-scalar-families.md) and
[ADR 0032](decisions/0032-breadth-pack.md). For the interface, see the
[UI runbook](ui-runbook.md), Demos 2–3.

## Severity

Every family has one strength, the **severity** `s`, from 0 to 1:

- `s = 0` is exactly no change.
- `s = 1` is the strongest version Faultline tests.
- In between, the physical change grows in a straight line with `s`.

The `s = 1` bounds were chosen so the scene is still recognisable to a person
at full strength. Calibration renders:
`docs/experiments/assets/scene-family-calibration.png`.

## How an audit searches

1. **Control.** The start is run unperturbed, 5 attempts. If the policy does
   not pass reliably, nothing can be judged and the audit stops
   (`nominal_controls_failed`).
2. **Sweep.** For each chosen family, severities 0.2, 0.4, 0.6, 0.8 and 1.0,
   in that order, 5 attempts each. A level **fails reproducibly** at 4 of 5
   policy failures.
3. **Bisect.** At the first failing level, four bisection steps between the
   last passing level and it narrow the threshold to 0.0125 of the severity
   scale.
4. **Result per family.** "Fails from severity *x*" (the smallest
   reproducibly failing severity found), "No failure up to severity 1.00"
   (searched to the top, nothing reproduced), or "Not tested" / "Incomplete"
   (the run stopped before or during this family).

A level's ladder row such as **1/5** means one of five attempts failed: not
reproducible, but worth noting.

## Image families

These alter the **pictures the policy receives**, from both cameras: the
agent-view camera and the wrist camera (256×256 pixels by default). The simulator,
the physics and what an observer would see are unchanged. They approximate
camera and sensor effects; they do not simulate them.

| Family | What changes | Formula | s = 0.2 | 0.4 | 0.6 | 0.8 | 1.0 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Blur** (`blur`) | Gaussian blur, as from an out-of-focus lens | sigma `8 s` pixels | 1.6 px | 3.2 px | 4.8 px | 6.4 px | 8 px |
| **Noise** (`noise`) | Random grain on every pixel, as from a poor sensor in low light | Gaussian noise, sigma `100 s` (of 0–255) | 20 | 40 | 60 | 80 | 100 |
| **Darken** (`darken`) | Darker image, as from underexposure | brightness × `(1 − 0.95 s)` | ×0.81 | ×0.62 | ×0.43 | ×0.24 | ×0.05 |
| **Contrast** (`contrast`) | Washed-out image: every pixel pulled towards the image's average | contrast × `(1 − 0.9 s)` | ×0.82 | ×0.64 | ×0.46 | ×0.28 | ×0.10 |
| **JPEG compression** (`jpeg`) | Compression blocks and smearing, as from a low-bandwidth video link | JPEG quality `95 − 90 s` | 77 | 59 | 41 | 23 | 5 |
| **Colour cast** (`colour_cast`) | A warm tint, as from a white-balance error | red × `(1 + 0.6 s)`, blue × `(1 − 0.6 s)` | R ×1.12, B ×0.88 | ×1.24, ×0.76 | ×1.36, ×0.64 | ×1.48, ×0.52 | ×1.60, ×0.40 |
| **Motion blur** (`motion_blur`) | Horizontal streaking, as from a moving or shaking camera | line kernel `1 + 30 s` pixels long | 7 px | 13 px | 19 px | 25 px | 31 px |
| **Dead pixels** (`dead_pixels`) | Pixels stuck at black or white, as from a damaged sensor | fraction `0.2 s` of all pixels | 4% | 8% | 12% | 16% | 20% |

Noise and dead pixels are random, but repeatable. The pattern is a fixed
function of the episode, step, camera, family and severity, so every attempt
at one level sees the identical frames, and a replay reproduces them exactly.
Differences between attempts then come only from the policy and the
simulator, which is what the 4-of-5 rule measures.

## Scene families

These change the **simulated scene itself**, once, when the episode starts
(after the start layout is set and before the settling steps). Everything the
cameras see follows from the changed scene.

| Family | What changes | Formula | s = 0.2 | 0.4 | 0.6 | 0.8 | 1.0 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Camera viewpoint** (`viewpoint`) | The agent-view camera moves sideways and turns back towards the table, so the scene stays in view (the wrist camera is unchanged) | shift `0.10 s` m along the camera's right; turn `10 s` degrees | 2 cm, 2° | 4 cm, 4° | 6 cm, 6° | 8 cm, 8° | 10 cm, 10° |
| **Scene lighting** (`lighting`) | Every light in the scene dims (diffuse and ambient) | light × `(1 − 0.9 s)` | ×0.82 | ×0.64 | ×0.46 | ×0.28 | ×0.10 |

Lighting at `s = 1` leaves the scene very dark but visible. In the calibration
renders, mean brightness falls from 139 to 77 (s = 0.5) to 16 (s = 1).

## Other families (not audit severities)

- **Occlusion** (the September cases, M4): a grey rectangle over part of the
  agent-view image, described by its position and size as fractions of the
  image, not by a severity. It is reduced by trimming edges
  (`docs/experiments/` M4 notes).
- **Rewordings** (paraphrase mode): there is no severity. Each rewording is a
  separate candidate, checked for meaning and screened with the original
  wording as the control. A failing rewording is then reduced by word edits.

## Limits

- Results apply to the tested start, task, policy checkpoint and families.
  "No failure up to severity 1.00" means robust within this range, not to
  every possible disturbance of that kind.
- Image families approximate effects in the picture; scene families change
  the simulation, but only the camera pose and lights.
- One family is tested at a time; combinations are not tested.
