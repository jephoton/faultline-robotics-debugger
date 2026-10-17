# Faultline project handoff

> Generated handoff entry point. The canonical system description is now
> [docs/architecture.md](../architecture.md); do not maintain a competing
> full architecture here.

## Start here

- [Architecture](../architecture.md): plain-language terms, two product modes
  versus three execution paths, full-system and user-journey diagrams, model
  roles, UI fields/actions/evidence and known capability/clarity limits.
- [Current state](STATE.md): verified project position, active proposals,
  next actions and gates. Old run caps in the historical archive are not
  current authority.
- [Runbook](RUNBOOK.md): setup, diagnosis, recovery, replay, export and
  verification commands.
- [UI user runbook](../ui-runbook.md): click-by-click saved-case walkthrough
  and recipes for users, separate from setup and architecture reference.
- [Accepted decisions](../decisions/): rationale and scope; in particular
  [ADR 0027](../decisions/0027-m7-product-consolidation-and-access.md),
  [ADR 0032](../decisions/0032-breadth-pack.md) and
  [ADR 0033](../decisions/0033-control-panel-ui.md).
- [Results/document index](../README.md),
  [roadmap](../../PROJECT_PLAN.md) and [tool feedback](../../FEEDBACK.md).

## Stable boundaries

Faultline finds, confirms and reduces simulated robot-policy failures within
a bounded compute budget, then saves the evidence for inspection/regression
testing. Mode 1 debugs a failing scene; Mode 2 audits policy robustness through
visual/scene or instruction-wording tests. The UI currently exposes three
execution paths, not a two-card intent hierarchy. Regrouping remains proposed.

NVIDIA GR00T operates the simulated robot; LIBERO checks success. Nemotron
proposes/interprets and does not decide the measured verdict. Scenario Replay
is supported; audit/paraphrase Replay is not. Local controls can start paid
Jobs after confirmation; the public gallery is a separate read-only export.

Keep `robot_debug`, historical identities and the local checkout name intact.
Further M3/HPC is optional stretch. No global-minimality, universal-coverage,
causal-proof or formal-verification claim follows from a reduced case.
New paid work/publication requires its own authorization and checks. The
US$75 cloud-credit planning ceiling remains until Jethro changes it; the
GPU ledger is not an all-services bill. Never commit secrets or private
infrastructure data. Original code is MIT; see `NOTICE.md` for external terms.
