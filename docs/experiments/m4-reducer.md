# M4 bounded failure reducer

M4 records a bounded, replayable reduction of the known upper-right occlusion
failure. The reducer uses deterministic nested rectangles and the existing
four-of-five policy-failure screen. Its result is a budget-local certified
counterexample, not a causal explanation or a globally minimal mask.

## September 27 live result

**Status:** completed for LIBERO Object task 0, episode 0, seed 7, with the
pinned GR00T N1.7 policy on one Nebius L40S VM. Jethro approved a US$2
incremental session cap. The nominal sentinel succeeded. The parent
`(x=0.50, y=0, width=0.50, height=0.50)` failed 4/4 times. Two nested
edge-strip removals retained the failure:

| Decision | Rectangle `(x, y, width, height)` | Valid outcomes |
| --- | --- | --- |
| Parent passed | `(0.50, 0, 0.50, 0.50)` | 4/4 policy failures |
| Remove left strip; accepted | `(0.625, 0, 0.375, 0.50)` | 4/4 policy failures |
| Remove another left strip; rejected | `(0.75, 0, 0.25, 0.50)` | 2/2 successes |
| Remove bottom strip; accepted | `(0.625, 0, 0.375, 0.375)` | 4/4 policy failures |
| Remove another left strip; rejected | `(0.75, 0, 0.25, 0.375)` | 2/2 successes |
| Remove another bottom strip; inconclusive | `(0.625, 0, 0.375, 0.25)` | No launch; candidate budget exhausted |

The certified final rectangle covers 14.0625% of the image, versus 25% for
the parent: 43.75% less mask area. All five fresh unoccluded nominal controls
succeeded. The terminal reason is `reduced_failure_with_nominal_controls`,
with `candidate_budget_exhausted` recorded as the search stop. The session
used 22 physical/valid episodes, including all 12 allowed candidate attempts;
the 23-episode ceiling was not reached. This does not establish the smallest
possible rectangle or a general failure threshold. The final accepted case
is replayable from the exported manifest, but it has not yet been rerun against
a changed policy version.

The driver recorded 832.8 seconds of elapsed work. The VM ran from
`2026-09-27T09:49:01Z` to `2026-09-27T10:13:03Z` (24.03 minutes). At the
console's tax-exclusive GPU/CPU/RAM plus 200 GiB Network SSD rates, the
estimated incremental session cost is US$0.771 including a 9% GST assumption;
provider billing may post later. The existing stopped boot disk continues to
accrue storage charges outside this run window.

Ignored local evidence is under `artifacts/m4-20260927-session1/`: 22
aggregates, 22 JSONL traces, 22 MP4s, 22 SQLite recordings, generated YAML,
`session_summary.json`, and `replay_case.json`. Every aggregate's task,
episode, outcome, and rectangle agreed with the durable summary; all media
files were present and nonempty. The viewer indexed 22 episodes with video
and trace paths and zero catalog warnings. The full Python 3.11 suite passed
126 tests. A provider query confirmed the VM `STOPPED`, its public IP absent,
and the temporary SSH ingress rule removed.

## Free local verification

Use the repository's fake-evaluator/unit-test path before any live run:

```powershell
cd <repo-root>
$env:PYTHONPATH = "src"
C:\Windows\py.exe -3.11 -m unittest tests.test_reduce tests.test_failure_reduction tests.test_viewer_server -v
```

The reducer driver accepts only the flags shown by its help output:

```powershell
C:\Windows\py.exe -3.11 scripts/run_failure_reduction.py --help
```

For the free local fake-evaluator integration, use the focused tests:

```powershell
C:\Windows\py.exe -3.11 -m unittest tests.test_failure_reduction tests.test_viewer_server -v
```

Do not commit the generated `failure-reduction/` directory or its media.

## Live/Nebius run (fresh cap approval required)

A live reduction is gated by fresh human approval. Before launching, refresh
the selected account, region, GPU quota, credit expiry/balance, capacity,
price, and a run-specific dollar cap. No approval is implied by this document.
Use one worker/GPU for the first run and tear down unneeded resources promptly.

The run must preserve its `session_summary.json` and exported
`replay_case.json`; the viewer should show lineage only when both are present
and the recorded final geometry agrees with the replay rectangle.

After the help check and fresh cap approval, launch with the verified flags:

```powershell
C:\Windows\py.exe -3.11 scripts/run_failure_reduction.py `
  --upstream-root <upstream-root> `
  --project-root <repo-root> `
  --results-root <repo-root>/artifacts
```

## Replay

Replay the exported final rectangle using the `replay_command` recorded inside
`replay_case.json`. The manifest's relative config path is relative to
`<results-root>/failure-reduction`; start the replay from that session
directory (or resolve the path explicitly), while invoking the evaluator from
the appropriate environment/path identified by the evaluator setup. Inspect
the recorded command rather than inventing flags.
The manifest identifies the task, seeds, expected outcome, acceptance rule,
configuration, and repository revision.

## Claim limitations and deferred work

Supported claim: within the tested nested-rectangle search and retry budget,
the system reduced a reproducible failure to the recorded replayable
condition. This does not establish universal failure coverage, causality,
global minimality, or robustness across tasks, models, or initial states.

Fresh initial-state evaluation, broader generalization, and any claim beyond
this exact tested perturbation family are deferred to M6.
