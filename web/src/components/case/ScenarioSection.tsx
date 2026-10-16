import type { Detail, Rerun, ScenarioDetail } from '../../api/types';
import { percent } from '../../lib/format';
import { Icon } from '../Icon';
import { LinkedPlayer } from '../LinkedPlayer';
import { Outcomes } from '../Outcomes';
import { Empty, Section } from '../Section';

const PART_LABEL: Record<string, string> = { position: 'position', rotation: 'rotation', joints: 'joints' };

export function formatSelection(selection: Rerun['selection']): string {
  if (!selection) return 'none (unmodified)';
  const parts = Object.entries(selection).flatMap(([entity, values]) =>
    Object.entries(values).map(([part, fraction]) => `${entity} ${PART_LABEL[part] ?? part} ${percent(fraction)}`),
  );
  return parts.length ? parts.join('; ') : 'none (unmodified)';
}

function tri(value: boolean | null, yes: string, no: string, unknown = 'not tested') {
  if (value === null) return { icon: 'minus' as const, text: unknown };
  return value ? { icon: 'tick' as const, text: yes } : { icon: 'close' as const, text: no };
}

function Facts({ s }: { s: ScenarioDetail }) {
  return (
    <dl className="facts">
      <dt>Failing start</dt>
      <dd>
        {s.imported ? (
          <>
            your imported file <span className="mono" title="sha256 of the file">{s.imported.file_sha256.slice(0, 12)}</span>
          </>
        ) : s.failing_start !== null ? (
          `benchmark start ${s.failing_start}`
        ) : (
          'not recorded'
        )}
      </dd>
      <dt>Reference</dt>
      <dd>{s.reference_start !== null ? `benchmark start ${s.reference_start} (nearest passing start)` : 'none found'}</dd>
      <dt>Differences found</dt>
      <dd>{s.differences_count}</dd>
      <dt>Reduction</dt>
      <dd>
        {s.entity_minimal === null && s.reduced === null
          ? 'not run'
          : [s.entity_minimal ? 'each entity is needed' : null, s.reduced ? 'sizes reduced' : null].filter(Boolean).join(', ') ||
            'stopped before reducing'}
      </dd>
    </dl>
  );
}

export function ScenarioSection({ detail }: { detail: Detail }) {
  const s = detail.scenario;
  if (!s) return null;
  const hypothesis = s.hypothesis;
  return (
    <>
      <Section title="What changed between the passing and failing start">
        <Facts s={s} />
        {s.minimal_cause.length === 0 ? (
          <Empty>No minimal cause was found for this run.</Empty>
        ) : (
          <>
            <p className="muted">
              Applying these shifts to the passing reference is enough to make the policy fail. Share is how far each
              moves toward its failing value.
            </p>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">Entity</th>
                    <th scope="col">Part</th>
                    <th scope="col" className="num">
                      Share
                    </th>
                    <th scope="col">Size</th>
                  </tr>
                </thead>
                <tbody>
                  {s.minimal_cause.map((row) => (
                    <tr key={`${row.entity}-${row.part}`}>
                      <td className="mono">{row.entity}</td>
                      <td>{PART_LABEL[row.part] ?? row.part}</td>
                      <td className="num">{percent(row.fraction)}</td>
                      <td>{row.magnitude}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Section>

      <Section title="Videos" hint="Original failing start, the reference with the minimal cause applied, and the passing reference.">
        {detail.videos.length === 0 ? (
          <Empty>No videos were saved for this case.</Empty>
        ) : (
          <LinkedPlayer
            title="Original, minimal and reference videos"
            videos={detail.videos.map((video) => ({ key: video.role, label: video.label, url: video.url, outcome: video.outcome }))}
          />
        )}
      </Section>

      <Section title="Nemotron's guess and what was measured">
        {hypothesis === null ? (
          <Empty>Nemotron was not asked for a hypothesis in this run.</Empty>
        ) : (
          <div className="compare">
            <div className="compare__col">
              <h3>The guess</h3>
              <p className="muted">Nemotron's ranking of which entities matter most, before any rerun.</p>
              <ol className="ranked">
                {hypothesis.ranked.map((entity) => (
                  <li key={entity} className="mono">
                    {entity}
                  </li>
                ))}
              </ol>
            </div>
            <div className="compare__col">
              <h3>The measurement</h3>
              {hypothesis.verdict_text && <p>{hypothesis.verdict_text}</p>}
              {hypothesis.entities.length > 0 && (
                <div className="table-wrap">
                  <table className="data">
                    <thead>
                      <tr>
                        <th scope="col">Entity</th>
                        <th scope="col">Needed?</th>
                        <th scope="col">Enough alone?</th>
                      </tr>
                    </thead>
                    <tbody>
                      {hypothesis.entities.map((entity) => {
                        const necessary = tri(entity.necessary, 'needed', 'not needed');
                        const sufficient = tri(entity.sufficient, 'enough alone', 'not enough alone');
                        return (
                          <tr key={entity.entity}>
                            <td className="mono">{entity.entity}</td>
                            <td>
                              <Icon name={necessary.icon} /> {necessary.text}
                            </td>
                            <td>
                              <Icon name={sufficient.icon} /> {sufficient.text}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}
      </Section>

      <Section title="Reruns">
        {s.reruns.length === 0 ? (
          <Empty>No reruns were recorded.</Empty>
        ) : (
          <details className="reruns">
            <summary>Show all {s.reruns.length} reruns</summary>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col" className="num">
                      #
                    </th>
                    <th scope="col">Phase</th>
                    <th scope="col">Start</th>
                    <th scope="col">Shifts applied</th>
                    <th scope="col">Attempts</th>
                    <th scope="col">Decision</th>
                  </tr>
                </thead>
                <tbody>
                  {s.reruns.map((rerun) => (
                    <tr key={rerun.index}>
                      <td className="num">{rerun.index}</td>
                      <td>{rerun.phase}</td>
                      <td>{rerun.role}</td>
                      <td className="mono">{formatSelection(rerun.selection)}</td>
                      <td>
                        <Outcomes outcomes={rerun.outcomes} />
                      </td>
                      <td>{rerun.decision.replace(/_/g, ' ')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
      </Section>
    </>
  );
}
