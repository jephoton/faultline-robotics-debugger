# Project collaboration instructions

## Product name and core scope (October 8, 2026)

- The official product name is **Faultline**, not a provisional/KIV name.
- Preserve `robot_debug` imports, schema/case IDs, environment variables,
  historical resource identities and artifact paths when updating branding.
  Folder and GitHub repository renames require separate user direction.
- Further M3/HPC work, including batched inference, portfolio scheduling and
  scale-out, is optional stretch work. Jethro may pursue deeper HPC exploration
  in another project. Retain the measured replay-throughput result, but do not
  make new HPC implementation or claims a core Faultline/submission gate.
- The core remains robotics failure discovery, confirmation, reduction,
  inspection and replay; this does not approve a formal-verification feature.
  See `docs/decisions/0019-faultline-name-and-hpc-scope.md`.

These preferences were explicitly provided by Jethro on September 12, 2026. Apply them throughout this project.

## Resources and credentials

- Cloud compute is included among the project's main available hackathon resources, as confirmed by the user. Plan around using it; do not assume only inference credits are available.
- When cloud access is actually needed, ask the user again to configure credentials or sign in. Prefer local CLI authentication or a local secret store rather than pasting secrets into chat.
- Never commit credentials, access tokens, private keys, or secret-bearing logs.
- Confirm the accessible project, region, GPU quota, credit balance/expiry, and allocation limits at setup time. Resource availability does not authorize unlimited spending or provisioning arbitrary resources.

## Cloud budget and account isolation (September 13, 2026)

- The total intended Nebius-credit envelope for this project is **US$75**. Treat it as a hard planning ceiling until Jethro changes it explicitly.
- The account currently authenticated in the local Nebius CLI has an initial US$25 balance. Use it for the first bounded baseline and integration runs; do not deliberately burn credit merely to exhaust it.
- The intended main account will have US$50 available: US$25 from its required initial balance plus US$25 from the hackathon promo code. Reserve it for the perturbation, reduction, parallel-evaluation, and demo work.
- Nebius projects cannot be moved between tenants or regions. When changing accounts, create or select a separate project and local CLI profile, reuse this Git repository, and preserve the account boundary in run records.
- Before any billable provisioning, verify the chosen account is active, the actual credit balance/expiry and GPU quota, the live selected-resource price, storage charges, capacity, and the run-specific cap. Use one GPU and one active worker for the first pilot, then tear down compute and any unneeded persistent resources promptly.

## Frequent conventional commits

- Commit often, after each small coherent unit of completed and appropriately checked work. Do not wait until the entire feature is finished.
- Use Conventional Commits: `docs: explain baseline setup`, `feat(runner): record episode outcomes`, `fix(replay): preserve initial state`, `test(search): cover exhausted budgets`, or `chore: pin evaluation dependencies`.
- Stage explicit related paths. Preserve unrelated user changes and never include secrets or large experiment artifacts.
- Run checks proportionate to the change before committing. Report material limitations honestly.
- Commit frequency does not imply rewriting history or automatically publishing unreviewed changes.

## User-led architecture and design

- Hand most architectural and design decisions to the user before implementing the selected approach. Learning HPC and robotics is a central project goal.
- Treat technologies and architecture in existing plans as proposals unless the user has explicitly accepted them. Choosing failure diagnosis does not approve every suggested library or deployment topology.
- Decision examples: model/benchmark pairing, simulator, cloud resource shape, worker topology, batching strategy, data schema and persistence, failure definitions, search/reduction algorithms, and interface design.
- For each material decision, explain the problem in plain language, give two or three practical options, describe tradeoffs and what the user would learn, and recommend one with evidence. Identify reversibility and the next experiment that would reduce uncertainty.
- Ask a focused question and wait for the user's choice before dependent implementation. Continue independent read-only research or already-approved work while waiting.
- Handle routine implementation details autonomously within approved decisions; do not ask about every variable name, formatting choice, or minor helper function.
- Record accepted decisions and their rationale in `docs/decisions/`. Mark proposed, accepted, and superseded status explicitly. Do not repeatedly ask about settled decisions unless new evidence materially changes the tradeoff.

## Product differentiator and claim boundary

- Preserve this core positioning: find a robot-policy failure within a fixed compute budget, confirm that it repeats, minimize its triggering condition, and save it as a replayable regression test.
- Existing VLA harnesses already provide evaluation, perturbation suites already test robustness, and prior falsification systems already search simulations. Do not present occlusion, episode sharding, batching, or parallelism alone as this project's novelty.
- The intended contribution is the integrated diagnostic loop—search, repeatability control, counterexample reduction, replay, and GPU time/cost measurement—specialized to modern VLA manipulation policies.
- Measure the differentiator against explicit baselines such as grid or random search using time to first apparent failure, time to first reproducible failure, time/cost to a reduced failure, and final perturbation size.
- Do not claim coverage of all possible failure modes, causal proof, or research novelty until experiments support it. State the tested perturbation family and search space explicitly.

## Hackathon tool feedback

