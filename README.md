# Faultline — turn robot failures into replayable tests

Built for the Nebius × NVIDIA hackathon. Faultline is a debugger for
simulated robot-manipulation policies (vision-language-action models such as
NVIDIA GR00T). It finds a failure, confirms that it repeats, reduces it to
its minimal trigger, and saves it as a replayable regression test, with the
evidence beside it. Scenario and occlusion cases also get a Nemotron
explanation, and the earlier occlusion cases have Tavily research context.

The repository is
[`jephoton/faultline-robotics-debugger`](https://github.com/jephoton/faultline-robotics-debugger).
The local checkout folder and the `robot_debug` Python package keep their
original names for compatibility.

## See a real result in one minute

[`demo/`](demo/README.md) holds one finished diagnosis (the LIBERO-10 failure
below, with its report, Nemotron explanation and the original, minimal and
reference videos). No GPU or cloud account is needed:

```bash
python -B -c "import sys; sys.path.insert(0, 'src'); from robot_debug.viewer.server import main; sys.exit(main(['--artifacts', 'demo/root', '--port', '8765']))"
```

Then open <http://127.0.0.1:8765/diagnoses>.

## Two modes, one engine

| Mode | Question it answers | What you give it |
| --- | --- | --- |
| **1. Debug a failure you bring** | "My policy failed from this start. What is the minimal cause?" | A failing start: let Faultline **screen** benchmark starts for one that fails reliably, name a **benchmark start**, or **import your own failing start-state file** (`scenario.import`). It confirms the failure repeats, then delta-debugs its differences from the nearest passing start down to the shifts that are needed together. Nemotron proposes the order and a hypothesis; the simulator decides. Demonstrated on one case (LIBERO-10 task 0, start 14). |
| **2. Audit a policy** | "What is the smallest disturbance that breaks this policy?" | A passing start and a list of families. **Audit families:** the eight image families (blur, noise, darken, contrast, JPEG compression, colour cast, motion blur, dead pixels) plus camera viewpoint and lighting, which change the simulated scene. **Paraphrase** is the language mode: Nemotron rewords the instruction and a failing wording is reduced to the minimal word change. |

Occlusion (a black rectangle over a camera) is not an audit family. It ran
through the earlier experiment modes (M4 to M6) and its results are listed
below.

Both modes share the same loop: a fixed compute budget, a repeatability gate
(a failure must reproduce in at least 4 of 5 attempts while unperturbed
controls succeed), a reducer, and a saved case. `faultline replay` re-runs a
saved **scenario** case (audit and paraphrase cases are not replayed yet) and
can aim at a different checkpoint through `policy.checkpoint` in the replay
spec, so you can test a retrained policy against the failure you found.

## What it has found so far

All results are for GR00T N1.7 on LIBERO, one seed per run, on single Nebius
L40S GPUs. Each is budget-local evidence for the tested task, start and
family, not a general claim.

- **A natural failure reduced to its cause (mode 1):** on LIBERO-10 task 0
  ("put both the alphabet soup and the tomato sauce in the basket"), start 14
  fails reliably while the nearby start 28 passes. No single difference
  causes it: the failure needs **five small shifts together** (the soup,
  three distractor objects and a tiny arm offset). The size search reached
  three of the five: the soup and the arm offset each needed at least 87.5%
  of their shift and the orange juice all of it; the milk and cream cheese
  were not shrunk because the candidate budget ran out. Nemotron 3 Ultra
  predicted the soup; the reruns showed it is necessary but not sufficient.
  Replaying the case two days later with `faultline replay` still reproduced
  it ([mode 1](docs/experiments/m7-scenario-reduction.md)).

- **Minimal occlusion (LIBERO-Object task 0, start 0):** a black rectangle over the upper-right 14% of the
  third-person camera reproducibly breaks the task (reduced from 25%). The
  robot still grasps the soup but times out carrying it
  ([M4](docs/experiments/m4-reducer.md)). The same reduction was reproduced
  from an imported external demonstration
  ([M5B](docs/experiments/m5b-external-replay.md)).
- **Camera roles (hypothesis, same task):** blacking out the wrist camera as well stops
  the grasp entirely, while the same rectangle on the wrist camera alone is
  harmless. The wrist view appears to drive grasping and the third-person
  view the carry ([M6](docs/experiments/m6-camera-and-scalar-families.md)).
- **Thresholds (same LIBERO-Object task 0):** the policy fails reliably from a blur of sigma 3.9 px and
  from Gaussian noise of sigma 95 (of 255), but never under darkening down to
  5% brightness or contrast down to 10% (M6).
- **Robust within the tested ranges (breadth pack, one task and start per
  family):** GR00T N1.7 kept succeeding in every case below; the breadth
  pack is a robustness check, not a failure find
  ([breadth pack](docs/experiments/m7-breadth-pack.md)).
  - *Image catalog* on LIBERO-Spatial task 0, start 0: JPEG compression down
    to quality 5, a strong colour cast and 20% dead pixels never failed;
    motion blur failed once in five attempts, only at its strongest setting.
  - *Lighting and viewpoint* on LIBERO-Object task 0, start 0: lights at 10%
    never failed; the viewpoint failed once in five at 80% and at 100% of its
    range. The same audit on LIBERO-Goal task 0 stopped before testing
    anything, because unperturbed GR00T passed only 2 of 5 from that start.
  - *Paraphrases*: 10 Nemotron-written rewordings each on LIBERO-Object
    task 0, start 0 and LIBERO-10 task 0, start 7; all 20 succeeded.

  Separately, all four LIBERO suites (Object, 10, Spatial, Goal) now run end
  to end through `faultline diagnose`.
- **Cheaper runs:** batching concurrent inference requests on one GR00T server
  gave +18% throughput at 12 parallel workers in two runs, and no gain at 8,
  where the GPU was not yet the bottleneck
  ([M3 batching](docs/experiments/m3-batched-inference.md)).

## How NVIDIA and Nebius are used

- **NVIDIA GR00T N1.7** (one checkpoint per LIBERO suite) is the robot policy
  under test, served on Nebius AI Cloud GPUs.
- **NVIDIA Nemotron on Nebius Token Factory**, each model chosen by a measured
  comparison ([ADR 0030](docs/decisions/0030-nemotron-model-per-task.md)):
  Nemotron 3 Ultra ranks a scenario failure's differences and states a
  hypothesis before any rerun, and explains each verified scenario and
  occlusion case; Nemotron 3 Super writes instruction paraphrases; Nemotron 3
  Nano summarises research. Audit and paraphrase cases have no Nemotron
  explanation yet. Model output is kept separate from measured evidence: "the
  model proposes, the simulator verifies".
- **Nebius AI Cloud Serverless Jobs** run every diagnosis, replay and audit
  (one L40S each), with evidence exported to private Object Storage.
- **Tavily** finds source-linked public research. It is run by hand with
  `scripts/research_case.py` and has been used on the earlier occlusion cases
  only, not on scenario, audit or paraphrase cases
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
  evidence, writes the report and case, and enforces a spend cap. Before each
  Job it reserves a worst case: the provider timeout (deadline plus ten
  minutes) plus a four-minute start allowance, at the hourly rate, which is
  our understanding of how Serverless bills. That has not yet been reconciled
  against the Nebius bill. `faultline replay CASE` re-runs a saved scenario
  case as a regression test ([quickstart](docs/setup/diagnose.md)).
- **Cost:** a typical Job is US$0.3–0.9 on one L40S; the dry run prints every
  planned Job's worst case before anything is created.
- **Locally:** specs, the spend ledger, Nemotron calls, reports and the viewer
  run on the workstation, as does Tavily research when you run it; keys never
  enter a Job.

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
task failures. Evidence must first be downloaded into `artifacts/`; finished
`faultline diagnose` runs appear under `/diagnoses`. To browse the shipped
demo instead, pass `--artifacts demo/root`.

## Documentation

- [Where to look](docs/README.md): an index of the quickstart, results,
  decisions and internal history.
- [Quickstart: run a diagnosis](docs/setup/diagnose.md) (Python 3.10 or 3.11).
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
this repository does not relicense model weights or assets. See
[NOTICE.md](NOTICE.md) for the third-party components and where their terms
live.
