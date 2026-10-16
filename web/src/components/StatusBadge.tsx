import type { Verdict } from '../api/types';
import { statusFor } from '../lib/status';
import { Icon } from './Icon';

/** Verdict as an icon plus a word; red only for a repeating failure, amber for attention. */
export function StatusBadge({ verdict, attention }: { verdict: Verdict; attention: boolean }) {
  const view = statusFor(verdict, attention);
  const cls = view.tone === 'neutral' ? 'badge' : `badge badge--${view.tone}`;
  return (
    <span className={cls} data-tone={view.tone}>
      <Icon name={view.icon} />
      {view.label}
    </span>
  );
}
