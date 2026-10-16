import { Link, NavLink } from 'react-router-dom';
import type { LibraryItem, RunSummary, Session } from '../api/types';
import { KIND_GROUP, statusFor } from '../lib/status';
import { usd } from '../lib/format';
import { Icon, Mark, type IconName } from './Icon';
import { ThemeToggle } from './ThemeToggle';

export type LoadState = 'loading' | 'ready' | 'error';

interface Props {
  session: Session;
  items: LibraryItem[];
  runs: RunSummary[];
  libraryState: LoadState;
  onNavigate?: () => void;
}

function CaseRow({ item, onNavigate }: { item: LibraryItem; onNavigate?: () => void }) {
  const status = statusFor(item.verdict, item.attention);
  const bar = status.tone === 'neutral' ? '' : ` nav-item--${status.tone}`;
  return (
    <li>
      <NavLink to={`/case/${item.id}`} className={`nav-item${bar}`} onClick={onNavigate}>
        <span className="nav-item__name" title={item.name}>
          {item.name}
        </span>
        <span className="nav-item__meta">
          <span className="nav-item__code">{item.fault_code}</span>
          <span className="nav-item__status">
            <Icon name={status.icon} />
            {status.short}
          </span>
        </span>
      </NavLink>
    </li>
  );
}

function RunRow({ run, onNavigate }: { run: RunSummary; onNavigate?: () => void }) {
  const stopping = run.status === 'stopping';
  const tone = run.attention ? ' nav-item--attention' : '';
  const icon: IconName = run.attention ? 'attention' : stopping ? 'stop' : 'clock';
  return (
    <li>
      <NavLink to={`/run/${run.run}`} className={`nav-item${tone}`} onClick={onNavigate}>
        <span className="nav-item__name" title={run.name}>
          {run.name}
        </span>
        <span className="nav-item__meta">
          <span className="nav-item__status">
            <Icon name={icon} />
            {stopping ? 'Stopping' : 'Running'}
            {run.step ? `: ${run.step}` : ''}
          </span>
          {run.spent_usd !== null && <span>{usd(run.spent_usd)}</span>}
        </span>
      </NavLink>
    </li>
  );
}

function FootLink({ to, icon, label, onNavigate }: { to: string; icon: IconName; label: string; onNavigate?: () => void }) {
  return (
    <NavLink to={to} className="nav-item nav-item--plain" onClick={onNavigate}>
      <Icon name={icon} />
      {label}
    </NavLink>
  );
}

export function Sidebar({ session, items, runs, libraryState, onNavigate }: Props) {
  const local = session.mode === 'local';
  return (
    <>
      <Link to="/" className="sidebar__brand" onClick={onNavigate}>
        <Mark />
        Faultline
      </Link>
      {local && session.controls && (
        <Link to="/new" className="btn sidebar__new" onClick={onNavigate}>
          <Icon name="plus" />
          New diagnosis
        </Link>
      )}
      <nav className="sidebar__nav" aria-label="Runs and cases">
        {local && (
          <section className="nav-section" aria-labelledby="nav-running">
            <h2 className="nav-label" id="nav-running">
              Running
            </h2>
            {runs.length === 0 ? (
              <p className="nav-empty">Nothing running.</p>
            ) : (
              <ul className="nav-list">
                {runs.map((run) => (
                  <RunRow key={run.run} run={run} onNavigate={onNavigate} />
                ))}
              </ul>
            )}
          </section>
        )}
        {libraryState === 'loading' && <p className="nav-empty">Loading cases.</p>}
        {libraryState === 'error' && <p className="nav-empty">Cases could not be loaded.</p>}
        {libraryState === 'ready' && items.length === 0 && <p className="nav-empty">No cases yet.</p>}
        {KIND_GROUP.map((group) => {
          const rows = items.filter((item) => item.kind === group.kind);
          if (rows.length === 0) return null;
          const id = `nav-${group.kind}`;
          return (
            <section className="nav-section" aria-labelledby={id} key={group.kind}>
              <h2 className="nav-label" id={id}>
                {group.title}
              </h2>
              <ul className="nav-list">
                {rows.map((item) => (
                  <CaseRow key={item.id} item={item} onNavigate={onNavigate} />
                ))}
              </ul>
            </section>
          );
        })}
      </nav>
      <div className="sidebar__foot">
        {local && <FootLink to="/setup" icon="setup" label="Setup" onNavigate={onNavigate} />}
        <FootLink to="/guide" icon="guide" label="Run your own" onNavigate={onNavigate} />
        {local && <FootLink to="/evidence" icon="evidence" label="All evidence" onNavigate={onNavigate} />}
        <ThemeToggle />
      </div>
    </>
  );
}
