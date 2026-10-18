import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ApiError } from '../../api/client';
import { useApi, useAppData } from '../../api/context';
import type { DryRun, ImportFile } from '../../api/types';
import { usd } from '../../lib/format';
import { MODE_LABEL } from '../../lib/status';
import { useAsync } from '../../lib/useAsync';
import { asksForResearch, asksForRewordings, usesNemotron, yamlValue } from '../../lib/specYaml';
import { Icon } from '../Icon';
import { DryRunTable, EnvironmentList, type DiagnosisSource } from './Review';
import { PIPELINE_PROMISE } from './StepChoose';

interface Props {
  yaml: string;
  importFile: ImportFile | null;
  /** Starts the run for a fresh dry run of the same spec; resolves with the run folder name. */
  launch: (plan: DryRun) => Promise<{ run: string }>;
  /** Label of the confirm button, for example "Start diagnosis" or "Start replay". */
  startLabel?: string;
  /** The sentence above the confirm button about cost. */
  consequence?: string;
  /** Heading level of the three sections, so the page's outline stays in order. */
  headingLevel?: 2 | 3 | 4;
}

/** What the diagnose spec checks, for the review facts. */
function describeSource(yaml: string): { source: DiagnosisSource; text: string } {
  const range = /screen:\s*\{[^}]*starts:\s*"?([^",}]+)/.exec(yaml);
  if (range) return { source: 'screen', text: `a range of starts (${range[1]})` };
  const file = /^\s*import:\s*(\S+)/m.exec(yaml);
  if (file) return { source: 'import', text: `your start file (${(file[1] as string).replace(/^["']|["']$/g, '')})` };
  return { source: 'start', text: `benchmark start ${yamlValue(yaml, 'start') ?? '?'}` };
}

