# Faultline — turn robot failures into replayable tests

Faultline is a debugging workbench for robot foundation models. Find a
repeatable failure, reduce its triggering condition, and keep a test you can
replay on a compatible checkpoint.

## Quick links

[Public demo](https://faultline-robotics-debugger.vercel.app/) ·
[Run your own](docs/setup/diagnose.md) ·
[UI walkthrough](docs/ui-runbook.md) ·
[Architecture](docs/architecture.md) ·
[Results](#demonstrated-results) ·
[Tool feedback](FEEDBACK.md) ·
[MIT license](LICENSE)

> **The public gallery is read-only.** It shows saved reports and recordings;
> it cannot start a diagnosis or replay. New experiments run through the local
> app using your own Nebius account, model access and paid compute.
> Browsing the gallery or bundled offline case needs no cloud account.

## Why Faultline

A success rate tells a robotics team how often a policy fails, not which
conditions make one failure repeat. Faultline connects discovery,
confirmation, reduction and replay so engineers can investigate a specific
failure and test it again after changing the policy.

It builds on existing evaluation harnesses and reduction methods. The
contribution is the combined debugging workflow, not a new robot policy,
perturbation technique or claim to cover every possible failure.

## Try it

### Explore recorded cases

Open the [public gallery](https://faultline-robotics-debugger.vercel.app/).
Its four examples cover layout reduction, image probes, instruction
rewordings and a bounded no-failure result.

To inspect the bundled layout case locally, clone this repository and run
from its root with Python **3.10 or 3.11**:

```bash
python -B -c "import sys; sys.path.insert(0, 'src'); from robot_debug.cli import main; sys.exit(main(['ui', '--artifacts', 'demo/root']))"
```

Open <http://127.0.0.1:8765>. No GPU or cloud account is needed to inspect
this case. See [demo contents](demo/README.md) and the
[UI walkthrough](docs/ui-runbook.md).

### Run your own diagnosis

Install the CLI and cloud dependencies:

```bash
python -m pip install -e ".[cli,cloud]"
```

Follow the [diagnosis quickstart](docs/setup/diagnose.md) to configure Nebius
sign-in, GPU quota, a private simulator image and model access. Nemotron
features also need a Token Factory key; Tavily research is optional.
Keep credentials out of Git.

Then open the local control panel:

```bash
faultline ui --open
```

Choose **New diagnosis**, select a task and starting state, then review the
budget before confirming a run. The same workflow is available from the CLI:

```bash
faultline diagnose my-spec.yaml --dry-run
faultline diagnose my-spec.yaml
```

The first command previews the plan; the second can start paid cloud work.
First-time image building needs Docker and a roughly 20 GB build/push.
Docker is not needed to view evidence or submit an already-built image.

## How diagnosis works

| Untouched starting state | Next step |
| --- | --- |
| Fails reliably | Find a passing reference and reduce the layout differences while retaining the failure. |
| Passes | Try the selected image, scene or instruction changes within the budget. |
| Fails inconsistently | Report the baseline as flaky; do not blame a disturbance. |

Layout confirmation requires at least **4 failures in 5 attempts**, with
the passing reference succeeding **5 of 5**. Reduction tests which changes can
be removed or shrunk. Completed entity-removal checks show whether removing
any single retained shift loses the failure gate in those tests; they do
not prove globally smallest shift sizes or the underlying cause.

The app keeps reports, inputs and available videos together. **Stop/Resume**
handles interrupted runs, and **Replay** reruns a saved failing condition on
a compatible checkpoint. A no-failure screen is also a valid result; it does
not become a failing regression case.

For example, with a configured replay spec:

```bash
faultline replay CASE --spec replay.yaml --expect reproduces
```

Set `policy.checkpoint` in that spec to select a compatible policy.
`--expect fixed` checks for the expected fixed outcome; it does not fix the
model. Recorded showcase replays used the original checkpoint, not a proven
improved model. See the [reference](docs/reference.md) for gates, levels,
report columns and stop reasons.

## Demonstrated results

The gallery reports specific GR00T N1.7 runs in LIBERO simulation, not broad
robustness claims.

| Case | Recorded finding |
| --- | --- |
| **FL-S-8E0D — layout** | LIBERO-10 task 0, start 14 failed 4/5 attempts. Against passing start 4, basket, milk, orange juice and arm shifts were needed together. Removing any one lost the failure gate; sizes were not fully minimized. The reduced scene failed on replay; the reference passed 5/5. |
| **FL-A-D582 — image probes** | LIBERO-Object task 0, start 0 passed untouched. Blur at severity 0.4625 (sigma 3.7 px) failed 5/5 in search and 4/5 on replay. Noise fell below the gate on replay: 3/5. |
| **FL-A-F526 — bounded no-failure result** | LIBERO-Spatial task 0, start 0 had no reliable failure under the tested JPEG, colour-cast, dead-pixel and motion-blur ranges. Motion blur failed once in five attempts at maximum tested strength. |
| **FL-L-C72C — rewordings** | The original instruction succeeded twice; four Nemotron-generated variations passed the mechanical meaning check and each succeeded once. No wording failure or reduction. This screen has no recorded video. |

[Layout/blur experiment](docs/experiments/m7-final-showcase.md) ·
[Breadth measurements](docs/experiments/m7-breadth-pack.md) ·
[Wording walkthrough](docs/ui-runbook.md#optional-wording-example-also-in-the-public-gallery)

Earlier experiments reduced an occlusion from 25% to 14.06% image area and
replayed it from an imported state. Occlusion belongs to the earlier tooling,
not the current New diagnosis probe list. Supporting throughput experiments
are also recorded; they do not establish diagnostic time or cost savings.
See the [results index](docs/README.md#results).

## How NVIDIA and Nebius are used

- **NVIDIA GR00T N1.7** is the robot policy under test. It turns observations
  and instructions into actions in LIBERO/robosuite/MuJoCo through the
  [AllenAI VLA evaluation harness](https://github.com/allenai/vla-evaluation-harness).
- **NVIDIA Nemotron on Nebius Token Factory** ranks layout hypotheses and
  writes explanations/next steps with Ultra; Super generates instruction
  rewordings. Nano handled earlier research summaries. Hosted API calls avoid
  operating a separate Nemotron server. Models were selected through
  [small task-specific comparisons](docs/decisions/0030-nemotron-model-per-task.md).
  Model suggestions are separate from measured test outcomes.
- **Nebius AI Cloud Serverless Jobs** run the current robot evaluations and
  replays on one L40S per Job. A private registry holds the simulator image;
  Object Storage holds evidence; the secret store supplies model-access
  credentials. Earlier experiments also used L40S/H100 VMs.
- **Tavily** supplies public research sources for optional next-step suggestions.
  A cited suggestion is not a verified remedy.

Python coordinates jobs, budgets and reports; React provides the local UI
and exported static gallery. The local panel binds to loopback, requires a
session token for actions and allows one paid run at a time. Token Factory
and Tavily keys stay on the workstation, not in simulator Jobs.
[Full architecture](docs/architecture.md).

Per-run costs are estimates. Supplied September 19–October 19, 2026 billing
views show AI Cloud **$42.04** and Token Factory **$0.13**, including VAT.
These are period totals, not lifetime spend or matched per-run charges.
[Billing scope](docs/submission/billing-reconciliation.md).

## Scope and limitations

Support covers the four LIBERO suite paths—Object, 10, Spatial and Goal—not
validation of all 40 tasks. Results depend on the checkpoint, task, start,
seed and tested range. Another simulator needs an adapter; arbitrary video
is not a replayable starting state.

A reduced failure is not causal proof or a guarantee of the smallest trigger.
Image changes approximate physical effects; simulated results do not establish
real-robot safety. Nemotron assistance is demonstrated, but diagnostic savings,
verified remedies and universal checkpoint compatibility are not.
Training and formal verification are out of scope.

## Documentation

Use the [documentation index](docs/README.md) for setup, reference material,
experiment records and maintainer notes. The
[learning guide](PROJECT-LEARNING-GUIDE.md) explains the project in plain language.

## License

Original project code uses the [MIT License](LICENSE). External models,
datasets and assets retain their own terms; see [third-party notices](NOTICE.md).
