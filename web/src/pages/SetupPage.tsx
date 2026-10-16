import { Link } from 'react-router-dom';
import { useApi, useAppData } from '../api/context';
import type { EnvironmentCheck } from '../api/types';
import { Icon } from '../components/Icon';
import { checkLabel } from '../components/new/Review';
import { useAsync } from '../lib/useAsync';
import { useDocumentTitle } from '../lib/useDocumentTitle';
import { LocalOnlyPage } from './NotFoundPage';

// What each check is for and where to read more. The server's own `fix` text (when a check fails) comes first.
const ABOUT: Record<string, { why: string; guide: string }> = {
  nebius_cli: {
    why: 'Faultline runs its GPU work as Nebius Serverless Jobs through the Nebius CLI. The sign-in expires after about a day.',
    guide: 'prerequisites',
  },
  docker: { why: 'Only needed to build the simulator image once. Runs do not need it.', guide: 'image' },
  token_factory_key: {
    why: 'Nemotron hypotheses, explanations and rewordings use a Token Factory key. It stays on this machine and never enters a Job. Presence is checked, the value is never shown.',
    guide: 'prerequisites',
  },
  spec_template: {
    why: 'New diagnoses reuse the backend block (image and secret name) of a local spec. Only names are shown, never ids.',
    guide: 'spec',
  },
};

function CheckCard({ check }: { check: EnvironmentCheck }) {
  const about = ABOUT[check.key];
  return (
    <li className={check.ok ? 'setup-check' : 'setup-check setup-check--attention'}>
      <h2>
        <Icon name={check.ok ? 'check' : 'attention'} /> {checkLabel(check.key)}
        <span className="setup-check__word">{check.ok ? 'Ready' : 'Needs attention'}</span>
      </h2>
      <p>{check.detail}</p>
      {!check.ok && check.fix && (
        <p className="check-row__fix">
          <strong>To fix it:</strong> {check.fix}
        </p>
      )}
      {about && (
        <p className="muted">
          {about.why} <Link to={`/guide#${about.guide}`}>Read the guide</Link>.
        </p>
      )}
    </li>
  );
}

export function SetupPage() {
  const { session } = useAppData();
  if (session.mode !== 'local') return <LocalOnlyPage what="Setup" />;
  return <Setup />;
}

function Setup() {
  useDocumentTitle('Setup');
  const api = useApi();
  const env = useAsync(() => api.environment(), [api]);
  const failing = env.data?.checks.filter((check) => !check.ok).length ?? 0;
  return (
    <section>
      <h1>Setup</h1>
      <p className="lede">What this machine needs before it can start a diagnosis. Nothing here creates or changes anything.</p>
      {env.loading && (
        <p role="status" aria-busy="true">
          Checking. The Nebius sign-in check can take a few seconds.
        </p>
      )}
      {env.error && (
        <div className="notice notice--attention" role="alert">
          <Icon name="attention" />
          <div className="notice__body">
            <p className="notice__title">The checks could not run</p>
            <p>{env.error.message}</p>
          </div>
        </div>
      )}
      {env.data && (
        <>
          <p role="status">
            {failing === 0 ? (
              <>
                <Icon name="check" /> Everything needed is ready.
              </>
            ) : (
              <>
                <Icon name="attention" /> {failing} {failing === 1 ? 'item needs' : 'items need'} attention.
              </>
            )}
          </p>
          <ul className="setup-checks">
            {env.data.checks.map((check) => (
              <CheckCard key={check.key} check={check} />
            ))}
          </ul>
        </>
      )}
      <div className="actions">
        <button type="button" className="btn btn--secondary" onClick={env.reload}>
          <Icon name="restart" /> Check again
        </button>
        <Link to="/guide" className="btn btn--secondary">
          <Icon name="guide" /> Open the guide
        </Link>
      </div>
    </section>
  );
}