export function StepReview({
  yaml,
  importFile,
  launch,
  startLabel = 'Start diagnosis',
  consequence = 'Starting creates cloud Jobs on your Nebius account and spends real credit, up to the worst case above. You can stop a run at any time.',
  headingLevel = 2,
}: Props) {
  const Heading = `h${headingLevel}` as 'h2' | 'h3' | 'h4';
  const api = useApi();
  const navigate = useNavigate();
  const { refreshRuns } = useAppData();
  const plan = useAsync(() => api.dryRun(yaml, importFile ?? undefined), [api, yaml, importFile?.content]);
  const env = useAsync(() => api.environment(), [api]);
  const [problems, setProblems] = useState<string[]>([]);
  const [starting, setStarting] = useState(false);
  // A start that timed out or failed on the server may still have launched the run: never offer Start again
  // from this page, so one click cannot become two paid runs.
  const [uncertain, setUncertain] = useState(false);

  const mode = yamlValue(yaml, 'mode') ?? 'scenario';
  const checking = mode === 'diagnose' ? describeSource(yaml) : null;
  const check = (key: string) => env.data?.checks.find((entry) => entry.key === key);

  function blockers(): string[] {
    const list: string[] = [];
    if (plan.loading) list.push('The dry run is still running. Wait a moment and try again.');
    else if (plan.error) {
      list.push(plan.error.message);
      if (plan.error instanceof ApiError) for (const error of plan.error.errors) list.push(`${error.path || 'spec'}: ${error.message}`);
    } else if (plan.data) {
      // Only the first Job must fit: the run reserves each Job's worst case just before submitting it.
      const first = plan.data.jobs[0];
      if (first && first.worst_case_usd > plan.data.cap_usd) {
        list.push(
          `Even the first Job could cost up to ${usd(first.worst_case_usd)}, above your ${usd(plan.data.cap_usd)} cap, so nothing could run. Raise the spend cap.`,
        );
      }
    }
    const nebius = check('nebius_cli');
    if (nebius && !nebius.ok) list.push('You are not signed in to Nebius. Sign in, then start (see Setup for how).');
    const key = check('token_factory_key');
    if (key && !key.ok && usesNemotron(yaml)) {
      list.push(
        mode === 'paraphrase'
          ? 'Rewordings are written by Nemotron, which needs NEBIUS_API_KEY in your .env file (see Setup).'
          : asksForRewordings(yaml)
            ? 'Rewordings are written by Nemotron, which needs NEBIUS_API_KEY in your .env file (see Setup). Add the key, or go back and set the rewordings to 0 (and turn Nemotron off).'
            : /nemotron:\s*\{[^}]*(hypothesis|explain):\s*true/.test(yaml)
              ? 'Nemotron needs NEBIUS_API_KEY in your .env file (see Setup). Add the key, or go back and turn Nemotron off.'
              : 'The research summary is written by Nemotron, which needs NEBIUS_API_KEY in your .env file (see Setup). Add the key, or go back and turn Find related research off.',
      );
    }
    const tavily = check('tavily_key');
    if (tavily && !tavily.ok && asksForResearch(yaml)) {
      list.push('Related research needs a Tavily key (TAVILY_API_KEY) in your .env file (see Setup). Add the key, or go back and turn Find related research off.');
    }
    return list;
  }

  async function start() {
    if (starting || uncertain) return;
    const found = blockers();
    setProblems(found);
    if (found.length > 0 || !plan.data) return;
    setStarting(true);
    try {
      const result = await launch(plan.data);
      refreshRuns();
      navigate(`/run/${encodeURIComponent(result.run)}`);
    } catch (error) {
      refreshRuns();
      if (mayHaveStarted(error)) {
        setUncertain(true);
        setProblems([
          'The run may have started even though this page did not hear back. Check Running in the sidebar ' +
            'before starting anything again; it appears there within a minute if it started.',
        ]);
        return;
      }
      setProblems([error instanceof ApiError ? error.message : 'The run could not be started.']);
      setStarting(false);
    }
  }

  return (
    <div className="review">
      <section aria-labelledby="review-what">
        <Heading id="review-what">What will run</Heading>
        {checking && <p>{PIPELINE_PROMISE}</p>}
        <dl className="facts">
          <dt>Name</dt>
          <dd className="mono">{yamlValue(yaml, 'name') ?? 'not set'}</dd>
          <dt>Kind</dt>
          <dd>{MODE_LABEL[mode] ?? mode}</dd>
          {checking && (
            <>
              <dt>Checking</dt>
              <dd>{checking.text}</dd>
            </>
          )}
          {/suite:\s*(\w+)/.exec(yaml) && (
            <>
              <dt>Suite and task</dt>
              <dd>
                {/suite:\s*(\w+)/.exec(yaml)?.[1]}, task {yamlValue(yaml, 'task') ?? '?'}
              </dd>
            </>
          )}
        </dl>
        <details>
          <summary>Show the spec</summary>
          <pre>{yaml}</pre>
        </details>
      </section>

      <section aria-labelledby="review-plan">
        <Heading id="review-plan">Dry run</Heading>
        <div aria-live="polite">
          {plan.loading && <p className="muted">Working out the plan.</p>}
          {plan.error && (
            <div className="notice notice--alarm" role="alert">
              <Icon name="alarm" />
              <div className="notice__body">
                <p className="notice__title">The dry run could not be made</p>
                <p>{plan.error.message}</p>
                {plan.error instanceof ApiError && plan.error.errors.length > 0 && (
                  <ul>
                    {plan.error.errors.map((error) => (
                      <li key={`${error.path}-${error.message}`}>
                        <code>{error.path || 'spec'}</code> {error.message}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
          {plan.data && <DryRunTable plan={plan.data} source={checking?.source} headingLevel={headingLevel} />}
        </div>
      </section>

      <section aria-labelledby="review-env">
        <Heading id="review-env">This machine</Heading>
        {env.loading && <p className="muted">Checking sign-in and keys.</p>}
        {env.error && <p className="muted">The environment could not be checked ({env.error.message}). You can still try to start.</p>}
        {env.data && <EnvironmentList environment={env.data} />}
        <p className="muted">
          <Link to="/setup">Open Setup</Link> for how to fix anything above.
        </p>
      </section>

      {problems.length > 0 && (
        <div className="notice notice--attention" role="alert">
          <Icon name="attention" />
          <div className="notice__body">
            <p className="notice__title">Not started yet</p>
            <ul>
              {problems.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <p className="review__confirm">
        {consequence}
      </p>
      {uncertain ? (
        <p className="muted">Start is off on this page for safety. Open Running in the sidebar to follow the run.</p>
      ) : (
        <button type="button" className="btn" onClick={() => void start()} aria-busy={starting} data-testid="start-diagnosis">
          <Icon name="play" /> {startLabel}
        </button>
      )}
    </div>
  );
}

/** A refusal (4xx) means nothing started; a timeout, a lost connection or a server error might not. */
function mayHaveStarted(error: unknown): boolean {
  if (!(error instanceof ApiError)) return true;
  return error.status === 0 || error.status >= 500;
}
