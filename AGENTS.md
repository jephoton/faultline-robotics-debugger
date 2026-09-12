# Project collaboration instructions

These preferences were explicitly provided by Jethro on September 12, 2026. Apply them throughout this project.

## Resources and credentials

- Cloud compute is included among the project's main available hackathon resources, as confirmed by the user. Plan around using it; do not assume only inference credits are available.
- When cloud access is actually needed, ask the user again to configure credentials or sign in. Prefer local CLI authentication or a local secret store rather than pasting secrets into chat.
- Never commit credentials, access tokens, private keys, or secret-bearing logs.
- Confirm the accessible project, region, GPU quota, credit balance/expiry, and allocation limits at setup time. Resource availability does not authorize unlimited spending or provisioning arbitrary resources.

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
