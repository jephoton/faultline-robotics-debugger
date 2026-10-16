# Third-party notices

Faultline's own code is licensed under the [MIT License](LICENSE). This file
lists the third-party software, models, services and media it uses or shows,
and where their terms live. **Faultline does not relicense any of them**, and
this repository contains none of their weights. The only third-party code it
contains is the compiled control-panel bundle and its fonts (see "Control
panel" below), shipped with their licence texts. Where we have
not verified a licence ourselves we say so and link the project's own page
instead of naming one: check it before you redistribute anything.

## Simulator and benchmark

| Component | How Faultline uses it | Terms |
| --- | --- | --- |
| [LIBERO](https://github.com/Lifelong-Robot-Learning/LIBERO) | The benchmark: tasks, scenes and initial states in four suites (Object, 10, Spatial, Goal). | The upstream README labels the code MIT and its datasets CC BY 4.0 (recorded in `docs/research/2026-10-03-m5-feasibility-checkpoints.md`). A Hugging Face mirror of the datasets declares Apache-2.0, which conflicts; the discrepancy is unresolved (`docs/research/2026-10-04-m5-external-sample.md`). The 3D scene assets inside LIBERO have their own terms: see the project's licence. |
| [robosuite](https://github.com/ARISE-Initiative/robosuite) | The robot-simulation framework LIBERO is built on. | See the project's own licence at that URL. |
| [MuJoCo](https://github.com/google-deepmind/mujoco) | The physics engine under robosuite. | See the project's own licence at that URL. |
| [vla-evaluation-harness](https://github.com/allenai/vla-evaluation-harness) (Allen Institute for AI) | Evaluator, simulator image and model-server protocol. Pinned at commit `35f1200eb15608aa898f727a3722f7eef889c6cd`; the Faultline image builds on its LIBERO image. | See the project's own licence at that URL. |
| [LeRobot](https://github.com/huggingface/lerobot) (Hugging Face) | Provides the GR00T policy code that the harness's model server loads. | See the project's own licence at that URL. |

## Models

| Component | How Faultline uses it | Terms |
| --- | --- | --- |
| NVIDIA GR00T N1.7 base model ([nvidia/GR00T-N1.7-3B](https://huggingface.co/nvidia/GR00T-N1.7-3B)) and the four LIBERO checkpoints `nvidia/gr00t17-lerobot-libero_{object,10,spatial,goal}-640` ([example](https://huggingface.co/nvidia/gr00t17-lerobot-libero_object-640)) | The robot policy under test, downloaded at Job run time at pinned revisions. Weights are never in this repository or in Faultline's image. | The Object checkpoint was listed as Apache-2.0 when we selected it (`docs/experiments/stack-selection.md`); we did not re-verify the base model's or the other checkpoints' licences. See each model page for the current terms. |
| [Cosmos-Reason2-2B](https://huggingface.co/nvidia/Cosmos-Reason2-2B) (NVIDIA) | A gated dependency GR00T loads when it processes an observation. | Gated: the account that makes the Hugging Face token must accept NVIDIA's model terms on the model page. Faultline accepts nothing on anyone's behalf (`docs/setup/model-access.md`). |
| NVIDIA Nemotron 3 Nano, Super and Ultra on [Nebius Token Factory](https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference) | Hosted text models that write hypotheses, explanations, paraphrases and research summaries. Faultline calls them over the API; it does not host or redistribute them. | See the model cards linked from that page and Nebius Token Factory's terms. |

## Services

| Service | How Faultline uses it | Terms |
| --- | --- | --- |
| [Nebius AI Cloud](https://nebius.com/) (Serverless Jobs, Object Storage, Container Registry, Secret Stash/MysteryBox) | Runs the Jobs; stores evidence and the simulator image. | Governed by your own agreement with Nebius. |
| [Tavily Search](https://tavily.com/) | Source discovery for research context on the earlier occlusion cases. | See Tavily's terms of service at that URL. Search results are cached in the ignored `artifacts/` folder and summarised with links, not committed. |

## Python dependencies

Faultline's own Python package depends only on NumPy (`numpy>=1.24,<1.25`);
the optional extras add PyYAML, boto3 and truststore. Each carries its own
licence, installed with the package. The simulator image additionally holds
PyTorch, LeRobot and the harness's dependencies, which come from the upstream
image and the pinned requirements in `deploy/serverless/`. Faultline's
image is not published; if it ever is, a licence check of everything inside it
is required first (ADR 0031).

## Control panel (front end)

The control panel's built bundle (`src/robot_debug/viewer/app/`, and any
`faultline export` of it) includes compiled copies of the packages below and
three fonts. Their full licence texts are in
`src/robot_debug/viewer/app/THIRD-PARTY-LICENSES.txt`, generated from the
installed packages by `web/scripts/third-party-licenses.mjs` at every build.

| Component | Licence |
| --- | --- |
| [React](https://react.dev/) and React DOM 18.3.1, scheduler 0.23.2 | MIT |
| [React Router](https://reactrouter.com/) 6.30.6 (with `@remix-run/router`) | MIT |
| [marked](https://marked.js.org/) 15.0.12 (renders report Markdown) | MIT |
| [DOMPurify](https://github.com/cure53/DOMPurify) 3.4.17 (sanitises it) | MPL-2.0 or Apache-2.0 |
| Fonts [Barlow, Barlow Condensed](https://github.com/jpt/barlow) and [DM Mono](https://github.com/googlefonts/dm-mono) | SIL Open Font License 1.1 (texts also in `web/src/assets/fonts/`) |

Build and test tools (Vite, Vitest, TypeScript, Testing Library, jsdom,
axe-core, cross-env) are development dependencies in `web/package.json`; they
are not part of the bundle.

## Images and media in this repository

- `docs/experiments/assets/scene-family-calibration.png` shows renders from
  the LIBERO simulator (its scenes, objects and robot) at several camera and
  lighting settings. The scene content belongs to LIBERO and its asset
  authors; see the LIBERO row above.
- `demo/root/` holds one finished diagnosis with three short robot videos
  rendered by the LIBERO simulator during our Nebius runs (scene content as
  above). All other robot videos and traces produced by Faultline runs stay in
  the ignored `artifacts/` folder and are not part of this repository.

If you believe a notice is missing or wrong, please open an issue.
