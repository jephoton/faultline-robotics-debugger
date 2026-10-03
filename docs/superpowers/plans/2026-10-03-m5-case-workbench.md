# M5 Case Workbench Plan

> **For agentic workers:** After the relevant design checkpoint is approved,
> use subagent-driven-development or executing-plans for its bounded sub-plan.
> Steps use checkboxes. This is a proposed milestone plan, not approval to
> implement undecided interfaces, send data to providers, or spend credits.

**Status:** Written for Jethro's scope/design review. No implementation started.

**Goal:** Let a simulation-based robotics developer bring a supported case,
understand replay readiness, inspect confirmed/reduced evidence, and export a
reproducible regression recipe from one coherent workbench.

**Proposed architecture:** Keep the existing loopback viewer read-only. Local
CLI commands register/import cases and export validated recipes; a separate
explicitly approved execution path produces new evidence. Normalize supported
inputs into a small case/capability index without modifying source files.
Nemotron adds optional evidence-linked explanations, not authoritative outcomes
or autonomous experiment control.

**Tech stack:** Existing Python 3.11/unittest, JSON artifacts and vanilla
HTML/CSS/JavaScript viewer. Preserve GR00T/LIBERO and current diagnostic rules.
Do not add HDF5 dependencies until sample feasibility and the reader design
are approved. Verify the actual hosted Nemotron API before choosing a client.

## 1. Starting point and scope boundaries

- M1/M2 work on the pinned simulation setup; M4 has a real bounded reduction
  from 25% to 14.0625% image area with replay/control evidence.
- `src/robot_debug/viewer/catalog.py` normalizes aggregate/media evidence;
  `server.py` serves read-only GET APIs and local assets in `viewer/web/`.
- The viewer already supports paired videos, traces, reduction lineage and
  representative-nominal filtering. Preserve equal evidence-panel sizing and
  Jethro's one-representative-nominal default.
- Task-filtered runs can use local `task0000` filenames for global task IDs
  1/2. Resolve this by evidenced identity, never guess among ambiguous videos.
- No general case importer or Nemotron product client exists. An external
  simulator-state sample has not yet been demonstrated replayable here.
- Expanded M3, its unfinished host launcher and portfolio UI are frozen under
  [ADR 0011](../../decisions/0011-freeze-expanded-m3.md). M5 does not depend on
  completing them. Retain existing fixed-replay HPC evidence separately.
- A formal-methods addition remains a separate human decision. Do not insert
  an SMT solver, TLA+ model or verification milestone into this plan silently.

M5 is three bounded increments, not one all-or-nothing platform. M5A works
offline with existing evidence; M5B adds a demonstrated external-input path;
M5C adds grounded explanations. Submission tooling must not imply M5A alone
delivers external closed-loop diagnosis or actual Nemotron use.

## 2. Decisions before dependent work

### D1 — Product entry point (red; recommendation pending approval)

1. **Read-only viewer plus CLI import/export/execution — recommended.** Reuses
   the working UI and keeps local mutations and paid operations explicit.
   The viewer shows status and exact next commands; a terminal is part of the
   documented workflow, not hidden behind a nonfunctional button.
2. Local browser import/export actions: friendlier interaction, but adds write
   endpoints, upload limits and cross-origin/request protections. Consider only
   after the case contract works; no direct browser cloud provisioning.
3. Full browser cloud job control: broad lifecycle/security scope and renewed
   dependency on unfinished infrastructure. Excluded from this MVP.

The CLI-first recommendation prioritizes a completed evidence-to-regression
journey over a new launcher. It is reversible: browser actions can call the
same validated case services after separate design approval.

### D2 — External input and replay capability (red)

Honor the accepted direction in
[the external-import decision](../../decisions/2026-09-15-first-external-import-priority.md):
inspect one rights-compatible LIBERO/robomimic-style HDF5 sample. Before coding
that reader, identify full simulator state/reset information, task/assets,
camera/controller mapping and runtime compatibility. Saved actions or video
playback do not prove counterfactual policy replay.

Alternatives at the checkpoint: the replay-feasible HDF5 adapter if proven;
an inspection-only adapter honestly labeled as such; or another artifact
direction selected by Jethro. Do not silently replace external import with
our own bundle and describe it as frictionless production interoperability.

### D3 — Nemotron role and input (red)

Recommend a bounded explanation service: known outcomes and perturbation
metadata, selected trace events, and timestamped frames only if the verified
endpoint supports them. Compare text-only simplicity versus multimodal symptom
inspection with Jethro after current model/API, data handling and price checks.
No inference/model choice or spending is approved by this plan. No raw-video
upload or general chat interface is required.

