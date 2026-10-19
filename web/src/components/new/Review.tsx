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

/**
 * The Jobs that the cap rule would refuse, in plan order: for each branch the required Job at which the
 * running worst case (the check first, then that branch's Jobs) first passes the cap. The optional
 * continuations run only if needed and are not counted, as in the plan's total.
 */
function refusedJobs(plan: DryRun): { name: string; branch?: Branch }[] {
  const required = plan.jobs.filter((job) => !job.optional);
  const lanes: (Branch | undefined)[] = required.some((job) => job.branch) ? ['layout', 'probes'] : [undefined];
  const found: { name: string; branch?: Branch }[] = [];
  for (const lane of lanes) {
    let running = 0;
    for (const job of required.filter((entry) => entry.branch === 'check' || entry.branch === lane)) {
      running += job.worst_case_usd;
      if (running > plan.cap_usd + 1e-9) {
        found.push({ name: job.name, branch: job.branch === 'check' ? undefined : lane });
        break;
      }
    }
  }
  return found;
}

const REFUSED_BRANCH: Partial<Record<Branch, string>> = { layout: 'layout branch', probes: 'probe branch' };

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
            <Icon name="attention" /> The first Job fits, but not all of them. Each Job is charged what it
            measured, so this matters only if the Jobs before it cost their worst case. Then the first to be
            refused is{' '}
            {refusedJobs(plan)
              .map((job) => (job.branch ? `${job.name} (${REFUSED_BRANCH[job.branch]})` : job.name))
              .join('; ')}
            , and the run stops there; you can raise the cap and resume.
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
    'Searches each chosen disturbance family for the smallest severity that breaks the policy, and asks Nemotron for rewordings, reducing a failing one to the smallest word change. A check that finds the start flaky ends the run. A probe control that fails skips the probes still to come.',
};

interface Typical {
  usd: number | null;
  minutes: number | null;
}

const typicalOf = (entry: DryRunBranch | undefined): Typical => ({ usd: entry?.typical_usd ?? null, minutes: entry?.typical_minutes ?? null });

/** The typical cost and time of the check followed by one branch; a figure is null when either part is unknown. */
function typicalWith(branches: DryRunBranch[], branch: Branch): Typical {
  const first = typicalOf(branches.find((entry) => entry.branch === 'check'));
  const next = typicalOf(branches.find((entry) => entry.branch === branch));
  return {
    usd: first.usd === null || next.usd === null ? null : first.usd + next.usd,
    minutes: first.minutes === null || next.minutes === null ? null : first.minutes + next.minutes,
  };
}

/** "about US$0.65 and 25 minutes", saying plainly which figure is not known yet. */
function typicalText(typical: Typical): string {
  const minutes = typical.minutes === null ? null : `${Math.max(1, Math.round(typical.minutes))} minutes`;
  if (typical.usd !== null && minutes) return `about ${usd(typical.usd)} and ${minutes}`;
  if (typical.usd !== null) return `about ${usd(typical.usd)}, time not known yet`;
  if (minutes) return `about ${minutes}, cost not known yet`;
  return 'not known yet';
}

const TYPICAL_NOTE = '(typical, an estimate; GPU waits can add more)';

interface BranchPlanProps {
  plan: DryRun;
  branches: DryRunBranch[];
  source: DiagnosisSource;
  headingLevel: 2 | 3 | 4;
}

/** A diagnose plan: the check, then the two branches of which only one runs, each with its Jobs and cost. */
function BranchPlan({ plan, branches, source, headingLevel }: BranchPlanProps) {
  const Heading = `h${Math.min(headingLevel + 1, 6)}` as 'h3' | 'h4' | 'h5';
  const present = (branch: Branch) => branches.some((entry) => entry.branch === branch);
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
                {typicalText(typicalOf(entry))} <span className="muted">{TYPICAL_NOTE}</span>
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
        {present('layout') && (
          <>
            <dt>Typical total if it fails</dt>
            <dd>
              {typicalText(typicalWith(branches, 'layout'))} <span className="muted">{TYPICAL_NOTE}</span>
            </dd>
          </>
        )}
        {present('probes') && (
          <>
            <dt>Typical total if it passes</dt>
            <dd>
              {typicalText(typicalWith(branches, 'probes'))} <span className="muted">{TYPICAL_NOTE}</span>
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
