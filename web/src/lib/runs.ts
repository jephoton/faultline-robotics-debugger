import type { IconName } from '../components/Icon';
import type { JobPhase, Progress, Route } from '../api/types';
import type { Tone } from './status';

export const TERMINAL: Progress['status'][] = ['completed', 'stopped', 'failed', 'interrupted'];

export function isTerminal(status: Progress['status']): boolean {
  return TERMINAL.includes(status);
}

export const PHASE_LABEL: Record<JobPhase, string> = {
  submitting: 'Submitting the Job',
  waiting_for_gpu: 'Waiting for a GPU',
  running: 'Running on the GPU',
  downloading: 'Downloading the results',
  settled: 'Job finished and charged',
};

export interface RunStatusView {
  word: string;
  tone: Tone;
  icon: IconName;
}

/** One plain word for where the run is, with amber for anything that needs a person. */
export function runStatusView(progress: Progress): RunStatusView {
  const phase = progress.job?.phase ?? null;
  switch (progress.status) {
    case 'running':
      if (phase === 'waiting_for_gpu') return { word: 'Waiting for a GPU', tone: 'attention', icon: 'clock' };
      if (phase === 'submitting') return { word: 'Submitting a Job', tone: 'neutral', icon: 'clock' };
      if (phase === 'downloading') return { word: 'Downloading results', tone: 'neutral', icon: 'clock' };
      return { word: 'Running', tone: progress.attention ? 'attention' : 'neutral', icon: 'clock' };
    case 'stopping':
      return { word: 'Stopping', tone: 'attention', icon: 'stop' };
    case 'completed':
      return { word: 'Completed', tone: 'neutral', icon: 'check' };
    case 'stopped':
      return { word: 'Stopped', tone: 'attention', icon: 'attention' };
    case 'failed':
      return { word: 'Failed', tone: 'attention', icon: 'attention' };
    case 'interrupted':
      return { word: 'Interrupted', tone: 'attention', icon: 'attention' };
  }
}

const KIND_LETTER: Record<string, string> = { scenario: 'S', audit: 'A', paraphrase: 'L', replay: 'R' };

/**
 * A code is assigned when the case is saved; until then the readout shows its shape. A diagnosis does not know
 * its kind until the untouched check has chosen a route.
 */
export function pendingCode(mode: string, route?: Route | null): string {
  if (mode === 'diagnose') {
    const letter = route === 'layout' ? 'S' : route === 'probes' ? 'A' : '·';
    return `FL-${letter}-····`;
  }
  return `FL-${KIND_LETTER[mode] ?? 'X'}-····`;
}

export interface RouteView {
  tone: Tone;
  icon: IconName;
  title: string;
  /** One more sentence, when the title alone could be misread. */
  detail?: string;
}

/**
 * What the untouched check decided, in plain words. Red for the confirmed failure, green for a pass, amber for a start
 * that cannot be judged.
 */
export function routeView(route: Route): RouteView {
  switch (route) {
    case 'layout':
      return { tone: 'alarm', icon: 'alarm', title: 'The start failed untouched: finding the smallest layout change' };
    case 'probes':
      return { tone: 'pass', icon: 'check', title: 'The start passed: probing' };
    case 'flaky':
      return {
        tone: 'attention',
        icon: 'attention',
        title: 'The start is flaky untouched: rewordings skipped',
        detail: 'It does not pass reliably on its own, so no disturbance or wording can be blamed for a failure.',
      };
    case 'passes':
      return { tone: 'pass', icon: 'check', title: 'Passes untouched', detail: 'The start did not fail, so there was no failure to reduce.' };
  }
}