### D4 — Live execution path (red)

M5 must not revive the frozen host launcher. Before any live replay or external
restore experiment, review a small exact-run execution plan with one lifecycle
owner, proven independent stop protection, bounded artifact copy and cleanup.
Use existing verified primitives only where sufficient. If safe execution
cannot be arranged without expanding infrastructure, stop at the checkpoint
and present the limitation; do not conceal it with synthetic evidence.

## 3. Planned dependency/concurrency map

```text
scope / D1 approval
  -> M5A case contract checkpoint
      -> case import/export builder ----+
      -> existing-media fix builder ----+ -> independent review -> integration
      -> read-only sample feasibility --+                     -> viewer journey
      -> read-only Nemotron feasibility-+                         -> offline demo
  -> D2 + replay integration approval -> M5B adapter -> bounded live validation
  -> D3 + data/spend approval --------> M5C explanations -> grounded report
  -> final workflow acceptance -> M6 validation / M7 submission packaging
```

Sample and model feasibility may run independently of M5A code after scope
approval. No agent acquires cloud resources or performs inference. Root is
the sole Git integrator, external execution/spend owner and publication owner.
Do not add agents for small edits or give two builders the same viewer files.

| Owner / model handoff | Exact boundary | Expected output |
| --- | --- | --- |
| Root coordinator | Plans, ADRs, main handoff, resource authority and integration | Settled gates, combined evidence, approved sub-plans |
| Case builder: Terra medium, balanced fallback if unavailable | Proposed `src/robot_debug/cases.py`, `case_io.py`, `scripts/manage_cases.py`, matching `test_cases.py`, `test_case_io.py`, `test_manage_cases.py` | Validated internal case index, CLI import/export, fixture evidence |
| Media builder: Luna | `viewer/catalog.py`, `tests/test_viewer_catalog.py` only | Task-local lookup regression and ambiguity-safe resolution |
| UI builder: Terra medium, after case/media integration | `viewer/server.py`, `viewer/web/index.html`, `app.js`, `styles.css`, `tests/test_viewer_server.py` | Read-only case journey reusing existing evidence UI |
| Sample scout: Luna / balanced if runtime ambiguity | `docs/research/2026-10-03-m5-external-sample.md` only | Sample provenance/rights and inspect versus restore capability evidence |
| Model scout: Luna / balanced if API ambiguity | `docs/research/2026-10-03-m5-nemotron-feasibility.md` only | Verified or explicitly unverified model/input/price/data constraints |
| Nemotron builder: Terra medium after D3 | Proposed `evidence_packet.py`, `explanation.py`, `scripts/explain_case.py`, matching tests | Offline schema/client tests, bounded grounded-output path |
| Independent reviewer | Read-only code/fixtures/evidence | Spec review, then quality/security review; no self-approval |

New paths above are proposed ownership boundaries, not finalized function/API
contracts. Each increment receives a short approved implementation sub-plan
with exact schemas, function signatures and failing tests before a builder
starts. Use smaller capable agents automatically after those approvals; do not
pretend the active chat model was changed. No retired external coding provider.

## 4. M5A — Offline evidence-to-regression workbench

### A1: Approve the case/capability boundary (red)

Inspect `records.py`, `viewer/catalog.py`, the M4 summary and `replay_case.json`
with private identifiers omitted from documentation. Propose a strict,
versioned internal case index covering source format/provenance, policy and
runtime revisions, task/reset identity, perturbation, evidence references,
measurement provenance and independently derived capabilities.

Keep these questions separate:

- Can we inspect the recording?
- Are the inputs sufficient for a compatible closed-loop replay recipe?
- Has that recipe actually been exercised in the intended runtime?
- Does fresh controlled evidence confirm the suspected failure?

Missing metadata cannot become guessed replay readiness. Imported claims are
not fresh confirmations. A known seed is not a portable world snapshot.
Review the schema and state transitions with Jethro before implementation.

### A2: Import and export existing supported evidence (green after A1)

- [ ] Write failing tests for a complete existing case, missing media, absent
  reset/model revisions, inconsistent rectangle/outcome, duplicate identity,
  unknown schema, escaping paths and symlink references.
- [ ] Implement non-destructive local registration under a separate dedicated
  case workspace. Hash referenced inputs; never execute embedded commands,
  deserialize executable objects, fetch model weights or start compute.
- [ ] Preserve raw outcome categories; infrastructure errors cannot certify
  policy failure. Missing or conflicting measurements stay unknown.
