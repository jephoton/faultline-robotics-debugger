# Robot Debugging System Startup Plan

> **For agentic workers:** Follow the current scoped execution plan and the human-guided multi-agent workflow in `AGENTS.md`. Use parallel agents only for substantial independent work; retain one owner for cloud spending and Git integration. Steps use checkboxes for tracking.

**Goal:** Reproduce a working simulated robot policy, discover and replay one meaningful failure, and establish the measurements needed to build an efficient parallel debugging system.

**Architecture:** An existing model server chooses robot actions; simulation workers run independent task attempts. Our application records attempts, selects controlled perturbations, reduces failures, and produces replayable reports. Start with one worker and retain the upstream runner until there is evidence that custom infrastructure is necessary.

**Tech stack:** Python, Linux, Docker, a candidate GR00T checkpoint through LeRobot and the AllenAI VLA evaluation harness, LIBERO/MuJoCo, Nebius GPU compute, JSON/JSONL artifacts, and lightweight reports. Formal verification is optional and outside the critical path.

**Status:** M2 found a reproducible upper-right occlusion failure after a 20/20 nominal baseline. On September 27, M4 reduced its mask from 25% to 14.0625% of image area within 12 candidate attempts; the final accepted mask failed 4/4 times and five fresh nominal controls succeeded. The 22-episode evidence set is indexed by the local viewer. This is a budget-local reduced counterexample, not a proven minimum or causal diagnosis. M3 parallel-performance design is next.

**Completed scoped plan (September 16):** Jethro accepted a fixed-area position search rather than increasing centered severity or changing perturbation family. Task 6 of [`2026-09-15-position-grid-search.md`](2026-09-15-position-grid-search.md) completed in the corrected `5-series` session. The fourth ordered cell, upper-right `x=0.50, y=0.00`, produced a policy failure that repeated 5/5 times; matched nominal controls succeeded 5/5. The VM was independently verified stopped with no temporary rule. The estimated session cost is US$0.5118 including the 9% GST assumption, inside the cumulative US$2 cap. Sample-format inspection remains independent of this result.

**Proposed product/submission plan:** [Replayable case import, Nemotron, and license](2026-09-15-case-import-nemotron-submission.md) scopes the post-grid product experience and remaining submission requirements. Jethro prioritized a replay-feasible LIBERO/robomimic-style external episode as the first import direction; exact implementation/model designs remain proposed. Apache-2.0 was selected under Jethro's delegation and added locally. [Production-artifact and Nemotron research](../../research/2026-09-15-production-artifacts-and-nemotron.md) explains the format alternatives and capability checks.

**User collaboration preferences (September 12):** Cloud compute is a confirmed main project resource. Ask the user to configure credentials when cloud access is needed. Commit small coherent changes frequently using Conventional Commits. Hand most architecture and design choices to the user with plain-language context, options, and a recommendation before implementing them. Follow `AGENTS.md`; the stack and design below remain proposals, not blanket approvals.

**Budget and account update (September 13):** The total intended Nebius-credit envelope is US$75: use the initial account's US$25 for the first baseline/integration work without deliberately wasting it, then use US$50 on the main account (US$25 initial balance plus US$25 promo) for perturbation, reduction, parallel-evaluation, and demo work. Nebius projects cannot move between tenants or regions, so this is an account/profile handoff using the same Git repository, not a project migration. The initial CLI-authenticated account is active and currently shows suitable `eu-north1` L40S capacity; its billing, live complete-VM price, quota, capacity, and balance/expiry must still be verified immediately before provisioning. Keep US$5--10 of the combined plan in reserve and treat the US$75 total as a hard ceiling unless Jethro explicitly changes it.

---

## 1. The project we are starting

Working description:

> Give a robot policy a task, search for conditions that make it fail, reduce those conditions into a repeatable bug report, and replay the report against a changed policy.

The intended user is a robotics engineer testing an existing manipulation policy. The initial field is tabletop manipulation: an arm moving objects between locations. This is a research prototype for policy debugging, not an industrial safety certification system.

