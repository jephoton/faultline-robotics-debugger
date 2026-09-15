# Existing robotics artifacts and Nemotron: decision brief

Date: September 15, 2026. Import/model choices below are proposals, not implementation or spending approval. Apache-2.0 was selected under Jethro's explicit delegation and implemented by Terra, reviewed by the coordinator.

## 1. Import what people already have

Recommendation: accept an existing supported episode directory or dataset, leave its files unchanged, and generate our own diagnostic index/results separately. Ask only for missing replay prerequisites. A custom bundle should be an internal representation or an export, not mandatory preparation imposed on every user.

Three capabilities must be distinct:

1. **Inspect a recording:** show what happened, including cameras and robot telemetry.
2. **Evaluate recorded inputs:** run a policy on saved observations and compare actions. This is open-loop: changed actions cannot change the recorded next image.
3. **Rerun the robot in simulation:** restore a compatible environment and let new actions change subsequent observations. This closed-loop capability is necessary for our confirmation and reduction loop.

An MP4 or dataset may support the first two without supporting the third. A seed alone is not a portable world snapshot; robot joint state alone is not the entire simulator state.

### Evidence and format options

| Existing artifact | Who uses it / contents | What we could honestly offer |
| --- | --- | --- |
| MCAP / ROS bags | Field robotics logs: timestamped cameras, sensors, state and command topics. Foxglove accepts MCAP and ROS 1 bag files. | Direct log inspection after schema/topic mapping. Simulator restoration is not guaranteed. |
| GR00T-compatible LeRobot v2 | Model-development datasets: metadata JSON/JSONL, per-episode Parquet state/actions, per-camera MP4, GR00T `modality.json` mapping. | Natural GR00T episode inspection; closed-loop replay requires additional compatible environment/reset/policy information. |
| LeRobot v3 | Multi-episode Parquet and video shards, metadata giving episode boundaries and offsets. | Broad learning-data interoperability, but a separate version-aware reader; not automatically GR00T-compatible. |
| robomimic-style HDF5 | Simulation/research episodes: actions, observations and environment metadata; robosuite datasets can include full MuJoCo states and model XML. | Closest candidate for stateful simulator import. Validate the particular LIBERO variant and pinned runtime before promising replay. |
| RLDS | Episodes and steps with observations/actions and boundary flags; environment metadata optional. | Dataset analysis, not a universal self-contained simulator bundle. Defer another ecosystem until there is a user need. |

