# M5B/C feasibility checkpoints

Generated read-only research, October 3, 2026. No dataset acquired, credentials
read, API inference requested or compute started in this research batch.

## External episode

No HDF5 file was found in the current checkout/ignored local artifacts. Existing
M4 task/reset-index replay is not demonstrated external-state restoration.

The official [LIBERO README](https://github.com/Lifelong-Robot-Learning/LIBERO/blob/master/README.md)
labels code MIT and datasets CC BY 4.0. The official
[dataset creation script](https://github.com/Lifelong-Robot-Learning/LIBERO/blob/master/scripts/create_dataset.py)
documents model XML, flattened simulator states, initial state, actions and
camera observations. This suggests a suitable Object-suite sample, but actual
sample bytes/runtime compatibility are unverified. Third-party asset terms,
controller/action semantics and state/model closure require separate inspection.
The [robomimic schema](https://robomimic.github.io/docs/datasets/overview.html)
does not guarantee useful simulator states for every environment.

The [official downloader change](https://github.com/Lifelong-Robot-Learning/LIBERO/commit/8f1084e3132a39270c3a13ebe37270a43ece2a01)
endorses `yifengzhu-hf/LIBERO-datasets`; its helper downloads a whole suite.
A single task file is available at repository revision
`97773100c1474cd0d686ebd173cc0e4fd5442466`, path
`libero_object/pick_up_the_alphabet_soup_and_place_it_in_the_basket_demo.hdf5`.
Root verified public HF metadata: 780,145,352 bytes (744.1 MiB), SHA-256
`42189d4415d4c51aaaf0708300653fccc39239cd3f2709079a713cd8d1678a8d`.
It bundles the task's demos, not a standalone episode. The mirror card declares
Apache-2.0, conflicting with the upstream README's CC BY 4.0. Do not conceal the
discrepancy or present mirror metadata as an authoritative relicensing grant.
One-file acquisition/isolated h5py metadata inspection with an 800 MB bound was
requested from Jethro; no download happened merely because the source is public.

Recommendation: identify one official Object task file, bound acquisition size
and inspect one episode's metadata before proposing an adapter. Dataset/frame
playback is not closed-loop robot-policy replay. HDF5 dependency/adapter and a
later reset/parity/control experiment retain D2/D4 review and spending gates.

## Nemotron explanation

The [Nebius public Nemotron catalog](https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference)
lists Nano 30B A3B public inference at $0.06/M input and $0.24/M output tokens.
Scout-verified API candidate is `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`;
account entitlement remains unverified. The documented API base is
`https://api.tokenfactory.nebius.com/v1/`.

The [structured-output documentation](https://docs.tokenfactory.nebius.com/ai-models-inference/json)
defines JSON-object/schema response modes but conditions model support on the
model-card JSON-mode tag. Do not assume this exact model supports a mode until
verified. Local parsing, schema/evidence-ID validation and deterministic fallback
are required regardless. No vision/video interpretation is claimed for a
text-only endpoint.

Recommended pilot: at most ten text-only calls, no more than 6,000 input and
600 output tokens per call, $0.02 approved ceiling before requests. Public-rate
arithmetic gives approximately $0.00504 total model usage at those limits,
excluding billing differences. Token limits/account billing/actual usage must
be verified; this estimate is not a spend authorization or hard runtime guard.

Transmit only approved de-identified task/outcome/mask metadata and evidence
IDs, not videos, private paths, credentials or operator logs. Model explains
provided evidence; it does not decide outcomes or control experiments. D3
approval for exact model/data/cap was requested asynchronously while offline
M5A work continued. Configure any later key locally, never paste it into chat.

## Boundary

M5A may finish offline. Full M5 completion additionally requires demonstrated
external restoration/diagnosis under the accepted scope and an actual approved
Nemotron explanation; these cannot be replaced by fake fixtures or documentation.
