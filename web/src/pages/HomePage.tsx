import { Link } from 'react-router-dom';
import { useAppData, useControls } from '../api/context';
import type { LibraryItem } from '../api/types';
import { Icon } from '../components/Icon';
import { StatusBadge } from '../components/StatusBadge';
import { shortDate, suiteLabel, usd } from '../lib/format';
import { KIND_GROUP, KIND_LABEL } from '../lib/status';
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
      <p className="lede lede--tight">
        Faultline finds a failure of a robot policy, confirms that it repeats, reduces it to its cause and saves it as a replayable case.
      </p>
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
        Each case below was made by one diagnosis of a GR00T policy on LIBERO tasks. It describes the disturbances that were tested and
        the reruns that were made; it does not claim every failure mode, and a reduced cause is the smallest one found, not proof of
        causation.
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
        {KIND_LABEL[item.kind]}
        {item.suite ? `, ${suiteLabel(item.suite)} task ${item.task_id ?? '?'}` : ''}
      </p>
    </li>
  );
}

export function HomePage() {
  useDocumentTitle(null);
  const { session, items, runs, libraryState } = useAppData();
  const controls = useControls();
  const isStatic = session.mode === 'static';
  const latest = [...items].filter((item) => item.created).sort((a, b) => String(b.created).localeCompare(String(a.created)))[0] ?? items[0];

  if (isStatic) {
    return (
      <section>
        <h1>Faultline</h1>
        <p className="lede">A gallery of diagnoses of a robot policy: what failed, how often, the smallest change that causes it, and how it was made.</p>
        <Intro />
        {libraryState === 'loading' && <p role="status">Loading the cases.</p>}
        {libraryState === 'error' && <p className="empty">The cases could not be loaded.</p>}
        {KIND_GROUP.map((group) => {
          const rows = items.filter((item) => item.kind === group.kind);
          if (rows.length === 0) return null;
          return (
            <section className="section" key={group.kind} aria-labelledby={`home-${group.kind}`}>
              <h2 id={`home-${group.kind}`}>{group.title}</h2>
              <ul className="cards">
                {rows.map((item) => (
                  <CaseCard key={item.id} item={item} />
                ))}
              </ul>
            </section>
          );
        })}
        <p className="muted">
          Want to run one yourself? <Link to="/guide">Read how to run your own</Link>.
        </p>
      </section>
    );
  }

  return (
    <section>
      <h1>Faultline</h1>
      <p className="lede">Find a robot-policy failure, confirm it repeats, reduce it to its cause and keep it as a replayable test.</p>

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

      <section className="section" aria-labelledby="home-latest">
        <h2 id="home-latest">Latest case</h2>
        {libraryState === 'loading' && <p role="status">Loading the cases.</p>}
        {libraryState === 'error' && <p className="empty">The cases could not be loaded.</p>}
        {libraryState === 'ready' && !latest && (
          <p className="empty">
            No cases yet. {controls ? 'Start a diagnosis to make the first one.' : 'Cases appear here after a diagnosis finishes.'}
          </p>
        )}
        {latest && (
          <ul className="cards">
            <CaseCard item={latest} />
          </ul>
        )}
        {latest && (
          <p className="muted">
            Made {shortDate(latest.created)}. Every case is listed in the sidebar.
          </p>
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
