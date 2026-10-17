# Faultline project handoff

> Generated architecture summary. Read `STATE.md` for the current checkpoint,
> `RUNBOOK.md` for operations and `docs/decisions/` for accepted decisions.

## Product and evidence boundary

Faultline turns a simulated robot-policy failure into a small, repeatable,
replayable case within a fixed compute budget. The loop searches, confirms a
failure (at least four of five reruns while controls pass), reduces its
trigger, and stores the report, videos, spend ledger and case. Its contribution
is that integrated diagnostic loop, not a claim of universal coverage, causal
proof or formal verification. Reports must name the policy, LIBERO suite,
task, start, seed, perturbation family and tested range. See [ADR 0027](../decisions/0027-m7-product-consolidation-and-access.md)
and the [experiment notes](../experiments/).

The official name is Faultline and the canonical repository is
[`jephoton/faultline-robotics-debugger`](https://github.com/jephoton/faultline-robotics-debugger).
Keep the `robot_debug` package, schema/case IDs, environment variables,
historical artifact identities and local checkout folder unchanged. M3/HPC
scale-out is optional stretch work; preserve its measured replay-throughput
result without making further HPC work a product gate ([ADR 0019](../decisions/0019-faultline-name-and-hpc-scope.md)).

## Two user modes

1. **Debug a failing start (scenario):** screen benchmark starts, select a
   known failing start, or import a start-state file. Find a nearby passing
   reference, confirm the failure, and delta-debug the differences down to
   shifts needed together. Nemotron 3 Ultra proposes an ordering and a
   hypothesis before reruns; only simulator results establish the observed
   outcome. The demonstrated case is LIBERO-10 task 0, start 14.
2. **Audit a passing policy start:** search a specified family for a small
   disturbance that causes a repeatable failure. Eight image families (blur,
   noise, darken, contrast, JPEG compression, colour cast, motion blur and
   dead pixels) and two simulator scene families (viewpoint and lighting)
   use the threshold search. The language mode uses Nemotron 3 Super to
   generate instruction paraphrases and reduces a failing wording by word
   edits. The earlier camera-occlusion work is a historical M4–M6 path, not
   an audit-family option. See [ADR 0032](../decisions/0032-breadth-pack.md).

The tested policy is NVIDIA GR00T N1.7, with a pinned checkpoint for each of
LIBERO Object, 10, Spatial and Goal. The evaluator uses the AllenAI VLA
evaluation harness, robosuite/MuJoCo and a GR00T model server on one Nebius
L40S GPU per Serverless Job. A local NVIDIA GPU backend is implemented but
has not been validated on hardware. A checkpoint override can target a
different policy, but compatibility remains the operator's responsibility.

## Runtime map

- `faultline diagnose SPEC.yaml` is the local coordinator for both modes.
  `src/robot_debug/cli.py` and the diagnosis/orchestration modules validate
  the spec, reserve a bounded worst-case Job cost, drive search and reduction,
  store reports/cases, and manage stop/resume. The Nebius backend wraps the
  official CLI, submits finite Jobs, resubmits capacity failures within its
  bound, watches deadlines, downloads evidence from private Object Storage
  and cleans up temporary access. Local specs, ledgers, provider keys and
  optional LLM calls remain on the workstation. See [ADR 0031](../decisions/0031-faultline-diagnose.md).
- `faultline replay` reruns a saved **scenario** case against its minimal
  scene and passing reference, optionally with another checkpoint. Audit and
  paraphrase cases do not yet have this replay command. `faultline cases`
  lists registered cases.
- `web/` contains the React/Vite control panel. Its committed build lives in
  `src/robot_debug/viewer/app/` and is served by the Python loopback server
  through `faultline ui`. It shows runs, cases, Setup, diagnosis form/dry run,
  live progress and safe Stop/Resume/Replay controls. The browser controls
  call the same CLI workflow and require a session token and same-origin
  checks. `faultline export` makes a separate static gallery of finished
  cases with no provider calls or controls. It is a filtered publication
  artifact, not a live copy of the local server ([ADR 0033](../decisions/0033-control-panel-ui.md)).
- Nemotron 3 Ultra writes pre-rerun scenario hypotheses and explanations of
  verified scenario and historical occlusion cases. Nemotron 3 Super writes
  paraphrases; Nemotron 3 Nano summarizes related research. Audit and
  paraphrase cases have no generated explanations yet. Model text is marked
  as interpretation and validated against recorded evidence, never used as
  the success oracle ([ADR 0030](../decisions/0030-nemotron-model-per-task.md)).
- `scripts/research_case.py` is an optional, manual Tavily workflow used on
  historical occlusion cases only. Source-linked research is context, not
  evidence for a robot-policy result; it has not been run on the newer
  scenario, audit or paraphrase cases.

`configs/specs/` holds portable example specs. `artifacts/` holds ignored
local run data and private provider details; `demo/root/` holds one safe,
finished diagnosis viewable without cloud access. `docs/experiments/` records
evidence and claim limits; `FEEDBACK.md` records actual tool experience.

## Operating boundaries

Every paid run needs an approved per-run cap, fresh authentication, account,
balance/expiry, quota/capacity and price checks. Keep Nebius account/project
boundaries in run records and one owner for cloud lifecycle and spending. The
original US$75 overall credit envelope remains a planning ceiling until
Jethro changes it. Cost estimates based on container time and assumed
Serverless billing are not reconciled posted bills. Cloud architecture,
new model/simulator or perturbation choices, higher caps, public publication
and submission claims are Jethro's decisions. Never commit credentials,
private resource identifiers, secret-bearing logs or model weights. Original
project code remains under the MIT licence; external assets retain their own
terms (`NOTICE.md`).