- [ ] Export a machine-readable recipe plus a human summary: pinned versions,
  task/reset, exact mask, expected outcome, gate rules, evidence references and
  limitations. Validate source integrity and identities before export. Report
  missing prerequisites explicitly; generate commands only from trusted
  templates/validated fields, not copied arbitrary shell strings.
- [ ] Test export/reimport equivalence and invalid-case refusal. Large artifacts
  remain ignored; source files are unchanged. Commit boundary:
  `feat(cases): register and export supported replay evidence`.

### A3: Fix task-local media identity (green, parallel to A2)

- [ ] Add fixtures where global task IDs 1/2 have local-ordinal `task0000`
  filenames, plus multi-task and ambiguous-media negatives.
- [ ] Prefer explicit artifact identity; allow local-ordinal fallback only
  when aggregate/output context proves the mapping. Ambiguity is a warning,
  not an arbitrary first match. Preserve deduplication and nominal filtering.
- [ ] Run focused catalog/server regressions. Commit boundary:
  `fix(viewer): resolve task-local evidence with proven identity`.

### A4: Add the case journey to the viewer (amber after A2/A3 review)

- [ ] Expose validated read-only case/status/recipe data through the existing
  loopback server; keep media containment and range streaming intact.
- [ ] Show case identity and readiness/missing prerequisites before findings;
  then nominal, suspected, confirmed and reduced evidence, measured counts,
  lineage and an export/replay recipe. Labels reflect actual records, not an
  assumed linear success path. Budget-exhausted and unavailable are valid views.
- [ ] Keep both evidence panels equal in size and one nominal representative
  visible by default. No portfolio cards, dashboard redesign or browser-run
  cloud buttons. Explain CLI next steps without implying they were executed.
- [ ] Separate warm estimates, full-allocation estimates and billed values;
  show absent values as unknown. Do not display 3.715× as case diagnosis speedup.
- [ ] Add HTTP fixture tests for complete, inspection-only, missing evidence,
  conflicting metadata and partial/budget-exhausted cases; perform visual QA
  against real saved M4 evidence without running robotics again.
- [ ] Commit boundary: `feat(viewer): present the case-to-regression journey`.

**A exit gate:** A fresh operator registers existing saved evidence, identifies
what is/is not replayable, inspects parent/reduced videos and gate counts, and
exports a valid recipe. This proves offline usability, not a new live replay
or external-input diagnosis. Checkpoint with Jethro before B/C implementation.

## 5. M5B — One genuinely replayable external artifact

- [ ] Sample scout records a specific rights-compatible source/version, bounded
  sample size, episode identity, fields and missing replay prerequisites.
  Do not commit the dataset or personal/customer data. No cloud restoration
  during this read-only/local metadata batch.
- [ ] Present D2 choices with actual evidence. If HDF5 is selected, approve its
  bounded dependency, reader schema, asset mapping and restoration strategy.
- [ ] Plan/test one adapter against that actual schema: metadata-only reads,
  controlled episode selection, array/resource bounds, missing-state refusal,
  corrupt-file errors and no external links/embedded execution. Integrate into
  A's case interface without building a plugin ecosystem.
- [ ] Resolve existing runner hardcoding explicitly: the M4 driver starts from
  the known task/reset and parent mask. Supporting an imported initial state
  is not solved by filling a manifest. Approve a narrow runner input adapter
  and parity tests; preserve fault family, failure gates and reduction moves.
- [ ] Only after D4 and fresh credentials/preflight/cap approval, restore one
  selected state with the pinned simulator and run a matched nominal control.
  Verify GR00T closed-loop actions affect subsequent observations, rather than
  merely playing saved images/actions. A mismatch blocks diagnostic claims.
- [ ] Run bounded confirmation/reduction only for a compatible approved case,
  preserve all valid episode videos/traces and export the final recipe. No
  guaranteed failure is promised; no failure within budget is an honest result.
- [ ] Record tested versus untested restore/replay capabilities and observed
  friction in the dev-log/FEEDBACK.md with correct tool attribution.

**B exit gate:** One external case has a verified import/restoration path and
an audited bounded diagnosis result. Failure confirmation requires fresh valid
outcomes and controls; reduction is conditional on a repeatable failure.
If feasibility fails, Jethro chooses the revised product boundary; do not
silently claim B complete or make many-format support a prerequisite.

## 6. M5C — Evidence-grounded Nemotron explanation

