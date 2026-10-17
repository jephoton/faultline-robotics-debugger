import type { AuditFamily, Detail } from '../../api/types';
import { Icon } from '../Icon';
import { LinkedPlayer } from '../LinkedPlayer';
import { Empty, Section } from '../Section';

function severity(value: number): string {
  return value.toFixed(2);
}

/** One row per severity level: attempts as cells (failed ones solid) and the threshold marked. */
function Ladder({ family }: { family: AuditFamily }) {
  const threshold = family.threshold_severity;
  const robust = threshold === null;
  // Only a family that was searched and found nothing is "no failure": one the run never reached was not tested.
  const tested = family.stop_reason === 'no_reproducible_failure' && family.levels.length > 0;
  const highest = Math.max(...family.levels.map((level) => level.severity));
  return (
    <article className="ladder" aria-label={`${family.label} severity ladder`}>
      <header className="ladder__head">
        <h3>{family.label}</h3>
        {robust && tested ? (
          <p className="ladder__result">
            <Icon name="check" /> No failure up to severity {severity(highest)}
          </p>
        ) : robust && family.levels.length > 0 ? (
          <p className="ladder__result ladder__result--attention">
            <Icon name="attention" /> Incomplete: searched up to severity {severity(highest)}, then stopped
          </p>
        ) : robust ? (
          <p className="ladder__result ladder__result--attention">
            <Icon name="attention" /> Not tested: the run stopped before this family was searched
          </p>
        ) : (
          <p className="ladder__result ladder__result--alarm">
            <Icon name="alarm" /> Fails from severity {severity(threshold)}
          </p>
        )}
      </header>
      <ol className="ladder__levels">
        {family.levels.map((level) => {
          const isThreshold = threshold !== null && Math.abs(level.severity - threshold) < 1e-9;
          const cells = Array.from({ length: level.attempts }, (_, index) => index < level.failures);
          return (
            <li key={level.severity} className={isThreshold ? 'level level--threshold' : 'level'}>
              <span className="level__sev mono">s = {severity(level.severity)}</span>
              <span
                className="level__cells"
                role="img"
                aria-label={`${level.failures} of ${level.attempts} attempts failed at severity ${severity(level.severity)}`}
              >
                {cells.map((failed, index) => (
                  <span key={index} className={failed ? 'cell cell--fail' : 'cell cell--pass'}>
                    <Icon name={failed ? 'close' : 'tick'} />
                  </span>
                ))}
              </span>
              <span className="level__count mono">
                {level.failures}/{level.attempts}
              </span>
              {isThreshold && (
                <span className="level__mark">
                  <Icon name="alarm" /> Threshold
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </article>
  );
}

export function AuditSection({ detail }: { detail: Detail }) {
  const audit = detail.audit;
  if (!audit) return null;
  const nominal = audit.nominal;
  return (
    <>
      <Section
        title="Severity by family"
        hint="Each family is searched from severity 0 (no change) to 1 (the strongest). A row shows how many attempts failed at that level."
      >
        <dl className="facts">
          <dt>Start</dt>
          <dd>{audit.start_index !== null ? `benchmark start ${audit.start_index}` : 'not recorded'}</dd>
          <dt>Unperturbed control</dt>
          <dd>{nominal ? `${nominal.failures} of ${nominal.attempts} attempts failed` : 'not recorded'}</dd>
        </dl>
        {audit.families.length === 0 ? (
          <Empty>No family results were recorded.</Empty>
        ) : (
          <div className="ladders">
            {audit.families.map((family) => (
              <Ladder key={family.family} family={family} />
            ))}
          </div>
        )}
      </Section>
      {detail.videos.length > 0 && (
        <Section title="Videos">
          <LinkedPlayer
            title="Audit videos"
            videos={detail.videos.map((video) => ({ key: video.role, label: video.label, url: video.url, outcome: video.outcome }))}
          />
        </Section>
      )}
    </>
  );
}
