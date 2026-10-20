# Faultline operator runbook

> Generated operational summary. Run commands from the repository root.
> The [diagnosis quickstart](../setup/diagnose.md) has first-time Nebius,
> Hugging Face secret, registry and image setup details. This document does
> not grant approval for new paid work.

For a guide to **using the interface**, rather than setting up or operating
the CLI, read the [UI user runbook](../ui-runbook.md). It starts with a free
walkthrough of recorded evidence and covers concrete diagnosis/replay scenarios.

## Install and inspect an offline case

Use Python **3.10 or 3.11** (NumPy 1.24 has no wheel for newer versions).
Install the CLI and cloud libraries:

```bash
python -m pip install -e ".[cli,cloud]"
faultline --help
faultline ui --artifacts demo/root --open
```

Open `http://127.0.0.1:8765` if the browser does not open automatically.
`demo/root/` is a finished diagnosis and needs no cloud account. From a
source checkout without installation, use `PYTHONPATH=src python -B -m
robot_debug.cli ui --artifacts demo/root` on POSIX; in PowerShell set
`$env:PYTHONPATH = 'src'` and run `py -3.11 -B -m robot_debug.cli ui --artifacts
demo/root`. On machines where the launcher is absent, use the selected
Python 3.10/3.11 executable in place of `py -3.11`. The local panel binds
loopback only. Its controls can start paid Jobs after explicit confirmation;
opening or refreshing a page does not.

## Prepare a bounded diagnosis

### Windows PATH when the panel cannot find installed tools

If the native Python panel reports missing Nebius/Docker even though they are
installed, check its process PATH, not only a separate terminal's PATH. For
Nebius installed in WSL and Docker Desktop at its default location:

```powershell
$env:PATH = "$env:SystemRoot\System32;$env:ProgramFiles\Docker\Docker\resources\bin;$env:PATH"
$env:PYTHONPATH = 'src'
py -3.11 -B -m robot_debug.cli ui --artifacts artifacts --port 8765
```

Restart the panel only after checking there are no active runs. The launcher
can then find `wsl.exe` and invoke the existing WSL Nebius installation. For
interactive sign-in inside WSL, Windows System32 must also be on its PATH so
the CLI can open the Windows browser:

```bash
export PATH="/mnt/c/Windows/System32:$PATH"
"$HOME/.nebius/bin/nebius" iam whoami
```

Keep identity output private. After sign-in, use Setup's Check again. Its
authentication result may be cached for 60 seconds. The current Docker check
only finds the executable; separately use `docker info` to confirm the engine
is running. Docker is needed for building an image, not browsing saved cases
or submitting an already-built image to a Job.

### Before starting cloud work

1. Prefer the unified `configs/specs/diagnose.yaml` example; specialized
   scenario, audit and paraphrase CLI examples remain available. Copy it to
   an ignored local path. Fill in project, image digest and secret
   **name**, not the secret value. Every spec needs `budget.max_spend_usd` and
   `budget.max_hours`. For imported scenario starts, follow the JSON contract
   in [the quickstart](../setup/diagnose.md); a checkpoint override needs a
   compatible checkpoint and token access.
2. For Nebius, sign in locally and verify `nebius iam whoami`, project/region,
   live balance and expiry, L40S quota/capacity, exact Job and storage prices,
   image access and the user-approved numeric cap. The local `.env` can hold
   `NEBIUS_API_KEY` for Nemotron; never commit or paste it. The gated
   Cosmos-Reason2 model requires a Hugging Face read token stored in Nebius
   MysteryBox, as described in the quickstart. Recheck account isolation
   before provisioning. A local NVIDIA GPU backend exists but remains
   untested on a real GPU.
3. Inspect the plan without creating cloud resources:

```bash
faultline diagnose <ignored-spec.yaml> --dry-run
```

The dry run shows Jobs, deadlines and reserved worst-case costs. Its estimate
uses the provider timeout plus a start allowance at the specified hourly
rate. It has not been reconciled with Nebius billing; treat it as a run guard,
not a final invoice. A real run is:

```bash
faultline diagnose <ignored-spec.yaml> --env-file .env
```

Use `--no-llm` when a supported mode can run without Nemotron; paraphrase
generation needs the Token Factory key. The local control panel provides a
spec form, validation, dry run and confirmation over the same workflow:

```bash
faultline ui --open
```

Specs written by the panel stay under ignored `artifacts/specs-ui/`; it starts
at most one paid run at a time unless an operator explicitly overrides that
guard. Completed runs are under `artifacts/runs/` with a report, spend ledger,
case and downloaded evidence. Controls are local-only and require the page's
session token, exact Origin and Host checks.

## Stop, recover and replay

```bash
faultline stop artifacts/runs/<run-folder>
faultline diagnose --resume artifacts/runs/<run-folder>
faultline cases
faultline replay artifacts/runs/<run-folder> --spec <replay-spec.yaml>
faultline replay artifacts/runs/<run-folder> --spec <replay-spec.yaml> --expect fixed
```

Stop cancels the active Job, waits for its terminal state and settles measured
time (or zero if it never started), leaving the run resumable. On expired
Nebius sign-in, authenticate again before `--resume`; the coordinator
reattaches to submitted Jobs so an uncertain submission is not duplicated.
After an interruption, inspect the run ledger and actual Job state before
starting another paid action. A quota error needs the specific quota or stale
resource to be resolved; never delete another account's resources merely to
continue. Downloaded evidence and temporary access must be checked after a
run. If cleanup is uncertain, verify the exact Job is terminal and review
remaining storage/access costs before another run.

Replay currently supports **scenario cases only**. It reruns both the minimal
failure and passing reference five times each; `--expect reproduces` or
`--expect fixed` makes its exit status useful in a regression check. Audit
and paraphrase cases are inspectable but have no replay command yet. A replay
spec can name a different compatible `policy.checkpoint`.

## Static gallery and front end

The public [gallery](https://faultline-robotics-debugger.vercel.app) is live.
Its [publication record](../experiments/m7-public-gallery.md) documents the
reviewed evidence scope, missing media/interpretation limitations, visitor
checks and regeneration/deployment commands. It is not a hosted execution
service; keep local run controls and credentials out of future deployments.

```bash
faultline export --out artifacts/<fresh-gallery-dir>
npm --prefix web ci
npm --prefix web run typecheck
npm --prefix web test -- --run
npm --prefix web run build
```

`export` selects finished cases and produces static data/media plus the
committed React bundle. Inspect the exact output for omitted cases, media
availability and private IDs/paths before publication. It has no Python
backend, provider calls, session token or run controls. `npm --prefix web run
dev:mock` previews the front end with mock data. Node 24 is used for web
development; users of the committed bundle need only Python. Building the
web app rewrites `src/robot_debug/viewer/app/`; CI checks that the committed
bundle matches its source. Public hosting is a separate authorized step,
never implied by running `export`.

## Local verification and historical operations

```bash
PYTHONPATH=src python -B -m unittest discover -s tests
npm --prefix web run typecheck
npm --prefix web test -- --run
npm --prefix web run build
git diff --check
```

On PowerShell, set `$env:PYTHONPATH = 'src'` and run `py -3.11 -B -m unittest
discover -s tests` instead of the POSIX first line. Python tests use fake
providers and do not provision resources. The October 17 control-panel
integration reported 2,851 Python tests with platform skips, and the
front-end suite had 175 passing tests; these are dated evidence, not fixed
expected totals. CI is authoritative for its tested commit.

The old VM pilot, M3 parallel/batch benchmarks, watchdog and synthetic
portfolio procedures are historical experiments, not today's diagnosis
setup. See `docs/experiments/m3-parallel.md`,
`docs/experiments/m3-batched-inference.md` and their linked run notes before
interpreting throughput or cost. Do not restart old VMs or live experiments
from their notes without a fresh decision and cap. Use Conventional Commits,
stage explicit related paths, and leave ignored artifacts and secrets out
of Git.