- [ ] Verify current exact model ID, access, modalities/API shape, pricing,
  limits and data handling from primary documentation and account metadata.
  Existing September research is historical, not live entitlement. CLI cloud
  login does not configure Token Factory credentials.
- [ ] Before sending case data, obtain D3 approval for model/input, data scope
  and numeric pilot cap. Ask for local secret setup; never request a pasted key.
- [ ] Build a bounded evidence packet and locally validated report schema:
  observations/hypotheses, evidence IDs, missing evidence and limitations.
  Known outcomes/masks are disclosed inputs for explanation, not concealed
  answer labels for a claimed failure-discovery benchmark.
- [ ] Test offline fake responses: unsupported evidence IDs, malformed JSON,
  timeouts, missing frames, prompt-injection text and over-limit payloads.
  Schema validation checks structure/citations, not truth. Preserve the
  deterministic report when explanations are unavailable or rejected.
- [ ] Run a small approved pilot against a deterministic-summary baseline;
  root logs actual input modality, latency, token cost and human-reviewed
  unsupported claims/useful observations. Failures never change robot outcomes.
- [ ] Persist accepted outputs as local case artifacts. The viewer reads them
  with evidence navigation; it never calls the provider on page load and does
  not offer unrestricted chat or automatic test/cloud execution.
- [ ] If usefulness is poor, record that honestly and discuss a revised role.
  A fake response is not demonstrated NVIDIA/Nebius integration.

**C exit gate:** A real approved Nemotron invocation provides a reviewable,
evidence-linked explanation in the viewer with modality/cost provenance, while
deterministic replay outcomes remain authoritative.

## 7. Verification, review, commits and handoff

Use synthetic tiny fixtures in Git, and real ignored evidence for local visual
acceptance. Unit tests must never invoke Nebius, SSH, GPU simulation or provider
inference. Keep a separate explicitly gated live validation record.

From the appropriate worktree:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
C:/Windows/py.exe -3.11 -m unittest discover -s tests -p 'test_case*.py' -v
C:/Windows/py.exe -3.11 -m unittest discover -s tests -p 'test_viewer*.py' -v
C:/Windows/py.exe -3.11 -m unittest discover -s tests -q
git diff --check
```

Before integration: independent spec review then quality/security review,
fresh complete tests (last main baseline: 385 tests/four platform skips), and
source/data-rights/secrets checks. New focused test names are finalized in
each approved implementation sub-plan; a zero-test discovery is not acceptance.
Include CLI tests and model packet/client tests in those sub-plans.

Root updates `PROJECT_PLAN.md`, `docs/codex-handoff/STATE.md`, relevant ADRs,
`docs/dev-log.md` and observed-tool `FEEDBACK.md` after material changes.
Conventional commits per coherent verified unit; explicit staging, no large
media/private control files. Publish only under existing user authority and
verify remote identity; commit-only is reported if networking blocks push.

### Learning and authority checkpoints

- **Red:** D1/A1 interface and case state semantics; external format/reset
  adapter; failure/search/reducer changes; new model/data transfer; live
  topology/spend; deletion; submission claims. Jethro decides first.
- **Amber:** approved viewer presentation, metadata reconciliation and bounded
  report parsing. Explain evidence/tradeoffs at the next batch checkpoint;
  stop before executing if uncertainty changes the accepted boundary.
- **Green:** tests, fixture construction, accepted interface implementation,
  local analysis, documentation and scoped bug fixes. Smaller agents execute.

After each parallel batch root synthesizes what works, what does not, evidence,
cost implications and the next decision. Do not ask Jethro to reconstruct agent
logs. Invite interpretation of live results before turning them into claims.

### Final M5 acceptance and next milestones

- [ ] Demonstrate the supported import/readiness/evidence/export journey with
  source provenance and correct distinctions between saved and fresh evidence.
- [ ] Demonstrate the approved external replay path, or record a human-approved
  narrower scope rather than implying unimplemented restoration.
- [ ] Demonstrate actual Nemotron use and honest deterministic fallback.
- [ ] Document a fresh-operator walkthrough in `docs/setup/case-workbench.md`
  and known limitations; no universal video-to-regression promise.
- [ ] Keep project naming brainstorming queued for Jethro's decision. M6 adds
  broader validation under separate scope; M7 handles final video pitch,
  feedback reconciliation, licensing/data rights and judge-run public-repo audit.

**Immediate next step after plan review:** settle D1 and A1, then write only
the bounded M5A implementation contract. Do not start B/C or revive M3 while
waiting. This milestone plan deliberately keeps undecided architecture out of
mechanical implementation handoffs.