An **episode** means one complete attempt. **Inference** means asking the trained model for actions. A **worker** runs episodes. A **perturbation** is a controlled change to an otherwise valid test.

### First visible result

Two recordings of the same task: a nominal attempt that succeeds and a deliberately changed condition that causes a repeatable failure. Each has a machine-readable configuration and outcome.

### Competition-sized result

- One supported NVIDIA robot policy, one simulator, and three related tasks.
- Nominal tests plus two controlled perturbation families.
- Sequential and parallel evaluation with measured performance.
- Failure reduction and replay bundles.
- A small report interface showing nominal, failing, and reduced cases.
- A real Nebius execution path, reproducible setup, and submission artifacts.

Do not make training, a second simulator, a robot purchase, SMT integration, or a large dashboard prerequisites for that result.

## 2. What we know about this machine

Read-only checks on September 12, 2026 found:

| Item | Evidence | Consequence |
| --- | --- | --- |
| GPU | RTX 3050 Laptop GPU, 4096 MiB VRAM | Do not assume the proposed VLA model fits locally |
| Driver | 591.59 | Record it; compatibility still needs a runtime check |
| System memory | 16,487,870,464 bytes, about 15.36 GiB | Avoid running many heavyweight local workers |
| WSL | Ubuntu and docker-desktop registered as WSL2, both stopped | Existing Linux tooling can be checked before installing anything |
| Docker Desktop | Executable present | Installation is present; a working engine and GPU passthrough are unverified |
| Repository | Repository root | Current source location |
| GitHub | Private repository created previously | Public release belongs in the final submission stage |

Use the laptop for editing, small CPU tests, report viewing, and lightweight simulator exploration if it works. Prefer colocating model inference and simulation on the cloud pilot to avoid sending every camera frame over the laptop's internet connection.

Cloud compute is included among the main resources, as confirmed by the user. WSL/Docker functionality, disk space, cloud allocation details, and model access still need discovery. Ask for cloud authentication when it is needed, rather than assuming only inference credits are available.

## 3. Starting technology decision

**Primary candidate:** GR00T N1.7, the LIBERO Object checkpoint, and the AllenAI evaluation harness's LeRobot adapter.

The inspected upstream configuration names:

```text
configs/model_servers/lerobot/groot_n17.yaml
nvidia/gr00t17-lerobot-libero_object-640
configs/benchmarks/libero/object.yaml
```

The adapter documentation distinguishes model loading from actual task reproduction. It also identifies gated model dependencies. Treat the entire pairing as a hypothesis to reproduce: exact versions, checkpoint access, camera mapping, state normalization, action chunks, and reset behavior matter. Do not substitute a generic GR00T base checkpoint and expect the same skill.

