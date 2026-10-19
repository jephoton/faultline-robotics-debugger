import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

const DOCS = 'https://github.com/jephoton/faultline-robotics-debugger/blob/main/docs/';

function Code({ children }: { children: string }) {
  return <pre><code>{children}</code></pre>;
}

export interface GuideSection {
  id: string;
  title: string;
  body: ReactNode;
}

export const GUIDE: GuideSection[] = [
  {
    id: 'view', title: '1. Preview without cloud access',
    body: <>
      <p>To inspect the bundled case, install with Python 3.10 or 3.11 and run:</p>
      <Code>{`python -m pip install -e ".[cli,cloud]"
faultline ui --artifacts demo/root --open`}</Code>
      <p>No cloud credentials are needed to read saved evidence. The published gallery is read-only; paid controls require your local server.</p>
      <p><a href={`${DOCS}ui-runbook.md`}>UI walkthrough and demo scenarios</a> gives exact clicks and outcomes. <Link to="/reference">Reference</Link> explains counts, severity and verdicts.</p>
    </>,
  },
  {
    id: 'prerequisites', title: '2. Prepare your account',
    body: <>
      <p>Paid diagnoses need the Nebius CLI, an active AI Cloud project and balance, L40S Serverless quota, a private simulator image and model access. Docker is needed to build the image, not to browse results.</p>
      <p>Sign in from a terminal with <code>nebius iam whoami</code>. Check project/region, balance/expiry, quota, resource prices and your intended cap before Start. Setup checks local readiness, not the full cloud allowance.</p>
      <p>Use Python 3.10/3.11 for the pinned NumPy version. On Windows, the CLI can use WSL; sign in in the environment Faultline uses.</p>
      <p><a href={`${DOCS}setup/diagnose.md`}>Detailed setup and CLI quickstart</a> has infrastructure commands. Optional keys belong in ignored <code>.env</code>: <code>NEBIUS_API_KEY</code> for Nemotron and <code>TAVILY_API_KEY</code> for research. Never put keys in YAML or Git.</p>
    </>,
  },
  {
    id: 'huggingface', title: '3. Hugging Face model access',
    body: <>
      <p>Use the same account to accept required model terms and create a read token. GR00T loads gated <a href="https://huggingface.co/nvidia/Cosmos-Reason2-2B">Cosmos-Reason2-2B</a> at runtime; missing access can fail the first observation.</p>
      <p>Store the token in a MysteryBox secret using your Nebius console. Put only its <strong>name</strong> in <code>backend.hf_token_secret</code>. The secret is injected into the Job, not copied into YAML. See <a href={`${DOCS}setup/model-access.md`}>model access instructions</a>.</p>
    </>,
  },
  {
    id: 'image', title: '4. Registry and simulator image',
    body: <>
      <p>Build and push once to a private Nebius registry, from the repository root. The first upload is large. Model weights are downloaded at runtime, not bundled.</p>
      <Code>{`faultline image build --push cr.<region>.nebius.cloud/<your-registry-id>`}</Code>
      <p>Follow the quickstart for registry creation and Docker sign-in. Put the printed pinned image reference in your local spec. Renew stale registry login if needed; do not disable TLS verification.</p>
    </>,
  },
  {
    id: 'spec', title: '5. Configure one diagnosis',
    body: <>
      <p>Copy <code>configs/specs/diagnose.yaml</code> into <code>artifacts/specs-local/</code>. Fill project, pinned image and Hugging Face secret name. Keep account-specific specs ignored. New diagnosis reuses that backend block and saves YAML under <code>artifacts/specs-ui/</code>.</p>
      <ol>
        <li>Choose suite, task and benchmark start. Verify your evaluator&apos;s episode-to-start mapping.</li>
        <li>Select disturbances and optional rewordings for a passing start. A reliable untouched failure instead takes layout reduction; a flaky start stops.</li>
        <li>Set the spend cap and hour limit, then Review. Inspect YAML for exact inputs.</li>
      </ol>
      <p>Range search and imported start-state files seek a layout failure only. Imports must match an existing LIBERO task, not arbitrary video. Rewordings require Nemotron; optional research needs Tavily. Missing research never blocks diagnosis.</p>
    </>,
  },
  {
    id: 'run', title: '6. Dry run, then run',
    body: <>
      <Code>{`faultline diagnose my-spec.yaml --dry-run
faultline diagnose my-spec.yaml --env-file .env`}</Code>
      <p>Review lists Jobs, deadlines and estimates without starting compute. Inspect both possible branches; only one runs after the check. Start requires the first Job to fit. A later Job may stop at the cap.</p>
      <p><strong>Start spends money.</strong> Token Factory and storage are outside the Job cap, as is optional Tavily research. Reservations guard estimated Job cost, not the account bill; reconcile with billing.</p>
      <p>Follow progress in Running. Evidence stays in <code>artifacts/runs/&lt;run-folder&gt;/</code>; finished findings appear in Cases. No failure found is a valid result, not a reason to Resume.</p>
    </>,
  },
  {
    id: 'resume', title: '7. Stop, recover and test a case again',
    body: <>
      <Code>{`faultline stop artifacts/runs/<run-folder>
faultline diagnose --resume artifacts/runs/<run-folder>
faultline replay artifacts/runs/<run-folder> --spec my-replay.yaml --expect fixed`}</Code>
      <p>Stop requests cancellation and keeps resumable progress. Closing the browser/restarting the panel does not stop the detached diagnosis. Resume reattaches to a recorded Job; a failed download retries downloading rather than the experiment. It may submit later Jobs, so is not always free.</p>
      <p>Renew expired sign-in in a terminal first. For a cap/time stop, inspect saved progress before raising limits for more paid work. Do not launch a second diagnosis as a recovery shortcut.</p>
      <p>For a saved failure, choose Regression test and the original policy or a compatible checkpoint&apos;s Hugging Face ID and exact revision; Review, then confirm the paid test. The original policy needs no replacement ID. New checkpoints need supported GR00T N1.7 LeRobot format; compatibility is not established automatically.</p>
      <p>CLI overrides go under <code>policy.checkpoint</code>. <code>--expect fixed</code> or <code>--expect reproduces</code> checks a verdict in CI. <Link to="/reference#md-8-replay-verdicts">Replay verdicts</Link> explains the outcomes.</p>
      <p>The <a href={`${DOCS}codex-handoff/RUNBOOK.md`}>operator runbook</a> covers recovery. Local GPU execution remains unvalidated on real hardware. Storage object expiry does not remove buckets; clean up only resources you own after preserving evidence.</p>
    </>,
  },
];
