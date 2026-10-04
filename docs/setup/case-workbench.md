# Offline case workbench

The workbench turns an **existing M4-format diagnostic session** into a local
case registration and portable metadata export. It does not import arbitrary
video, execute a replay, start a GPU, or call a model. Original recordings and
source JSON remain unchanged. Videos and model weights are not included in the
export.

## Setup and supported input

Run from the repository root with Python 3.11. In PowerShell:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
python scripts/manage_cases.py --help
```

On a Unix shell, use `export PYTHONPATH=src` and the same commands (use
`python3` if needed). This offline path uses the standard library; it needs
neither Nebius nor Hugging Face credentials.

Supply a local directory containing the saved M4 layout:

```text
source-root/
  failure-reduction/
    session_summary.json
    replay_case.json
    runs/<stage>/<stage>_aggregate.json
    runs/<stage>/... recorded video and trace files ...
```

`--summary` and `--replay` can select other contained relative paths. This is a
specific adapter, not a promise that every simulation bundle has this schema.
Raw videos or action-only datasets cannot establish closed-loop replay inputs.
Real experiment artifacts are ignored and are not distributed in the public
repository. The test suite uses small synthetic fixtures instead.

## Register, inspect, export and rebind

Replace `SOURCE_ROOT` with your existing source directory. Keep the workspace
and export outside that directory. Registration writes only to the separate
workspace; the default is ignored `artifacts/cases`.

```powershell
python scripts/manage_cases.py import-m4 --source-root SOURCE_ROOT --workspace artifacts/cases
python scripts/manage_cases.py list --workspace artifacts/cases
python scripts/manage_cases.py inspect --workspace artifacts/cases --case-id CASE_ID
python scripts/manage_cases.py export --workspace artifacts/cases --case-id CASE_ID --output artifacts/export-new
python scripts/manage_cases.py reimport --index artifacts/export-new/case.json --source-root SOURCE_ROOT --workspace artifacts/cases-copy
```

Use the full 64-character `case_id` returned by import/list. Choose a new export
directory each time: an existing destination is refused rather than overwritten.
Commands print JSON; invalid inputs produce a sanitized error and exit code 2.

The registration contains public `case.json` plus a **private local source
binding**. Do not publish that workspace or its `local-source.json`. Export
omits the binding. Reimport requires an explicit local source root and checks
the evidence again; exported badges are not trusted.

An export contains `case.json` and a human-readable `README.md`. It also contains
`replay_recipe.json` **only when its required inputs are complete**. The recipe
is structured data, not an executable command. Metadata export does not mean a
compatible simulator, model checkpoint, or live execution path is installed.

## Understand the four capabilities

| Capability | What it answers |
| --- | --- |
| Inspection | Are valid selected episode records available locally? |
| Replay recipe | Are the required task, policy, runtime and mask inputs present? |
| Exercised replay | Has this recipe actually been run in the intended runtime? |
| Historical failure | Do the saved raw outcomes and controls reconcile with the claimed failure and policy identity? |

Import/export cannot upgrade exercised replay beyond **unverified**. A supplied
profile can fill missing recipe pins with contained, hash-checked provenance;
it cannot retroactively prove which model produced old outcomes. Missing media
affects viewing availability, not otherwise intact historical evidence. Changed
core sources invalidate claims and block export. Missing or contradictory pins
must be resolved from actual provenance, never guessed from today's defaults.

The real saved M4 session has 22 videos/traces, but its legacy records omit the
checkpoint revision, simulator-image digest and upstream-harness revision.
Its aggregates also do not carry an exact policy identity linked to the summary.
The importer reports these limitations even though the earlier controlled run
and its videos remain useful experimental evidence.

## View the registered case

After registration, start the loopback viewer with the same artifact and case
workspaces:

```powershell
python -m robot_debug.viewer.server --artifacts artifacts --cases artifacts/cases --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/`. Select the case to inspect its capability labels,
missing prerequisites and saved evidence. Compare nominal, parent and reduced
episodes using the paired video selectors and trace view. **All saved evidence**
returns to the original catalog workflow. The panel supplies a local CLI export
template; the browser does not create an archive, upload files or run a replay.
Open **Replay inputs and export details** for missing pins, source-reported
metrics and the export template. Evidence is linked by validated exact episode
IDs; unsupported links are disclosed instead of substituting another recording.

The viewer only reads registrations. Refreshing it must not change recordings,
badges or recipes on disk. If no case is registered, follow the import command
shown in the empty state. A broken case entry does not disable the remaining
episode catalog. Stop the local server with Ctrl+C.

## Boundaries

The reduced mask is budget-local, not a proven global minimum. Source-reported
elapsed time and episode counts are not reconciled billing. The first adapter
supports the existing opaque-rectangle family and M4 protocol only. External
state restoration and real Nemotron explanations are separate M5B/M5C gates,
not functionality demonstrated by a synthetic fixture or metadata export.
