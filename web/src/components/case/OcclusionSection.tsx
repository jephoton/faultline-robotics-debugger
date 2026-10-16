import type { Detail, OcclusionRect } from '../../api/types';
import { LinkedPlayer } from '../LinkedPlayer';
import { Empty, Section } from '../Section';

const EDGE_WORD: Record<string, string> = { left: 'left', right: 'right', top: 'top', bottom: 'bottom', start: 'start' };

function area(rect: OcclusionRect): string {
  return `${Math.round(rect.width * rect.height * 1000) / 10}%`;
}

/** Nested outlines of the rectangle at each reduction step, inside the camera frame. */
function Lineage({ lineage }: { lineage: NonNullable<Detail['occlusion']>['lineage'] }) {
  const size = 200;
  return (
    <svg
      className="lineage__svg"
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={`Rectangle shrinking from ${area(lineage[0]!.rectangle)} to ${area(lineage[lineage.length - 1]!.rectangle)} of the image`}
    >
      <rect x="0.5" y="0.5" width={size - 1} height={size - 1} className="lineage__frame" />
      {lineage.map((step, index) => {
        const last = index === lineage.length - 1;
        return (
          <rect
            key={index}
            x={step.rectangle.x * size}
            y={step.rectangle.y * size}
            width={step.rectangle.width * size}
            height={step.rectangle.height * size}
            className={last ? 'lineage__rect lineage__rect--final' : 'lineage__rect'}
          />
        );
      })}
    </svg>
  );
}

export function OcclusionSection({ detail }: { detail: Detail }) {
  const o = detail.occlusion;
  if (!o) return null;
  return (
    <>
      <Section title="Occluded episodes" hint="Each episode was run with a rectangle covering part of the agent-view camera.">
        {o.episodes.length === 0 ? (
          <Empty>No episodes were recorded.</Empty>
        ) : (
          <LinkedPlayer
            title="Occlusion episodes"
            videos={o.episodes.map((episode) => ({
              key: episode.episode_id,
              label: `${episode.stage}, ${episode.role}`,
              url: episode.url,
              outcome: episode.outcome,
            }))}
          />
        )}
      </Section>
      <Section title="How the rectangle was reduced" hint="Each step trims one edge and keeps the failure if it still repeats.">
        {o.lineage.length === 0 ? (
          <Empty>No reduction steps were recorded.</Empty>
        ) : (
          <div className="lineage">
            <Lineage lineage={o.lineage} />
            <ol className="lineage__steps">
              {o.lineage.map((step, index) => (
                <li key={index}>
                  <span className="mono">{area(step.rectangle)} of the image</span>
                  <span className="muted">
                    {step.edge === 'start'
                      ? ' starting rectangle'
                      : ` trimmed the ${EDGE_WORD[step.edge] ?? step.edge} edge by ${Math.round(step.delta * 1000) / 10}% of the image`}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        )}
      </Section>
    </>
  );
}
