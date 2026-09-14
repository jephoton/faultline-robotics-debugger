# ADR 0001: Preserve the upstream baseline and add a diagnostic trace

**Status:** accepted on September 12, 2026

## Context

The upstream LIBERO adapter already records an episode video and per-step
`reward`, `done`, and `success`. That is enough to establish whether a task
completed, but it cannot explain a failure: it omits the commanded action and
the robot state that produced it.

Replacing the evaluator before proving a clean baseline would confound model,
simulator, and debugging-tool failures.

## Decision

1. Run the unmodified one-episode baseline first.
2. After it works, add a thin `DiagnosticLIBERO` subclass rather than modify
   the policy or replace the evaluator.
3. The subclass will add serializable per-step commanded actions and
   end-effector/gripper state to the harness recording store, alongside the
   upstream video and outcome fields.
4. The first fault family will be policy-input perception faults: bounded
   camera occlusion, blur, brightness shift, and optional wrist-camera dropout.
   The simulator's ground-truth state remains unchanged.

Each generated case will also retain its task, instruction, initial-state
index, environment seed, fault specification, model/container revisions, and
replay command.

## Why perception faults first

They are controllable, reversible, and can be minimized into a small statement
such as “covering this part of the wrist image causes this task to fail.” They
also avoid early dependence on fragile MuJoCo scene editing. Action
delay/scaling and world/physics changes remain follow-on families once the
recording and replay path are proven.

## Consequences

The first clean baseline remains comparable with the standard harness. The
diagnostic extension creates a small amount of adapter code but does not
require model training or a second simulator. It will be tested with a nominal
restoration case so a disabled fault is observationally equivalent to the
baseline.
