# M4 bounded failure reducer

M4 records a bounded, replayable reduction of the known upper-right occlusion
failure. The reducer uses deterministic nested rectangles and the existing
four-of-five policy-failure screen. Its result is a budget-local certified
counterexample, not a causal explanation or a globally minimal mask.

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
`replay_case.json`, from the upstream evaluator working directory identified
by `<upstream-root>` so relative config paths resolve correctly. Inspect that
recorded command rather than inventing flags.
The manifest identifies the task, seeds, expected outcome, acceptance rule,
configuration, and repository revision.

## Claim limitations and deferred work

Supported claim: within the tested nested-rectangle search and retry budget,
the system reduced a reproducible failure to the recorded replayable
condition. This does not establish universal failure coverage, causality,
global minimality, or robustness across tasks, models, or initial states.

Fresh initial-state evaluation, broader generalization, and any claim beyond
this exact tested perturbation family are deferred to M6.
