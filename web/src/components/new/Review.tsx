import type { DryRun, Environment } from '../../api/types';
import { duration, usd } from '../../lib/format';
import { Icon } from '../Icon';

const CHECK_LABEL: Record<string, string> = {
  nebius_cli: 'Nebius sign-in',
  docker: 'Docker (only for building the image)',
  token_factory_key: 'Token Factory key',
  spec_template: 'Backend settings in a local spec',
};

export function checkLabel(key: string): string {
  return CHECK_LABEL[key] ?? key.replace(/_/g, ' ');
}

/** The dry-run table: every planned Job, its deadline and worst-case cost, and the total against the cap. */
export function DryRunTable({ plan }: { plan: DryRun }) {
  const over = plan.worst_case_total_usd > plan.cap_usd;
  return (
    <>
      <div className="table-wrap">
        <table className="data">
          <caption>Planned Jobs. Nothing has been created yet.</caption>
          <thead>
            <tr>
              <th scope="col">Job</th>
              <th scope="col" className="num">
                Deadline
              </th>
              <th scope="col" className="num">
                Worst case
              </th>
            </tr>
          </thead>
          <tbody>
            {plan.jobs.map((job) => (
              <tr key={job.name}>
                <td className="mono">{job.name}</td>
                <td className="num">{duration(job.deadline_seconds)}</td>
                <td className="num">{usd(job.worst_case_usd)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">Total worst case</th>
              <td />
              <td className="num">{usd(plan.worst_case_total_usd)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
      <dl className="facts">
        <dt>Spend cap</dt>
        <dd>
          {usd(plan.cap_usd)}{' '}
          {over ? (
            <strong className="warn-text">
              <Icon name="attention" /> The required Jobs could cost more than the cap.
            </strong>
          ) : (
            <span className="muted">(the worst case is {usd(plan.cap_usd - plan.worst_case_total_usd)} under it)</span>
          )}
        </dd>
        <dt>Hour limit</dt>
        <dd>{plan.max_hours} hours</dd>
      </dl>
    </>
  );
}

export function EnvironmentList({ environment }: { environment: Environment }) {
  return (
    <ul className="checks">
      {environment.checks.map((check) => (
        <li key={check.key} className={check.ok ? 'check-row' : 'check-row check-row--attention'}>
          <Icon name={check.ok ? 'check' : 'attention'} />
          <span>
            <strong>{checkLabel(check.key)}</strong>: {check.ok ? 'ready' : 'needs attention'}
            <span className="muted"> {check.detail}</span>
            {!check.ok && check.fix && <span className="check-row__fix">{check.fix}</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}
