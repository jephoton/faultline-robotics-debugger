# Plan: showcase cleanup, polish pass and workflow evidence (October 19, 2026)

**Status:** approved by Jethro on October 19, 2026.

## A. Polish pass (green; one Sonnet agent, worktree)

These were found on the showcase runs. Each fix is a small, separate commit.
No cloud use, and no simulator image change.

1. **Report title.** A pipeline audit case's report is titled "M6 results:
   camera reliance and scalar image families". Title pipeline audit cases
   "Stress test: <suite> task <t>, start <n>", and keep the legacy title for
   old M6 runs. Re-register `FL-A-D582` locally so its report updates; its
   case id must not change.
2. **Duplicate citation.** The research summary repeats a citation
   ("[S1] [S1]"). Collapse adjacent duplicate citation markers where the
   summary is written, and defensively where it is shown.
3. **Route log for a passing start.** The log says "the start does not fail
   reliably: trying the chosen probes" when the start passed 5 of 5. Say "the
   start passed untouched: probing the chosen families". Keep a separate text
   for a start that failed some attempts (the flaky route).
4. **Replay run names.** These come out as
   `replay-object-start0---stress-test`. Collapse repeated separators in the
   slug.
5. **Form name.** The New diagnosis form's Name does not follow Suite, Task
   or Start changes. Derive the default from them (for example
   `l10-t0-start14`) until the person types their own name.
6. **Review probe-branch text.** It still says "A start that is flaky
   untouched is reported as that, and rewordings are skipped". Match the
   current behaviour:
   - a check that finds the start flaky ends the run;
   - a probe control that fails skips the probes still to come.
7. **Checkpoint on audit cases.** Audit cases record no checkpoint, so their
   replays show "checkpoint not recorded". Record the suite's pinned
   checkpoint (id and revision) in pipeline audit and wording cases. A replay
   with no override records the checkpoint it used. Re-register `FL-A-D582`;
   its case id must not change.

**Owner:** the polish agent owns `src/robot_debug/**`, `scripts/**`,
`web/src/components/**` and `web/src/lib/**`, plus their tests. It does not
edit `docs/` or `README.md`; it reports every user-visible string it changes.

## B. Showcase cleanup (coordinator, after run 2's case exists)

The gallery cases leaving are:
- `FL-S-AFB5`, replaced by run 2's layout case;
- `FL-A-08D3` and `FL-A-A70E`;
- the September occlusion case `FL-M-52D8`.

The wording cases (`FL-L-*`) were never in the gallery.

- **Remove** mentions of these cases from the product and demo surface:
  - `README.md`, `NOTICE.md` and `demo/README.md`;
  - `docs/reference.md`, `docs/ui-runbook.md` and `docs/architecture.md`;
  - comments in `configs/specs/*.yaml`;
  - user-facing strings in `web/src` and `src/robot_debug/viewer`.
- **Keep** historical records:
  - `docs/experiments/`, `docs/decisions/` and `docs/superpowers/`;
  - the `docs/codex-handoff/` state and history files;
  - `FEEDBACK.md`;
  - test fixtures.
- **README results** keep the project's measured findings as text, linked to
  the experiment notes, without case codes.
- **Code** that supports the older kinds (occlusion, wording) stays, because
  the local library still holds those cases. Only special-cased names and
  examples go.
- **Bundled demo** (`demo/root`): replace the October 13 recording with run 2's
  case, after inspecting its payload.

## C. Evidence of the team workflow (research agent, read-only)

Find public, citable material showing how teams evaluating on LIBERO see
failing episodes by task and episode (init-state) index, such as:
- evaluation scripts and their logs;
- rollout video file names;
- issue threads.

This shows how a team goes from "episode n failed" to a start number in
Faultline. Report links and short descriptions only. Never copy third-party
images or long text into the repository.
