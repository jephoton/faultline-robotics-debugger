# Plan: the Replays section becomes a regression test (October 19, 2026)

**Status:** approved by the project owner on October 19, 2026 (option 1: a per-case
reframe; a suite-wide page was considered and left for later).

## Problem

Each case is meant to be a regression test (ADR 0034), but the case page's
**Replays** form is laid out in CLI-flag order:
1. "What do you expect?";
2. the spend cap and hour limit;
3. "A different checkpoint (optional)";
4. "Dry run the replay".

The field that matters most, which policy to test, looks optional. The
expectation only affects a script's exit code. The history rows do not say
which checkpoint was tested.

## Decisions

- The section is titled **Regression test**. It opens with one line on what it
  checks.
- The first choice is the **policy to test**:
  - **The original policy** (the case's checkpoint, shown as `id` at a short
    revision). This confirms the failure still repeats.
  - **A new checkpoint**: Hugging Face id plus revision. Both are needed; the
    backend rule is unchanged.
- **Cost:** one line with the worst case from the existing per-case dry-run
  suggestion. The spend cap and hour limit fold under a **Limits** disclosure,
  pre-filled as today.
- **Buttons:** **Estimate cost** (was "Dry run the replay") opens the existing
  review; its start button reads **Run the test**.
- **Expectation:** removed from the form. A muted line shows the script form:
  `faultline replay <case folder> --checkpoint … --expect fixed`. Use the CLI's
  real flags; check `cli.py`. If the CLI has no checkpoint flag, the line
  shows `--expect` only and says the checkpoint goes in the spec.
- **Results:** each history row names the checkpoint tested and whether it is
  the case's original, with these words:

  | Verdict | On a new checkpoint | On the original policy |
  | --- | --- | --- |
  | still reproduces / still fails | **Still fails** (red) | **Still fails** (red) |
  | no longer | **Fixed** (green) | **Did not repeat** (amber: the case may be flaky) |
  | anything else | **Inconclusive** (amber) | **Inconclusive** (amber) |

  A row without a recorded checkpoint (the October 15 replay) is treated as
  the original policy, with "(checkpoint not recorded)".
- **Static gallery:** history only, with the same words; no form.
- **Docs.** The Reference explains replay versus a New diagnosis:

  | | Regression test (replay) | New diagnosis |
  | --- | --- | --- |
  | Question | Is this known failure fixed, and does it stay fixed? | Where does this policy fail now? |
  | What runs | The pinned condition, 5 attempts | A fresh check and search |
  | Repeatable | yes | no |

  It also says that a fixed failure which comes back in a later checkpoint is
  what a regression test catches. The runbook's Demo 7 follows the new form.

## Scope and files (one implementation agent, worktree)

**Autonomy:** green or amber inside the decisions above. A new red question
(changing the backend's checkpoint rule, new routes) stops and reports.

1. `src/robot_debug/viewer/library.py`: replay rows gain
   `checkpoint: {id, revision} | null`, read from `replay-result.json`, and
   `original: bool | null`, which compares it with the case's checkpoint. The
   export carries the same fields. Add tests in the existing library/export
   test modules.
2. `web/src/api/types.ts`: `ReplayRow` gains the two optional fields; older
   exports lack them.
3. `web/src/components/case/CommonSections.tsx`: `replayLabel(verdict,
   original)` and `ReplayHistory` with the table above, plus a checkpoint
   line per row.
4. `web/src/components/case/ReplaySection.tsx`: the new title, purpose line,
   policy choice, cost line, Limits disclosure, buttons and CLI hint. Keep
   `showsReplay`, the per-case dry run and `StepReview`.
5. Tests: update `ReplaySection.test.tsx`, the CommonSections and case page
   tests, and `NewDiagnosisPage`/`CasePage` tests that match old wording.
6. `docs/reference.md`: section 1 "What a replay reruns" becomes the
   regression test, with the comparison table. Leave the stop reasons
   untouched.
7. `docs/ui-runbook.md`: Demo 7 and the "Read the result" notes. In
   `web/src/content/guide.tsx`, update any "Replays" wording.
8. Rebuild the bundle (`npm run build` from `web/`, LF line endings) and
   commit it with each web change.

**Checks before each commit:**
- Python: `PYTHONPATH=src python -m pytest -q` for the touched modules, and
  the full suite once at the end.
- Web: `npm run typecheck`, `npm test -- --run` and `npm run build`.

**Commits:** Conventional Commits, one logical change each: library field, web
section, docs. No AI co-author trailers.

**Out of scope:**
- a suite-wide "replay every case" page;
- any change to replay Jobs, the CLI's checkpoint rule or paid runs.

## Integration

The coordinator does the following:
- merges the branch;
- runs the full suites;
- checks the case page in the browser for a scenario case with a replay
  (`FL-S-AFB5`), an audit case without one, and the static export;
- scans the diff and pushes.
