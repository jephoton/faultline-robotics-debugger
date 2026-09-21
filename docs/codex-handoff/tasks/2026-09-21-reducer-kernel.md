# DeepSeek handoff: M4 pure reducer kernel

> Generated task handoff. Do not add credentials or unrelated user data.

## 1. Objective and user-visible outcome

Implement the deterministic, dependency-free kernel for shrinking a proven
robot-policy occlusion failure. Users will later see a smaller certified
rectangle and its lineage; this task only supplies geometry generation and the
adaptive repeatability decision.

## 2. Repository path

Canonical repository: `C:\Users\Jethro\Documents\nebius-nvidia-hackathon`.

## 3. Starting Git state

Starting commit: `fb8727d75875b670f4a96bdfe3d682962d49e34e`.
The implementation worktree starts at detached HEAD from that commit. Create a
single conventional commit in the worktree; do not create, switch, merge, or
publish branches.

## 4. Exact implementation worktree

`C:\Users\Jethro\.codex\worktrees\m4-reducer-kernel\nebius-nvidia-hackathon`

## 5. Architecture and current behavior

Read `docs/codex-handoff/PROJECT.md`, `docs/codex-handoff/STATE.md`,
`docs/superpowers/specs/2026-09-21-m4-bounded-failure-reducer-design.md`, and
Task 2 of `docs/superpowers/plans/2026-09-21-m4-bounded-failure-reducer.md`.
The repository already classifies completed episodes as `policy_failure` or
`success`, and excludes `infrastructure_error` from policy gates. No reducer
module currently exists.

## 6. In-scope files

Create and commit exactly:

- `src/robot_debug/reduce.py`
- `tests/test_reduce.py`

## 7. Forbidden scope and side effects

Do not edit any other file. Do not access the network, Nebius, Hugging Face,
secrets, credentials, experiment artifacts, or the viewer. Do not provision,
publish, push, merge, install dependencies, or alter Git configuration. Do not
implement evaluator orchestration, YAML generation, persistence, or UI.

## 8. Functional and non-functional requirements

- Use only the Python 3.11 standard library.
- Provide immutable `Rect` and `Candidate` dataclasses.
- Validate finite normalized geometry, positive dimensions/delta, and bounds.
- `candidates(parent, delta=...)` returns strict nested candidates in exact
  order `left`, `bottom`, `right`, `top`, omitting impossible removals.
- Provide `GateDecision` values `pending`, `pass`, and `reject`.
- `classify_attempts` accepts only `policy_failure` and `success`, passes at
  four failures, rejects at two successes, remains pending otherwise, and
  rejects more than five attempts.
- Keep the implementation deterministic, pure, documented, and independent of
  subprocesses, filesystem state, networking, and third-party packages.

## 9. Acceptance criteria

Tests must cover candidate order and exact geometry, strict nesting, area,
invalid/non-finite/out-of-bounds rectangles, invalid delta, impossible edge
removal, early pass, early reject, pending decisions, unknown outcomes, and the
five-attempt limit. All focused tests pass and only the two authorized files
appear in the implementation commit.

## 10. Verification commands and expected results

The September 21 retry is authorized after a diagnosed sandbox ACL mismatch.
The worktree now grants scoped modify permission to `BUILTIN\Users`; do not
change ACLs or Git configuration further. The sandbox cannot launch Jethro's
Windows Store Python 3.11 package, so use the bundled Python 3.12 interpreter
for the worker's red/green loop:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
& 'C:\Users\Jethro\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_reduce -v
```

The OpenAI coordinator will independently run the required Python 3.11 check
outside the sandbox before accepting the result:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
& 'C:\Windows\py.exe' -3.11 -m unittest tests.test_reduce -v
git diff --check
git status --short
```

Expected in both environments: every reducer test passes. `git diff --check` is
silent; before the commit only the two authorized paths are changed, and
afterward the worktree is clean at the new detached commit. For Git commands,
use per-process `GIT_CONFIG_COUNT` safe-directory environment entries; do not
persist configuration.

## 11. Required instructions and skills

Read completely before editing:

- repository `AGENTS.md`;
- `C:\Users\Jethro\.codex\skills\test-driven-development\SKILL.md`;
- the living documents, design, and Task 2 listed in section 5.

Follow test-first red/green/refactor and make one Conventional Commit named
`feat(reducer): add deterministic reduction kernel`.

## 12. Data sensitivity and provider routing

This task contains source code and public project design only. Do not seek or
emit authentication material, private experiment artifacts, user-home data
beyond the stated paths, or unrelated conversation. The authorized provider is
the external Codex profile `deepseek` using model `deepseek-flash`. Do not
change models or providers.

## 13. Attempt limit

Jethro authorized one fresh handoff after the original worktree-permission
failure was diagnosed and repaired. Within this fresh handoff, make no more
than two implementation attempts for the same code/test failure. A focused
test/fix cycle counts as one attempt when it addresses the same root failure.

## 14. Stop conditions

Stop and return control without broadening scope if an instruction conflicts,
an authorized file is insufficient, the baseline is unexpectedly broken, the
profile/model/API is unavailable, a test failure repeats twice, any external
access appears necessary, or the requested design is ambiguous.

## 15. Completion report

Report status (`DONE`, `DONE_WITH_CONCERNS`, or `BLOCKED`), exact files changed,
commit SHA, commands run, test counts/results, number of attempts, limitations,
and unresolved risks. Explicitly confirm whether only authorized files changed
and whether the worktree is clean.
