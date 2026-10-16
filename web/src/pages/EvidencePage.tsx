import { useMemo, useState } from 'react';
import { useApi, useAppData } from '../api/context';
import type { EvidenceEpisode } from '../api/types';
import { Icon } from '../components/Icon';
import { isFail, isPass, outcomeWord } from '../components/Outcomes';
import { duration, shortDate, suiteLabel } from '../lib/format';
import { useAsync } from '../lib/useAsync';
import { useDocumentTitle } from '../lib/useDocumentTitle';
import { LocalOnlyPage } from './NotFoundPage';

const PAGE = 100;

function Row({ episode }: { episode: EvidenceEpisode }) {
  const [shown, setShown] = useState(false);
  const failed = isFail(episode.outcome);
  return (
    <>
      <tr>
        <td className="mono">{episode.episode_id}</td>
        <td>{episode.run_name}</td>
        <td>
          {suiteLabel(episode.benchmark)}, task {episode.task_id}
          <div className="muted">{episode.instruction}</div>
        </td>
        <td>
          <span className="outcome-word">
            <Icon name={failed ? 'close' : isPass(episode.outcome) ? 'tick' : 'minus'} /> {outcomeWord(episode.outcome)}
          </span>
          {episode.failure_detail && <div className="muted">{episode.failure_detail}</div>}
        </td>
        <td className="num">
          {episode.steps} steps, {duration(episode.elapsed_seconds)}
        </td>
        <td>{shortDate(episode.created_at)}</td>
        <td>
          {episode.video_url ? (
            <button
              type="button"
              className="btn btn--secondary btn--small"
              aria-expanded={shown}
              onClick={() => setShown((value) => !value)}
              aria-label={`${shown ? 'Hide' : 'Show'} video of ${episode.episode_id}`}
            >
              <Icon name={shown ? 'close' : 'play'} /> {shown ? 'Hide' : 'Video'}
            </button>
          ) : (
            <span className="muted">none</span>
          )}
        </td>
      </tr>
      {shown && episode.video_url && (
        <tr className="evidence-video">
          <td colSpan={7}>
            <video
              src={mediaSrc(episode.video_url)}
              controls
              muted
              playsInline
              preload="metadata"
              aria-label={`Video of ${episode.episode_id}`}
            />
          </td>
        </tr>
      )}
    </>
  );
}

export function EvidencePage() {
  const { session } = useAppData();
  if (session.mode !== 'local') return <LocalOnlyPage what="All evidence" />;
  return <Evidence />;
}

function Evidence() {
  useDocumentTitle('All evidence');
  const api = useApi();
  const evidence = useAsync(() => api.evidence(), [api]);
  const [outcome, setOutcome] = useState<'all' | 'failed' | 'passed'>('all');
  const [query, setQuery] = useState('');
  const [limit, setLimit] = useState(PAGE);

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (evidence.data?.episodes ?? []).filter((episode) => {
      if (outcome === 'failed' && !isFail(episode.outcome)) return false;
      if (outcome === 'passed' && !isPass(episode.outcome)) return false;
      if (!needle) return true;
      return `${episode.episode_id} ${episode.run_name} ${episode.instruction}`.toLowerCase().includes(needle);
    });
  }, [evidence.data, outcome, query]);

  return (
    <section>
      <h1>All evidence</h1>
      <p className="lede">Every recorded episode under the artifact folder, with its outcome and video. This is raw evidence, not a diagnosis.</p>
      {evidence.loading && (
        <p role="status" aria-busy="true">
          Reading the episode catalog. A large artifact folder can take a little while the first time.
        </p>
      )}
      {evidence.error && (
        <div className="notice notice--attention" role="alert">
          <Icon name="attention" />
          <div className="notice__body">
            <p className="notice__title">The catalog could not be read</p>
            <p>{evidence.error.message}</p>
          </div>
        </div>
      )}
      {evidence.data && (
        <>
          {evidence.data.warnings.length > 0 && (
            <ul className="notice notice--neutral">
              {evidence.data.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
          <div className="filters">
            <div className="field">
              <label htmlFor="evidence-outcome">Outcome</label>
              <select
                id="evidence-outcome"
                value={outcome}
                onChange={(event) => {
                  setOutcome(event.target.value as typeof outcome);
                  setLimit(PAGE);
                }}
              >
                <option value="all">All outcomes</option>
                <option value="failed">Failed</option>
                <option value="passed">Passed</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="evidence-search">Search</label>
              <input
                id="evidence-search"
                type="text"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setLimit(PAGE);
                }}
                placeholder="run, episode or instruction"
              />
            </div>
          </div>
          <p role="status" aria-live="polite">
            Showing {Math.min(limit, rows.length)} of {rows.length} episodes{rows.length !== evidence.data.episodes.length ? ` (${evidence.data.episodes.length} in total)` : ''}.
          </p>
          {rows.length === 0 ? (
            <p className="empty">No episodes match.</p>
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">Episode</th>
                    <th scope="col">Run</th>
                    <th scope="col">Task</th>
                    <th scope="col">Outcome</th>
                    <th scope="col" className="num">
                      Length
                    </th>
                    <th scope="col">Recorded</th>
                    <th scope="col">Video</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, limit).map((episode) => (
                    <Row key={episode.episode_id} episode={episode} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {rows.length > limit && (
            <button type="button" className="btn btn--secondary" onClick={() => setLimit((value) => value + PAGE)}>
              Show {Math.min(PAGE, rows.length - limit)} more
            </button>
          )}
        </>
      )}
    </section>
  );
}

/** The server sends "/media/<path>" unencoded; encode each path segment for the src attribute. */
function mediaSrc(url: string): string {
  const prefix = '/media/';
  if (!url.startsWith(prefix)) return url;
  return prefix + url.slice(prefix.length).split('/').map(encodeURIComponent).join('/');
}
