import type { Detail, HistoryStep } from '../../api/types';
import { duration, shortDate, usd } from '../../lib/format';
import { Icon, type IconName } from '../Icon';
import { Markdown } from '../Markdown';
import { Empty, Section } from '../Section';

function stepIcon(step: HistoryStep): IconName {
  if (step.status === 'completed') return 'tick';
  if (step.status === 'stopped' || step.status === 'failed') return 'attention';
  if (step.status === 'running') return 'clock';
  return 'minus';
}

function stateText(step: HistoryStep): string {
  const status = step.status.replace(/_/g, ' ');
  const state = step.state && step.state !== 'succeeded' ? `, ${step.state.replace(/_/g, ' ')}` : '';
  return `${status}${state}${step.partial ? ' (partial)' : ''}`;
}

export function HistorySection({ detail }: { detail: Detail }) {
  const h = detail.history;
  return (
    <Section title="How it was made">
      {!h ? (
        <Empty>No run record is stored for this case.</Empty>
      ) : (
        <>
          <ol className="timeline">
            {h.steps.map((step) => (
              <li key={step.key} className={step.status === 'stopped' || step.status === 'failed' ? 'timeline__step timeline__step--attention' : 'timeline__step'}>
                <Icon name={stepIcon(step)} />
                <span className="timeline__label">{step.label}</span>
                <span className="timeline__state muted">{stateText(step)}</span>
                <span className="timeline__cost mono">{step.cost_usd !== null ? usd(step.cost_usd) : ''}</span>
              </li>
            ))}
          </ol>
          <dl className="facts">
            <dt>Cloud Jobs</dt>
            <dd>{h.jobs}</dd>
            <dt>Spent</dt>
            <dd>
              {usd(h.spent_usd)} of a {usd(h.cap_usd)} cap
              {h.hourly_usd !== null && <span className="muted"> (at {usd(h.hourly_usd, 4)} an hour)</span>}
            </dd>
            <dt>Time</dt>
            <dd>
              {duration(h.elapsed_seconds)}
              {h.max_hours !== null && <span className="muted"> of a {h.max_hours} hour limit</span>}
            </dd>
          </dl>
        </>
      )}
    </Section>
  );
}

function EvidenceIds({ ids }: { ids: string[] }) {
  if (ids.length === 0) return null;
  return (
    <span className="evidence-ids">
      <span className="muted">Evidence:</span>{' '}
      {ids.map((id) => (
        <code key={id}>{id}</code>
      ))}
    </span>
  );
}

export function ExplanationSection({ detail }: { detail: Detail }) {
  const e = detail.explanation;
  return (
    <Section title="Nemotron's reading">
      {!e ? (
        <Empty>No Nemotron reading was made for this case.</Empty>
      ) : (
        <div className="panel">
          <p className="explain__meta">
            <span className="badge">
              <Icon name="attention" /> Review required
            </span>
            {e.model && (
              <span className="muted">
                Written by <span className="mono">{e.model}</span>
              </span>
            )}
          </p>
          {e.disclaimer && <p className="muted">{e.disclaimer}</p>}
          {e.hypotheses.length > 0 && (
            <>
              <h3>Hypotheses to test</h3>
              <ul className="reading">
                {e.hypotheses.map((item) => (
                  <li key={item.text}>
                    <p>{item.text}</p>
                    <EvidenceIds ids={item.evidence_ids} />
                  </li>
                ))}
              </ul>
            </>
          )}
          {e.observations.length > 0 && (
            <>
              <h3>Observations</h3>
              <ul className="reading">
                {e.observations.map((item) => (
                  <li key={item.text}>
                    <p>{item.text}</p>
                    <EvidenceIds ids={item.evidence_ids} />
                  </li>
                ))}
              </ul>
            </>
          )}
          {e.limitations.length > 0 && (
            <>
              <h3>Limits</h3>
              <ul>
                {e.limitations.map((text) => (
                  <li key={text}>{text}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </Section>
  );
}

export function ResearchSection({ detail }: { detail: Detail }) {
  const r = detail.research;
  if (!r) return null;
  return (
    <Section title="Research context">
      {r.related && <p>{r.related}</p>}
      {r.sources.length > 0 ? (
        <ul>
          {r.sources.map((source) => (
            <li key={source.url}>
              <a href={source.url} rel="noopener noreferrer" target="_blank">
                {source.title}
              </a>
            </li>
          ))}
        </ul>
      ) : (
        <Empty>No sources were listed.</Empty>
      )}
    </Section>
  );
}

export function replayLabel(verdict: string): { icon: IconName; label: string; tone: 'alarm' | 'neutral' } {
  if (/fixed|no_longer|not_reproduce|does_not/.test(verdict)) return { icon: 'check', label: 'Fixed', tone: 'neutral' };
  if (/reproduces|still/.test(verdict)) return { icon: 'alarm', label: 'Still reproduces', tone: 'alarm' };
  return { icon: 'dash', label: verdict.replace(/_/g, ' '), tone: 'neutral' };
}

export function ReplayHistory({ detail }: { detail: Detail }) {
  if (detail.replays.length === 0) {
    return <Empty>This case has not been replayed yet.</Empty>;
  }
  return (
    <ul className="replays">
      {detail.replays.map((replay, index) => {
        const view = replayLabel(replay.verdict);
        return (
          <li key={replay.run ?? index} className="replay">
            <span className={view.tone === 'alarm' ? 'badge badge--alarm' : 'badge'}>
              <Icon name={view.icon} />
              {view.label}
            </span>
            <span>{replay.verdict_text}</span>
            <span className="muted mono">
              {shortDate(replay.created)}
              {replay.cost_usd !== null ? `, ${usd(replay.cost_usd)}` : ''}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export function ReportSection({ detail }: { detail: Detail }) {
  return (
    <Section title="Report">
      {detail.report_markdown ? <Markdown source={detail.report_markdown} /> : <Empty>No report was saved for this case.</Empty>}
    </Section>
  );
}

export function FilesSection({ detail }: { detail: Detail }) {
  if (detail.files.length === 0) return null;
  return (
    <Section title="Files">
      <ul className="files">
        {detail.files.map((file) => (
          <li key={file.name}>
            <Icon name="file" />{' '}
            <a href={file.url} className="mono" download>
              {file.name}
            </a>
          </li>
        ))}
      </ul>
    </Section>
  );
}
