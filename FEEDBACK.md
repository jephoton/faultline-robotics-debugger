# Faultline — tool feedback

Submission-facing summary of tools we actually used. Each row links to
supporting observations; the [dated history](docs/experiments/tool-feedback-history.md)
preserves the detail without making judges read every debugging session.
Our implementation mistakes are separated from provider/model limitations.

## Feedback at a glance

| Tool | Use and onboarding | What worked well | What needs work | Would we use it again? |
| --- | --- | --- | --- | --- |
| **Nebius AI Cloud Serverless Jobs** | Run GR00T simulation, diagnosis and regression replays. First setup required a private image, GPU quota and a model-access secret. [Details](docs/experiments/tool-feedback-history.md#october-10-first-real-serverless-jobs) | Same-project image pulls, exact-Job logs/status and recoverable lookup by name supported the full workflow. All four LIBERO suite checkpoints ran. | Capacity waits were the largest friction: four of nine submissions in one session found no GPU after about 27 minutes. Create sometimes returned non-JSON despite the format flag; expired sign-in could look like a timeout. [Capacity/auth](docs/experiments/tool-feedback-history.md#october-13-serverless-jobs-for-m7-mode-1-libero-10) | **Yes**, for bounded asynchronous evaluation; expose clearer capacity and authentication states. |
| **Nebius AI Cloud Compute (VMs)** | Earlier L40S baseline/reduction and H100 experiments. Quota, SSH and lifecycle configuration added onboarding work. [Details](docs/experiments/m3-three-task-screen.md) | Snapshot cloning, serial logs and exact-state read-back made recovery possible. | Exact-shape capacity was uncertain. Our stale SSH rule/key-path mistakes and orchestration delays were not provider defects. | **Yes** when persistent environments are useful; Jobs fit our current product better. |
| **Registry, Object Storage and Secret Stash/MysteryBox** | Store the private image, export evidence and inject a Hugging Face token. [Details](docs/experiments/tool-feedback-history.md#october-10-first-real-serverless-jobs) | Same-project pulls and scoped download keys with expiry worked well. | Document bucket-mount filesystem semantics and bucket-policy limits more prominently. Our exporter assumed atomic rename/inode behavior; fixing that assumption was our responsibility. | **Yes**, with explicit export checks and retention limits. |
| **Nebius Token Factory + NVIDIA Nemotron** | Text API key is separate from AI Cloud CLI login. Ultra ranks layout hypotheses and writes explanations/next steps; Super generates rewordings; Nano handled early summaries. [Model comparison](docs/decisions/0030-nemotron-model-per-task.md) | OpenAI-compatible calls and token/latency reporting were useful. The hosted thinking toggle reduced unnecessary output. | Cookbook/quickstart identifiers and endpoint examples differed. Models miscounted or misread evidence; our first output limit was too low. Give them precomputed facts and validate the answer. A recent Ultra response needed one repair. [Iterations](docs/experiments/tool-feedback-history.md#october-10-token-factory--nemotron-v2-iteration) | **Yes** for human-reviewed hypotheses, explanations and wording—not as the authority on what failed or whether a fix works. |
| **NVIDIA GR00T N1.7 / Cosmos dependency** | Robot policy under test. A read token needed access to gated Cosmos-Reason2-2B; a 403 disappeared after accepting its terms. [Access](docs/setup/model-access.md) | Closed-loop recorded manipulation and repeatable failures made diagnosis practical across four suite paths. | The gated dependency was easy to miss, and model downloads took roughly six minutes per Job. Benchmark success varies by start; that is evaluation evidence, not a hosting bug. | **Yes**, within the tested simulation scope; not evidence of real-robot safety. |
| **Tavily Search** | Optional public-source context; onboarding was an API key and one endpoint. [Details](docs/experiments/tool-feedback-history.md#october-11-tavily-search-m5d-and-nemotron-research-summaries) | Descriptive queries surfaced relevant occlusion research and a GR00T issue; usage reporting supported a credit ledger. | Very narrow numerical queries drifted to unrelated industrial pages. Finding a source does not validate the generated recommendation. | **Yes** for discovery, with citations and human review. |
| **AllenAI VLA harness / LIBERO stack** | Evaluator, simulator and model-server adapter; not a Nebius service. [Integration](docs/architecture.md) | Videos, traces and structured results supported independent inspection and replay. | The pinned image/CLI needed permission and child-process containment work; generic schema warnings appeared on successful episodes. These are upstream/project integration issues, not Nebius defects. | **Yes**, with pinned versions and lifecycle checks. |

## Jethro's first-hand notes

These existing notes are retained for Jethro's confirmation before submission.

- **The daily CLI sign-in got in the way of long runs.** The Nebius CLI's
  interactive sign-in expires after about a day. Twice a run stopped partway
  because the session had lapsed, once mid-Job, so I had to come back, sign in
  through the browser and resume. For automated, multi-hour work, a
  longer-lived, scoped credential would help, or at least a clear "your session
  expired" error instead of a generic timeout.
- **Waiting for GPU capacity was the biggest time cost.** On October 13, four
  of nine L40S Serverless submissions found no machine after about 27 minutes
  of retries, and another took 22 minutes to start. Nothing was billed while
  waiting, which was fair, but it stretched short experiments into hours. An
  estimate of when capacity would free up, or a suggested alternative preset,
  would have let me plan around it.

## Costs and evidence boundaries

Run-level figures in the linked notes are estimates, not finalized bills.
The latest supplied billing screenshot shows a **$42.04 total including VAT**
for an unidentified date/account filter; it is not yet a reconciled project
total. See the [billing worksheet](docs/submission/billing-reconciliation.md).
Do not add overlapping session totals or treat a reservation as a charge.

The [development log](docs/dev-log.md) records our exporter, Windows-process,
download/recovery and UI bugs. [Publication checks](docs/experiments/m7-public-gallery.md)
created no new Nebius/model usage. Keep credentials and private infrastructure
details out of feedback; add future detail to the history/experiment note and
link only the material lesson here.