- Maintain the repository-root `FEEDBACK.md` as the submission's working log
  for Nebius AI Cloud, Token Factory, and NVIDIA models actually used.
- After a material tool interaction or experiment, add specific observed
  strengths, friction, onboarding steps, and whether the tool merits reuse.
  Attribute project setup mistakes and upstream-harness defects separately
  from provider behavior; link to the relevant experiment note when useful.
- Keep untested tools explicitly marked untested. Reconcile cost estimates
  against billing before making final claims, and ask Jethro for first-hand
  experience before submission. Do not record secrets, account IDs, or private
  infrastructure details in the log.

## Multi-agent development with human learning

Use **parallel work between learning checkpoints** as the default operating
model. Agents accelerate evidence gathering and implementation; Jethro retains
control over the questions, tradeoffs, budgets, and conclusions.

### When plans should use multiple agents

- Use multiple agents when at least two substantial tasks can proceed independently, such as upstream research, implementation, test construction, experiment-validity review, results analysis, or documentation.
- Keep tasks with tight sequential dependencies in one agent. Do not create agents merely to increase agent count or split a small change.
- Every multi-agent plan must include a dependency/concurrency map, exact task boundaries, file ownership, expected outputs, an integration owner, and review checkpoints.
- Avoid overlapping file ownership. Prefer isolated worktrees or branches when agents edit code concurrently; only the integration owner merges or resolves conflicts.
- Give a reviewing agent evidence and acceptance criteria rather than asking it to repeat the builder's implementation. Preserve disagreements and escalate material ones to Jethro with context.
- Use one execution owner for any shared or stateful external resource: Nebius lifecycle and spending, a live experiment, Git integration, artifact publication, or submission changes. Other agents may inspect, analyze, or prepare work without independently mutating that resource.

### Autonomy levels

Classify plan steps explicitly when the boundary may be unclear:

- **Green — autonomous:** reversible routine work inside an approved design, including tests, parsing, formatting, documentation maintenance, local analysis, and small implementation fixes. Proceed and report evidence.
- **Amber — explain and execute within the accepted boundary:** implementation structure, worker allocation inside an approved experiment, retry policy, metric calculation, or another choice that affects results without changing the project's goal or authorized cap. Explain the choice and rationale at the next checkpoint. Stop first if new evidence turns it into a material architecture, experiment, or cost decision.
- **Red — Jethro decides before dependent execution:** model or simulator changes, new perturbation families, failure definitions, search/reduction algorithms, cloud architecture, increases to a spending cap, destructive actions, public publishing, and claims used in the submission.

Existing approval persists. Do not repeatedly ask about a red decision that
Jethro has already accepted unless scope changes or new evidence materially
changes its tradeoff.

### Learning checkpoints

Place a checkpoint before a new red decision and after a meaningful parallel
work batch. Present enough context for Jethro to learn and decide, answering:

1. What problem are we solving?
2. What alternatives were considered?
3. Why is the recommended approach appropriate here?
4. What evidence would cause us to change direction?

After agents finish a batch, the coordinating agent must synthesize their work
into decisions, evidence, unresolved disagreements, cost implications, and the
next question. Do not make Jethro reconstruct the result from individual agent
logs. For experiments, invite Jethro to predict or interpret the result before
turning it into a project claim; then compare that interpretation with the raw
evidence.

The preferred project loop is:

```text
human question or material decision
    → bounded parallel agent work
    → independent review
    → coordinated evidence summary
    → human interpretation or next decision
    → autonomous execution within the accepted boundary
```

## Plan-first model handoff

For every new material project step, separate design reasoning from routine
execution so Jethro can learn from the decision without paying the strongest
model's token cost for mechanical implementation.

1. Use the stronger currently selected model to inspect evidence, explain the
   decision, settle red choices with Jethro, and write a committed implementation
   plan under `docs/superpowers/plans/`.
2. Make the plan self-contained: include exact scope, files, tests, conventional
   commit boundaries, autonomy levels, agent ownership, review checkpoints, and
   any cloud or spending gate. Do not start billable work merely because the plan
   exists.
3. After Jethro approves the design and plan, hand green and bounded amber
   implementation to a smaller capable model by default. Prefer a balanced
   implementation model such as `gpt-5.6-terra` at medium reasoning when it is
   available. The stronger-model coordinator remains the integration owner and
   synthesizes reviews and learning checkpoints.
4. If the product cannot change the active task's model directly, use a
   smaller-model sub-agent for the implementation handoff or pause and tell
   Jethro exactly what model change is needed. Never imply that the active model
   was changed when it was not.
5. Escalate back to a stronger model when evidence exposes a new red decision,
   experiment-validity ambiguity, architectural conflict, difficult live-system
   debugging, or repeated implementation failure. Routine test failures and
   plan-conforming fixes stay with the smaller model first.

This handoff is automatic after an already approved plan; do not repeatedly ask
whether to downscale. It does not override user review gates, cloud caps, the
single external-resource owner rule, or verification before integration.
