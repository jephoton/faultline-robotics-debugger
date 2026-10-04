# M5 External Sample and Nemotron Preflight Plan

> For agentic workers: use subagent-driven-development for bounded preparation;
> root alone owns downloads, dependencies, credentials, provider calls and Git.

**Goal:** Inspect one actual external episode and establish the prerequisites
for the approved text-only Nemotron pilot without starting cloud compute.

**Architecture:** Download the immutable official-mirror task file into ignored
local artifacts, verify bytes/hash, and read demo_0 metadata with an isolated
h5py environment. Separately verify the hosted model and credential setup.
Neither track implements a restore adapter or upgrades imported case claims.

**Tech stack:** PowerShell streaming HTTPS, Python 3.11, isolated binary h5py,
official provider documentation. No production dependency changes.

## Authority and boundaries

Jethro's October 4 "go" accepts the two preceding bounded proposals:

- Sample: one 780,145,352-byte file (744.1 MiB), hard 800,000,000-byte ceiling,
  immutable revision `97773100c1474cd0d686ebd173cc0e4fd5442466`, SHA-256
  `42189d4415d4c51aaaf0708300653fccc39239cd3f2709079a713cd8d1678a8d`.
  Source: `yifengzhu-hf/LIBERO-datasets`,
  `libero_object/pick_up_the_alphabet_soup_and_place_it_in_the_basket_demo.hdf5`.
- Model/data/cap: `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` through Nebius Token
  Factory; at most ten text-only calls and US$0.02 total. Only deidentified
  task/outcome/mask metadata and evidence IDs may be sent. No media, paths,
  private logs or credentials. Account entitlement, live price, balance and
  locally configured key must be checked before inference. Approval is not
  proof that a key or funded account exists.

Sample acquisition is not redistribution permission. Preserve the upstream
CC BY 4.0 versus mirror Apache-2.0 metadata discrepancy. No VM start, simulator
restore implementation or paid replay is authorized; M3 remains frozen.

## Ownership and concurrency

```text
root: bounded download/hash + isolated environment -> actual metadata inspection
sample helper (smaller balanced agent): ignored inspector preparation ------^
model scout (Luna): official model/setup documentation ---------------------+
root: reconcile evidence, persist results, identify remaining red decisions -+
```

Sample helper owns only `artifacts/m5-sample-preflight/inspect_sample.py` and
tiny generated fixture checks in that ignored directory. It does not acquire
the dataset, install dependencies, run providers or commit. Model scout owns
only `docs/research/2026-10-04-m5-nemotron-access.md`; no credentials or API
requests. Root owns this plan, ADR 0014, research synthesis, handoff, feedback
and Git. Root reviews helper before execution; independent review verifies
actual results before an adapter design. No overlapping production edits.

## Task 1 — Acquisition and metadata inspection (green/amber)

- [ ] Commit this plan and the accepted authority record before execution.
- [ ] Check ignored target and free disk. Stream immutable HTTPS into an
  exclusively created partial file; require expected Content-Length if given,
  cap actual bytes at 800,000,000 and fail if final bytes differ from expected.
  Print bounded progress only. Never overwrite a prior downloaded file.
- [ ] Require exact SHA-256 before naming the completed file. Keep partial
  bytes on failure for diagnosis; do not silently accept incomplete data.
- [ ] Create `artifacts/m5-sample-preflight/venv` using Python 3.11 and install
  binary h5py from PyPI there, not in the production environment.
- [ ] Helper: `inspect_sample.py FILE` opens HDF5 read-only; inspect only
  `data/demo_0`, bounded attributes, dataset shapes/dtypes, one initial state,
  controller/camera/environment metadata and model-XML closure hints. Avoid
  image/action bulk reads and external-link traversal. Output JSON metadata,
  no raw XML, absolute embedded asset paths or full frame arrays. A tiny local
  HDF5 fixture should prove missing-state disclosure and bounded reporting.
- [ ] Root runs helper on checksum-verified bytes and records actual initial
  state, model/task/assets, camera/controller and format facts in
  `docs/research/2026-10-04-m5-external-sample.md`. Presence of states/XML is not
  proof of runtime restore or closed-loop GR00T parity.

## Task 2 — Token Factory access and pilot prerequisite check (green)

- [ ] Scout checks official endpoint/model/input/price/setup documentation,
  distinguishing current public facts from account-specific unknowns.
- [ ] Root checks only names/presence of relevant locally configured variables
  or known secret-store bindings. Never print values or search unrelated secrets.
- [ ] If no key is configured, give exact local setup instructions and stop
  provider execution. Do not substitute Nebius AI Cloud CLI OAuth for an
  inference API key; do not create paid infrastructure.
- [ ] Before any inference, settle and commit the packet/client implementation
  sub-plan: strict allowlisted evidence schema, local output validation, bounded
  calls/tokens, conservative price reservations, sanitized errors, immutable
  source evidence, and honest deterministic fallback. This preflight does not
  authorize improvising a product client or fabricating a Nemotron result.

## Review, handoff and commits

- [ ] Root checks actual sample hash/metadata and scout links independently.
- [ ] Update `PROJECT_PLAN.md`, `docs/codex-handoff/STATE.md`, the research
  notes, and `FEEDBACK.md` only for observed tool interactions. Mark Token
  Factory untested until a real inference occurs.
- [ ] Commit related paths explicitly: `docs(m5): approve sample and model
  preflight`, then `docs(m5): record actual external sample feasibility`.
  `git diff --check`; never stage dataset, venv, raw provider logs or secrets.
- [ ] Explain the findings and required next decisions. Actual adapter/runtime
  changes and a new live replay cap remain Jethro's checkpoints.
