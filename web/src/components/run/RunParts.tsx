import { useEffect, useRef } from 'react';
import type { Progress, ProgressStep } from '../../api/types';
import { duration, usd } from '../../lib/format';
import { PHASE_LABEL } from '../../lib/runs';
import { Icon, type IconName } from '../Icon';

function stepIcon(step: ProgressStep): IconName {
  if (step.status === 'completed') return 'tick';
  if (step.status === 'stopped' || step.status === 'failed') return 'attention';
  if (step.status === 'running') return 'clock';
  return 'minus';
}

function stepText(step: ProgressStep): string {
  const parts: string[] = [];
  if (step.state === 'waiting_for_gpu') parts.push('waiting for a GPU');
  else if (step.status === 'running') parts.push(step.state && step.state !== 'running' ? step.state.replace(/_/g, ' ') : 'running');
  else parts.push(step.status.replace(/_/g, ' '));
  if (step.attempts > 1) parts.push(`${step.attempts} attempts`);
  if (step.capacity_waits > 0) parts.push(`${step.capacity_waits} capacity ${step.capacity_waits === 1 ? 'wait' : 'waits'}`);
  return parts.join(', ');
}

export function StepList({ steps }: { steps: ProgressStep[] }) {
  return (
    <ol className="timeline" aria-label="Steps of this run">
      {steps.map((step) => {
        const attention = step.status === 'stopped' || step.status === 'failed' || step.state === 'waiting_for_gpu';
        return (
          <li
            key={step.key}
            className={attention ? 'timeline__step timeline__step--attention' : 'timeline__step'}
            aria-current={step.status === 'running' ? 'step' : undefined}
          >
            <Icon name={stepIcon(step)} />
            <span className="timeline__label">{step.label}</span>
            <span className="timeline__state muted">{stepText(step)}</span>
            <span />
          </li>
        );
      })}
    </ol>
  );
}

export function JobPanel({ progress }: { progress: Progress }) {
  const job = progress.job;
  if (!job || !job.phase) {
    return <p className="muted">No cloud Job is active right now.</p>;
  }
  const waiting = job.phase === 'waiting_for_gpu';
  const waits = progress.steps.reduce((total, step) => total + step.capacity_waits, 0);
  return (
    <div className={waiting ? 'panel panel--attention' : 'panel'}>
      <p className="job__phase">
        <Icon name={waiting ? 'attention' : 'clock'} />
        <strong>{PHASE_LABEL[job.phase]}</strong>
        <span className="muted mono">{job.name}</span>
      </p>
      {waiting && (
        <p>
          No GPU is free yet. Faultline resubmits the Job automatically, up to six times
          {waits > 0 ? `; ${waits} ${waits === 1 ? 'wait' : 'waits'} so far in this run` : ''}. The worst case stays reserved until the Job is settled at its measured time.
        </p>
      )}
    </div>
  );
}

function pct(value: number, max: number): number {
  if (max <= 0) return 0;
  return Math.max(0, Math.min(100, (value / max) * 100));
}

export function Meters({ progress }: { progress: Progress }) {
  const spentPct = pct(progress.spent_usd, progress.cap_usd);
  const reservedPct = Math.min(100 - spentPct, pct(progress.reserved_usd, progress.cap_usd));
  const limit = progress.max_hours * 3600;
  const timePct = pct(progress.elapsed_seconds, limit);
  return (
    <div className="meters">
      <div>
        <p className="meter__label">
          <strong>Spend</strong>
          <span className="mono">
            {usd(progress.spent_usd)} spent
            {progress.reserved_usd > 0 ? `, ${usd(progress.reserved_usd)} reserved` : ''} of {usd(progress.cap_usd)}
          </span>
        </p>
        <div
          className="meter"
          role="meter"
          aria-label="Spend against the cap"
          aria-valuemin={0}
          aria-valuemax={progress.cap_usd}
          aria-valuenow={Math.min(progress.cap_usd, progress.spent_usd + progress.reserved_usd)}
          aria-valuetext={`${usd(progress.spent_usd)} spent and ${usd(progress.reserved_usd)} reserved of a ${usd(progress.cap_usd)} cap`}
        >
          <span className="meter__spent" style={{ width: `${spentPct}%` }} />
          <span className="meter__reserved" style={{ width: `${reservedPct}%` }} />
        </div>
        <p className="muted meter__legend">Solid is spent. Hatched is the worst case held back for a Job that is still running.</p>
      </div>
      <div>
        <p className="meter__label">
          <strong>Time</strong>
          <span className="mono">
            {duration(progress.elapsed_seconds)} of {progress.max_hours} h
          </span>
        </p>
        <div
          className="meter"
          role="meter"
          aria-label="Time against the limit"
          aria-valuemin={0}
          aria-valuemax={limit}
          aria-valuenow={Math.min(limit, progress.elapsed_seconds)}
          aria-valuetext={`${duration(progress.elapsed_seconds)} of ${progress.max_hours} hours`}
        >
          <span className="meter__spent" style={{ width: `${timePct}%` }} />
        </div>
      </div>
    </div>
  );
}

export function LogTail({ lines }: { lines: string[] }) {
  const ref = useRef<HTMLPreElement>(null);
  useEffect(() => {
    const element = ref.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [lines]);
  return (
    <details className="log" open>
      <summary>Run log (last {lines.length} lines)</summary>
      {lines.length === 0 ? (
        <p className="empty">Nothing has been logged yet.</p>
      ) : (
        <pre ref={ref} tabIndex={0} aria-label="Last lines of the run log">
          {lines.join('\n')}
        </pre>
      )}
    </details>
  );
}

/** Stop is the one control that is always red. It asks first, in words, and Escape cancels. */
export function StopConfirm({ onConfirm, onCancel, busy }: { onConfirm: () => void; onCancel: () => void; busy: boolean }) {
  const first = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    first.current?.focus();
  }, []);
  return (
    <div
      className="confirm"
      role="alertdialog"
      aria-labelledby="stop-title"
      aria-describedby="stop-text"
      onKeyDown={(event) => {
        if (event.key === 'Escape') onCancel();
      }}
    >
      <p id="stop-title" className="confirm__title">
        Stop this run?
      </p>
      <p id="stop-text">The current Job is cancelled and charged for the time it ran. You can resume later.</p>
      <div className="actions">
        <button type="button" className="btn btn--stop" ref={first} onClick={onConfirm} aria-busy={busy}>
          <Icon name="stop" /> Stop the run
        </button>
        <button type="button" className="btn btn--secondary" onClick={onCancel}>
          Keep running
        </button>
      </div>
    </div>
  );
}
