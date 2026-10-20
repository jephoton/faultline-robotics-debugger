import { Link } from 'react-router-dom';
import { useAppData, useControls } from '../api/context';
import type { LibraryItem } from '../api/types';
import { Icon } from '../components/Icon';
import { StatusBadge } from '../components/StatusBadge';
import { suiteLabel, usd } from '../lib/format';
import { useDocumentTitle } from '../lib/useDocumentTitle';

const LOOP = [
  { title: 'Find', text: 'Search for a robot-policy failure inside a fixed compute budget.' },
  { title: 'Confirm', text: 'Run it again to check that it repeats, not that it happened once.' },
  { title: 'Reduce', text: 'Shrink the triggering condition to the smallest change that still fails.' },
  { title: 'Replay', text: 'Keep it as a case you can rerun after changing the policy.' },
];

function Intro() {
  return (
    <section className="panel intro" aria-labelledby="intro-title">
      <h2 id="intro-title">What Faultline does</h2>
      <ol className="loop">
        {LOOP.map((step, index) => (
          <li key={step.title}>
            <span className="loop__num mono">{index + 1}</span>
            <span>
              <strong>{step.title}.</strong> {step.text}
            </span>
          </li>
        ))}
      </ol>
      <p className="muted">
        Cases cover the disturbances tested and the reruns made, not every failure mode. A reduced cause is the smallest one found, not
        proof of causation.
      </p>
    </section>
  );
}

function CaseCard({ item }: { item: LibraryItem }) {
  return (
    <li className="card">
      <p className="card__code mono">{item.fault_code}</p>
      <h3>
        <Link to={`/case/${encodeURIComponent(item.id)}`}>{item.name}</Link>
      </h3>
      <p>
        <StatusBadge verdict={item.verdict} attention={item.attention} />
      </p>
      <p className="muted">{item.verdict_text}</p>
      <p className="card__meta muted">
        {item.suite ? `${suiteLabel(item.suite)} task ${item.task_id ?? '?'}` : ''}
      </p>
    </li>
  );
}

export function HomePage() {
  useDocumentTitle(null);
  const { session, items, runs, libraryState } = useAppData();
  const controls = useControls();
  const isStatic = session.mode === 'static';

  if (isStatic) {
    return (
      <section>
        <h1>Faultline</h1>
        <p className="lede">A gallery of diagnoses of a robot policy: what failed, how often, the smallest change that causes it, and how it was made.</p>
        <Intro />
        {libraryState === 'loading' && <p role="status">Loading the cases.</p>}
        {libraryState === 'error' && <p className="empty">The cases could not be loaded.</p>}
        <section className="section" aria-labelledby="home-cases">
          <h2 id="home-cases">Cases</h2>
          <ul className="cards">
            {items.map((item) => (
              <CaseCard key={item.id} item={item} />
            ))}
          </ul>
        </section>
      </section>
    );
  }

  return (
    <section>
      <h1>Faultline</h1>

      {runs.length > 0 && (
        <section className="section" aria-labelledby="home-running">
          <h2 id="home-running">Running now</h2>
          <ul className="cards">
            {runs.map((run) => (
              <li className={run.attention ? 'card card--attention' : 'card'} key={run.run}>
                <h3>
                  <Link to={`/run/${encodeURIComponent(run.run)}`}>{run.name}</Link>
                </h3>
                <p>
                  <Icon name={run.attention ? 'attention' : 'clock'} /> {run.status === 'stopping' ? 'Stopping' : 'Running'}
                  {run.step ? `: ${run.step}` : ''}
                </p>
                {run.spent_usd !== null && (
                  <p className="muted mono">
                    {usd(run.spent_usd)}
                    {run.cap_usd !== null ? ` of ${usd(run.cap_usd)}` : ''}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="section" aria-labelledby="home-cases">
        <h2 id="home-cases">Cases</h2>
        {libraryState === 'loading' && <p role="status">Loading the cases.</p>}
        {libraryState === 'error' && <p className="empty">The cases could not be loaded.</p>}
        {libraryState === 'ready' && items.length === 0 && (
          <p className="empty">No cases yet.</p>
        )}
        {items.length > 0 && (
          <ul className="cards">
            {items.map((item) => (
              <CaseCard key={item.id} item={item} />
            ))}
          </ul>
        )}
      </section>

      {controls && (
        <p>
          <Link to="/new" className="btn">
            <Icon name="plus" /> New diagnosis
          </Link>
        </p>
      )}
      <Intro />
    </section>
  );
}
