import { Link } from 'react-router-dom';
import type { Detail, Route } from '../../api/types';
import { KIND_LABEL } from '../../lib/status';
import { StatusBadge } from '../StatusBadge';
import { Section } from '../Section';

/**
 * How the diagnosis run that made this case went. The server may send the route; otherwise it is read from the
 * findings: a run whose findings all found nothing passed untouched, and a case that stopped because its control
 * failed belongs to a start that is flaky untouched.
 */
export function routeOf(detail: Detail): Route | null {
  if (detail.route) return detail.route;
  const list = detail.findings ?? [];
  if (list.length === 0) return null;
  if (detail.stop_reason === 'nominal_controls_failed') return 'flaky';
  if (list.every((finding) => finding.verdict === 'no_failure')) return 'passes';
  return null;
}

/** The list is for a run with several findings, or one that ended without a failure to reduce. */
export function showsFindings(detail: Detail): boolean {
  const list = detail.findings ?? [];
  if (list.length > 1) return true;
  const route = routeOf(detail);
  return list.length > 0 && (route === 'passes' || route === 'flaky');
}

/** Every case one diagnosis run registered, in route order, with this one marked. */
export function FindingsList({ detail }: { detail: Detail }) {
  if (!showsFindings(detail)) return null;
  const route = routeOf(detail);
  const hint =
    route === 'passes'
      ? 'The start passed untouched, so there was no failure to reduce.'
      : route === 'flaky'
        ? 'The start is flaky untouched, so no failure can be blamed on a disturbance or a wording.'
        : 'One diagnosis run can end in several findings. Each one is its own case with its own report and replay.';
  return (
    <Section title="Findings of this diagnosis" hint={hint}>
      <ul className="findings">
        {(detail.findings ?? []).map((finding) => {
          const current = finding.id === detail.id;
          return (
            <li key={finding.id} className={current ? 'finding finding--current' : 'finding'} aria-current={current ? 'true' : undefined}>
              <StatusBadge verdict={finding.verdict} attention={false} />
              <span className="finding__code mono">
                {current ? (
                  finding.fault_code
                ) : (
                  <Link to={`/case/${encodeURIComponent(finding.id)}`}>{finding.fault_code}</Link>
                )}
              </span>
              <span className="finding__kind">{KIND_LABEL[finding.kind]}</span>
              <span className="finding__text">{finding.verdict_text}</span>
              {current && <span className="finding__here muted">This case</span>}
            </li>
          );
        })}
      </ul>
    </Section>
  );
}
