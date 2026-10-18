import type { Branch, DryRun, DryRunBranch, DryRunJob, Environment } from '../../api/types';
import { duration, usd } from '../../lib/format';
import { Icon } from '../Icon';

const CHECK_LABEL: Record<string, string> = {
  nebius_cli: 'Nebius sign-in',
  docker: 'Docker (only for building the image)',
  token_factory_key: 'Token Factory key',
  tavily_key: 'Tavily key (related research)',
  spec_template: 'Backend settings in a local spec',
};

export function checkLabel(key: string): string {
  return CHECK_LABEL[key] ?? key.replace(/_/g, ' ');
}

function JobsTable({ jobs, caption, total }: { jobs: DryRunJob[]; caption: string; total?: number }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <caption>{caption}</caption>
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
          {jobs.map((job) => (
            <tr key={job.name}>
              <td className="mono">{job.name}</td>
              <td className="num">{duration(job.deadline_seconds)}</td>
              <td className="num">{usd(job.worst_case_usd)}</td>
            </tr>
          ))}
        </tbody>
        {total !== undefined && (
          <tfoot>
            <tr>
              <th scope="row">Total worst case</th>
              <td />
              <td className="num">{usd(total)}</td>
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}

/** The spend cap and hour limit, with the cap rule: only the first Job must fit to start. */
function CapFacts({ plan }: { plan: DryRun }) {
  const over = plan.worst_case_total_usd > plan.cap_usd;
  // The CLI reserves each Job's worst case just before submitting it, so only the first Job must fit to start;
  // a later Job that would not fit stops the run (resumable after raising the cap).
  const firstFits = (plan.jobs[0]?.worst_case_usd ?? 0) <= plan.cap_usd;
  return (
    <dl className="facts">
      <dt>Spend cap</dt>
      <dd>
        {usd(plan.cap_usd)}{' '}
        {over && !firstFits ? (
          <strong className="warn-text">
            <Icon name="attention" /> Even the first Job could cost more than the cap.
          </strong>
        ) : over ? (
          <strong className="warn-text">
            <Icon name="attention" /> The first Job fits, but not all of them. A later Job (for example a
            reduction, which runs only if a failure is found) would be refused and the run would stop there;
            you can raise the cap and resume.
          </strong>
        ) : (
          <span className="muted">(the worst case is {usd(plan.cap_usd - plan.worst_case_total_usd)} under it)</span>
        )}
      </dd>
      <dt>Hour limit</dt>
      <dd>{plan.max_hours} hours</dd>
    </dl>
  );
}

/** The flat dry-run table of the CLI modes and replay: every planned Job and the total against the cap. */
function FlatPlan({ plan }: { plan: DryRun }) {
  return (
    <>
      <JobsTable jobs={plan.jobs} caption="Planned Jobs. Nothing has been created yet." total={plan.worst_case_total_usd} />
      <CapFacts plan={plan} />
    </>
  );
}

export type DiagnosisSource = 'start' | 'screen' | 'import';

const BRANCH_ORDER: Branch[] = ['check', 'layout', 'probes'];

const BRANCH_TITLE: Record<Branch, Record<DiagnosisSource, string>> = {
  check: {
    start: 'First: check the start untouched',
    screen: 'First: search the range for a start that fails reliably',
    import: 'First: check that your start file fails',
  },
  layout: {
    start: 'If it fails: find the smallest layout change',
    screen: 'Then: find the smallest layout change',
    import: 'Then: find the smallest layout change',
  },
  probes: {
    start: 'If it passes: probe',
    screen: 'If it passes: probe',
    import: 'If it passes: probe',
  },
};

const BRANCH_TEXT: Record<Branch, string> = {
  check: 'Runs the start as it is, with confirmation attempts if it fails. Everything after this depends on the result.',
  layout:
    'Finds the nearest passing start as a reference, then shrinks the differences until only the shifts that cause the failure remain. This becomes a replayable case.',
  probes:
    'Searches each chosen disturbance family for the smallest severity that breaks the policy, and asks Nemotron for rewordings, reducing a failing one to the smallest word change. A start that is flaky untouched is reported as that, and rewordings are skipped.',
};

/** The check plus the larger of the two "if" branches, or null when any branch has no estimate. */
function typicalTotal(branches: DryRunBranch[]): number | null {
  if (branches.some((entry) => entry.typical_usd === null)) return null;
  const typical = (branch: Branch) => branches.find((entry) => entry.branch === branch)?.typical_usd ?? 0;
  return typical('check') + Math.max(typical('layout'), typical('probes'));
}

interface BranchPlanProps {
  plan: DryRun;
  branches: DryRunBranch[];
  source: DiagnosisSource;
  headingLevel: 2 | 3 | 4;
}

/** A diagnose plan: the check, then the two branches of which only one runs, each with its Jobs and cost. */
function BranchPlan({ plan, branches, source, headingLevel }: BranchPlanProps) {
  const Heading = `h${Math.min(headingLevel + 1, 6)}` as 'h3' | 'h4' | 'h5';
  const total = typicalTotal(branches);
  return (
    <>
      {BRANCH_ORDER.map((branch) => {
        const entry = branches.find((candidate) => candidate.branch === branch);
        const jobs = plan.jobs.filter((job) => job.branch === branch);
        if (!entry && jobs.length === 0) return null;
        const title = BRANCH_TITLE[branch][source];
        return (
          <section key={branch} className={`branch branch--${branch}`} aria-label={title}>
            <Heading className="branch__title">{title}</Heading>
            <p className="muted">{BRANCH_TEXT[branch]}</p>
            {jobs.length > 0 ? (
              <JobsTable jobs={jobs} caption={`Planned Jobs. ${title}. Nothing has been created yet.`} />
            ) : (
              <p className="muted">No Jobs are planned for this branch.</p>
            )}
            <dl className="facts">
              <dt>Worst case</dt>
              <dd>{usd(entry?.worst_case_usd ?? jobs.reduce((sum, job) => sum + job.worst_case_usd, 0))}</dd>
              <dt>Typical</dt>
              <dd>
                {entry && entry.typical_usd !== null ? (
                  <>
                    about {usd(entry.typical_usd)} <span className="muted">(typical, an estimate)</span>
                  </>
                ) : (
                  <span className="muted">not known yet (typical, an estimate)</span>
                )}
              </dd>
            </dl>
          </section>
        );
      })}
      <dl className="facts">
        <dt>Total worst case</dt>
        <dd>
          {usd(plan.worst_case_total_usd)}{' '}
          <span className="muted">(the check plus the larger of the two branches, because only one of them runs)</span>
        </dd>
        {total !== null && (
          <>
            <dt>Typical total</dt>
            <dd>
              about {usd(total)} <span className="muted">(typical, an estimate)</span>
            </dd>
          </>
        )}
      </dl>
      <CapFacts plan={plan} />
    </>
  );
}

interface DryRunTableProps {
  plan: DryRun;
  /** What the person is checking, so the first branch is named for it. */
  source?: DiagnosisSource;
  /** Level of the section heading above, so branch headings sit one level below it. */
  headingLevel?: 2 | 3 | 4;
}

/**
 * The dry run. A diagnose plan shows its branches (what runs first, if it fails, if it passes) with the worst
 * case and a typical estimate for each; any other plan is a flat table of Jobs.
 */
export function DryRunTable({ plan, source = 'start', headingLevel = 2 }: DryRunTableProps) {
  const branches = plan.branches;
  if (branches && branches.length > 0 && plan.jobs.every((job) => job.branch)) {
    return <BranchPlan plan={plan} branches={branches} source={source} headingLevel={headingLevel} />;
  }
  return <FlatPlan plan={plan} />;
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
