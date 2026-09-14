# Project collaboration instructions

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
