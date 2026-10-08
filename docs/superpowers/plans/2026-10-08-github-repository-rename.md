# Faultline GitHub Repository Rename Implementation Plan

**Goal:** Apply Jethro's approved `faultline-robotics-debugger` repository name,
without moving the local checkout or changing runtime/artifact identities.

**Architecture:** Rename the existing GitHub repository in place. Retain its
repository ID, owner, private visibility, history and branches. Update only
matching local remote URLs and current repository references.

**Tech Stack:** GitHub CLI, Git, Markdown; no cloud compute or provider calls.

## Ownership, checkpoints and boundaries

Root is the sole GitHub/configuration/Git integration owner. A smaller-model
documentation worker owns README.md, AGENTS.md, docs/codex-handoff/PROJECT.md,
STATE.md and RUNBOOK.md, and the supersession note in ADR 0019. Root owns this
plan. Independent reviewers read only; they must not change external state.
Concurrency: root rename/config verification || documentation preparation,
then spec review -> quality review -> root checks/commit/push.

The red naming/publication boundary is settled by Jethro's explicit request
to proceed with this exact repository rename. Preserve PRIVATE visibility.
Do not rename the local folder, worktree paths, Python imports, cloud resources,
or saved evidence. No package publication, paid work or experiment is included.

## Task 1 — root remote migration (approved amber)

- [ ] Verify `gh repo view jephoton/nebius-nvidia-hackathon --json
  nameWithOwner,id,isPrivate,viewerPermission`: expected ADMIN/private and ID
  `R_kgDOUXkIhg`; check destination does not already exist.
- [ ] Run `gh repo rename faultline-robotics-debugger --repo
  jephoton/nebius-nvidia-hackathon --yes` once; if interrupted, inspect both names
  and the immutable ID before retrying.
- [ ] Verify the new name retains the same ID and private visibility.
- [ ] Run `git remote set-url origin
  https://github.com/jephoton/faultline-robotics-debugger.git`.
  Inspect each registered worktree's effective fetch/push URLs; update only
  matching old-repository URL overrides, if any. Do not change other remotes.
- [ ] Run `git ls-remote origin refs/heads/main`; fetch/push configuration
  must resolve to the renamed repository without relying on the old redirect.

## Task 2 — smaller-model handoff docs (green)

- [ ] In README.md name/link the new repository; explicitly distinguish the
  unchanged local folder and `robot_debug` namespace.
- [ ] In AGENTS.md record the accepted repository slug and unchanged folder.
- [ ] Update current statements in PROJECT.md, STATE.md and RUNBOOK.md so
  they no longer say GitHub rename is unapproved or has not happened. Keep
  historical experiment paths and original branding-plan outcomes intact.
- [ ] Mark ADR 0019's repository-name boundary superseded by this approved
  rename, preserving its original historical decision and all other boundaries.
- [ ] Documentation worker runs `git diff --check` and reports owned files;
  root alone stages, commits and pushes.

## Task 3 — review and delivery (root)

- [ ] Independent spec review checks exact name, private visibility, unchanged
  local folder/import/artifact identities and truthful current handoff state.
- [ ] Independent quality review checks links, compatibility and history.
- [ ] Run `git diff --check`, audit remaining old-name references (only real
  local/historical paths are expected), and run the focused viewer/branding suite:
  `$env:PYTHONPATH='src'; C:/Windows/py.exe -3.11 -B -m unittest
  tests.test_faultline_branding tests.test_viewer_server -q`.
- [ ] Commit explicit documentation paths as
  `docs: record Faultline GitHub repository rename`, then push reviewed main
  commits with `git push origin main`. No force push or visibility change.
- [ ] Verify GitHub main SHA equals local HEAD, all effective remotes use the
  new URL, and the local viewer's `/api/health` and Faultline homepage still work.

## Commit boundaries

1. `docs: plan approved Faultline repository rename` (this plan only).
2. `docs: record Faultline GitHub repository rename` (reviewed documentation and
   completed plan). Remote configuration is local, not a tracked-file commit.
