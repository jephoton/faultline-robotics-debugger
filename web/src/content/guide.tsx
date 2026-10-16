import type { ReactNode } from 'react';

// The quickstart (docs/setup/diagnose.md) as a page. Placeholders in angle brackets are for you to fill in;
// nothing here is a real id.

function Code({ children }: { children: string }) {
  return (
    <pre>
      <code>{children}</code>
    </pre>
  );
}

export interface GuideSection {
  id: string;
  title: string;
  body: ReactNode;
}

export const GUIDE: GuideSection[] = [
  {
    id: 'prerequisites',
    title: '1. What you need',
    body: (
      <>
        <ul>
          <li>
            <strong>Python 3.10 or 3.11</strong> and this repository, installed with <code>pip install -e ".[cli,cloud]"</code>. The
            package pins NumPy 1.24, which has no wheels for Python 3.12 or later.
          </li>
          <li>
            <strong>Docker</strong>, to build the simulator image once. On Windows, run Docker and the <code>nebius</code> CLI from the
            same environment (Git Bash, or WSL).
          </li>
          <li>
            The <strong>Nebius CLI</strong>, signed in to a project (<code>nebius iam whoami</code> works). The interactive sign-in
            expires after about a day; if a run stops with &ldquo;sign-in has expired&rdquo;, sign in again and press Resume on the run.
          </li>
          <li>
            <strong>L40S Serverless quota</strong> in that project: one <code>gpu-l40s-a</code> GPU with the{' '}
            <code>1gpu-16vcpu-64gb</code> preset per Job. If GPUs are scarce, a Job waits and is resubmitted automatically, up to six times.
          </li>
          <li>
            <strong>Hugging Face access</strong> (next section).
          </li>
          <li>
            For Nemotron hypotheses, explanations and rewordings, a <strong>Token Factory key</strong> as <code>NEBIUS_API_KEY=...</code>{' '}
            in a local <code>.env</code> file. Never commit it; it stays on your machine and never enters a Job.
          </li>
        </ul>
      </>
    ),
  },
  {
    id: 'huggingface',
    title: '2. Hugging Face: accept the model terms and store a token',
    body: (
      <>
        <p>
          GR00T loads NVIDIA&rsquo;s gated Cosmos-Reason2-2B model at run time, so every Job needs a Hugging Face token whose account has
          accepted its terms. Without that the first observation fails with an HTTP 403.
        </p>
        <ol>
          <li>Sign in to Hugging Face with the account you will make the token on, open the model page and accept the terms.</li>
          <li>Create a read token for that account.</li>
          <li>
            Store it as a MysteryBox secret in your Nebius project. The secret&rsquo;s name is what a spec calls{' '}
            <code>hf_token_secret</code>. Create it in the Nebius console, or from a bash shell without the token touching your history:
          </li>
        </ol>
        <Code>{`read -rs HF_TOKEN_VALUE   # paste the token, press Enter (nothing is shown)
nebius mysterybox secret create --parent-id <your-project-id> --name faultline-hf-token \\
  --secret-version-payload "[{\\"key\\":\\"HF_TOKEN\\",\\"string_value\\":\\"$HF_TOKEN_VALUE\\"}]"
unset HF_TOKEN_VALUE`}</Code>
        <p>Never put the token in a spec or a chat. Faultline looks the secret up by name and gives the Job only its id.</p>
      </>
    ),
  },
  {
    id: 'image',
    title: '3. Registry and simulator image',
    body: (
      <>
        <p>
          Create a private Nebius container registry once, sign Docker in to it, then build and push the image from the repository
          root. It is about 20 GB, so the first push takes a while. Model weights are never in the image.
        </p>
        <Code>{`nebius registry create --parent-id <your-project-id> --name faultline
nebius iam get-access-token | docker login cr.<region>.nebius.cloud --username iam --password-stdin
faultline image build --push cr.<region>.nebius.cloud/<your-registry-id>`}</Code>
        <p>
          The build prints the pushed <code>repository@sha256:...</code> reference to put in your spec. Repeat the{' '}
          <code>docker login</code> line if a push is refused as unauthorised: that token is short-lived.
        </p>
      </>
    ),
  },
  {
    id: 'spec',
    title: '4. The spec',
    body: (
      <>
        <p>
          The New diagnosis page writes a spec for you and shows it under &ldquo;Edit YAML&rdquo;. It reuses the backend block (project,
          image, secret name) from a local spec file, so keep one with your real values in a copy of an example from{' '}
          <code>configs/specs/</code>, outside version control.
        </p>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th scope="col">Example</th>
                <th scope="col">What it does</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="mono">scenario-start.yaml</td>
                <td>Mode 1 for a known failing benchmark start: screen a reference pool, reduce the failure to the shifts that cause it.</td>
              </tr>
              <tr>
                <td className="mono">scenario-screen.yaml</td>
                <td>Mode 1 that first searches a range of starts for one that fails reliably.</td>
              </tr>
              <tr>
                <td className="mono">scenario-import.yaml</td>
                <td>Mode 1 for a failing start of your own, from a start-state file.</td>
              </tr>
              <tr>
                <td className="mono">audit.yaml</td>
                <td>Mode 2: the smallest image or scene disturbance that breaks a passing start.</td>
              </tr>
              <tr>
                <td className="mono">paraphrase.yaml</td>
                <td>Mode 2 for language: find a rewording that breaks the policy and reduce it to the minimal word change.</td>
              </tr>
              <tr>
                <td className="mono">replay.yaml</td>
                <td>Settings for replaying a saved case.</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p>
          Every spec needs <code>budget.max_spend_usd</code> and <code>budget.max_hours</code>. Two options are worth knowing:
        </p>
        <h3>Bring your own failing start</h3>
        <p>
          Scenario mode takes exactly one of <code>start</code> (a benchmark start index), <code>screen</code> (a range to search) or{' '}
          <code>import</code> (a file of your own):
        </p>
        <Code>{`scenario:
  task: 0
  import: my-failing-start.json`}</Code>
        <p>
          The file is a JSON start-state candidate for one LIBERO suite and task. Faultline rejects anything malformed, oversized or from
          a different scene, confirms your start fails at least 4 of 5 attempts, finds the nearest benchmark start that passes, and
          reduces the differences between them.
        </p>
        <h3>Test a different checkpoint</h3>
        <p>By default a Job serves the pinned GR00T N1.7 checkpoint for the spec&rsquo;s suite. To test a retrained policy, name it:</p>
        <Code>{`policy:
  suite: libero_10
  checkpoint: {id: your-org/your-checkpoint, revision: <commit sha>}`}</Code>
        <p>The checkpoint is downloaded with your Hugging Face token, so that account needs access. Faultline does not check that it fits the suite.</p>
      </>
    ),
  },
  {
    id: 'run',
    title: '5. Dry run, then run',
    body: (
      <>
        <p>
          The dry run lists every planned Job with its deadline and worst-case cost and creates nothing. The control panel always does a
          dry run before it lets you start. From a terminal:
        </p>
        <Code>{`faultline diagnose my-spec.yaml --dry-run
faultline diagnose my-spec.yaml --env-file .env`}</Code>
        <p>
          Before each Job Faultline reserves a worst case: the provider timeout (deadline plus ten minutes) plus a four-minute start
          allowance, at the hourly rate in the spec. The reservation is settled at the measured container time, and the run refuses a
          Job that could exceed the cap. Treat the cap as a safety limit rather than a guarantee: the cost model has not been reconciled
          against a Nebius bill yet. When no GPU is free, the Job is resubmitted automatically.
        </p>
        <p>
          Results land in <code>artifacts/runs/&lt;name&gt;-&lt;timestamp&gt;/</code>: a report, a case, a spend ledger, the downloaded
          evidence and, when Nemotron is on, an explanation.
        </p>
      </>
    ),
  },
  {
    id: 'resume',
    title: '6. Resume, stop and replay',
    body: (
      <>
        <Code>{`faultline diagnose --resume artifacts/runs/<run-folder>
faultline stop artifacts/runs/<run-folder>
faultline replay artifacts/runs/<run-folder> --spec my-replay.yaml --expect fixed`}</Code>
        <p>
          <strong>Resume</strong> continues an interrupted run with the same spec: it re-attaches to Jobs already submitted (never paying
          twice) and replaces a worst-case charge with the measured one once it can read the Job. <strong>Stop</strong> cancels the current
          Job, waits for the provider to confirm, settles the cost and leaves the run resumable.
        </p>
        <p>
          <strong>Replay</strong> re-runs a saved scenario case (its minimal scene and its passing reference, five times each) and reports
          &ldquo;still reproduces&rdquo; or &ldquo;no longer reproduces&rdquo;: the regression test after you change the policy.{' '}
          <code>--expect fixed</code> or <code>--expect reproduces</code> states which verdict you hope for, so the exit code tells a script
          whether you got it. Audit and language cases are not replayed yet.
        </p>
      </>
    ),
  },
  {
    id: 'view',
    title: '7. This control panel',
    body: (
      <>
        <p>Start it from the repository, then open the address it prints:</p>
        <Code>{`faultline ui --artifacts artifacts`}</Code>
        <p>
          It listens on this machine only. Starting, stopping, resuming and replaying are controls of this local server; a published
          gallery of the same pages has none. Each spec the panel runs is saved under <code>artifacts/specs-ui/</code>, so any run can be
          repeated from a terminal.
        </p>
      </>
    ),
  },
  {
    id: 'notes',
    title: 'Notes',
    body: (
      <ul>
        <li>
          <strong>Costs.</strong> A typical Job is roughly US$0.3 to 0.9 on one L40S; about ten minutes of each Job is image pull and model
          download. Figures are estimates from measured container time, pending billing reconciliation.
        </li>
        <li>
          <strong>Bucket quota.</strong> Each diagnosis uses one Object Storage bucket whose objects expire after a day. Tenants have a
          bucket access-policy quota, so delete emptied buckets from time to time.
        </li>
        <li>
          <strong>Local backend.</strong> <code>backend: {'{kind: local}'}</code> needs Docker with the NVIDIA runtime and a large GPU; it is
          implemented but untested on a real GPU.
        </li>
      </ul>
    ),
  },
];