Sources: [adapter documentation](https://github.com/allenai/vla-evaluation-harness/tree/main/configs/model_servers/lerobot), [GR00T config](https://github.com/allenai/vla-evaluation-harness/blob/main/configs/model_servers/lerobot/groot_n17.yaml), [reproduction report](https://github.com/allenai/vla-evaluation-harness/blob/main/docs/reproductions/lerobot.md).

**First simulator choice:** LIBERO/MuJoCo. Isaac Lab-Arena remains an alternative if the chosen integration fails, not an additional initial dependency. Review a simulator's hardware requirements before selecting a GPU; CUDA model inference and RTX rendering are different requirements.

**Dependency policy:** inspect the harness's documented release, select a revision containing the required configuration, and record the exact commit SHA. Pin model revisions and container image digests after the first successful run. A moving `main` branch is not an experiment identity.

## 4. File layout and responsibilities

Only this plan and a root README are created during planning. The following are planned execution artifacts.

| Path | Responsibility |
| --- | --- |
| `docs/setup/local-environment.md` | Commands, output summaries, OS/tool versions, disk and GPU checks |
| `docs/setup/cloud-pilot.md` | Account/region, resource shape, explicit spending cap, expiry and teardown procedure; no credentials |
| `docs/experiments/stack-selection.md` | Chosen upstream revisions, model revisions, licenses, and exact launch commands |
| `docs/experiments/first-baseline.md` | Task selection, nominal outcomes, timings, and observations |
| `configs/baseline.yaml` | A self-contained, validated copy of the selected experiment configuration |
| `configs/search.yaml` | Perturbation bounds, seeds, episode and time budgets |
| `src/robot_debug/records.py` | Experiment and attempt records |
| `src/robot_debug/runner.py` | Thin adapter over the working upstream runner |
| `src/robot_debug/perturb.py` | Apply and validate the selected scene changes |
| `src/robot_debug/search.py` | Budgeted random search first |
| `src/robot_debug/reduce.py` | Remove or shrink changes while retesting failure |
| `src/robot_debug/report.py` | Static report generation first |
| `src/robot_debug/viewer/` | Implemented local read-only artifact viewer: run catalog, media/trace serving, paired comparison, diagnostics, and timeline |
| `docs/superpowers/plans/2026-09-14-viewer-demo-clarity.md` | Completed viewer implementation and acceptance evidence, including current missing-baseline-video limitation |
| `tests/test_records.py` | Round-trip configuration and duplicate-attempt handling |
| `tests/test_perturb.py` | Bounds, nominal restoration, invalid configuration rejection |
| `tests/test_reduce.py` | Reducer behavior using a deterministic toy failure function |
| `tests/test_runner.py` | Crash, timeout, completion, and replay record handling |
| `artifacts/` | Ignored local videos, traces, and run output; large artifacts go to object storage |
| `submission/` | Demo script, Devpost draft, testing instructions, feedback, and final evidence |

Keep third-party checkouts outside the tracked project source. Save their revisions and any patches. Keep secrets, model weights, datasets, and large recordings out of Git.

## 5. Startup tasks: first three working sessions

These are discovery and reproduction tasks. Their outputs determine the subsequent implementation details. Time estimates are planning targets, not promises about downloads or GPU availability.

### Task 1 — establish a usable local environment

**Output:** `docs/setup/local-environment.md`.

- [x] Read applicable `AGENTS.md` instructions in the project and target checkout locations.
- [x] Run these read-only checks from PowerShell and record the results in `docs/setup/local-environment.md`:

```powershell
& 'C:\Windows\System32\nvidia-smi.exe' --query-gpu=name,memory.total,driver_version --format=csv,noheader
& 'C:\Windows\System32\wsl.exe' --list --verbose
& 'C:\Windows\System32\wsl.exe' -d Ubuntu -- bash -lc 'cat /etc/os-release; df -h .; command -v python3; command -v uv; command -v docker'
```

Expected: Ubuntu runs, available tools are identified, and free disk space is known. Missing tools are setup actions to record; they do not imply reinstalling WSL.

- [ ] Check Docker using `docker version` from the Linux shell where it will be used. Docker is not currently available in WSL, so cloud-host validation is still required.
- [ ] Verify GPU passthrough using the chosen runtime's documented diagnostic before attempting model installation. WSL can see the GPU; Docker GPU support remains unverified.
- [x] Decide whether to retain the Windows checkout or create a separate Linux-filesystem development checkout. The Windows checkout is authoritative; cloud execution will use its own pinned checkout.

**Gate:** Linux commands run, storage is sufficient for the selected downloads, and the actual Docker/GPU state is documented. No model download is needed to pass the local discovery gate.

### Task 2 — inspect and freeze the proposed policy pairing

**Output:** `docs/experiments/stack-selection.md`.

- [x] Inspect the upstream release and the GR00T adapter, benchmark configuration, and reproduction instructions linked above.
- [x] Obtain a separate upstream checkout, then record `git rev-parse HEAD` and `git status --short` from it.
- [x] Confirm the chosen revision includes the GR00T and LIBERO Object configuration files. Copying a configuration from a newer revision into an older runtime requires a separate compatibility check.
- [x] Record the checkpoint, base-model dependencies, observed revisions, licence evidence, access requirements, and download-size constraints. Do not accept terms on the user's behalf. The live run exposed an unresolved transitive gated dependency; see `docs/setup/model-access.md`.
- [x] Inspect the benchmark configuration schema and determine how to select one task, one episode, recording, seed, and episode horizon. Produce `configs/baseline.yaml` with actual supported fields.
- [x] Write the server and experiment commands into the stack-selection document before any paid experiment.

The upstream server command to validate in its own checkout is:

```bash
vla-eval serve --config configs/model_servers/lerobot/groot_n17.yaml
```

The upstream suite configuration is:

```bash
vla-eval run --config configs/benchmarks/libero/object.yaml
```

**Do not launch the full suite as the first experiment.** Inspect its episode count first and use the single-task configuration produced above. These commands are upstream entry points, not newly implemented project commands.

**Gate:** accessible model artifacts, a version-pinned stack, and a one-episode configuration. If unresolved after two focused setup sessions, try the original documented policy evaluation path. Do not spend the first week building a new model adapter.

### Task 3 — configure one bounded cloud pilot

**Output:** `docs/setup/cloud-pilot.md`.

- [x] Ask the user to configure cloud credentials or sign in locally when starting cloud setup. Local CLI authentication is complete; the initial account and its projects are active, and a read-only capacity check found the one-L40S pilot candidate available.
- [x] Select a proposed smallest available resource that meets the model and simulator requirements with memory headroom. Read-only capacity evidence supports `eu-north1` `gpu-l40s-a` / `1gpu-16vcpu-64gb` (48 GB GPU memory); measure peak usage during the pilot before accepting it as the ongoing worker shape.
- [x] Calculate a preflight cost estimate from the current public rate: US$1.7468 per running hour for the candidate, plus roughly US$0.47/day for a 200 GiB Network SSD. The proposed 8-hour pilot is about US$14.44 including one day of disk, within the user-confirmed US$20--25 initial-account allocation. Recheck live price and balance immediately before creation; this is not provisioning approval.
- [x] Set a proposed maximum job duration and one active pilot worker: one regular VM, one worker, and an 8-hour runtime ceiling. A VM, unlike a Serverless AI job, has no assumed one-hour batch timeout to configure; do not start additional workers until the baseline is measured.
- [x] Configure the proposed first-pilot persistence approach: keep the model cache and artifacts on a managed 200 GiB boot disk for no more than 24 hours, copy selected artifacts to the workstation, then delete the VM. The model server remains loopback-only. The remaining user security choice is temporary public SSH/scp access versus an isolated jump-host path.
- [x] Document the exact teardown sequence: `nebius compute instance delete <instance-id>` deletes the managed boot disk; then list project disks to detect any separately created storage. No resources currently exist in the selected project.

Nebius Jobs run containerized batch work; detailed creation and storage configuration are in the [job guide](https://docs.nebius.com/serverless/jobs/manage). Prefer one colocated inference/simulation pilot before splitting services.

**Gate:** resource compatibility, access, cost ceiling, persistence, and teardown are concrete. No paid resource is authorized merely by this written plan.

### Task 4 — obtain one working robot episode

**Outputs:** `docs/experiments/first-baseline.md`, plus ignored videos and run records.

- [x] Start the model server using the pinned setup and wait for its documented readiness signal.
- [x] Run the single-task, single-episode configuration. Save logs and recording even if it fails.
- [ ] Watch the video. Check that the instruction, observed objects, robot movement, and success check agree.
- [ ] If motion is nonsensical, check observation names, normalization, action convention, embodiment, and chunk buffering before blaming the policy.
- [x] Separate dependency errors, model failures, simulator crashes, and genuine completed task failures in the report.
- [x] Once a successful episode exists, replay its configuration and record whether the result repeats.

**Gate:** a visible successful task and replayable configuration. If this fails, continue debugging the baseline rather than adding perturbations.

### Task 5 — measure a small baseline and choose the first perturbation

**Outputs:** baseline results and an implementation brief for the runner/perturbation adapter.

- [ ] Run 20 nominal episodes of one preselected supported task using a fixed recorded seed list. Treat this as a pilot, not a paper-level reproduction.
- [ ] Record success, failure, timeout, infrastructure error, episode length, and wall-clock time separately.
- [ ] Use at least 16 successes out of 20 as an engineering gate for a useful first task. Report the actual count; this threshold is a project choice, not a claim of general model capability.
- [ ] If the gate fails, diagnose the setup. If choosing a different task, record the original results and the selection rule to avoid hiding unfavorable evidence.
- [x] Choose the first perturbation surface with the user. The accepted first family is a normalized opaque rectangle on the global `agentview`, preserving wrist input, robot state, physics, and success predicate. Camera pose and lighting remain later families.
- [x] Document the exact observation transform and nominal-restoration behavior. The fixed sweep remains the next design gate before adaptive search.
- [x] Save a concrete follow-on implementation plan using the inspected API. `docs/superpowers/plans/2026-09-13-global-scene-occlusion.md` covers the adapter, tests, cloud compatibility run, and infrastructure-error separation.

**Gate:** we understand a working policy/task combination, have baseline timing, and know the API needed for one controlled change.

#### NEXT STEP — accepted combined cloud session

The accepted two-attempt, **US$2 aggregate** session ended as infrastructure
only and does not satisfy this sequence. Before a new paid run, first prove
SSH/VM connectivity without starting the model or evaluator, then obtain a
fresh cap decision for this sequence:

- [ ] Complete a 20-episode nominal baseline across different initial states.
- [ ] Sweep centered-square occlusion severity from 6.25% toward 25% image area.
- [ ] Replay the first apparent failure five times before classifying it as a
   reproducible perturbation-induced failure.

The nominal sample estimates whether the selected task is naturally flaky.
The one-dimensional centered-square sweep then isolates an occlusion severity
threshold that can seed the later reducer. A position-grid sweep would map
spatial sensitivity better, but is deferred because it does not establish a
clean first severity threshold as efficiently. Keep infrastructure errors out
of both policy-failure and replay counts.

## 6. Implementation roadmap after the startup gates

Each milestone produces working software; avoid opening all subsystems at once. The file map above defines ownership, while the code-level steps are written after Task 5 resolves the runtime interfaces.

| Milestone | Work | Evidence required before moving on |
| --- | --- | --- |
| M1: reproducible runner | Wrap upstream execution; record configs and outcomes; save failure video | Nominal episode runs and replays; timeout/crash classified distinctly |
| M2: first failure | Apply one bounded perturbation family; run a fixed sweep | Nominal/perturbed paired attempts and a failure that repeats |
| M3: useful parallelism | Profile; use upstream worker sharding and batching where supported | Equal-work sequential vs parallel results, memory use, and speedup |
| M4: failure reducer | Remove factors, then reduce their magnitude under a fixed retry budget | Smaller case retains the same defined failure; nominal restoration checked |
| M5: diagnostic report | Show case, measured violation, original/reduced videos, replay recipe | Another session reproduces the report's case from saved artifacts |
| M6: stronger experiments | Add a second perturbation family and two related tasks | Held-out evaluation, budget-matched baselines, uncertainty reported |
| M7: submission | Package reproducible cloud run, public release, video and feedback | Fresh setup succeeds; submitted artifact versions are frozen |

### Current roadmap position — September 16

We have completed **M1: reproducible runner** and the engineering gate for
**M2: first failure** on one exact case:

- The runner, structured evidence, replay control, first perturbation adapter,
  and viewer are implemented locally and tested.
- The September 15 bounded session established a 20/20 nominal result and saved
  videos and traces for every nominal and perturbed attempt.
- The runner, structured evidence, first perturbation adapter, replay control,
  and viewer are now exercised end to end on Nebius.
- The upper-right 25%-area cell failed in discovery and 5/5 exact replays;
  the nominal sentinel and 5/5 fresh nominal controls succeeded.
- M2 and M4 are complete for this narrow experiment contract. The September 27
  M4 run certified a 14.0625%-area mask and exhausted its 12 candidate attempts;
  see [M4 evidence](../../experiments/m4-reducer.md).
- M3 has not started. Its equal-work 1/2/4-worker comparison should accelerate
  this real diagnostic workload, subject to a new topology and spending gate.

### Immediate decision after the bounded session

Interpret the raw counts, timings, and cost with Jethro before choosing the next
implementation plan. Follow the branch supported by the evidence:

| Bounded-session result | Immediate next work |
| --- | --- |
| Reproducible perturbed failure and valid nominal gate | Design the bounded failure reducer (M4) next, then use that real search-and-reduction workload for the M3 sequential-versus-parallel comparison. |
| Apparent failure does not repeat | Diagnose stochasticity and strengthen repeatability controls or failure classification before claiming M2. |
| No failure through 25% centered occlusion | Decide whether to expand severity/position coverage or approve a second perturbation family; do not silently enlarge the search space. |
| Nominal gate fails | Stabilize the benchmark, seeds, or failure definition before further perturbation search. |
| Infrastructure invalidates the session | Repair the execution path and rerun the same bounded design; do not count infrastructure errors as policy evidence. |

The recommended happy-path order is **reducer before parallel scaling**. It
gives the HPC experiment a meaningful end-to-end workload to accelerate instead
of benchmarking arbitrary episode throughput. The reducer algorithm, parallel
worker topology, any new perturbation family, and any higher spending cap remain
separate user decisions.

### Record contract

Every episode record must contain:

- Experiment ID, scenario ID, attempt ID, and parent case if reduced.
- Task ID and instruction; full initial scene state where export is supported.
- Model/checkpoint revision, runner commit, environment/container version, and configuration hash.
- Seed, perturbation parameters, action horizon, and action-chunk settings.
- Outcome: `success`, `task_failure`, `episode_timeout`, `infrastructure_error`, or `invalid_scenario`.
- Timing fields with units; startup and steady-state inference separated.
- Video/trace locations and the exact replay invocation.

The same scenario may have multiple attempts. Preserve all attempts; do not overwrite earlier failures with later successful retries. Retry infrastructure errors at most once automatically during the pilot and retain both records.

### First meaningful failure

Use matched nominal and perturbed initial states/seeds. Repeat a candidate case five times as an engineering screen; label the observed failure fraction rather than calling it deterministic. A practical first demonstration target is four failures in five perturbed attempts with four successes in five matched nominal attempts. Later report more repetitions and intervals; five attempts do not support strong statistical claims.

An invalid initial scene or unavailable model server is not a robot-policy failure. Camera variations must preserve usable target visibility for the chosen test contract; record intentionally unobservable cases separately.

### HPC experiment

Start with 1, 2, and 4 workers on the same allocated resource. Use the same finite scenario list, model, horizon, simulation timestep, and inference semantics.

Measure:

```text
throughput = completed valid episodes / wall-clock hour
speedup(n) = sequential wall time / n-worker wall time
parallel efficiency(n) = speedup(n) / n
cost per valid episode = allocated compute and related run cost / valid episodes
```

Also record peak GPU memory, CPU use, inference latency, and time in rendering, simulation, queues, and serialization. Include an end-to-end result with startup/download costs and a separate warm steady-state result.

Keep policy state and buffered action chunks isolated per episode. Check the same fixed cases for outcome drift after batching. If the simulator advances while inference waits, batching changes control latency and may alter the experiment; use fixed stepping initially and explicitly label any later real-time mode.

If more workers slow the system or exhaust memory, report that result and address the measured bottleneck. Multi-node execution is a stretch goal, not a prerequisite for substantive HPC work.

### Reduction experiment

Use greedy factor removal followed by bounded magnitude reduction. Do not assume failure is monotonic in camera displacement; a simple binary search can miss disconnected failure regions. Keep the tested sequence and stop at an explicit attempt budget.

Define case size as active-factor count first, then normalized perturbation magnitude. Keep a reduction only when it preserves the selected failure category under the chosen repeated-trial rule. Call the output a reduced counterexample, not a globally minimal or causally proven explanation.

Reserve fresh seeds for confirming selected cases. Adaptive-search samples must not be presented as an unbiased population success-rate estimate.

## 7. Research and product boundary

Existing benchmarks and harnesses already cover perturbations and parallel evaluation. Our proposed contribution is the workflow from a valid failure to a reduced, replayable engineering report, plus measured compute efficiency. This is a contribution hypothesis, not an established novelty claim.

The first version explains measured conditions and outcomes. Automated root-cause claims require stronger intervention evidence. A language model can later help propose tests or summarize records, but a generated story must not become the failure oracle.

Formal methods can inform explicit test contracts. TLA+ modeling of coordinator retries is optional after M5; SMT integration is not part of the initial schedule.

## 8. Schedule and scope controls

Assuming work begins around September 12:

| Period | Target |
| --- | --- |
| Sep 12–18 | Startup gates, nominal robot episode, resource decision |
| Sep 19–25 | First perturbation, failure replay, thin runner |
| Sep 26–Oct 2 | Profiling and one-GPU parallel evaluation |
| Oct 3–9 | M3 interpretation and product-flow work; M4 reduction completed September 27 |
| Oct 10–16 | Held-out experiments and related tasks |
| Oct 17–23 | Reproducibility, documentation, demo draft |
| Oct 24–29 | Freeze, public release, final video and submission |

These are target weeks; access delays consume the buffer. If no real policy episode runs in week one, focus on compatibility rather than UI. If behind after M3, finish a strong one-task diagnosis demo before adding tasks. If adaptive search adds little, keep the measured random-search baseline and improve replay/reduction.

## 9. Submission checklist

- [ ] Record substantive NVIDIA model usage and Nebius execution with exact model and job identifiers, excluding secrets.
- [ ] Complete the required tool feedback using [FEEDBACK.md](../../../FEEDBACK.md): what each actually used Nebius/NVIDIA tool did, zero-to-hello-world experience, precise strengths/friction, and whether Jethro would build with it again. Do not imply Token Factory was used unless its pilot runs.
- [ ] Recheck official Physical AI requirements before finalizing the submission.
- [ ] Prepare a public judge-runnable repository: visible Apache-2.0 license, attribution/third-party rights, pinned setup and sample-artifact access, one verified smoke-test path, and a tracked-file/history secret scan before visibility changes.
- [ ] Pick a human project name and draft a sub-three-minute pitch, not a tutorial: problem and user, nominal robot, reproducible failure, reduction, M3 cost/performance evidence, and honest limits.
- [ ] Record at least one minute of operating simulator and key viewer modules (the official no-physical-hardware alternative); narrate Nebius AI Cloud and NVIDIA GR00T explicitly and list them under Built With.
- [ ] Upload a public YouTube demo only after checking media rights and that the video matches the runnable build.
- [ ] Explain limitations: simulation only, selected task/policy coverage, empirical evidence rather than safety certification.
- [ ] Preserve a test build and required artifacts for judging through December 15; continuous GPU uptime is not assumed necessary.
- [ ] Submit by the October 30 Pacific deadline, equivalent to October 31 at 01:00 Singapore time; target October 29 to leave a buffer.

See [official rules](https://nebiusglobalaihackathon.devpost.com/rules). Publishing, paid compute, and model-license acceptance are separate actions from writing this plan.

## 10. The next working session

M2 and the bounded M4 live reduction are complete for one named policy, task,
initial state, and visual-occlusion family. The next material step is to review
an M3 equal-work 1/2/4-worker design around the recorded reduction workload.
No M3 worker topology or paid cap is authorized yet. Tool feedback is now
tracked in [FEEDBACK.md](../../../FEEDBACK.md). The video pitch and judge-run
public repository audit are explicit submission gates after M3, as Jethro
requested.

The parallel sample check found no external file in this repository. Upstream
LIBERO HDF5 does contain actions, observations, simulator states, model XML,
task/BDDL and reset metadata, so the proposed adapter remains promising. The
next unbilled import task is metadata-only inspection of one rights-compatible
sample, followed by a local restoration check. This does **not** authorize
changing grid inputs or implementing the importer. Nemotron API feasibility is
a later product step, separate from GR00T's current robot runs.
