# UI user runbook plan

> **For agentic workers:** Use subagent-driven-development for the bounded
> documentation handoff; the coordinator owns integration and verification.

**Goal:** Let a first-time reader use Faultline by following concrete UI
scenarios without understanding the implementation or reading setup docs.

**Architecture:** Add `docs/ui-runbook.md` as the task-based user guide. Keep
`docs/architecture.md` for system explanations and the existing operator
runbook for setup/CLI/recovery commands. Link them without duplicating them.

**Tech Stack:** Markdown and inspection of the existing React UI; no UI code,
build, model call, paid run or public deployment.

## Ownership and dependency map

```text
Coordinator commits scope and checks real labels / saved-case identity
  -> smaller-model writer owns only docs/ui-runbook.md
  || coordinator owns README, docs index, architecture and handoff links
  -> coordinator checks completeness -> independent source/clarity review
  -> link/diff/privacy validation -> documentation commit
```

All file work is Green documentation maintenance. The user asked for this
guide, not a new UI design or experiment; do not request another design gate.
Do not treat walkthrough examples or default form values as spending approval.

## Deliverables and acceptance

- [x] Start with a five-minute, zero-new-compute walkthrough of the saved soup
  failure: sidebar choice, three videos, reduction table, reruns, hypothesis
  versus evidence and interpretation. Include a compact demonstration route.
- [x] Add a choose-your-goal table with literal existing card labels. Include
  numbered recipes for known failing start, unknown-start screen, imported
  state, visual/scene stress test, rewordings and scenario replay. Every recipe
  states input, clicks, expected output, limitations and a safe stopping point.
- [x] Explain the shared review/start/progress workflow, cap versus all-service
  charges, Stop versus navigation, Resume versus new run and uncertain Start.
- [x] Add result interpretation and troubleshooting (no failure, control failure,
  incomplete reduction, missing video, absent Replay, stalled/expired run).
- [x] Writer self-checks labels against source. Coordinator checks spec coverage;
  independent reviewer checks usability and source accuracy. Validate relative
  links and `git diff --check`; confirm only documentation is staged.
- [x] Link from README, docs index, architecture and existing handoff/runbook.
  Commit as `docs(ui): add task-based user runbook`; no public redeploy.

**Done October 18:** restructured into the Tencent demo-runbook format
(Setup, nine demos with point, steps, expected output and talking point,
then result reading, recovery, reset and a video route). Expected values were
checked against the live API; an independent review checked labels and
behaviour against `web/src`. Product fixes found on the way: the replay cap
default and the audit wording for families a run never searched.
