# M5B narrow external-reset kernel

Status: Accepted local boundary, ADR 0016. This first implementation increment
provides a tested reader/resolver/restoration kernel; it does not yet modify
case capabilities, launch evaluators or claim external replay succeeded.

## Fixed scope and identities

Only acquired LIBERO Object task 0, `data/demo_0`, `states[0]`. Source SHA-256
`42189d4415d4c51aaaf0708300653fccc39239cd3f2709079a713cd8d1678a8d`,
size 780145352. State exactly 110 finite float64 values; little-endian hash
`5d4cd69032368d08d09453ef6ed4fa8c4ad697bf152d919eb673837274ba0df1`.
Task instruction, environment, Panda/OSC_POSE/20Hz and OpenGL metadata must
match the inspected sample. No selecting another task/demo/state through CLI.

New `external_reset.py` exposes `ExternalResetError(ValueError)` with fixed
safe messages; `read_external_reset(path: Path) -> dict`;
`validate_external_reset(value: dict) -> dict`;
`resolve_external_assets(xml: str, roots: dict) -> dict`;
`restore_external_reset(env, candidate: dict, resolved: dict) -> dict`.

Candidate exact keys: schema_version ordinary int 1, suite `libero_object`,
task_id ordinary int 0, demo `demo_0`, state_index ordinary int 0, source_sha256
fixed above, state_sha256 fixed above, state list of exactly110 finite ordinary
numbers (not Booleans), model_xml bounded UTF-8 text, model_xml_sha256, reset_id.
Canonical sorted compact finite UTF-8 JSON excluding reset_id determines
reset_id SHA-256. Validate XML and recompute every hash, detach input; errors
omit raw source paths/XML/HDF5 attributes. XML/state are local simulator input,
never sent to Token Factory. This kernel is intentionally sample-specific.

## Reader and dependency boundary

Reject nonregular or symlink/reparse paths/ancestors. Hash a bounded regular
file read-only in chunks, verify exact source size/hash, and compare stat
identity before/after HDF5 reads. Reject changes. Lazy-import h5py: no new
global dependency or pyproject change. Missing h5py gives a fixed prerequisite
error. Research venv supplies actual-sample acceptance; normal suite exercises
validation and injected fake HDF5 objects without requiring h5py.

Use only hard-linked data/demo_0/states; refuse virtual or external-storage
datasets before reading. Float64 states must be 2-D with 110 columns, at least
one row; read only first row. Bounded init_state attribute must equal it.
Bound attribute storage before reading; XML limit2MiB; metadata limit64KiB
each, strict UTF-8 and JSON (duplicate keys/nonfinite rejected). No image or
action array reads. Require robot/controller/control frequency/cameras/image
convention/task metadata checked in the research note. BDDL name must match
the known task, but never open the embedded path. Generating runtime version
is unknown and must remain unknown; candidate does not assert parity.

## XML and asset closure

Reject DTD/entity declarations, includes, non-mujoco root, over50000elements,
invalid encoding, empty/control-bearing file paths, arbitrary file attributes
outside mesh/texture/hfield, and compiler directory settings other than the
actual sample's `meshdir="meshes/"`. Remove that meshdir from the rewritten XML
once every asset file is an explicitly resolved absolute installed path;
reject other meshdir/texturedir settings. Parse using standard-library
ElementTree, no expansion.

Actual sample references 81 assets, from two explicit source namespaces:
`/chiliocosm/assets/` (18 references) and `/robosuite/models/assets/`
(63). Map the former to roots['libero'] and the latter to roots['robosuite'].
The old Chiliocosm namespace is an explicit source alias, not a basename
fallback or permission to open original absolute paths. Require exactly one
recognized marker per path. Normalize relative suffix components, allowing
the sample's `scenes/../textures` only while remaining within the selected root.
Reject escaping `..`, backslashes/control characters, other absolute suffixes,
URLs, ambiguous markers and unknown namespaces. Never recursively search.

Roots exact keys libero/robosuite, both existing regular directories; reject
linked/reparse ancestors/files. Each target must be a regular nonsymlink file
contained in its root; distinguish duplicate basenames by full suffix. Hash
each target with a64MiB per-file ceiling and256MiB total closure ceiling,
at most128references. No runtime asset transfer/download. Bounds that reject
the actual installed closure require review, not silent enlargement.

Resolved exact keys: xml (rewritten absolute installed file paths),
source_xml_sha256, resolved_xml_sha256, assets (deduplicated sorted list of
{namespace, relative_path, sha256}), asset_closure_sha256. Hash canonical asset
list; source_xml hash must match candidate. These private runtime paths are
not public handoff or outbound model input. Revalidate hashes and local file
identities before simulator mutation; caller owns installed pinned roots.

## Restoration helper and evidence boundary

Existing upstream environment construction and known BDDL remain outside this
kernel. Caller creates the pinned task0 environment at256px and validates
runtime pins/controller. Helper first validates candidate/resolved asset
closure without mutation, then follows:

```text
env.reset -> env.reset_from_xml_string(resolved.xml)
 -> compare flattened sim-state length with110
 -> env.set_init_state(candidate.state) [upstream forward/observations]
 -> hash env.get_sim_state() [pre-settle]
 -> ten env.step([0,0,0,0,0,0,-1]) -> hash get_sim_state [post-settle]
 -> return last raw observation + immutable reset metadata
```

After XML reset, dimension mismatch stops before applying state. Pre-settle
state must match the selected state hash exactly; no tolerance silently masks
a different state layout. Post-settle vector must be finite110values. Actual
controller/policy compatibility still needs live validation. Returned exact
keys observation/reset_metadata; metadata contains reset_id, source/state/XML/
closure hashes, pre_settle_state_sha256, post_settle_state_sha256,
settling_steps10, restoration_verified false (kernel alone never certifies
robot replay). No saved actions/images or failure oracle in helper. Caller
records first frame through existing preprocessing after this returns.

Later wiring must preserve external reset identity separately from benchmark
initial-state index0, and bind runtime/controller/checkpoint/BDDL evidence into
new case recipes. Existing M4 cases and schema cannot be upgraded by this
kernel. Successful synthetic tests do not count as M5B completion.

## Source basis

- Pinned harness: `35f1200eb15608aa898f727a3722f7eef889c6cd`.
- Pinned LIBERO: `8f1084e3132a39270c3a13ebe37270a43ece2a01`.
- The wrapper's set_init_state regenerates observations from restored state.
- Dataset states precede recorded actions, images follow actions; saved first
  frame is not a direct restore parity oracle. See the sample research note.

No paid compute, public dataset redistribution, case-schema migration or
expanded M3 work is included in this increment.
