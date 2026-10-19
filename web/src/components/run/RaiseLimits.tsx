import { useId } from 'react';
import { Icon } from '../Icon';

/** The stop reasons that a larger limit fixes. */
export function raisesLimits(reason: string | null | undefined): boolean {
  return reason === 'spend_cap' || reason === 'max_hours';
}

export interface LimitText {
  spend: string | null;
  hours: string | null;
}

export interface LimitRequest {
  max_spend_usd?: number;
  max_hours?: number;
}

function parse(text: string | null): number | null | 'bad' {
  if (text === null) return null;
  const trimmed = text.trim();
  if (trimmed === '') return 'bad';
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : 'bad';
}

/**
 * What the two fields ask for, against the limits the run has now: the values that went up, and a sentence for
 * the first one that is not acceptable (a limit can be raised on a resume, never lowered).
 */
export function limitRequest(text: LimitText, cap: number, hours: number): { request: LimitRequest; problem: string | null } {
  const request: LimitRequest = {};
  const spend = parse(text.spend);
  const time = parse(text.hours);
  if (spend === 'bad' || (spend !== null && spend < cap)) {
    return { request, problem: `The spend cap can be raised, not lowered: enter US$${cap.toFixed(2)} or more.` };
  }
  if (time === 'bad' || (time !== null && time < hours)) {
    return { request, problem: `The hour limit can be raised, not lowered: enter ${hours} or more.` };
  }
  if (spend !== null && spend > cap) request.max_spend_usd = spend;
  if (time !== null && time > hours) request.max_hours = time;
  return { request, problem: null };
}

interface Props {
  reason: 'spend_cap' | 'max_hours';
  cap: number;
  hours: number;
  spent: number;
  text: LimitText;
  problem: string | null;
  onChange: (text: LimitText) => void;
}

/** New limits for a run that stopped at its spend cap or hour limit, shown next to Resume. */
export function RaiseLimits({ reason, cap, hours, spent, text, problem, onChange }: Props) {
  const uid = useId();
  return (
    <fieldset className="raise-limits" aria-describedby={`${uid}-hint`}>
      <legend>Raise the limit before you resume</legend>
      <p className="field__hint" id={`${uid}-hint`}>
        {reason === 'spend_cap'
          ? `The run stopped because the next Job could pass the US$${cap.toFixed(2)} cap (US$${spent.toFixed(2)} spent). `
          : `The run stopped at its ${hours} hour limit. `}
        A limit can be raised on a resume, never lowered.
      </p>
      <div className="raise-limits__fields">
        <div className="field">
          <label htmlFor={`${uid}-spend`}>New spend cap (US$)</label>
          <input
            id={`${uid}-spend`}
            type="number"
            inputMode="decimal"
            min={cap}
            step="0.1"
            value={text.spend ?? String(cap)}
            onChange={(event) => onChange({ ...text, spend: event.target.value })}
            aria-invalid={problem !== null && problem.startsWith('The spend cap') ? true : undefined}
          />
        </div>
        <div className="field">
          <label htmlFor={`${uid}-hours`}>New hour limit</label>
          <input
            id={`${uid}-hours`}
            type="number"
            inputMode="decimal"
            min={hours}
            step="0.25"
            value={text.hours ?? String(hours)}
            onChange={(event) => onChange({ ...text, hours: event.target.value })}
            aria-invalid={problem !== null && problem.startsWith('The hour limit') ? true : undefined}
          />
        </div>
      </div>
      {problem && (
        <span className="field__error" role="alert">
          <Icon name="alarm" /> {problem}
        </span>
      )}
    </fieldset>
  );
}
