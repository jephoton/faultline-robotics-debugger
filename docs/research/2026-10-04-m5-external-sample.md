# Actual external LIBERO sample: M5B feasibility

Generated research, October 4, 2026. This records actual downloaded bytes and
read-only metadata inspection, not a simulated result or executed robot replay.

## Provenance and acquisition

Jethro approved the bounded acquisition in ADR 0014. Downloaded one file from
the official-endorsed `yifengzhu-hf/LIBERO-datasets` mirror at immutable revision
`97773100c1474cd0d686ebd173cc0e4fd5442466`:

`libero_object/pick_up_the_alphabet_soup_and_place_it_in_the_basket_demo.hdf5`.

Actual size: **780,145,352 bytes**, below the 800,000,000-byte ceiling.
Actual SHA-256:
`42189d4415d4c51aaaf0708300653fccc39239cd3f2709079a713cd8d1678a8d`.
Both exactly match the pre-acquisition metadata. The completed file is ignored
at `artifacts/m5-sample-preflight/libero-object-alphabet-soup.hdf5`; no dataset
or frames were staged, published or sent to an inference provider.

The upstream README identifies datasets as CC BY 4.0; the mirror card identifies
Apache-2.0. This discrepancy remains unresolved. Acquisition does not establish
redistribution permission. See the source links in
[the earlier feasibility note](2026-10-03-m5-feasibility-checkpoints.md).

## Verified demo_0 contents

Read only `data/demo_0`, selected bounded attributes, and one state vector;
no bulk image or action reads and no simulator execution.

| Field | Actual observation |
| --- | --- |
| Task instruction | pick up the alphabet soup and place it in the basket |
| Environment | `Libero_Floor_Manipulation`; domain `robosuite` |
| Robot / controller | `Panda` / `OSC_POSE` |
| Control frequency | 20 Hz |
| Actions | float64, `(148, 7)` |
| Flattened simulator states | float64, `(148, 110)` |
| First state | 110 finite values; exactly equals the `init_state` attribute |
| Agent-view recording | uint8, `(148, 128, 128, 3)` |
| Wrist recording | uint8, `(148, 128, 128, 3)` |
| Camera names | `agentview`, `robot0_eye_in_hand` |
| Image convention | `opengl` |
| Model XML | present, parses as `mujoco`; references 72 distinct asset basenames |
| Task definition | BDDL filename reference present; embedded BDDL content absent |
| Link traversal | no soft/external links encountered in the selected tree |

SHA-256 of the first state converted to little-endian float64:
`5d4cd69032368d08d09453ef6ed4fa8c4ad697bf152d919eb673837274ba0df1`.
This identifies the observed vector, not compatibility with another MuJoCo model.
Rewards/dones and recorded action arrays were only inspected for shape/dtype;
they were not used to certify a GR00T outcome.

## Meaning for the product

This is a **plausible restore candidate**, not just an action/video recording.
It includes simulator state, scene XML, task identity and camera/controller
metadata. Those are the ingredients a targeted adapter can reconcile with the
existing LIBERO environment. The official
[LIBERO environment wrapper](https://github.com/Lifelong-Robot-Learning/LIBERO/blob/master/libero/libero/envs/env_wrapper.py)
provides XML reset, flattened-state restore and observation regeneration.
These code paths suggest a feasible implementation; they have not been run
against this file in our pinned evaluator.

It is **not a self-contained replay bundle**: scene asset references require
installed LIBERO/robosuite assets, BDDL content must come from a verified task
definition, and dataset runtime versions are not established. The official
[dataset creator](https://github.com/Lifelong-Robot-Learning/LIBERO/blob/master/scripts/create_dataset.py)
also filters early demonstration steps. A selected dataset state is therefore
not automatically one of the benchmark's initial-state indices, nor does its
stored action trajectory constitute a new closed-loop policy evaluation.

Independent read-only review confirmed the metadata and found an important
asset-closure detail: XML contains 81 file references, 80 distinct paths, but
only 72 distinct basenames. Some names occur at different paths. An adapter
must not resolve every asset by basename alone and assume it chose correctly.

## Required next checks before an adapter can claim replay

1. Resolve the exact BDDL/task and all scene assets from pinned dependencies,
   rejecting arbitrary embedded path loading. Confirm state/model dimensions.
2. Restore XML and the selected vector in the existing runtime; verify simulator
   state layout compatibility as well as robot
   and object state and regenerated camera observations. Reconcile OpenGL
   orientation and 128px recorded views with the live policy preprocessing.
3. Confirm the full controller configuration, action scaling and reset semantics;
   simulator state alone may not encode all policy/controller history. Define
   the selected episode start and observation timing relative to reset/actions.
4. Run the actual GR00T policy from that restored state, not saved actions.
   Reconstruct the BDDL success predicate rather than trusting saved demo flags.
   Use matched nominal/perturbed attempts and existing outcome gates before
   treating it as a diagnosis/regression case.
5. Record actual runtime/checkpoint pins and source hashes in new evidence.
   Do not retroactively fill the missing pins in legacy M4 recordings.

Recommended next design: one task, one explicit demo/state start, explicit
asset/runtime prerequisites and capability labels. An inspection-only adapter
is a fallback if restore parity fails; it must not be presented as replay.
Actual adapter implementation and a later bounded cloud validation remain
their own review and spending gates. Expanded M3 is not a dependency.

## Local inspection setup and checks

Python 3.11 isolated venv: `artifacts/m5-sample-preflight/venv`.
Binary h5py 3.14.0, NumPy 2.4.6. pip 24.0 needed
`--use-feature=truststore` to use existing Windows roots; TLS verification was
not disabled and no global Python dependencies changed.

One-off ignored `inspect_sample.py` and `check_inspector.py` live alongside the
sample for local continuation. Root read the helper and reran its fixtures:
missing state, matching state, link skipping, correct attribute ownership and
private-path/content omission passed. These are research aids, not a supported
production importer. The actual helper command exited zero and explicitly
returned `restoration_verified: false`.
