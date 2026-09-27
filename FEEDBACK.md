# Hackathon tool feedback log

Working notes for the required submission feedback. Distinguish observed tool
behavior from our own configuration mistakes; verify current product details
and add Jethro's first-hand impressions before submitting. Do not put account
identifiers, tokens, private addresses, or payment details here.

| Tool | What we used it for | What worked | Friction and attribution | Would we use it again? |
| --- | --- | --- | --- | --- |
| Nebius AI Cloud Compute | One L40S VM hosted the pinned GR00T model server and LIBERO evaluator for baseline, search, and reduction. | GPU capacity, model caching, and a stoppable VM let us complete bounded experiments with video and trace evidence. The September 27 M4 session ran 22 episodes in a roughly 24-minute VM window. | The CLI's authenticated profile did not provide a `parent-id`, so commands needed an explicit discovered project ID. One control-plane lookup timed out during an earlier readiness poll; using the already verified host avoided repeated lookups. Usage posting did not isolate an aborted session's cost immediately, so our per-run costs are estimates pending billing. | Provisionally yes for reproducible GPU evaluation; review after M3's throughput/cost comparison. |
| NVIDIA GR00T N1.7 and LIBERO checkpoint | Produced robot actions from agent-view and wrist images plus state. | The pinned policy completed 20/20 nominal baseline episodes. It also supplied repeatable, recorded behavior for the controlled failure and reduction experiments. | The first pilot hit a 403 on the transitive gated Cosmos dependency until account-holder access was granted. Model startup took time even with cached weights. These are model/dependency onboarding observations, not Nebius faults. | Provisionally yes for this manipulation-policy test; document task and simulator limits. |
| AllenAI VLA evaluation harness and LIBERO image | Hosted the evaluator, simulator, recordings, and model-server adapter. | Structured aggregates, traces, SQLite recordings, and MP4s made independent validation and the viewer possible. | The pinned image contained a root-only upstream file and needed a root container user. Generic schema warnings appeared even on successful episodes. Attribute these to the upstream integration, not NVIDIA or Nebius without further evidence. | Yes for the pinned benchmark, with explicit version and compatibility checks. |
| Nebius Token Factory / Nemotron | Not used yet. Planned small evidence-grounded triage pilot after M3, subject to model/API and price verification. | No first-hand result to report. | Do not claim model quality, onboarding success, or API problems before a real pilot. AI Cloud CLI authentication does not itself configure a Token Factory key. | Undecided until a bounded pilot compares it with a deterministic report. |

## Our setup errors, not provider bugs

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

- Record Jethro's own zero-to-hello-world experience for each tool actually
  used: precise command or screen, elapsed time, blocker, and what helped.
- Reconcile estimated VM costs against posted billing; keep taxes and disk
  accrual separate from running-compute time.
- Add specific, constructive improvements and a final yes/no/why on reuse.
- Never imply Token Factory was used if the pilot is not completed.
