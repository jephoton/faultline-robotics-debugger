# Hackathon tool feedback log

Working notes for the required submission feedback. Distinguish observed tool
behavior from our own configuration mistakes; verify current product details
and add Jethro's first-hand impressions before submitting. Do not put account
identifiers, tokens, private addresses, or payment details here.

| Tool | What we used it for | What worked | Friction and attribution | Would we use it again? |
| --- | --- | --- | --- | --- |
| Nebius AI Cloud Compute | One L40S VM hosted the pinned GR00T server and LIBERO evaluators for baseline, search, reduction, and M3 parallel replay. | GPU capacity, model caching, and a stoppable VM enabled bounded experiments with video and trace evidence. M3 completed 48/48 valid equal-work episodes and measured 3.715× warm throughput at four evaluator workers versus one on the same VM. | The CLI's authenticated profile lacked `parent-id`, so commands needed an explicit discovered project ID. A prior control-plane lookup timed out. During M3, local OAuth expired while waiting on a start request, although the start had reached Nebius; the console provided a stop fallback. Exact-shape capacity briefly showed no available count. Usage posting lags, so M3 cost is estimated pending billing. | Provisionally yes for reproducible GPU evaluation; final answer after billing and Jethro's own onboarding assessment. |
| NVIDIA GR00T N1.7 and LIBERO checkpoint | Produced robot actions from agent-view and wrist images plus state. | The pinned policy completed 20/20 nominal baseline episodes. It also supplied repeatable, recorded behavior for the controlled failure and reduction experiments. | The first pilot hit a 403 on the transitive gated Cosmos dependency until account-holder access was granted. Model startup took time even with cached weights. These are model/dependency onboarding observations, not Nebius faults. | Provisionally yes for this manipulation-policy test; document task and simulator limits. |
| AllenAI VLA evaluation harness and LIBERO image | Hosted the evaluator, simulator, recordings, and model-server adapter. | Structured aggregates, traces, SQLite recordings, and MP4s made independent validation and the viewer possible. | The pinned image contained a root-only upstream file and needed a root container user. Generic schema warnings appeared even on successful episodes. M3 local review also found that the pinned CLI can leave its Docker client child alive after the evaluator exits; this is an upstream process-lifecycle integration risk, not evidence of a Nebius or NVIDIA fault. | Yes for the pinned benchmark, with explicit version, compatibility, and process-cleanup checks. |
| Nebius Token Factory / Nemotron | Authenticated catalog and two real text-only M5C generation attempts. | The separately approved4096-token attempt returned valid JSON and exact episode IDs, readable in the viewer; usage and latency support auditing. | Our600-token limit was inadequate for the first attempt. The successful prose is shallow; its mask caveat cites nominal episodes rather than supporting reduction evidence. Posted billing remains unknown. | Provisionally for human-reviewed summaries, not autonomous diagnosis; final choice needs Jethro's review. |

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
factual fallback. The global endpoint returned1,096input and600output tokens
in8.703seconds. Usage reporting and exact model discovery were useful for
auditing the request without exposing credentials or robot recordings.

No interpretation passed validation. Hitting our600-token ceiling suggests
truncation, but the retained record does not establish finish reason or hosted
reasoning behaviour. This is not evidence of an API outage or low model quality.
The onboarding distinction remains important: AI Cloud CLI sign-in and an
inference key are separate. Documentation did not establish the exact hosted
thinking toggle in our reviewed sources; do not substitute self-hosted options.

Estimated cost was US$0.00020976 at published rates; actual billing is unknown.
The conservativeUS$0.02 reservation remains consumed with no automatic retry.
We cannot yet recommend reuse based on explanation quality; a useful follow-up
output and Jethro's first-hand feedback remain needed. See the
[pilot record](docs/experiments/m5-nemotron-pilot.md). Local parser, test-fixture,
asset-resolution and viewer defects are logged separately in `docs/dev-log.md`.

### October 6: Separately approved longer attempt

Same model, prompt, metadata packet and JSON mode; fixed4096-token output
limit and90-second socket timeout. The request completed with1096input and
2142output tokens in20.656seconds. EstimatedUS$0.00057984; posted billing is
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
