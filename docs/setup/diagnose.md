# Quickstart: run a diagnosis with `faultline`

`faultline diagnose SPEC.yaml` runs one whole diagnosis on Nebius AI Cloud
Serverless Jobs (or, untested, on a local NVIDIA GPU) and leaves a report, a
case for the control panel, and a spend ledger. Design: ADR 0031. Everything
below can also be done from the control panel (`faultline ui`, step 7).

The first-time setup is mostly the roughly 20 GB image build and push. The dry
run (step 5) prints every Job's worst-case cost before anything is created.

## 1. Prerequisites

- **Python 3.10 or 3.11** and this repository:
  `pip install -e ".[cli,cloud]"` (PyYAML, boto3, truststore). The package
  pins NumPy 1.24, which has no wheels for Python 3.12 or later.
- **Docker**, to build the simulator image. On Windows, run Docker and the
  `nebius` CLI from the same environment (Git Bash, or WSL).
- The [Nebius CLI](https://docs.nebius.com/cli/) signed in to a project
  (`nebius iam whoami` works). The interactive sign-in expires after about a
  day; if a run stops with "sign-in has expired", sign in again and use
  `--resume` (step 6).
- **L40S Serverless quota** in that project. Faultline asks for one
  `gpu-l40s-a` GPU with the `1gpu-16vcpu-64gb` preset per Job. Check your
  quota in the Nebius console, or with the CLI's quota commands
  (`nebius quotas --help`), before you start. If GPUs are scarce, a Job waits
  and is resubmitted automatically (step 5).
- **Hugging Face access** (step 2 below).
- For Nemotron hypotheses, explanations and paraphrases: a Nebius Token
  Factory key in a local `.env` file as `NEBIUS_API_KEY=...` (never commit it;
  it stays on your machine and never enters a Job). Without it, use `--no-llm`.
  Rewordings (paraphrase mode, or `diagnose.probes.rewordings` above 0) need
  the key: `--no-llm` with rewordings is refused up front, before anything is
  spent.

## 2. Hugging Face: accept the gated model terms and store a token

GR00T loads NVIDIA's gated **Cosmos-Reason2-2B** model at run time, so every
Job needs a Hugging Face token whose account has accepted its terms. Without
that the Job's first observation fails with an HTTP 403.

1. Sign in to Hugging Face in a browser **with the account you will make the
   token on**, open
   [nvidia/Cosmos-Reason2-2B](https://huggingface.co/nvidia/Cosmos-Reason2-2B)
   and accept the terms. Details: [model-access.md](model-access.md).
2. Create a **read** token for that account.
3. Store the token as a **MysteryBox secret** in your Nebius project. The
   secret's name is what the spec calls `hf_token_secret` (for example
   `faultline-hf-token`), and its value is the token. Create it in the Nebius
   console (MysteryBox, Secrets). Add the key `HF_TOKEN` with the token as
   its secret value. This avoids putting the token in terminal history or
   process arguments.

   Never put the token in a spec or a chat. Faultline looks the secret up by
   name and hands the Job only its id, injected as the `HF_TOKEN` environment
   variable (`--env-secret HF_TOKEN=<secret>`).

The GR00T checkpoints are public and the Cosmos revision is pinned by
Faultline; the token only needs read access.

## 3. Registry and simulator image

Create a private Nebius container registry once, sign Docker in to it, then
build and push the image from the **repository root** (the build needs the
repository as its context):

```bash
nebius registry create --parent-id <your-project-id> --name faultline   # note the registry id
nebius iam get-access-token | docker login cr.<region>.nebius.cloud --username iam --password-stdin
faultline image build --push cr.<region>.nebius.cloud/<your-registry-id>
```

(`<region>` is your project's region, for example `eu-north1`; run
`nebius registry --help` if the create flags differ in your CLI version.) The
Docker sign-in uses a short-lived token, so repeat the `docker login` line if
a push is refused as unauthorised.

The build prints the pushed `repository@sha256:...` reference to put in your
spec. It is about 20 GB, so the first push takes a while. Faultline does not
publish a public image yet, and `faultline image push` refuses public
registries. Model weights are never in the image.

## 4. Write a spec

Copy one of the examples in `configs/specs/` and fill in your own values
(`project`, `image`, `hf_token_secret`):

| Example | What it does |
| --- | --- |
| `diagnose.yaml` | Recommended: check untouched, reduce a reliable layout failure or probe a passing start |
| `scenario-start.yaml` | Layout-only diagnosis of a known failing benchmark start |
| `scenario-screen.yaml` | Search a range of starts for a reliable layout failure |
| `scenario-import.yaml` | Diagnose a failing start-state file for an existing task |
| `audit.yaml` | Disturbance probes only, with controls and severity search |
| `paraphrase.yaml` | Rewording probes only, confirming and reducing any faithful failing wording |
| `replay.yaml` | Settings for `faultline replay` |

Every spec needs `budget.max_spend_usd` and `budget.max_hours`. Keep specs
with real ids out of version control. Two spec options are worth knowing:

**Bring your own failing start (`diagnose.import`).** A diagnosis takes exactly one
of `start` (a benchmark start index), `screen` (a range to search) or `import`
(a file of your own):

```yaml
diagnose:
  task: 0
  import: my-failing-start.json
```

The file is a JSON start-state candidate for one LIBERO suite and task (its
suite, task id and one flat simulator state vector; the exact fields are
checked by `src/robot_debug/scenario_import.py`, which rejects anything
malformed, oversized or from a different scene). Faultline confirms your start
fails at least 4 of 5 attempts, finds the nearest benchmark start that passes,
and reduces the differences between them.

**Test a different checkpoint (`policy.checkpoint`).** By default a Job serves
the pinned GR00T N1.7 checkpoint for the spec's suite. To diagnose or replay
against a retrained or fine-tuned policy, name it:

```yaml
policy:
  suite: libero_10
  checkpoint: {id: your-org/your-checkpoint, revision: <commit sha>}
```

The checkpoint is downloaded with your Hugging Face token, so the token's
account needs access to it. Faultline does not check that it is compatible
with the suite.

## 5. Dry run, then run

```bash
faultline diagnose my-spec.yaml --dry-run
faultline diagnose my-spec.yaml --env-file .env
```

The dry run lists every planned Job with its deadline and worst-case cost and
creates nothing. A real run prints one line per step with the spend so far.
Before each Job Faultline reserves a worst case: the provider timeout
(deadline plus ten minutes) plus a four-minute start allowance, at the hourly
rate in the spec. That is our understanding of how Serverless bills; it has
not yet been reconciled against a Nebius bill, so treat the cap as a safety
limit rather than a guarantee. The reservation is settled at the measured
container time, and the run refuses a Job that could exceed the cap. When no
GPU is free, the Job is resubmitted automatically (up to six times).

Results land in `artifacts/runs/<name>-<timestamp>/`: `report.md`,
`case.json`, `ledger.json`, the downloaded evidence per Job, and an
explanation when enabled. Optional Tavily research and Nemotron next steps
are interpretations, not robot evidence. The wording check detects missing
object/target words, not arbitrary meaning drift: generated wording still
needs review. It is not a semantic-equivalence proof.

## 6. Resume, replay and list

```bash
faultline diagnose --resume artifacts/runs/<run-folder>
faultline replay artifacts/runs/<run-folder> --spec my-replay.yaml
faultline replay artifacts/runs/<run-folder> --spec my-replay.yaml --expect fixed
faultline cases
```

`--resume` continues an interrupted run with the same spec: it re-attaches to
Jobs it already submitted and replaces a worst-case charge with measured time
once it can read the Job. It may submit later planned Jobs; Resume is not
always free. A failed download retries downloading, not the experiment.

`replay` tests a saved failing case: the retained layout/reference, failing
disturbance thresholds/controls, or failing wording/original control. It
reports whether the failure still repeats; incomplete results or failing
controls are inconclusive. Add `policy.checkpoint` to the replay
spec to run the case against a different checkpoint. `--expect reproduces`
or `--expect fixed` states which verdict you are hoping for, so the exit code
tells a script whether you got it (use `fixed` after a change meant to cure
the failure).

## 7. The control panel

```bash
faultline ui --open
```

The control panel at <http://127.0.0.1:8765> wraps these commands:

- **Setup** checks the Nebius sign-in, the Token Factory key (presence only)
  and the backend block of a local spec (image and secret name).
- **New diagnosis** builds the spec from a form (or edit its YAML directly),
  validates it, shows the dry run and starts the run only after you confirm.
  It reuses the `backend` block of a spec in `artifacts/specs-local/`, and
  saves each spec it writes under `artifacts/specs-ui/`.
- **The run page** follows a run live (steps, the Job's state, spend against
  the cap, time against the limit) with **Stop** and **Resume**. Stop is the
  same as `faultline stop <run-folder>`: the current Job is cancelled, charged
  for the time it ran, and `--resume` continues on a new Job.
- **Case pages** show each finished diagnosis: the result, the evidence for
  its kind, how it was made, Nemotron's reading, the report and files, and
  the **Regression test** for supported saved failing cases.

The panel listens on 127.0.0.1 only and starts one paid run at a time.
`faultline export --out <folder>` writes the finished cases as a static
gallery with no controls.

## Notes

- Costs: a typical Job is US$0.3–0.9 on one L40S at about US$1.75/hour;
  about 10 minutes of each Job is image pull and model download. Figures are
  estimates from measured container time, pending billing reconciliation.
- **Bucket quota.** Each diagnosis uses one Object Storage bucket whose
  objects expire after a day. Tenants have a bucket access-policy quota (10 on
  ours, which stopped a run once), so delete emptied buckets from time to time.
- The local backend (`backend: {kind: local}`) needs Docker with the NVIDIA
  runtime and a large GPU; it is implemented but untested on a real GPU.
