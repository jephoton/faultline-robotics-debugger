# Faultline — turn robot failures into replayable tests

Built for the Nebius × NVIDIA hackathon. Faultline turns a robot-policy
failure into the **smallest confirmed trigger** and keeps it as a **regression
test** that reruns on every new checkpoint. It works on simulated manipulation
policies (vision-language-action models such as NVIDIA GR00T).

**Scope today:** GR00T N1.7 on the LIBERO benchmark (4 suites, 40 tasks, one
simulated arm). The loop itself is not tied to LIBERO. Another simulator
needs an adapter, which is not built. The adapter must:
- reset to an exact state;
- expose shiftable object and robot positions;
- rerun the policy;
- check success.

See [Where it applies](docs/reference.md#where-it-applies).

## The problem

A team fine-tuning a robot policy works in a loop:

1. **Evaluate.** Run hundreds of simulated episodes and get a success rate
   (say 82%).
2. **Triage.** Watch the failed episodes and sort them by hand: missed
   grasp, wrong object, timeout.
3. **Reproduce.** Try to make one failure happen again; the policy is
   stochastic, so a failure seen once may not repeat.
4. **Fix.** Guess what triggers it, then add training data or change
   training, and retrain.
5. **Re-check.** Did that failure go away, and did anything else break?

Published accounts of VLA deployment and evaluation describe this iterative
loop, with failure analysis done by people replaying videos and logs
([factory-floor case study](https://arxiv.org/pdf/2605.27461),
[VLA benchmarking](https://arxiv.org/pdf/2511.11298),
[HELM](https://arxiv.org/pdf/2604.18791)). Two steps are weak:

- **The average hides the failure.** A success rate says how often the
  policy fails, not under which conditions
  ([LIBERO-Plus](https://arxiv.org/pdf/2510.13626)).
- **Re-checking known failures is not systematic.** Simulated evaluation can
  gate a checkpoint release
  ([NVIDIA](https://perspectives.nvidia.com/isaac-sim/task/faq/policy-testing-systems-ab-evaluation-gated-promotion-regression-baselines-robotics-cicd-1/)),
  but a recent survey notes "a noticeable lack of systematic research on
  regression testing for autonomous systems"
  ([survey](https://arxiv.org/html/2506.16101v1)).

## What Faultline does

- **Confirms** a failure is real: it must fail at least 4 of 5 attempts, and
  a nearby passing layout must pass 5 of 5.
- **Reduces** it to the minimal trigger: of all the differences between the
  failing and passing layouts, the smallest set the failure needs, found by
  reruns (delta debugging, as compilers do with crashing programs). That is
  the cause in the sense of *what* triggers it. *Why* the network fails under
  those conditions is still for a person to work out; the minimal trigger is
  the sharpest clue for it.
- **Keeps** it as a case (videos, report, replay inputs) and **replays** it on
  any checkpoint.
- **Nemotron** proposes the order in which differences are tested and writes
  a labelled reading of the verified result. The reruns, not the model, decide.

One **New diagnosis** does it. It runs your start untouched:
- if it fails, Faultline finds the smallest change of layout that triggers
  the failure;
- if it passes, Faultline probes it with image, scene and wording
  disturbances and finds the smallest one that breaks it.

Every failing condition becomes a replayable case. "Nothing broke it in
these ranges" is a valid finding too.

### What is regression testing?

In software, a **regression** is something that used to work and breaks after
a change. A **regression test** is a small saved check, rerun after every
change, that catches it. Each test pins one known failure (or fix), so a
change that silently undoes a fix is noticed at once.

For robot policies, every fine-tune or retrain is a change. Faultline's cases
are the saved checks:

- `faultline replay CASE --spec replay.yaml --expect fixed` reruns the case's
  minimal scene and its passing reference on a checkpoint (5 attempts each).
  The exit code says whether you got the result you expected, so a script or
  CI job can gate a checkpoint on its known failures.
- `--expect reproduces` checks a failure is still there, for example before
  you claim a fix. `policy.checkpoint` in the spec points the replay at
  another checkpoint.

A replay covers its saved scene and its attempts only, not every task or
starting condition. That is why many small cases are more useful than one.

The repository is
[`jephoton/faultline-robotics-debugger`](https://github.com/jephoton/faultline-robotics-debugger).
The local checkout folder and the `robot_debug` Python package keep their
original names for compatibility.

## See a real result in one minute

Open the [public Faultline gallery](https://faultline-robotics-debugger.vercel.app)
to explore five recorded cases and their evidence without installing anything.
It is read-only: diagnoses and replays run through the local tool, not the site.

[`demo/`](demo/README.md) holds one finished diagnosis (the LIBERO-10 failure
below, with its report, Nemotron explanation and the original, minimal and
reference videos). No GPU or cloud account is needed:

```bash
python -B -c "import sys; sys.path.insert(0, 'src'); from robot_debug.cli import main; sys.exit(main(['ui', '--artifacts', 'demo/root']))"
```

Then open <http://127.0.0.1:8765> and select the case in the sidebar.

For a click-by-click walkthrough and recipes for different goals, start with
the [UI user runbook](docs/ui-runbook.md). The [Reference](docs/reference.md)
(also a page in the control panel) documents the modes, the gate, how a
reduction works, every severity, every report column and abbreviation, and
the stop reasons. Its first walkthrough uses saved
evidence and starts no new compute; setup instructions are separate.

## One diagnosis, routed on the untouched result

| The start, run untouched... | Route | What Faultline does | The case it keeps |
| --- | --- | --- | --- |
| **fails reliably** (4 of 5) | layout | Finds the nearest benchmark start that passes, then delta-debugs the differences (object positions, the arm's pose) down to the shifts needed together. Nemotron proposes the order; reruns decide. | The minimal layout trigger, with the original, minimal and reference videos |
| **passes** | probes | Runs the chosen disturbances (by default blur, noise, darken and contrast; JPEG, colour cast, motion blur, dead pixels, camera viewpoint, lighting and Nemotron-written rewordings are one tick away) and finds the smallest severity or word change that breaks it | The failing disturbance at its threshold, or the failing wording, with videos |
| **fails sometimes** | flaky | Reports the start as unreliable untouched; no disturbance is blamed | — |

You can also search a range of benchmark starts for one that fails, or import
your own failing start-state file. Both go straight to the layout route.

`faultline replay` (or **Replay** on any case page) reruns a case on any
checkpoint, `policy.checkpoint` in the replay spec included, so you can test
a retrained policy against the failures you found. Optionally, each new case
also gets related public research (Tavily sources, summarised by Nemotron 3
Nano), shown as context, not evidence.

Typical cost and time with the defaults (one L40S, measured runs):
- about US$1.25 and 45 minutes when the start passes;
- about US$1.10 and 40 minutes when it fails.

What everything means (routes, the gate, every severity, report columns,
verdicts) is in the [Reference](docs/reference.md), which is also a page in
the control panel.

Occlusion (a grey rectangle over a camera) is not a probe family. It ran
through the earlier experiment modes (M4 to M6); its results are listed
below.

## What it has found so far

All results are for GR00T N1.7 on LIBERO, one seed per run, on single Nebius
L40S GPUs. Each is budget-local evidence for the tested task, start and
family, not a general claim.

- **A natural failure reduced to its cause (layout route):** on LIBERO-10 task 0
  ("put both the alphabet soup and the tomato sauce in the basket"), start 14
  fails reliably while the nearby start 28 passes. No single difference
  causes it: the failure needs **five small shifts together** (the soup,
  three distractor objects and a tiny arm offset). The size search reached
  three of the five: the soup and the arm offset each needed at least 87.5%
  of their shift and the orange juice all of it; the milk and cream cheese
  were not shrunk because the candidate budget ran out. Nemotron 3 Ultra
  predicted the soup; the reruns showed it is necessary but not sufficient.
  Replaying the case two days later with `faultline replay` still reproduced
  it ([scenario reduction](docs/experiments/m7-scenario-reduction.md)).

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
  hypothesis before any rerun, and explains each verified scenario case;
  Nemotron 3 Super writes instruction paraphrases; Nemotron 3 Nano summarises
  research. Audit and paraphrase cases have no Nemotron
  explanation yet. Model output is kept separate from measured evidence: "the
  model proposes, the simulator verifies".
- **Nebius AI Cloud Serverless Jobs** run every diagnosis, replay and audit
  (one L40S each), with evidence exported to private Object Storage.
- **Tavily** finds source-linked public research for each new case, in the
  New diagnosis's optional research step (Nemotron 3 Nano summarises it). It
  is context, not evidence ([M5D](docs/experiments/m5d-tavily-research.md)
  records the first experiment).

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
- **Locally:** specs, the spend ledger, Nemotron calls, reports and the control panel
  run on the workstation, as does Tavily research when you run it; keys never
  enter a Job.

## Roadmap

M1–M6 are complete. **M7a** turns the engine into a product
([ADR 0027](docs/decisions/0027-m7-product-consolidation-and-access.md)):
scenario reduction, `faultline diagnose / replay`, and the breadth
pack (four suites; image, scene and language families) and the **control
panel** (a browser UI over the same commands,
[ADR 0033](docs/decisions/0033-control-panel-ui.md)) and the public static
**gallery** of finished cases are done
([publication checks and limits](docs/experiments/m7-public-gallery.md)).

M7b is the submission (demo video and write-up). LIBERO-Plus integration is a
post-M7 stretch goal.

## Local checks

```bash
PYTHONPATH=src python -B -m unittest discover -s tests
```

The suite (about 2800 tests, 60 platform skips on Windows) uses fakes for the
simulator, model and cloud; it does not start paid work. The control panel's
front end has its own checks (Node 24):

```bash
npm --prefix web ci
npm --prefix web test -- --run
```

## Control panel

```bash
faultline ui --open
```

(From a source checkout without installing: `PYTHONPATH=src python -m
robot_debug.cli ui --open`.) The control panel is a browser UI over the same
commands:
- A sidebar of runs and cases.
- **New diagnosis**: you choose the start and what to probe if it passes. The
  review shows both branches with their worst-case and typical cost and
  time, and the run starts only after you confirm.
- A live run page showing the route, with a safe **Stop** (the current Job is
  cancelled and charged for the time it ran; `--resume` continues) and
  **Resume**.
- Report-first case pages for every kind: a findings list, videos in step,
  the full report, Nemotron's reading labelled for review, related research
  as context.
- **Replay** for every case kind.
- A **Reference** page explaining everything shown.
- A **Setup** page that checks the Nebius sign-in, keys and image.

It listens on 127.0.0.1 only; every action needs the page's session token and
a same-origin request, and one paid run runs at a time. Everything it does can
be done from the terminal (`faultline diagnose`, `stop`, `replay`), and every
spec it writes is kept under `artifacts/specs-ui/`.

`faultline export --out site/` writes the finished cases as a static gallery
(no controls, private run folders, cloud resource IDs or local paths) for any
static host. Public case/evidence fingerprints remain available for reference.

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
