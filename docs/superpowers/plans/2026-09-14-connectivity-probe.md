# Observable Nebius Connectivity Probe

**Goal:** Prove the workstation-to-guest SSH path before another evaluation
run, while capturing enough evidence to distinguish firewall, routing, guest
boot, TCP, and authentication failures.

**Scope:** Start the existing stopped `robot-debug-pilot` VM once. Do not start
the model server, Docker evaluator, or an episode. Stop within five minutes of
the provider start request. Use the dedicated WSL key
`~/.ssh/nebius_robot_debug_2026` and a temporary TCP/22 rule restricted to the
current WSL egress `/32`.

## Evidence behind the probe

- Serial logs from both failed launches show cloud-init finishing in 13--14
  seconds and `ssh.socket` listening. The guest booted far enough to serve SSH.
- The VM's NIC has the security group containing the only TCP/22 ingress rule.
- The subnet uses provider-default routing and the VM uses a dynamic public IP.
- The current WSL egress address is outside the attached rule's source `/32`.
- The VM was provisioned with `~/.ssh/nebius_robot_debug_2026`. The later
  runbook selected a different Windows key, whose permissions WSL rejects.

The working hypothesis is: the stale `/32` caused the TCP timeout; after that
is corrected, the dedicated key is required for authentication.

## Cost boundary and ownership

One primary execution owner controls the VM, security rule, timers, evidence,
and shutdown. The live all-in 30-minute estimate is US$0.9626032, so five
minutes is approximately **US$0.1604339** including the existing 200 GiB disk
and Singapore GST. Use a **US$0.20 hard cap** for this probe. This is a new
spending-cap decision and must be approved before start.

## Procedure

1. Confirm the VM is `STOPPED`, the dedicated key exists with mode 600, the
   attached security group still contains the existing TCP/22 rule, and the
   local artifact directory is ignored.
2. Resolve the current public egress address from the same WSL namespace that
   will run SSH.
3. Create a second stateful allow rule in the attached group with the same
   protocol, port, and priority as the existing SSH rule, but with the current
   egress `/32`. Keep the original rule during the probe.
4. Record the start epoch, start the existing VM, and immediately create an
   independent stop watchdog for minute 4:30.
5. Stream `nebius compute instance logs --follow` into
   `artifacts/connectivity-diagnostics/serial-probe.log`. Save sanitized
   control-plane snapshots beside it without committing IDs or addresses.
6. Poll the VM state and public address. Once `RUNNING`, test TCP/22 every five
   seconds and record elapsed time plus `open`, `refused`, or `timeout`.
7. When TCP opens, run one verbose, non-interactive SSH command with the
   dedicated key. Save stderr locally, with public addresses and long key data
   redacted, and run only:

   ```bash
   ssh -vvv -o IdentitiesOnly=yes -o BatchMode=yes \
     -o ConnectTimeout=5 -o ConnectionAttempts=1 \
     -i "$HOME/.ssh/nebius_robot_debug_2026" "robot@${VM_HOST}" true
   ```

8. Stop immediately after SSH succeeds or after the first decisive failure.
   Confirm `STOPPED`, stop the serial-log follower, and remove only the
   temporary current-session SSH rule.

## Interpretation gate

| Evidence | Meaning | Next action |
| --- | --- | --- |
| Serial log never reaches `ssh.socket` | Guest boot/service fault | Diagnose boot image or ssh service before evaluation |
| Serial log listens; TCP times out | Security-group, propagation, or path fault | Inspect effective rule after propagation and provider networking |
| TCP is refused | Address reaches guest, but no listener at probe time | Correlate exact serial-log timestamp |
| TCP opens; SSH rejects public key | Authentication/config fault | Compare cloud-init key and requested identity |
| SSH command exits 0 | Connectivity gate passes | Remove temporary rule, then choose a separate evaluation cap |

The probe passes only when the exact non-interactive SSH command exits 0 and
the VM and temporary rule are both cleaned up afterward.
