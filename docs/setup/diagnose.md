# Quickstart: run a diagnosis with `faultline`

`faultline diagnose SPEC.yaml` runs one whole diagnosis on Nebius AI Cloud
Serverless Jobs (or, untested, on a local NVIDIA GPU) and leaves a report, a
case for the viewer, and a spend ledger. Design: ADR 0031.

## 1. Prerequisites

- Python 3.11 and this repository: `pip install -e ".[cli,cloud]"` (PyYAML,
  boto3, truststore). Docker, to build the simulator image.
- The [Nebius CLI](https://docs.nebius.com/cli/) signed in to a project with
  L40S Serverless quota (`nebius iam whoami` works). The interactive sign-in
  expires after about a day; if a run stops with "sign-in has expired", sign
  in again and use `--resume` (below).
- A Hugging Face token stored as a MysteryBox secret in that project (the
  spec's `hf_token_secret`, e.g. `faultline-hf-token`); Jobs download the
  pinned GR00T checkpoints with it.
- For Nemotron hypotheses, explanations and paraphrases: a Nebius Token
  Factory key in a local `.env` file as `NEBIUS_API_KEY=...` (never commit it;
  it stays on your machine and never enters a Job). Without it, use `--no-llm`.

## 2. Build and push the simulator image

```bash
faultline image build --push cr.eu-north1.nebius.cloud/<your-registry-id>
```

It prints the pushed `repository@sha256:...` reference to put in your spec.
(About 20 GB; the first push takes a while.) Faultline does not publish a
public image yet.

## 3. Write a spec

Copy one of the examples in `configs/specs/` and fill in your own values
(`project`, `image`, `hf_token_secret`):

| Example | What it does |
| --- | --- |
| `scenario-start.yaml` | Mode 1 for a known failing start: screen a reference pool, reduce the failure to the shifts that cause it |
| `scenario-screen.yaml` | Mode 1 that first searches for a start that fails reliably |
| `audit.yaml` | Mode 2: the smallest image or scene disturbance that breaks a passing start |
| `paraphrase.yaml` | Mode 2 for language: find a rewording that breaks the policy and reduce it to the minimal word change |
| `replay.yaml` | Settings for `faultline replay` |

Every spec needs `budget.max_spend_usd` and `budget.max_hours`. Keep specs
with real ids out of version control.

## 4. Dry run, then run

```bash
faultline diagnose my-spec.yaml --dry-run
faultline diagnose my-spec.yaml --env-file .env
```

The dry run lists every planned Job with its deadline and worst-case cost and
creates nothing. A real run prints one line per step with the spend so far.
Each Job's worst case is reserved before submission (the provider stops the
Job at deadline + 10 minutes even if your machine sleeps) and settled at the
measured container time; the run refuses a Job that could exceed the cap.
When no GPU is free, the Job is resubmitted automatically (up to six times).

Results land in `artifacts/runs/<name>-<timestamp>/`: `report.md`,
`case.json`, `ledger.json`, the downloaded evidence per Job, and an
explanation when Nemotron is enabled.

## 5. Resume, replay and list

```bash
faultline diagnose --resume artifacts/runs/<run-folder>
faultline replay artifacts/runs/<run-folder> --spec my-replay.yaml
faultline cases
```

`--resume` continues an interrupted run with the same spec: it re-attaches to
Jobs it already submitted (never paying twice) and replaces a worst-case
charge with the measured one once it can read the Job. `replay` re-runs a
saved scenario case (its minimal scene and its passing reference, five times
each) and reports `still reproduces` or `no longer reproduces`: the regression
test after you change the policy.

## 6. View the results

```powershell
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
python -m robot_debug.viewer.server --artifacts artifacts --port 8765
```

Finished diagnoses appear under `/diagnoses` with their report and videos.

## Notes

- Costs: a typical Job is US$0.3–0.9 on one L40S at about US$1.75/hour;
  about 10 minutes of each Job is image pull and model download.
- Each diagnosis uses one Object Storage bucket whose objects expire after a
  day; tenants have a bucket-policy quota (10 on ours), so delete emptied
  buckets from time to time.
- The local backend (`backend: {kind: local}`) needs Docker with the NVIDIA
  runtime and a large GPU; it is implemented but untested on a real GPU.
