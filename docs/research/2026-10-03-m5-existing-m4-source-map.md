# Existing M4 source mapping for M5A

Generated local metadata inspection, October 3. No new experiment or provider
interaction. This note prepares the next bounded case-I/O implementation plan;
it is not an implementation or evidence-certification result.

## Observed layout and fields

Selected source root contains `failure-reduction/session_summary.json`,
`failure-reduction/replay_case.json` and stage outputs under
`failure-reduction/runs/<stage>/`. Each stage has its own aggregate and media.
Operator logs exist separately and must not be copied into a public index.

The summary's completed stages record stage name, status, rectangle, physical
episode count and per-result outcome/episode index. Output/config fields refer
to the original execution environment. Do not follow arbitrary absolute paths
from these fields on the importing machine. The stage-name/local-layout mapping
must be constrained to the selected source root and checked for uniqueness.

The inspected aggregate exposes:

- `config.benchmark = robot_debug.libero:DiagnosticLIBEROBenchmark`;
- `config.params.suite = libero_object`, seeds 7/7;
- raw episode global task ID 0 and episode/reset index 0;
- enabled agent-view occlusion with normalized rectangle, opacity 1 and
  RGB color `[0, 0, 0]`;
- `server_info.model_server = LeRobotModelServer` and harness version metadata;
- a stage-specific `benchmark` value, not the suite name.

Normalize supported suite `libero_object` to case value `libero-object`.
The scalar fill value 0 represents equal RGB channels here; a colored or
transparent mask cannot silently become this opaque-gray rectangle family.
Use benchmark class for adapter identity, not the stage-specific benchmark name.

## Reconciliation work required after schema integration

1. Resolve each selected stage's unique contained aggregate via the known local
   layout; never execute embedded replay commands or follow remote paths.
2. Match stage/result identities to raw episodes and masks; preserve raw
   success/task-failure/timeout/infrastructure distinctions and compare the
   driver's normalized policy-failure outcome only via its existing rules.
3. Validate matching nominal controls independently of reduced-mask successes
   or failures. Missing and contradictory evidence are different states.
4. Establish the limits of policy identity: the aggregate's server class is
   not an exact checkpoint revision. Do not infer a historical checkpoint from
   the current checkout or a newly supplied runtime profile. Where evidence
   cannot establish a required identity, report `not-established`, not a
   fabricated confirmed badge. Existing experiment notes remain historical
   context rather than executable input or automatic certification.
5. Export only allowlisted normalized metadata and relative source references;
   no original command, operator logs, private infrastructure fields or videos
   are included by default.

The real saved source shape is now understood enough to write a bounded I/O
plan once the pure schema API is reviewed. It still does not demonstrate an
external HDF5 restoration path or a newly exercised replay.
