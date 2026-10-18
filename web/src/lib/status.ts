import type { IconName } from '../components/Icon';
import type { Kind, Verdict } from '../api/types';

/**
 * Outcome colour rule: red for a confirmed, reproducing failure (and Stop), green for a pass or "no failure
 * found", amber for attention, everything else neutral. Every status has an icon and a word as well.
 */
export type Tone = 'alarm' | 'pass' | 'attention' | 'neutral';

export interface StatusView {
  tone: Tone;
  icon: IconName;
  label: string;
  short: string;
}

export function statusFor(verdict: Verdict, attention: boolean): StatusView {
  if (verdict === 'reproduces') {
    return { tone: 'alarm', icon: 'alarm', label: 'Failure repeats', short: 'Repeats' };
  }
  const labels: Record<Exclude<Verdict, 'reproduces'>, { label: string; short: string; icon: IconName }> = {
    no_failure: { label: 'No failure found', short: 'No failure', icon: 'check' },
    stopped: { label: 'Stopped', short: 'Stopped', icon: 'attention' },
    failed: { label: 'Run failed', short: 'Failed', icon: 'attention' },
    incomplete: { label: 'Incomplete', short: 'Incomplete', icon: 'dash' },
  };
  const entry = labels[verdict];
  if (attention || verdict === 'stopped' || verdict === 'failed') {
    return { tone: 'attention', icon: 'attention', label: entry.label, short: entry.short };
  }
  // A pass is an outcome too, so it is green (with its tick and word) rather than neutral.
  if (verdict === 'no_failure') return { tone: 'pass', icon: 'check', label: entry.label, short: entry.short };
  return { tone: 'neutral', icon: entry.icon, label: entry.label, short: entry.short };
}

export const KIND_LABEL: Record<Kind, string> = {
  scenario: 'Scenario reduction',
  audit: 'Stress test',
  paraphrase: 'Language test',
  occlusion: 'Occlusion case',
};

export const KIND_GROUP: { kind: Kind; title: string }[] = [
  { kind: 'scenario', title: 'Scenario reductions' },
  { kind: 'audit', title: 'Stress tests' },
  { kind: 'paraphrase', title: 'Language' },
  { kind: 'occlusion', title: 'Earlier' },
];

export const MODE_LABEL: Record<string, string> = {
  diagnose: 'Diagnosis',
  scenario: 'Scenario reduction',
  audit: 'Stress test',
  paraphrase: 'Language test',
  replay: 'Replay',
};
