# Faultline — turn robot failures into replayable tests

Built for the Nebius × NVIDIA hackathon. Faultline is a debugger for
simulated robot-manipulation policies (vision-language-action models such as
NVIDIA GR00T). It finds a failure, confirms that it repeats, reduces it to
its minimal trigger, and saves it as a replayable regression test, with the
evidence, an explanation and related research beside it.

The repository is
[`jephoton/faultline-robotics-debugger`](https://github.com/jephoton/faultline-robotics-debugger).
The local checkout folder and the `robot_debug` Python package keep their
original names for compatibility.

## Two modes, one engine

| Mode | Question it answers | Status |
| --- | --- | --- |
| **1. Debug a failure you bring** | "My policy failed from this start. What is the minimal cause?" | **Works end to end:** screen for or bring a failing start, confirm it repeats, then delta-debug its differences from the nearest passing start down to the shifts that are needed together. Nemotron proposes the order and a hypothesis; the simulator decides. |
| **2. Audit a policy** | "What is the smallest disturbance that breaks this policy?" | **Works end to end:** occlusion (either camera), eight image families, camera viewpoint and lighting in the simulator, and instruction paraphrases reduced to the minimal wording change. |

Both modes share the same loop: a fixed compute budget, a repeatability gate
(a failure must reproduce in at least 4 of 5 attempts while unperturbed
controls succeed), a reducer, and a saved case that can be replayed against
a changed policy.

## What it has found so far

All results are for GR00T N1.7 on LIBERO, one seed per run, on single Nebius
L40S GPUs. Each is budget-local evidence for the tested task, start and
family, not a general claim.

- **A natural failure reduced to its cause (mode 1):** on LIBERO-10 task 0
  ("put both the alphabet soup and the tomato sauce in the basket"), start 14
  fails reliably while the nearby start 28 passes. No single difference
  causes it: the failure needs **five small shifts together** (the soup,
  three distractor objects and a tiny arm offset), each at nearly full size.
  Nemotron 3 Ultra predicted the soup; the reruns showed it is necessary but
  not sufficient. Replaying the case two days later with `faultline replay`
  still reproduced it
  ([mode 1](docs/experiments/m7-scenario-reduction.md)).

- **Minimal occlusion:** a black rectangle over the upper-right 14% of the
  third-person camera reproducibly breaks the task (reduced from 25%). The
  robot still grasps the soup but times out carrying it
  ([M4](docs/experiments/m4-reducer.md)). The same reduction was reproduced
  from an imported external demonstration
  ([M5B](docs/experiments/m5b-external-replay.md)).
- **Camera roles (hypothesis):** blacking out the wrist camera as well stops
  the grasp entirely, while the same rectangle on the wrist camera alone is
  harmless. The wrist view appears to drive grasping and the third-person
  view the carry ([M6](docs/experiments/m6-camera-and-scalar-families.md)).
- **Thresholds:** the policy fails reliably from a blur of sigma 3.9 px and
  from Gaussian noise of sigma 95 (of 255), but never under darkening down to
  5% brightness or contrast down to 10% (M6).
- **Robust within range (breadth pack):** across all four LIBERO suites,
  GR00T kept succeeding under JPEG compression down to quality 5, a strong
  colour cast, 20% dead pixels, scene lights at 10%, and 20 Nemotron-written
  paraphrases of its instructions; motion blur and camera viewpoint failed
  only occasionally at the top of their ranges
  ([breadth pack](docs/experiments/m7-breadth-pack.md)).
- **Cheaper runs:** batching concurrent inference requests on one GR00T server
  gave +18% throughput at 12 parallel workers in two runs, and no gain at 8,
  where the GPU was not yet the bottleneck
  ([M3 batching](docs/experiments/m3-batched-inference.md)).

## How NVIDIA and Nebius are used

- **NVIDIA GR00T N1.7** (one checkpoint per LIBERO suite) is the robot policy
  under test, served on Nebius AI Cloud GPUs.
- **NVIDIA Nemotron on Nebius Token Factory**, each model chosen by a measured
  comparison ([ADR 0030](docs/decisions/0030-nemotron-model-per-task.md)):
  Nemotron 3 Ultra ranks a failure's differences and states a hypothesis
  before any rerun, and explains each verified case; Nemotron 3 Super writes
  instruction paraphrases; Nemotron 3 Nano summarises related research.
  Model output is kept separate from measured evidence: "the model proposes,
  the simulator verifies".
- **Nebius AI Cloud Serverless Jobs** run every diagnosis, replay and audit
  (one L40S each), with evidence exported to private Object Storage.
- **Tavily** finds source-linked public research for each case
  ([M5D](docs/experiments/m5d-tavily-research.md)).

## How it runs

- **Simulator and policy:** LIBERO on robosuite/MuJoCo, through the
  [vla-evaluation-harness](https://github.com/allenai/vla-evaluation-harness),
  with GR00T N1.7 served by the harness's LeRobot server plus Faultline's
  batching server.
- **One command:** `faultline diagnose SPEC.yaml` runs a whole diagnosis on
  Nebius Serverless (or, untested, a local NVIDIA GPU): it creates and cleans
  up the results bucket and download key, submits each Job, waits under a
  watchdog, resubmits when no GPU is free, downloads only that Job's
  evidence, writes the report and case, and enforces a spend cap whose worst
  case is a real upper bound. `faultline replay CASE` re-runs a saved case as
  a regression test ([quickstart](docs/setup/diagnose.md)).
- **Cost:** a typical Job is US$0.3–0.9 on one L40S; the dry run prints every
  planned Job's worst case before anything is created.
- **Locally:** specs, the spend ledger, Nemotron calls, reports, the viewer and
  Tavily research run on the workstation; keys never enter a Job.

## Roadmap

M1–M6 are complete. **M7a** turns the engine into a product
([ADR 0027](docs/decisions/0027-m7-product-consolidation-and-access.md)):
scenario reduction (mode 1), `faultline diagnose / replay`, and the breadth
pack (four suites; image, scene and language families) are done. Next are a
**UI overhaul** around import → diagnose → reduced case → replay, and a
public **gallery** of finished cases.

M7b is the submission (demo video and write-up). LIBERO-Plus integration is a
post-M7 stretch goal.

## Local checks

```bash
PYTHONPATH=src python -B -m unittest discover -s tests
```

The suite (about 2400 tests, 60 platform skips on Windows) uses fakes for the
simulator, model and cloud; it does not start paid work.

## Viewer

```powershell
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
python -m robot_debug.viewer.server --artifacts artifacts --port 8765
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). After installing the
package, `faultline-viewer` does the same. The viewer is read-only, binds to
loopback by default, and labels infrastructure errors separately from robot
task failures. Evidence must first be downloaded into `artifacts/`.

## Documentation

- [Project plan and milestones](PROJECT_PLAN.md) and the
  [current handoff state](docs/codex-handoff/STATE.md).
- [Decision records](docs/decisions/) (ADRs) for every accepted design choice.
- [Experiment notes](docs/experiments/) with exact evidence, spend and claim
  limits for each run.
- [Hackathon tool feedback](FEEDBACK.md) on Nebius AI Cloud, Token Factory and
  NVIDIA models.
- [Learning guide](PROJECT-LEARNING-GUIDE.md) in plain language.

## Scope and claims

Faultline builds on existing VLA evaluation, perturbation testing and
parallel execution; its contribution is the integrated path from controlled
search to a small, reproducible, replayable counterexample, with time and GPU
cost measured. Results cover the tested policy, tasks, seeds and perturbation
families only. Image-space perturbations approximate, not simulate, physical
effects. Model training and formal verification are out of scope.

## License

Original project code is licensed under the [MIT License](LICENSE).
External models, datasets and other third-party assets keep their own terms;
this repository does not relicense model weights or assets.
