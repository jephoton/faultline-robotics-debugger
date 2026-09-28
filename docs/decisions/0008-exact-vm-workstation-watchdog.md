# ADR 0008: Exact-VM workstation watchdog

**Status:** Accepted for implementation planning

**Date:** 2026-09-29

## Context

The guest runner and Docker can hang while the Nebius VM keeps billing. Local process-group and container checks cannot independently enforce a cloud spending deadline.

## Decision

Implement a detached Windows Python guard before any paid M3 start. It uses the locally authenticated Nebius CLI through WSL, an ignored record with one exact instance ID, project ID, and UTC deadline, and durable local logs. It verifies the target's parent project, stops only that exact instance at the deadline, and polls until `STOPPED`; ambiguous results remain unconfirmed. The guest shutdown timer and manual console access are backups. Implementation and dry-run approval do not authorize a live stop, VM start, or spending cap.

## Alternatives and consequences

A manual timer depends on attention; a guest-only timer shares the VM failure domain. A provider-native scheduled stop has not been verified for this account. The workstation guard is independent of the guest but still depends on Windows staying awake, network, WSL, and valid CLI authentication. Disk charges continue after VM stop.

See `docs/superpowers/specs/2026-09-29-m3-exact-vm-watchdog-design.md` and `docs/superpowers/plans/2026-09-29-m3-exact-vm-watchdog.md`.
