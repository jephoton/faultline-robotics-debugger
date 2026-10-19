# M5C Nemotron v2: geometry-aware packet and prompt

**Goal:** Make the Token Factory interpretation useful: state the key
nominal-versus-mask contrasts with correct citations and propose testable
spatial hypotheses, while keeping evidence binding and human review.

**Approval (October 10, the project owner):** "continue trying Nemotron, improve the prompt
and stuff." Model stays `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` on Token Factory.
Spend cap for this iteration: **US$0.10 total**, at most five live attempts,
each with its own US$0.02 reservation (actual cost about US$0.001 per call).

## Diagnosis of the October 6 report

- The prompt's example literally contained `"hypotheses":[]` and asked for
  "1 or 2 brief" entries, so the model returned none.
- The packet carried roles and outcomes only. Per-role counts were computed
  locally but never sent, and per-episode mask geometry was absent, so the model
  could not see that `(0.625,0,0.375,0.5)` and `(0.625,0,0.375,0.375)` fail 4/4
  while `(0.75,0,0.25,·)` succeeds.
- Its first observation cited nominal episodes for a claim about the mask.

## Design

- **Packet v2** (`evidence_packet.py`): episodes gain `mask`: the rectangle for
  non-nominal roles, parsed strictly from the stage name our M4 driver writes
  (`x0625-y0000-w0375-h0500` → thousandths), else `null`. v1 stays valid;
  `validate_evidence_packet` accepts both; identity is still SHA-256 of the
  canonical packet.
- **Request context** (`token_factory.py`): for v2 the user message is
  `{"counts_by_role", "mask_groups", "packet"}`, where both summaries are pure
  functions of the packet, so the stored packet determines everything sent.
  Request cap rises from 6 KB to 16 KB (input tokens cost US$0.06/M).
- **Prompt v2:** 2–4 verifiable observations stating contrasts and citing
  episodes from each compared group; 1–3 testable hypotheses each naming the next
  bounded experiment; 1–3 limitations (sample size, single task/seed,
  budget-local reduction, no causal proof, human review). No empty-array example.
- **Store/viewer** (`explanation_store.py`): a stored report is shown when its
  packet equals the current case's fresh projection *of the same schema
  version*, so the three October 6 v1 reports remain visible.
- **CLI** (`scripts/explain_case.py`): `--packet-version {1,2}` (default 2 for
  `prepare`/`live`) and `live --attempt LABEL`, which reserves under
  `artifacts/m5-nemotron-attempts/LABEL/` (exclusive, never reused).

## Tests and commits

TDD with fixtures: v2 projection and stage parsing (masked, nominal, unparseable),
v1/v2 validation, mask groups, request payload/prompt selection and size, store
reading of mixed v1/v2 reports, attempt label validation and reservation path.
Full Windows suite and Python 3.11 only (workstation path). Commits:
`feat(m5): add geometry-aware evidence packet v2`,
`feat(m5): send counts and mask groups with a v2 interpretation prompt`,
`feat(m5): version reports and attempts in the explanation CLI`.

## Live attempts and acceptance

Offline `prepare --packet-version 2` first, then attempt `v2-01`. Judge against
the diagnosis above; iterate the prompt only, within the cap. The project owner decides
M5C acceptance from the stored report in the viewer.
