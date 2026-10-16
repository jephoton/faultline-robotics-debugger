import type { IconName } from '../components/Icon';
import type { JobPhase, Progress } from '../api/types';
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

/** A code is assigned when the case is saved; until then the readout shows its shape. */
export function pendingCode(mode: string): string {
  return `FL-${KIND_LETTER[mode] ?? 'X'}-····`;
}
