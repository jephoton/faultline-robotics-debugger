import { Icon } from './Icon';

const PASS = new Set(['success', 'passed', 'pass']);
const FAIL = new Set(['policy_failure', 'failure', 'failed', 'fail']);

export function isPass(outcome: string): boolean {
  return PASS.has(outcome);
}
export function isFail(outcome: string): boolean {
  return FAIL.has(outcome);
}

export function outcomeWord(outcome: string): string {
  if (isPass(outcome)) return 'passed';
  if (isFail(outcome)) return 'failed';
  if (outcome === 'invalid_scene' || outcome === 'invalid') return 'invalid scene';
  return outcome.replace(/_/g, ' ');
}

/** One attempt per cell: failed attempts are solid with a cross, passed attempts are outlined with a tick. */
export function Outcomes({ outcomes, label }: { outcomes: string[]; label?: string }) {
  if (outcomes.length === 0) {
    return <span className="muted">not run</span>;
  }
  const failed = outcomes.filter(isFail).length;
  const invalid = outcomes.filter((o) => !isPass(o) && !isFail(o)).length;
  const summary = `${failed} of ${outcomes.length} failed${invalid > 0 ? `, ${invalid} invalid` : ''}`;
  return (
    <span className="outcomes">
      <span className="outcomes__cells" role="img" aria-label={label ? `${label}: ${summary}` : summary}>
        {outcomes.map((outcome, index) => {
          const kind = isFail(outcome) ? 'fail' : isPass(outcome) ? 'pass' : 'other';
          return (
            <span key={index} className={`cell cell--${kind}`} title={outcomeWord(outcome)}>
              <Icon name={kind === 'fail' ? 'close' : kind === 'pass' ? 'tick' : 'minus'} />
            </span>
          );
        })}
      </span>
      <span className="outcomes__text">{summary}</span>
    </span>
  );
}
