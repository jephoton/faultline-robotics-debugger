# ADR 0003: Use temporary public SSH access for the first cloud pilot

**Status:** accepted on September 13, 2026

## Context

The first bounded Nebius experiment needs a simple way to install the pinned
evaluation stack, observe logs, copy recordings back, and tear down promptly.
The project has a small initial-account budget, so spending time and compute on
a jump host or private network overlay would not improve the robot baseline.

The model server never needs to be reachable from the internet: the evaluator
and model server run on the same VM and communicate over loopback.

## Decision

Use one temporary public IP only for SSH and `scp` during the first 8-hour
pilot. Create a project-specific SSH key locally, do not commit it, and use the
public key only in the VM's initial configuration. Do not expose the model
server, notebook server, simulator, or any other application port publicly.

Before teardown, copy selected logs, configuration, and recordings to the
workstation. Then delete the VM and its managed boot disk, and confirm that no
unmanaged disks remain.

## Alternatives considered

| Option | Benefit | Cost for this pilot |
| --- | --- | --- |
| Temporary public SSH IP | Fast install, log access, and artifact copy | Requires narrow operational discipline and deletion afterward |
| Private subnet plus jump host/WireGuard | Stronger network isolation | Adds an extra VM/service, setup work, and failure modes before one episode exists |

## Consequences

This decision is suitable only for the bounded pilot. A longer-running or
multi-user deployment should move to private access. The project-specific key
is disposable: remove its local private and public files after the pilot if no
follow-up run needs them.
