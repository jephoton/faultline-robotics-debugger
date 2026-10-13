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
| **1. Debug a failure you bring** | "My policy failed in this simulation run. What is the minimal cause?" | Import, replay and confirm work for verified LIBERO-Object demonstrations. **Reducing the imported scenario itself is being built in M7.** |
| **2. Audit a policy** | "What is the smallest disturbance that breaks this policy?" | **Works end to end** on Nebius Serverless: occlusion (either camera), blur, noise, darkening and contrast. |

Both modes share the same loop: a fixed compute budget, a repeatability gate
(a failure must reproduce in at least 4 of 5 attempts while unperturbed
controls succeed), a reducer, and a saved case that can be replayed against
a changed policy.

## What it has found so far

All results are for GR00T N1.7 on LIBERO-Object task 0 ("pick up the
alphabet soup and place it in the basket"), one seed, on single Nebius L40S
GPUs. Each is budget-local evidence, not a general claim.

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
- **Cheaper runs:** batching concurrent inference requests on one GR00T server
  gave +18% throughput at 12 parallel workers in two runs, and no gain at 8,
  where the GPU was not yet the bottleneck
  ([M3 batching](docs/experiments/m3-batched-inference.md)).

Each case in the viewer can carry a Nemotron explanation (NVIDIA Nemotron on
Nebius Token Factory, [M5C](docs/experiments/m5-nemotron-pilot.md)) and
source-linked public research found with Tavily
([M5D](docs/experiments/m5d-tavily-research.md)), both kept separate from the
measured evidence.

## How it runs

- **Simulator and policy:** LIBERO on robosuite/MuJoCo, through the
  [vla-evaluation-harness](https://github.com/allenai/vla-evaluation-harness),
  with GR00T N1.7 served by the harness's LeRobot server plus Faultline's
  batching server.
- **Cloud:** each diagnosis is one Nebius AI Cloud Serverless Job (one L40S,
  roughly US$0.4–0.6 per run), exporting evidence to private Object Storage
  ([Serverless setup](docs/setup/serverless-jobs.md)).
- **Locally:** the case store, the read-only viewer, Nemotron explanations and
  Tavily research run on the workstation.

## Roadmap

M1–M6 are complete. **M7a (in progress)** turns the engine into a product
([ADR 0027](docs/decisions/0027-m7-product-consolidation-and-access.md)):

- **Scenario reduction (centrepiece):** import a failing LIBERO run and reduce
  the differences between its start state and the normal one to the minimal
  cause.
- **One command:** `faultline diagnose <spec.yaml>` that owns the whole cloud
  lifecycle, with automatic viewer cases and `faultline replay <case>`.
- **Breadth:** all four LIBERO suites, camera-viewpoint and lighting
  families, and Nemotron-generated instruction paraphrases.
- **Access:** a public gallery of finished cases, a local-GPU backend, and
  runs in your own Nebius project.
- **UI overhaul** around import → diagnose → reduced case → replay.

M7b is the submission (demo video and write-up). LIBERO-Plus integration is a
post-M7 stretch goal.

## Local checks

```bash
PYTHONPATH=src python -B -m unittest discover -s tests
```

The suite (1371 tests, 60 platform skips on Windows) uses fakes for the
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
