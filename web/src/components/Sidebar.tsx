import { Link, NavLink } from 'react-router-dom';
import type { LibraryItem, RunSummary, Session } from '../api/types';
import { statusFor } from '../lib/status';
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
          <div className="nav-section" role="group" aria-labelledby="nav-running">
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
          </div>
        )}
        {libraryState === 'error' && <p className="nav-empty">Cases could not be loaded.</p>}
        <div className="nav-section" role="group" aria-labelledby="nav-cases">
          <h2 className="nav-label" id="nav-cases">
            Cases
          </h2>
          <ul className="nav-list">
            {items.map((item) => (
              <CaseRow key={item.id} item={item} onNavigate={onNavigate} />
            ))}
          </ul>
        </div>
      </nav>
      <div className="sidebar__foot">
        {local && <FootLink to="/setup" icon="setup" label="Setup" onNavigate={onNavigate} />}
        <FootLink to="/reference" icon="info" label="Reference" onNavigate={onNavigate} />
        <FootLink to="/guide" icon="guide" label="Run your own" onNavigate={onNavigate} />
        <ThemeToggle />
      </div>
    </>
  );
}
