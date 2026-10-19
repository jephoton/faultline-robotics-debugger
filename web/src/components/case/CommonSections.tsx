import type { ReactNode } from 'react';
import type { Detail, HistoryStep, ReplayRow } from '../../api/types';
import { duration, shortDate, usd } from '../../lib/format';
import { Icon, type IconName } from '../Icon';
import { LinkedPlayer } from '../LinkedPlayer';
import { LONG_TABLE_ROWS, Markdown } from '../Markdown';
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

/** The steps, Jobs, cost and time of the run that made the case. */
function HistoryBody({ detail }: { detail: Detail }) {
  const h = detail.history;
  if (!h) return <Empty>No run record is stored for this case.</Empty>;
  return (
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
  );
}

export function HistorySection({ detail }: { detail: Detail }) {
  return (
    <Section title="How it was made">
      <HistoryBody detail={detail} />
    </Section>
  );
}

/** Report-first layout: the steps, Jobs, cost and time, folded away until asked for. */
export function RunDetails({ detail }: { detail: Detail }) {
  return (
    <section className="section">
      <details className="fold">
        <summary>Run details</summary>
        <HistoryBody detail={detail} />
      </details>
    </section>
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

function ExplanationBody({ detail }: { detail: Detail }) {
  const e = detail.explanation;
  if (!e) return <Empty>No Nemotron reading was made for this case.</Empty>;
  return (
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
  );
}

export function ExplanationSection({ detail }: { detail: Detail }) {
  return (
    <Section title="Nemotron's reading">
      <ExplanationBody detail={detail} />
    </Section>
  );
}

/** Report-first layout: Nemotron's reading after the report, folded, and labelled as interpretation. */
export function ReadingFold({ detail }: { detail: Detail }) {
  if (!detail.explanation) return null;
  return (
    <Section
      title="Nemotron's reading"
      hint="An interpretation written by a language model from the results above. It is not evidence and needs human review."
    >
      <details className="fold">
        <summary>Show the reading (interpretation, not evidence)</summary>
        <ExplanationBody detail={detail} />
      </details>
    </Section>
  );
}

export function ResearchSection({ detail }: { detail: Detail }) {
  const r = detail.research;
  if (!r) return null;
  return (
    <Section
      title="Research context"
      hint="Context, not evidence: public sources found with Tavily and summarised by Nemotron 3 Nano. It does not show that anything above is true."
    >
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

type ReplayTone = 'alarm' | 'pass' | 'attention';

/**
 * A replay verdict in words. On the original policy a failure that did not repeat is not "fixed" (nothing changed,
 * so the case may be flaky); on a new checkpoint it is. A replay with no recorded checkpoint is the original.
 */
export function replayLabel(verdict: string, original?: boolean | null): { icon: IconName; label: string; tone: ReplayTone } {
  if (/fixed|no_longer|not_reproduce|does_not/.test(verdict)) {
    return original === false
      ? { icon: 'check', label: 'Fixed', tone: 'pass' }
      : { icon: 'attention', label: 'Did not repeat', tone: 'attention' };
  }
  if (/reproduces|still/.test(verdict)) return { icon: 'alarm', label: 'Still fails', tone: 'alarm' };
  return { icon: 'attention', label: 'Inconclusive', tone: 'attention' };
}

/** The checkpoint a replay tested, as `id at abc1234`. */
export function checkpointText(checkpoint: { id: string; revision: string | null }): string {
  return checkpoint.revision ? `${checkpoint.id} at ${checkpoint.revision.slice(0, 7)}` : checkpoint.id;
}

function ReplayCheckpoint({ replay }: { replay: ReplayRow }) {
  const { checkpoint, original } = replay;
  if (!checkpoint) return <span className="muted">Policy tested: the original policy (checkpoint not recorded)</span>;
  const which = original === true ? 'the original policy, ' : original === false ? 'a new checkpoint, ' : '';
  return (
    <span className="muted">
      Policy tested: {which}
      <span className="mono">{checkpointText(checkpoint)}</span>
    </span>
  );
}

export function ReplayHistory({ detail, slot }: { detail: Detail; slot?: (run: string | null) => ReactNode }) {
  if (detail.replays.length === 0) {
    return <Empty>This case has not been replayed yet.</Empty>;
  }
  return (
    <ul className="replays">
      {detail.replays.map((replay, index) => {
        const view = replayLabel(replay.verdict, replay.original);
        return (
          <li key={replay.run ?? index} className="replay">
            <span className={`badge badge--${view.tone}`}>
              <Icon name={view.icon} />
              {view.label}
            </span>
            <span>{replay.verdict_text}</span>
            <ReplayCheckpoint replay={replay} />
            <span className="muted mono">
              {shortDate(replay.created)}
              {replay.cost_usd !== null ? `, ${usd(replay.cost_usd)}` : ''}
            </span>
            {slot?.(replay.run)}
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

/** Report-first layout: the stored report is the body of the page; tables over 12 rows are folded. */
export function ReportBody({ detail }: { detail: Detail }) {
  if (!detail.report_markdown) return null;
  return (
    <Section title="Report">
      <Markdown source={detail.report_markdown} collapseAbove={LONG_TABLE_ROWS} />
    </Section>
  );
}

/** The case's videos in the linked player, above the report. */
export function CaseVideos({ detail }: { detail: Detail }) {
  if (detail.videos.length === 0) {
    return detail.kind === 'scenario' ? (
      <Section title="Videos">
        <Empty>No videos were saved for this case.</Empty>
      </Section>
    ) : null;
  }
  const scenario = detail.kind === 'scenario';
  // The control first, so every other clip is read against the unchanged start; the rest keep the server's order.
  const ordered = [...detail.videos.filter((video) => video.role === 'control'), ...detail.videos.filter((video) => video.role !== 'control')];
  const hint = scenario
    ? 'Original failing start, the reference with the minimal cause applied, and the passing reference.'
    : detail.kind === 'audit' && ordered.some((video) => video.role === 'control')
      ? 'The control (the start untouched) first, then each disturbance that broke the policy, at its threshold.'
      : detail.kind === 'paraphrase' && ordered.some((video) => video.role === 'control')
        ? 'The control (the original wording) first, then the failing wording.'
        : undefined;
  return (
    <Section title="Videos" hint={hint}>
      <LinkedPlayer
        title={scenario ? 'Original, minimal and reference videos' : detail.kind === 'audit' ? 'Audit videos' : detail.kind === 'paraphrase' ? 'Wording videos' : 'Case videos'}
        videos={ordered.map((video) => ({ key: video.role, label: video.label, url: video.url, outcome: video.outcome }))}
      />
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
