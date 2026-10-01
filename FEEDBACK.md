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
| Nebius Token Factory / Nemotron | Not used yet. Planned small evidence-grounded triage pilot after M3, subject to model/API and price verification. | No first-hand result to report. | Do not claim model quality, onboarding success, or API problems before a real pilot. AI Cloud CLI authentication does not itself configure a Token Factory key. | Undecided until a bounded pilot compares it with a deterministic report. |

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

The September 29 M3 pilot and bounded 1/2/4-worker comparison completed with
valid outcomes and media. Warm throughput scaling is measured; end-to-end
cost and provider billing remain estimates until posting is reconciled.
Engineering issues and operator errors are tracked in [`docs/dev-log.md`](docs/dev-log.md);
do not misattribute them to Nebius or NVIDIA.