Production evidence is strongest for logs: [Tangram Vision](https://foxglove.dev/customers/tangram-vision) describes engineers offloading MCAP files and inspecting them on site; [AIM](https://www.foxglove.dev/customers/aim) standardized autonomy logs to MCAP. These are specific customer deployments, not proof of industry-wide prevalence or simulator replay support. [Multiply Labs](https://www.foxglove.dev/customers/multiply-labs) also describes debugging deployed robotic clusters through logs and state.

Technical sources: [MCAP specification](https://mcap.dev/spec), [Foxglove import](https://docs.foxglove.dev/docs/data/importing-data), [NVIDIA GR00T data preparation](https://github.com/NVIDIA/Isaac-GR00T/blob/main/getting_started/data_preparation.md), [LeRobot v3 migration](https://huggingface.co/docs/lerobot/main/porting_datasets_v3), [robomimic schema](https://robomimic.github.io/docs/datasets/overview.html), [robomimic playback](https://robomimic.github.io/docs/tutorials/dataset_contents.html), [RLDS](https://github.com/google-research/rlds).

Important compatibility traps:

- NVIDIA's current preparation guide specifies LeRobot v2 plus `modality.json` and v3-to-v2 conversion. Do not advertise every LeRobot dataset as zero-conversion GR00T input.
- LeRobot v3 documentation has a metadata discrepancy: the general overview mentions `tasks.jsonl`, while the migration guide/current implementation use `tasks.parquet`. Pin the reader and detect dataset versions instead of guessing paths.
- robomimic explicitly separates saved-image playback, simulator-state playback, and action replay. None alone guarantees counterfactual policy replay. Some non-robosuite datasets have dummy states.
- Schemas in MCAP are optional. Message decoding and identifying which topic is the policy camera or command stream can still need mapping.

### Recommended first audience and acceptance experiment

Target **simulation-based manipulation-policy developers**, not arbitrary deployed fleets, for the hackathon. They are closest to the environment our debugger can actually rerun.

Jethro prioritized the option that makes the product usable and scalable. The resulting direction is: first support our existing evaluation artifacts, then test one external LIBERO/robomimic-style HDF5 episode as the first external adapter **if its simulator state is genuinely restorable**. This is the best chance of delivering the complete import-to-regression journey with one existing format. A format-independent episode/capability interface permits later LeRobot and MCAP readers without promising that they all support simulator replay. The internal interface is a design direction; exact schema and reader implementation need a sample feasibility check.

Before choosing the external adapter, inspect a real rights-compatible sample: identify its task, cameras, controller/actions, simulator reset information, model/assets and policy reference; try restoring and rerunning it with the pinned environment. If restoration is unavailable, label it inspection-only and reconsider the adapter before investing in UI.

Proposed user journey: select existing artifact → choose episode → see **inspectable / replay-ready / missing prerequisites** → fill only missing configuration → approve bounded diagnosis → inspect confirmed/reduced evidence → export a regression recipe. Imports must not execute embedded scripts, fetch untrusted checkpoints automatically, or start paid compute.

Next investigate direct GR00T-compatible LeRobot v2 ingestion for a broader VLA-developer audience. It can show and index episodes even when replay prerequisites are missing. MCAP is a sensible later production extension, but would initially add observational triage, not universal failure minimization. An un-restorable HDF5 sample or evidence that target teams mostly hand over LeRobot folders would change the ordering.

## 2. Nemotron: the diagnostic assistant, not the robot policy

GR00T produces robot actions. Nemotron would help a human interpret recorded evidence and choose a useful test. The simulator's task-success predicate and repeated controlled experiments remain authoritative.

### Model shortlist

| Candidate | Evidence / input | Proposed role |
| --- | --- | --- |
| Nemotron Nano 2 VL / Nano 12B v2 VL | NVIDIA documents image and video input; Nebius announced hosted availability. Current account availability still unverified. | Preferred first feasibility candidate: visual symptom/time-window triage with task and trace context. |
| Nemotron 3 Nano | Nebius family catalogue lists it; exact deployed variant/modalities must be checked. | Text-only trace/report fallback when selected endpoint is text-only. Never claim it watched the video. |
| Nemotron 3 Super 120B A12B | Nebius describes text input/output, reasoning and tool use. | Optional deeper analysis of structured evidence; not the default video model and no need to start with this larger option. |
| Nemotron Nano Omni | Current Nebius catalogue advertises it. | Alternative multimodal candidate only after checking actual endpoint, supported media and price; do not expand the pilot to compare every model. |

Sources: [Nebius Nemotron catalogue](https://nebius.com/services/token-factory/nemotron), [Nano 2 VL announcement](https://nebius.com/blog/posts/nvidia-nemotron-nano-2-vl-in-ai-studio), [Super announcement](https://nebius.com/blog/posts/nemotron3-super-now-available), [NVIDIA Nano VL API](https://docs.nvidia.com/nim/vision-language-models/1.5.0/examples/nemotron-nano-12b-v2-vl/api.html).

**Verification boundary:** an unauthenticated request to the Token Factory model catalogue returned HTTP 401. Marketing availability is not account entitlement. Before inference, use a locally configured Token Factory key to list models and verify exact model ID, modality, region/base URL, pricing, limits, and data handling. Nebius compute CLI login does not establish that Token Factory API credentials are configured. No inference was run for this research.

### Concrete input shape

Use Nebius's OpenAI-compatible chat-completions API. Its documented vision content supports text plus `image_url` with an HTTPS URL or inline base64 image. This illustrative request is a **shape**, not a verified runnable model configuration:

```json
{
  "model": "COPY_EXACT_VISION_MODEL_ID_FROM_AUTHENTICATED_CATALOGUE",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "Case c01. Task: put the object in the basket. Frame f12, agentview, t=2.4s. Describe visible evidence; separate observations from hypotheses."},
      {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,ENCODED_FRAME_BYTES"}}
    ]
  }],
  "max_tokens": 800
}
```

[Nebius vision request documentation](https://docs.tokenfactory.nebius.com/api-reference/examples/vision-capabilities) and [quickstart](https://docs.tokenfactory.nebius.com/quickstart) establish the transport. Credentials belong in local environment/secret storage, never committed JSON. Inline bytes avoid needing public video hosting but still transmit data to the provider.

NVIDIA NIM also documents `video_url` and video sampling controls for Nano VL; that does **not** prove the same extensions work on Nebius's hosted endpoint. Prefer a bounded set of explicitly timestamped frames for the first pilot, subject to a multi-image compatibility test. A provisional 8–16 frames total per case makes the input inspectable; sampling can miss brief events, so label temporal limitations. Preserve camera identity and distinguish the image GR00T actually received from an unobstructed renderer preview.

Send task instruction, selected timestamped frames, compact robot/action events, and evidence IDs. Do not upload entire datasets. Compare matched nominal and suspected episodes only when alignment and provenance are clear. Known occlusion coordinates should come from metadata, not a model guessing a rectangle.

### Useful output and evaluation

Proposed structured result: case ID; visible observations with frame/event references; suspected symptom/time window; alternative explanations; missing evidence; suggested test IDs restricted to our approved family. Examples include “gripper closes without securing the object” or “object leaves this camera view”; these are hypotheses requiring evidence, not known results from our current runs.

Use the report to navigate the viewer to cited frames and let the operator choose a diagnostic test. Do not permit the model to execute cloud commands, alter success criteria, or silently reorder the accepted grid. Treat imported instructions/log strings as untrusted data. Reject unknown evidence/test IDs. If model-specific structured output is unavailable, validate parsed output locally and surface failures rather than inventing a report. [Nebius JSON mode](https://docs.tokenfactory.nebius.com/ai-models-inference/json) is model-dependent and guarantees neither truth nor useful diagnosis.

For explanatory reports, known results/perturbations are legitimate inputs and should be disclosed. For a claim that Nemotron discovers/ranks faults, withhold the answer labels and fault parameters; otherwise the evaluation leaks the answer. Compare against a deterministic summary and simple candidate ordering on held-out, human-reviewed cases. Measure unsupported claims, useful localization/test selection, abstentions, latency and token cost. Our existing all-success cohort cannot measure failure-detection recall.

Later, if the assistant improves test selection, compare grid/random versus assisted search including **all** preprocessing, token and GPU costs. Until measured, position it as assisted diagnosis, not demonstrated budget optimization.

### Decision and spending checkpoint

Recommend hosted multimodal Nano feasibility before considering self-hosting another model beside GR00T. This preserves GPU resources for robotics and separates the report service from the evaluator. Verify Token Factory balance/credit eligibility separately; do not assume AI Cloud credit applies. Propose a small pilot cap only after current price and payload measurements. No new spend is approved by this document.

## 3. License outcome

Selected Apache-2.0 over MIT because its explicit contributor patent grant is useful for reusable robotics infrastructure. MIT is shorter, but that simplicity is less valuable here than the explicit patent terms. This is a project licensing choice, not legal advice or a guarantee concerning third-party patents.

Terra added the exact [Apache license text](https://www.apache.org/licenses/LICENSE-2.0.txt), a README scope statement and package license metadata. Original code only: model weights, datasets, media and dependencies retain upstream terms. No invented copyright owner or unnecessary NOTICE was added. Publication and any required third-party attribution audit remain separate from adding the license.
