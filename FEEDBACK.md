# Faultline — hackathon tool feedback log

Working notes for the required submission feedback, written from the dated
sections below. They distinguish observed tool behaviour from our own
configuration mistakes. Every cost in this file is an **estimate** (published
rates times measured time or tokens) and has not yet been reconciled with
posted Nebius billing. Do not put account identifiers, tokens, private
addresses or payment details here.

## October 17 publication-only checkpoint

**October 20 refresh:** the same three showcase cases were redeployed after
cleanup using the existing Vercel account/project. An exact dry-run file list
and checksum verification of all 40 served files worked, and an unauthenticated
browser saw the updated read-only experience. No new Nebius, NVIDIA or Tavily
interaction or inference spend occurred in this publication. Hosting usage is
subject to the existing account plan; no upgrade was made. This adds no new
provider/model-quality conclusion. See [the publication record](docs/experiments/m7-public-gallery.md).

The [public gallery](https://faultline-robotics-debugger.vercel.app) now exposes
reviewed recordings and reports from the completed Nebius/GR00T experiments.
Publication ran no additional Nebius Job, Token Factory generation or Tavily
search, so it adds no new provider-reliability or model-quality claim and no
new inference-cost estimate. Existing feedback and costs still need final
submission review and billing reconciliation. Local Node certificate-store
friction during Vercel deployment is documented separately in the
[development log](docs/dev-log.md), not attributed to Nebius or NVIDIA.

## Summary

### October 19 post-walkthrough cleanup

- **Token Factory / Nemotron 3 Ultra:** refreshed the LIBERO-Object showcase
  case's next steps from saved measurements and 13 cached sources. The first
  answer needed repair; the single permitted corrective response passed the
  checks and yielded four suggestions. Provenance records two attempts,
  6,973 prompt tokens and 472 completion tokens in total. No new Tavily search
  or GPU Job was run. The per-call reservation is US$0.02 (US$0.04 for this
  two-attempt envelope), not a reconciled price or measured charge.
- The bounded repair worked in this interaction; it does not eliminate human
  review. Suggestions include future tests or architectural changes that are
  not implemented or validated by Faultline. Schema/citation acceptance is
  not evidence that a proposed remedy will work.
- **Project defects, not provider defects:** captured Windows CLI subprocesses
  opened transient consoles; those calls now use the Windows no-window flag.
  The detached diagnosis/Stop/Resume settings are unchanged. An actual local
  child process reported no console handle. Old wording-report boilerplate
  also implied a minimum even when nothing failed; that formatter is fixed.
  See [the development log](docs/dev-log.md).

The required first-hand feedback and final billing reconciliation remain
submission tasks; this cleanup does not claim to have completed them.

| Tool | What we used it for | What worked | Friction and attribution | Would we use it again? |
| --- | --- | --- | --- | --- |
| Nebius AI Cloud Serverless Jobs | The main runtime from October 10: about 20 single-L40S Jobs (pilot, M5B re-run, M3 batching, M6, M7 mode 1, breadth pack, replay), most of them driven by `faultline diagnose`. About US$9 estimated for the October 12–16 Jobs. | Private-registry pulls, GR00T serving on one L40S, exact-ID status and logs, `get-by-name` recovery, dry-run validation, and a bucket policy plus lifecycle expiry for narrow read-only download keys all worked. Startup was consistent (image pull about 3 minutes, our model download 337–347 s). All four LIBERO suite checkpoints served the same way. | Provider side: L40S capacity waits (four of nine submissions in one M7 session found no machine after about 27 minutes; nothing billed), a tenant bucket access-policy quota of 10, `job create --format json` and `--async` sometimes returning non-JSON, an `@sha256` image reference rejected by a 64-character label limit, a completed Job still showing its instance as `RUNNING`, and an expired CLI sign-in surfacing as a generic "context deadline exceeded". Ours: the first export assumed local inode and rename semantics on a bucket mount; one workload deadline was too short for our own runtime. | Yes, for bounded single-GPU evaluation. Plan for capacity waits and keep buckets few. |
| Nebius AI Cloud Compute (VM) | Before Serverless: one L40S VM, and a snapshot-cloned H100, for the baseline, search, reduction and M3 parallel-replay work. | GPU capacity, a stoppable VM, snapshot cloning and serial logs. M3 completed 48/48 valid equal-work episodes and measured 3.715× warm throughput at four evaluator workers versus one. | Provider side: exact-shape capacity advice showed `LOW` or zero slots and two starts timed out with `NotEnoughResources`; OAuth expired during a start request; the tenant's non-GPU vCPU quota was 0. Ours: project-selection, SSH-rule and key-path mistakes. | Yes for reproducible GPU evaluation, though we moved to Serverless for cost and lifecycle reasons. |
| Nebius Container Registry, Object Storage and Secret Stash (MysteryBox) | Private image registry, results buckets with one-day expiry and a stored Hugging Face token for Jobs. | The registry was one CLI command and documented as free; same-project pulls needed no credentials; bucket policies and lifecycle expiry made retention and scoped download keys easy. | The bucket mount lacks inode identity and atomic rename (documenting this would help); the 10-bucket policy quota forced us to reuse one bucket per diagnosis. | Yes. |
| Nebius Token Factory with NVIDIA Nemotron 3 Nano, Super and Ultra | Text-only calls: Nano for early explanations and research summaries, Ultra for scenario hypotheses and explanations, Super for instruction paraphrases (model per task chosen by measurement, ADR 0030). Each call cost well under one cent (estimated). | Fast (7–35 s), cheap, OpenAI-compatible; usage and latency reporting supported auditing; `chat_template_kwargs: {"enable_thinking": false}` was honoured, cutting output from 4096 reasoning tokens to about 950. | Provider side: the model cookbook and quickstart disagree on identifier case and base URL. Ours: a 600-token limit was too small for the first attempt; we had to precompute counts because the models miscount. Model quality: Nano mislabelled applied entities as "reverted", Super inverted a correct prediction, Ultra stated the checked facts correctly. | Yes, for human-reviewed summaries, hypotheses and wording, with outputs checked against measured evidence; not as an autonomous root-cause authority. |
| Tavily Search | Source-linked public research for the earlier occlusion cases (run by hand, three fixed queries per case). | Onboarding was an API key and one endpoint; 3 credits of the free monthly plan per case; the generic occlusion query surfaced a directly relevant paper and a GR00T LIBERO issue. | The narrow numeric query drifted to unrelated industrial pages. Descriptive queries beat literal measurements. | Yes, for source discovery; summaries still need human review. |
| NVIDIA GR00T N1.7 and LIBERO checkpoints | The robot policy under test: the four suite checkpoints `libero_{object,10,spatial,goal}`. | 20/20 nominal baseline episodes on LIBERO-Object; repeatable recorded behaviour for the failure, reduction and breadth experiments. | The gated Cosmos-Reason2-2B dependency returned a 403 until the account holder accepted its terms (model onboarding, not a Nebius fault). Weights take about 6 minutes to download on every Job. Unperturbed GR00T passed only 2 of 5 from one LIBERO-Goal start. | Yes, with the task and simulator limits stated. |
| AllenAI VLA evaluation harness and LIBERO image | Evaluator, simulator, recordings and the LeRobot model-server adapter. | Structured aggregates, traces, SQLite recordings and MP4s made independent validation and the viewer possible. | The pinned image contained a root-only upstream file and needed a root container user; generic schema warnings appeared on successful episodes; the pinned CLI can leave its Docker client child alive after the evaluator exits (an upstream lifecycle risk, not a Nebius or NVIDIA fault). | Yes for the pinned benchmark, with version and cleanup checks. |

## Jethro's first-hand notes

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

## October 10 first Serverless Job and evidence recovery

The Job ran for about seven minutes after provisioning. The downloaded partial
model log confirms policy loading and two episode start/end pairs, but contains
no success classification. Export failed because our destination identity
checks assumed a local filesystem; Claude repaired that adapter. No provider
outage or NVIDIA model-quality conclusion follows from this failure. A fresh
registry lookup verified the repaired image tag/digest. Subsequent local review
caught a deadline-reset bug and an unbounded preflight probe before a retry;
see [`docs/dev-log.md`](docs/dev-log.md) and
[`docs/experiments/serverless-job-pilot.md`](docs/experiments/serverless-job-pilot.md).
Posted charges still need reconciliation. Reuse remains provisional until the
complete evidence path passes. No new paid Job was started during recovery.

## October 3 M5 documentation-only preparation

The [public Nemotron catalog](https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference)
made a small text-only explanation pilot easy to price. The
[structured-output documentation](https://docs.tokenfactory.nebius.com/ai-models-inference/json)
explicitly conditions JSON support on the model-card tag, so we still need to
verify that capability for the exact selected Nano endpoint rather than assume
all OpenAI-compatible endpoints support the same response format. Account
entitlement, credentials, actual request behavior, retention settings and cost
are untested. These are documentation/planning observations, not API bug or
model-quality claims. See [the feasibility note](docs/research/2026-10-03-m5-feasibility-checkpoints.md).

Offline case/viewer implementation and its local validation bugs are recorded
in `docs/dev-log.md`, not attributed to Nebius or NVIDIA. No additional cloud
or inference usage was created by this implementation batch.

## September 30 read-only AI Cloud preflight

The CLI's calculator returned separate hourly estimates for the same L40S VM
shape and retained Network SSD disk, and the capacity resource-advice service
returned an explicit on-demand count and `LOW` availability label for that
exact shape. This made a bounded screen easier to price and exposed restart
uncertainty without spending. The authenticated CLI still had no default
`parent-id`, so the correct regional project had to be selected explicitly;
checking an unrelated regional project first again returned an empty VM list.
That was our project-selection error, not a provider outage. The live console
balance was read in the signed-in console before the September 30 screen
attempt; posted billing for that attempt has not yet been reconciled. The
one-slot `LOW` capacity advice did not guarantee an actual allocation: two
separately approved exact-shape starts timed out with `NotEnoughResources`
and returned to `STOPPED` without an episode. This is a concrete capacity/scheduling friction
point, not an evaluator or model failure. See
[`docs/experiments/m3-three-task-screen.md`](docs/experiments/m3-three-task-screen.md).
Reuse judgment remains provisional until a real three-task run and Jethro's
feedback.

## Our setup errors, not provider bugs

The September 30 H100 migration preflight found a useful distinction in
Nebius pricing information: the public summary page did not itemize disk
snapshots, while the detailed Compute pricing documentation did state the
separate full-copy snapshot tariff and billing units. The CLI calculator
gave immediate H100 and Network SSD estimates, but its estimate fields did
not expose a standalone snapshot resource. The signed-in pricing-list page
returned "Access forbidden" for this account, though the console still
showed the balance. The detailed documentation resolved the pricing question;
the access restriction is a specific onboarding/friction observation, not a
claim that snapshot pricing was unavailable or that creation failed. See
[`docs/experiments/m3-three-task-screen.md`](docs/experiments/m3-three-task-screen.md).

- A September 29 read-only preflight initially checked a project identifier
  from an older console tab and found no VM. The saved exact-project run record
  identified the intended project; the stopped VM and disk were then verified.
  This was a project-selection mistake, not a Nebius disappearance. The live
  capacity dashboard showed zero regular launch slots for the exact L40S
  shape, so a restart is uncertain; it is not evidence of a quota denial or
  provider outage. See [`docs/experiments/m3-adaptive-live-proposal.md`](docs/experiments/m3-adaptive-live-proposal.md).

- A stale workstation-IP `/32` SSH rule and a wrong private-key path caused
  earlier access failures; a narrow current rule and the dedicated WSL key
  resolved them.
- A first source-transfer script assumed the VM project directory was a Git
  checkout. Cloning a private Git bundle into a fresh session directory fixed
  that operator error.
- Our first public-IP parser did not accept Nebius's CIDR-suffixed address
  representation. The parser was fixed; do not label the provider response a
  malformed IP.

## Before submission

### October 1 snapshot-backed H100 attempt

AI Cloud successfully created a snapshot of the stopped boot disk and booted
a separate H100 clone, preserving the original setup. CLI serial logs were
particularly useful: they exposed successful guest networking, the SSH socket,
cloud-init completion, and the backup shutdown deadline without SSH access.
However, workstation SSH remained unreachable despite a ready narrow ingress
rule and verified source address. The cause is unresolved, so this is access
friction, not an established Nebius defect. A Fabric Manager startup failure
also appeared in the cloned guest; its cause and inference impact are untested.
No NVIDIA model or episode ran in this attempt. We stopped early; billing must
still be reconciled. Snapshot cloning and serial observability merit reuse,
but remote-access reliability needs investigation before the next run. See
[the experiment record](docs/experiments/m3-three-task-screen.md).

An operator request initially used lowercase enum labels in a JSON file;
the CLI's protobuf JSON parser required uppercase labels. This failed locally
before resource creation and is separate from the remote access issue.

- Record Jethro's own zero-to-hello-world experience for each tool actually
  used: precise command or screen, elapsed time, blocker, and what helped.
- Reconcile estimated VM costs against posted billing; keep taxes and disk
  accrual separate from running-compute time.
- Add specific, constructive improvements and a final yes/no/why on reuse.
- Never imply Token Factory was used if the pilot is not completed.

## Maintenance boundary

### October 1 portfolio startup interruption

AI Cloud successfully started the separately approved snapshot-backed H100
clone. No model or evaluator was launched before the assistant turn was
interrupted. The independent exact-VM watchdog later confirmed STOPPED within
the allocation limit, after two observed CLI-call timeouts; their cause is
unestablished. Serial logs and resource read-back supported recovery and
verified cleanup. The failure to advance the workflow, idle allocated time,
and delayed temporary-storage deletion are orchestration/control-layer
failures on our side, not demonstrated Nebius or NVIDIA defects.
No robot/HPC result or model feedback follows from this allocation. Estimated
compute is roughly US$7.13 including assumed tax, before separate storage;
posted billing remains unreconciled. See [the experiment record](docs/experiments/m3-portfolio-comparison.md).

### October 1 hotspot H100 retry: model execution completed

Snapshot cloning preserved the cached model/simulator environment and the
original stopped VM. With a fresh narrow ingress rule on the hotspot, SSH
worked immediately after guest initialization. Serial logs and independently
read-back lifecycle state made startup/stop diagnosis practical; all temporary
resources were removed after evidence copy. This supports reusing AI Cloud
snapshot recovery and serial observability. It does not establish whether
hotel filtering or a provider path caused the earlier unreachable clone.

NVIDIA GR00T N1.7's LIBERO checkpoint loaded offline (the separate cache
resolution log recorded the pinned revision) and
completed three distinct nominal object-to-basket tasks, each with video and
trace evidence. Cold loading still consumed several minutes, materially more
than the 93-second warm screen. The cloned image's Fabric Manager service
reported a Pre-NVL5/NVSwitch startup failure; actual single-GPU CUDA and policy
inference passed, but we have not repaired or established the wider relevance
of that service warning. Clearer single-GPU image/service diagnostics would
help onboarding. Reuse is supported for this simulated evaluation workflow,
not yet demonstrated for other suites or physical hardware.

Wrong Python-environment probes and offline dependency refresh were operator/
environment issues; our CLI argument/admission defects were project bugs,
not provider faults. Token Factory remains untested. Warm US$0.116754 pre-tax
and roughly US$1.35 operation-envelope compute including assumed tax are
estimates with different boundaries; storage and posted billing still need
reconciliation. See [the experiment record](docs/experiments/m3-three-task-screen.md).

The September 29 M3 pilot and bounded 1/2/4-worker comparison completed with
valid outcomes and media. Warm throughput scaling is measured; end-to-end
cost and provider billing remain estimates until posting is reconciled.
Engineering issues and operator errors are tracked in [`docs/dev-log.md`](docs/dev-log.md);
do not misattribute them to Nebius or NVIDIA.

### October 4: Token Factory documentation preflight only

No inference has occurred; Token Factory and hosted Nemotron remain untested
in this project. The official model cookbook supplies a concrete Nano 30B A3B
chat-completions example and describes structured output. Onboarding still
requires a separately configured inference key and account/billing checks;
AI Cloud CLI sign-in does not provide that key automatically.

Documentation friction: the model cookbook uses a lowercase model identifier
and US-central regional base, while the generic quickstart uses the global
base. We will verify the account's live catalog rather than assume aliases or
switch processing regions. This is an example-consistency observation, not an
observed API defect. API reliability, output quality, latency, actual charges
and willingness to reuse cannot be judged until the approved real pilot.
See [access research](docs/research/2026-10-04-m5-nemotron-access.md).

### October 5: Authenticated Token Factory catalog check

The locally configured, ignored inference key authenticated a read-only model
catalog request on the global endpoint. It returned the exact capitalized
`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` identifier. Checking the catalog resolved
the cookbook/quickstart naming ambiguity without guessing aliases or changing
processing regions. No inference occurred, so this is onboarding/access
feedback only: output quality, generation latency, charges and willingness to
reuse hosted Nemotron remain untested. AI Cloud CLI authentication and this
inference key remain separate. No secrets or private infrastructure data are
included in this log.

### October 6: First real Token Factory / Nemotron attempt

The reviewed CLI authenticated with a locally configured ignored inference
key, sent only deidentified evidence metadata/IDs, and stored an immutable
factual fallback. The global endpoint returned 1,096 input and 600 output tokens
in 8.703 seconds. Usage reporting and exact model discovery were useful for
auditing the request without exposing credentials or robot recordings.

No interpretation passed validation. Hitting our 600-token ceiling suggests
truncation, but the retained record does not establish finish reason or hosted
reasoning behaviour. This is not evidence of an API outage or low model quality.
The onboarding distinction remains important: AI Cloud CLI sign-in and an
inference key are separate. Documentation did not establish the exact hosted
thinking toggle in our reviewed sources; do not substitute self-hosted options.

Estimated cost was US$0.00020976 at published rates; actual billing is unknown.
The conservative US$0.02 reservation remains consumed with no automatic retry.
We cannot yet recommend reuse based on explanation quality; a useful follow-up
output and Jethro's first-hand feedback remain needed. See the
[pilot record](docs/experiments/m5-nemotron-pilot.md). Local parser, test-fixture,
asset-resolution and viewer defects are logged separately in `docs/dev-log.md`.

### October 6: Separately approved longer attempt

Same model, prompt, metadata packet and JSON mode; fixed 4096-token output
limit and 90-second socket timeout. The request completed with 1096 input and
2142 output tokens in 20.656 seconds. Estimated US$0.00057984; posted billing is
unknown. No videos were sent, no original evidence changed, no GPU started.

The endpoint supplied locally valid structured output and IDs that navigate
the source episodes. The prose remains generic: no diagnostic hypotheses,
one matching success-outcome observation and a budget-local caveat whose
citations are nominal episodes. That caveat is consistent with packet-level
metadata but is not supported by those episode citations. Structural output
validation is useful, yet insufficient for semantic grounding. Human review
remains essential; we would consider reuse for constrained summaries, not
as a stand-alone root-cause authority. One successful request does not establish
reliability, and future prompt quality work needs its own scope/allowance.

### October 9: Local Serverless packaging checks only

No new Nebius service execution or NVIDIA model inference occurred. The pinned
upstream LIBERO image successfully supports direct evaluator execution inside
a container, avoiding nested Docker in the approved Job design. Actual installed
versions and CLI behavior were checked locally, not inferred from a different
upstream source revision. GR00T packaging/rendering and the live Job remain
unvalidated, so this adds no provider-reliability or model-quality claim.

Docker Desktop's inaccessible local runtime socket was resolved by a separately
approved, recoverable runtime-folder move and restart. Interrupt cleanup and
configuration validation defects were project bugs caught by review; neither
is attributed to Nebius or NVIDIA. See the
[migration record](docs/experiments/serverless-job-pilot.md) and
[development log](docs/dev-log.md). Reuse judgments and posted billing still
require actual service evidence and Jethro's first-hand submission review.

Further local packaging checks resolved model dependencies from pinned public
sources and passed Dockerfile validation. An actual CPU image build exposed our
overly strict comparison of `uv --version`: the pinned binary also prints its
platform. Correcting the expected output let the build reach package downloads.
This is our packaging defect, not a provider outage or model failure. Workload
review likewise caught requested-episode identity and dispatch-cutoff/liveness
defects using synthetic fixtures, before any paid Job. No new Token Factory or
NVIDIA inference call was made by these checks; image and live acceptance remain
open.

### October 9: Container Registry and CPU-builder quota

A private Container Registry was created with one CLI command; the service is
documented as free of charge. A planned short CPU builder VM (`cpu-d3`,
8 vCPU) was rejected at creation with `ResourceExhausted`: this tenant's
`compute.instance.non-gpu.vcpu` quota in eu-north1 is **0**, while GPU quotas
(L40S/H100/H200) are 32 each. Nothing was provisioned and no charge resulted;
the temporary SSH rule created for the builder was removed. The quota list
command made the cause clear, but the zero CPU quota was surprising for a
new-account onboarding path, since a CPU VM is the obvious cheap build host.
The image is therefore built locally and pushed from the workstation.

The October billing check also showed that a stopped VM's 200 GiB boot disk
costs about US$0.47/day, and that the hackathon US$25 promo applies to Token
Factory rather than AI Cloud. Both were our planning assumptions, not provider
defects; the console usage breakdown made them easy to see.

### October 10: First real Serverless Jobs

Two single-L40S Jobs ran from a private registry image with a Secret Stash token
and a mounted private bucket. Strengths: same-project registry pulls needed no
credentials; the dry-run caught a real request problem before spend; exact-ID
`get`, `logs --timestamps` and `get-by-name` recovery worked; image pull took
about three minutes for a 7 GB compressed image; GR00T ran on the L40S and both
episodes completed in about 30 seconds each. Bucket policy rules plus a
lifecycle expiry made a narrow read-only download key and automatic retention
easy to set up.

Friction: Job creation rejected an `@sha256` image reference because an
internal label exceeded 64 characters, while a tag reference validated — we
pin the tag to the digest ourselves. `--format json` on create did not return
JSON, so the Job ID came from `get-by-name`. A completed Job's status still
showed its compute instance as `RUNNING`. The bucket mount does not preserve
inode identity or atomic rename; that broke our first export, which was our
exporter's POSIX assumption, not a provider defect, though documenting mount
semantics would help. Verdict: yes for bounded single-GPU evaluation runs.

### October 10: Token Factory / Nemotron v2 iteration

Four more text-only calls to `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` (about
US$0.0024 total, estimated). Strength: fast (7–35 s), cheap, and the
OpenAI-compatible `chat_template_kwargs: {"enable_thinking": false}` was
honoured, which cut output from 4096 tokens (all reasoning, no answer) to
about 950. With thinking off the model follows structure and citations well
but miscounts unless every number is precomputed, and once violated our
evidence contract. Lesson for reuse: give the model computed facts and ask it
to interpret, not to count. Verdict unchanged: useful for human-reviewed
summaries, not autonomous diagnosis.

### October 11: Second Serverless workload (M5B)

A 14-minute single-L40S Job ran the certified case re-run and an
external-start reduction with two injected files (workload JSON and a 7.8 KB
gzip candidate) and exported 48 files to a fresh private bucket. Image pulls
reused the cached layers and took about three minutes; model prefetch about
6.5 minutes dominates short Jobs, so persistent model caching would help repeat
runs. One status poll returned an unknown state mid-run before recovering.
Nothing in this run was a provider defect.

### October 11: Tavily Search (M5D) and Nemotron research summaries

First runtime use of Tavily Search (`basic` depth, 5 results, 3 fixed queries
built from public case descriptors): 3 credits of the free 1,000-credit
monthly plan, 15 distinct sources, `usage.credits` reported and matching our
ledger. Onboarding was only an API key and one documented endpoint. Strength:
the generic occlusion query surfaced a directly relevant paper (LIBERO-Occ,
scene-induced occlusion of VLA policies in LIBERO) and a GR00T LIBERO issue on
GitHub; the narrow, numeric query ("upper-right 14% occluded") drifted to
industrial bin-picking pages. Lesson: descriptive queries beat literal
measurements. Three Nemotron summary attempts (about US$0.0007 total): the
first misattributed a source and compared unrelated benchmark numbers; the
second was rejected by our validator for causal wording; the third passed and
was on topic, though one paraphrase was muddled. Verdict: Tavily is worth
reusing for source discovery; the LLM note still needs human review and a
strict citation validator.

### October 12: Serverless Jobs for the M3 batching experiment

Four L40S Jobs (about 57 minutes, about US$1.66 estimated): a smoke Job, a
five-phase measurement, a failed rerun and a successful rerun. Strengths:
consistent startup (image pull about 3 minutes, our model download 339–344 s
every time), stable 16-vCPU/64 GB nodes that ran 12 simulator workers plus the
GR00T server without memory pressure, and dry-run validation that confirmed
each Job spec before submission. The one failure
was ours: a workload deadline too short for our own runtime's post-download
reserve; Serverless behaved correctly. Friction: the status API timed out
from the workstation for about a minute mid-run (the Job was unaffected), and
`job create --async` sometimes returned non-JSON, so we recovered the Job ID
by name. Verdict: well suited to short, repeatable measurement Jobs.

### October 13: Serverless Jobs for M6

Two L40S Jobs (about 34 minutes, about US$0.99 estimated) ran 173 policy
episodes with a batched 12-worker setup at about 21–23 episodes per minute,
including four concurrent threshold searches. Startup was again consistent
(model download 337–341 s). No provider issues; the only friction was the
daily CLI re-authentication before pushing the image.

### October 13: Serverless Jobs for M7 mode 1 (LIBERO-10)

Six Jobs ran (about 98 container minutes, about US$3.44 estimated) on a new
checkpoint and suite with no provider-side defects once a machine started:
startup stayed consistent (model download 338–347 s) and all exported
evidence verified. Friction was capacity and quota, not the runtime: four of
nine submissions of the L40S `1gpu-16vcpu-64gb` preset found no machine after
about 27 minutes of provider retries (`NotEnoughResources`; nothing billed),
another needed 22 minutes of provisioning retries, the tenant's bucket
access-policy quota stopped a new bucket at 10 buckets, and the CLI hit
several transient API connection timeouts. We worked around both by
resubmitting automatically and reusing one bucket across attempts. Verdict:
reliable once running; plan for capacity waits and keep buckets few. Token
Factory served Nemotron 3 Ultra for the hypothesis calls without issue.

### October 15–16: Serverless Jobs for the breadth pack, driven by `faultline diagnose`

Seven Jobs across all four LIBERO suites (about US$2.66 including the first
live replay) ran without provider-side defects; LIBERO-Spatial and
LIBERO-Goal checkpoints downloaded and served like the others. Token Factory
served Nemotron 3 Super for paraphrase generation reliably. Friction: the
Nebius CLI's interactive sign-in expires after about a day, and an expired
sign-in surfaces as a generic "context deadline exceeded", which a tool can
mistake for a network blip; a long-lived, scoped credential for automation
(or a clearer expiry error) would help. Verdict: with `faultline diagnose`
owning the lifecycle, Serverless Jobs are routine to use.

