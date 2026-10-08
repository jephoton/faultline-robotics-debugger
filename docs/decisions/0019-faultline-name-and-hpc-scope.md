# ADR 0019: Faultline branding and optional HPC scope

**Status:** Accepted by Jethro on October 8, 2026.

## Decision

The product is named **Faultline**: turn robot failures into replayable tests.
Update current product titles, viewer branding, package metadata and handoff
references. Naming is no longer provisional or a pending brainstorming task.

Retain the validated M3 fixed-replay result. Further HPC work, including
batched inference, portfolio scheduling, scale-out and adaptive optimization,
is optional stretch work, not a core product or submission gate. Jethro's
initial HPC exploration interest may instead be pursued in a separate project.
Faultline prioritizes robotics failure discovery, confirmation, reduction,
inspection and replay. No new formal-verification scope is approved here.

## Compatibility and publication boundary

Keep `robot_debug` Python imports, environment variables, schema/case identities,
historical resource names, artifact paths and original run provenance unchanged.
Add `faultline-viewer` while retaining `robot-debug-viewer` as a compatibility
alias. Set the local distribution name to `faultline`; this does not publish a
package or assert that its name is available on a public package registry.

The local directory and GitHub repository remain `nebius-nvidia-hackathon`.
Jethro asked for advice on those renames, not execution. Do not rewrite saved
paths or links to pretend the directory/repository has already moved. Repository
visibility, cloud resource names, third-party licenses and paid-run authority
are unchanged. Preserve historical decisions as history, marking superseded
naming statements explicitly rather than rewriting experiment evidence.

## October 8, 2026 repository-name amendment

Jethro subsequently authorized renaming the GitHub repository to
`jephoton/faultline-robotics-debugger`. This amendment supersedes the earlier
repository-name restriction above, while preserving it as historical context.
It does not authorize renaming the local `nebius-nvidia-hackathon` checkout
folder, rewriting `robot_debug` imports or historical identities, changing
repository visibility, publishing artifacts, or spending cloud credits.
