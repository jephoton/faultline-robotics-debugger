# Clean checkout audit

## Result

Audited the Git archive at source commit `171abae003a79093f986adacdcc04047659a714f` on Windows 11 with CPython 3.11.9. The source was extracted to a new temporary directory and installed into a new virtual environment with system site packages disabled. This confirms a clean snapshot and environment on this Windows machine; it is not a second-machine or cross-platform installation claim.

The isolated install, installed command, packaged viewer assets, offline demo control panel, and README unit-test command all passed. Installation downloaded dependencies; only the demo service is account-free/offline-capable. No live Nebius setup or cloud run was attempted. Those steps still require a separately configured account, project, region, quota and current resource/budget checks.

## Reproduction on Windows PowerShell

Run from the repository root. The commands create a Git archive of `HEAD`, so only committed files enter the snapshot. Choose a temporary directory path that does not already exist.

```powershell
$auditRoot = Join-Path $env:TEMP ('faultline-audit-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $auditRoot | Out-Null
$sourceZip = Join-Path $auditRoot 'source.zip'
git archive --format=zip --output=$sourceZip HEAD
Expand-Archive -LiteralPath (Join-Path $auditRoot 'source.zip') -DestinationPath (Join-Path $auditRoot 'source')
Remove-Item -LiteralPath (Join-Path $auditRoot 'source.zip')
C:/Windows/py.exe -3.11 -m venv (Join-Path $auditRoot '.venv')

Push-Location (Join-Path $auditRoot 'source')
& (Join-Path $auditRoot '.venv/Scripts/python.exe') -m pip install '.[cli,cloud]'
if ($LASTEXITCODE -ne 0) { throw 'install failed' }
Pop-Location

Push-Location $auditRoot
& (Join-Path $auditRoot '.venv/Scripts/faultline.exe') --help
& (Join-Path $auditRoot '.venv/Scripts/python.exe') -c "import pathlib, robot_debug; from robot_debug import viewer; p=pathlib.Path(viewer.__file__).parent/'app'; assert (p/'index.html').is_file(); assert len(list((p/'assets').glob('*'))) > 0; print(robot_debug.__file__, 'viewer assets:', len(list((p/'assets').glob('*'))))"
& (Join-Path $auditRoot '.venv/Scripts/python.exe') -m pip check
Pop-Location

Push-Location (Join-Path $auditRoot 'source')
$env:PYTHONPATH = 'src'
& (Join-Path $auditRoot '.venv/Scripts/python.exe') -B -m unittest discover -s tests
$testExit = $LASTEXITCODE
Remove-Item Env:PYTHONPATH
Pop-Location
if ($testExit -ne 0) { throw 'unit tests failed' }
```

The tested install resolved NumPy 1.24.4, PyYAML 6.0.3, boto3 1.43.114, truststore 0.10.5 and their dependencies. `faultline --help` listed all seven command groups; the installed `robot_debug` import resolved from the new environment, and the packaged viewer contained `index.html` and nine asset files. `pip check` reported no broken requirements.

## Offline demo service

From the extracted snapshot root, choose a free loopback port and run:

```powershell
& (Join-Path $auditRoot '.venv/Scripts/python.exe') -B -m robot_debug.cli ui --artifacts demo/root --host 127.0.0.1 --port 18765
```

On the audited port, `GET /` returned 200 with HTML; `GET /api/health` returned `{"status":"ok","read_only":true}`; `GET /api/library` returned the saved showcase entry; and `GET /api/library/<id>` returned its case detail. The ID is the `d-<digest>` value in the library entry's `id` field. The detail response lists metadata files; its three video URLs are served separately under `/media/diagnoses/<case-hash>/videos/`. A `GET` for `original.mp4` returned 200 as `video/mp4` (215,556 bytes). The service was stopped after inspection, and the port no longer served requests.

## Unit-test result and limits

The exact README command, `PYTHONPATH=src python -B -m unittest discover -s tests`, ran from the clean extracted source with the new virtual environment's Python:

```text
Ran 3166 tests in 258.950s
OK (skipped=63)
```

The command was nonverbose, so it reported the skip count but not individual skip reasons. The test suite emitted diagnostics from deliberate error-path/fault-injection cases; the final exit status was 0. Its raw local output stayed in the temporary audit directory because those synthetic diagnostics include secret-shaped strings and host-specific paths.

This audit did not build or push a simulator image, access Nebius or Token Factory, perform authentication, contact a live cloud API, or reconcile billing. The `cloud` extra was installed, but live cloud setup remains unverified. The README's Node frontend checks were also outside this Python install audit.
