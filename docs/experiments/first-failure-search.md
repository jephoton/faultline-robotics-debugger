# First bounded failure search

**Status:** prepared locally; cloud preflight not yet completed. This record is
not evidence of a new robot-policy result.

## Purpose and claim boundary

This is the first sequential reference session for the diagnostic loop. It
will establish nominal variability, look for the first failure in one clearly
bounded perturbation family, and test whether that failure repeats. It does
not establish general policy robustness, causal explanation, or coverage of
other failure modes.

## Accepted experiment identity

| Item | Value |
| --- | --- |
| Driver integration commit | `201712c` (`merge: integrate bounded failure search driver`) |
| Harness | `allenai/vla-evaluation-harness` at `35f1200eb15608aa898f727a3722f7eef889c6cd` |
| Simulator image | `ghcr.io/allenai/vla-evaluation-harness/libero@sha256:d0c45bc5a3720d569180e6b8dd92510da895f16c3cc509ccc76e4b4ffbb9e0f0` |
| Policy checkpoint | `nvidia/gr00t17-lerobot-libero_object-640` at `1499db357f6ca3762b56c2e8c00b530eb9a09444` |
| Base model | `nvidia/GR00T-N1.7-3B` at `2fc962b973bccdd5d8ce4f67cc63b264d6886495` |
| Suite / task | `libero_object` / task 0 (alphabet soup into basket) |
| Nominal sample | Episode indices 0–19; 20 episodes total |
| Nominal gate | At least 16 successes among 20 valid episodes; any infrastructure error stops the session |
| Sweep state | Episode 0, `seed=7`, `env_seed=7` |
| Perturbation | Opaque black centered square in agent view only; wrist view, state, physics, and success predicate unchanged |
| Square sides / areas | `0.25`, `0.30`, `0.35`, `0.40`, `0.45`, `0.50` / 6.25%, 9%, 12.25%, 16%, 20.25%, 25% |
| Failure definition | A completed episode whose `success=false`; setup/evaluator errors are infrastructure evidence |
| Replay | Five fresh exact replays of the first apparent failure |
| Reproducibility gate | At least 4 policy failures among 5 valid replays |
| Maximum planned episodes | 31: 20 nominal + 6 sweep + 5 replay |

## Cost and execution boundary

| Guard | Value |
| --- | --- |
| Account role | Initial US$25 account; pending live profile verification |
| Existing VM | `robot-debug-pilot`; must be confirmed stopped before start |
| Worker shape | One L40S GPU, one active worker, sequential evaluation |
| Session ceiling | 30 minutes from issuing VM start |
| New-launch cutoff | 26 minutes from issuing VM start (1560 seconds) |
| Hard spending cap | US$1 for this session |
| Live complete-VM rate | Pending read-only provider check |
| Live disk rate | Pending read-only provider check |
| Balance / expiry | Pending read-only provider check |
| Capacity / quota | Pending read-only provider check |

The historical planning estimate was US$1.7468 per running hour plus roughly
US$0.0195 per disk-hour, or about US$0.88315 for thirty minutes. It is not an
authoritative price and must be replaced or confirmed by the preflight check
before a VM is started.

## Preconditions and evidence handling

Before the single owner starts compute: verify the selected account/project,
stopped VM state, L40S capacity and quota, current rates, credit balance and
expiry, local SSH key presence without printing it, ignored artifact location,
and the final credential-free driver tests. Do not provision a replacement VM
or use a second worker.

The driver writes generated configurations, raw aggregates, and an atomic
`session_summary.json` under a fresh ignored results directory. It refuses a
nonempty or symlinked session output directory. It records evaluator failures,
bad aggregate evidence, and wrong episode indices as infrastructure/invalid
evidence rather than policy failures.

After the run, copy aggregate JSON, generated configurations, session summary,
and logs before optional video/SQLite media. Stop the VM by the 30-minute hard
deadline, verify that it is stopped, and record provider-visible cost when it
becomes available. Interpret outcomes only from the preserved raw episode
objects, then expose copied artifacts through the existing local viewer.

## Results

Pending. Permitted interpretations are limited to one of:

- nominal gate failed;
- infrastructure invalidated the session;
- no failure through 25% centered black occlusion;
- apparent failure was not reproducible; or
- a reproducible failure at the stated severity.
