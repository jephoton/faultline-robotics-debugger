# First bounded failure search

**Status:** local preparation and cloud preflight completed on September 14.
One infrastructure-only launch was stopped before SSH/model startup because
the current provider status supplies its public IPv4 with a CIDR suffix, which
the initial operator extractor rejected. The VM is confirmed stopped; no model
server or evaluation episode started. This record is not evidence of a new
robot-policy result.

## Purpose and claim boundary

This is the first sequential reference session for the diagnostic loop. It
will establish nominal variability, look for the first failure in one clearly
bounded perturbation family, and test whether that failure repeats. It does
not establish general policy robustness, causal explanation, or coverage of
other failure modes.

## Accepted experiment identity

| Item | Value |
| --- | --- |
| Driver commit for this session | `93b9306` (`fix(search): align episode selection with harness`) |
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
| Account role | Initial US$25 account; active card-funded balance verified |
| Existing VM | `robot-debug-pilot`; verified stopped before start |
| Worker shape | One L40S GPU, one active worker, sequential evaluation |
| Session ceiling | 30 minutes from issuing VM start |
| New-launch cutoff | 26 minutes from issuing VM start (1560 seconds) |
| Hard spending cap | US$1 for this session |
| Nebius CLI | 0.12.275, authenticated locally in WSL2 |
| Region / platform / preset | `eu-north1` / `gpu-l40s-a` / `1gpu-16vcpu-64gb` |
| Live compute rate, pre-tax | US$1.7468/hour: US$1.35 GPU + 16 × US$0.012 vCPU + 64 × US$0.0032 GiB RAM |
| Live Network SSD rate, pre-tax | US$0.000097222/GiB-hour; 200 GiB = US$0.0194444/hour |
| 30-minute pre-tax maximum | US$0.8831222 |
| Tax calculation | Singapore billing address; 9% GST applied to the provider's tax-exclusive list price |
| Effective 30-minute maximum | **US$0.9626032**, below the US$1 cap |
| Balance / expiry | US$22.38 active balance; card-funded balance is shown as active and no separately expiring credit is presented |
| Capacity / quota | Fresh medium on-demand capacity for the exact preset (limit 32); matching compute L40S quota is not used |

The price list excludes discounts and taxes. The estimate uses the live
provider rates above and Singapore's current 9% GST. It includes 30 minutes of
the existing VM's GPU, CPU, RAM, and 200 GiB Network SSD allocation, but not
new resources, workers, or large transfer/storage growth. The US$0.0373968
margin is deliberately narrow: stop at the hard deadline and do not extend the
session.

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

Pending. The provider usage page has not yet isolated the cost of the aborted
boot from earlier pilot usage, so do not assume the original US$1 batch has its
full US$0.9626032 run allowance remaining. The updated execution plan accepts
both CIDR-suffixed and bare public IPv4 status values. A fresh paid retry needs
an explicit remaining-budget decision before VM start.

Permitted completed-run interpretations are limited to one of:

- nominal gate failed;
- infrastructure invalidated the session;
- no failure through 25% centered black occlusion;
- apparent failure was not reproducible; or
- a reproducible failure at the stated severity.
