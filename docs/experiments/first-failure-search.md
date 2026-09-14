# First bounded failure search

**Status:** ready for the approved evaluation session on September 14. Two
earlier bounded launch attempts were stopped with no model server or evaluation episode started. The
first stopped before SSH/model startup because the provider supplied its public
IPv4 with a CIDR suffix, which the initial operator extractor rejected. The
second accepted that format, but SSH never became reachable; the current WSL
egress address was outside the original TCP/22 rule, and a temporary matching
rule still did not establish a connection. The VM is confirmed stopped and the
temporary rule is absent. This record is not evidence of a robot-policy result.

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
| Hard spending cap | **US$2 aggregate** for the aborted boot plus exactly one retry; no third billable session |
| Evaluation-session cap | **US$1.10**, explicitly approved after the separate connectivity probe passed |
| Remaining retry boundary | 28 minutes hard stop; **US$0.8984297** estimated maximum including GST |
| Nebius CLI | 0.12.275, authenticated locally in WSL2 |
| Region / platform / preset | `eu-north1` / `gpu-l40s-a` / `1gpu-16vcpu-64gb` |
| Live compute rate, pre-tax | US$1.7468/hour: US$1.35 GPU + 16 × US$0.012 vCPU + 64 × US$0.0032 GiB RAM |
| Live Network SSD rate, pre-tax | US$0.000097222/GiB-hour; 200 GiB = US$0.0194444/hour |
| 30-minute pre-tax maximum | US$0.8831222 |
| Tax calculation | Singapore billing address; 9% GST applied to the provider's tax-exclusive list price |
| Effective 30-minute maximum | **US$0.9626032** for one full retry |
| Conservative aggregate bound | **US$1.9252064** for two full 30-minute sessions, below the approved US$2 cap |
| Balance / expiry | US$22.38 active balance; card-funded balance is shown as active and no separately expiring credit is presented |
| Capacity / quota | Fresh medium on-demand capacity for the exact preset (limit 32); matching compute L40S quota is not used |

The price list excludes discounts and taxes. The estimate uses the live
provider rates above and Singapore's current 9% GST. It includes 30 minutes of
the existing VM's GPU, CPU, RAM, and 200 GiB Network SSD allocation, but not
new resources, workers, or large transfer/storage growth. Although the initial
launch was stopped far earlier than its deadline, the provider has not isolated
its cost. The approved cap therefore uses the conservative bound of two complete
30-minute sessions (US$1.9252064), leaving US$0.0747936. Stop at the hard
deadline and do not add a third billable session.

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

**Outcome: infrastructure invalidated the session.** The US$2 aggregate
authorization covered the first aborted boot plus exactly one retry. Neither
attempt reached remote source transfer, cached-runtime validation, model-server
startup, nominal evaluation, sweep evaluation, or replay. There are no driver
artifacts, raw aggregates, videos, episode timings, policy failures, or
replay counts to interpret.

The first attempt found and fixed an operator-only compatibility issue:
Nebius returns the public IPv4 as a CIDR-suffixed interface, so the extractor
now accepts both that form and a bare address. The second attempt isolated a
different access-path issue: its VM was `RUNNING`, but TCP/22 did not accept a
valid key. Read-only inspection showed that the current WSL egress `/32` was
not in the existing SSH rule. A temporary, otherwise equivalent TCP/22 rule
for that `/32` was created and verified absent after cleanup; SSH still did not
respond. The existing rule was not deleted or broadened.

Provider billing did not expose an isolated cost for either attempt at stop
time, so no actual cost is recorded. The conservative two-full-session bound
remains US$1.9252064; it is a cap calculation, not a measured charge.

Follow-up read-only diagnosis established both causes. Nebius serial logs show
that cloud-init completed in 13--14 seconds and `ssh.socket` listened on both
boots, then closed normally during shutdown. The attached security group is the
group containing the TCP/22 rule, the subnet uses provider-default routing, and
the public address is dynamic. The current WSL egress address is outside the
rule's stale `/32`, which explains the TCP timeout. Separately, the execution
plan selected `/mnt/c/Users/Jethro/.ssh/id_ed25519`; that key differs from the
dedicated `~/.ssh/nebius_robot_debug_2026` key injected by cloud-init, and WSL
rejects the Windows-mounted private key's mode. The dedicated key has mode 600
and matches cloud-init.

The five-minute, non-evaluation connectivity probe subsequently passed. With a
temporary current-egress `/32` rule, TCP/22 opened 64 seconds after the start
request. The SSH server accepted `~/.ssh/nebius_robot_debug_2026`, and the
non-interactive command exited 0. A post-run serial capture contains cloud-init
completion and `ssh.socket` listening evidence. Independent cleanup verification
found the VM `STOPPED` and the temporary rule absent.

Connectivity debugging is complete. Jethro explicitly approved a separate
US$1.10 cap for this unchanged evaluation session. The session may now start
only after its live preflight gates pass.

The first evaluation start after that approval also stopped before runtime
validation: SSH and source-bundle transfer succeeded, but the existing
`/home/robot/nebius-nvidia-hackathon` directory is not a Git checkout, so the
operator's `git fetch` command failed. No model server or episode started. The
retry clones the verified bundle into a fresh per-session directory rather than
altering that existing directory. Its hard stop is reduced to 28 minutes,
giving an estimated US$0.8984297 retry maximum and preserving room for the
short source-layout failure within the approved US$1.10 cap.

Permitted completed-run interpretations are limited to one of:

- nominal gate failed;
- infrastructure invalidated the session;
- no failure through 25% centered black occlusion;
- apparent failure was not reproducible; or
- a reproducible failure at the stated severity.
