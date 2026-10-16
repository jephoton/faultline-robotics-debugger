import type { FieldError, SpecMode } from '../api/types';
import { taskInstruction } from '../data/tasks';

/** The three things a person can ask for in step 1 (scenario has three ways to name the failing start). */
export type DiagnosisChoice = Exclude<SpecMode, 'replay'>;

export interface FormState {
  name: string;
  suite: string;
  task: string;
  start: string;
  range: string;
  confirm: string;
  families: string[];
  count: string;
  spend: string;
  hours: string;
  nemotron: boolean;
  importFile: { name: string; content: string } | null;
}

export function defaultsFor(choice: DiagnosisChoice): FormState {
  const base: FormState = {
    name: '',
    suite: 'libero_10',
    task: '0',
    start: '14',
    range: '10-49',
    confirm: '4',
    families: ['blur', 'noise', 'darken', 'contrast'],
    count: '10',
    spend: '3.5',
    hours: '2',
    nemotron: true,
    importFile: null,
  };
  switch (choice) {
    case 'scenario-start':
      return { ...base, name: 'soup-start14' };
    case 'scenario-screen':
      return { ...base, name: 'soup-screen', spend: '4', hours: '3' };
    case 'scenario-import':
      return { ...base, name: 'my-failing-start', spend: '3', hours: '2' };
    case 'audit':
      return { ...base, name: 'audit-task0', suite: 'libero_object', start: '0', spend: '2', hours: '1.5', nemotron: false };
    case 'paraphrase':
      return { ...base, name: 'paraphrase-task0', suite: 'libero_object', start: '0', spend: '4', hours: '3', nemotron: false };
  }
}

/** The `backend:` block of a spec template (from the first `backend:` line to the end), or null. */
export function extractBackend(template: string): string | null {
  const match = /^backend:[\s\S]*$/m.exec(template);
  return match ? match[0].replace(/\s+$/, '') : null;
}

/** A number as typed; anything that is not a number is quoted so the server reports it by name. */
function num(value: string, fallback: string): string {
  const trimmed = value.trim();
  if (trimmed === '') return fallback;
  return /^-?\d+(\.\d+)?$/.test(trimmed) ? trimmed : JSON.stringify(trimmed);
}

const NAME_OK = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

/** Build a spec from the form. Anything the form does not cover is added in the YAML panel. */
export function buildYaml(choice: DiagnosisChoice, form: FormState, backend: string | null): string {
  const name = NAME_OK.test(form.name.trim()) ? form.name.trim() : JSON.stringify(form.name.trim());
  const lines: string[] = ['faultline: 1', `name: ${name}`];
  const mode = choice.startsWith('scenario') ? 'scenario' : choice;
  lines.push(`mode: ${mode}`);
  lines.push(`policy: {suite: ${form.suite}}`);
  if (choice === 'scenario-start' || choice === 'scenario-screen' || choice === 'scenario-import') {
    lines.push('scenario:', `  task: ${num(form.task, '0')}`);
    if (choice === 'scenario-start') lines.push(`  start: ${num(form.start, '0')}`);
    if (choice === 'scenario-screen') lines.push(`  screen: {starts: ${JSON.stringify(form.range.trim())}, confirm: ${num(form.confirm, '4')}}`);
    if (choice === 'scenario-import') lines.push(`  import: ${form.importFile ? form.importFile.name : 'my-failing-start.candidate.json'}`);
    lines.push('  reference: auto');
  } else if (choice === 'audit') {
    lines.push('audit:', `  task: ${num(form.task, '0')}`, `  start: ${num(form.start, '0')}`, `  families: [${form.families.join(', ')}]`);
  } else {
    lines.push('paraphrase:', `  task: ${num(form.task, '0')}`, `  start: ${num(form.start, '0')}`, `  count: ${num(form.count, '10')}`);
    const instruction = taskInstruction(form.suite, Number(form.task));
    if (instruction) lines.push(`  instruction: ${JSON.stringify(instruction)}`);
  }
  lines.push('budget:', `  max_spend_usd: ${num(form.spend, '0')}`, `  max_hours: ${num(form.hours, '0')}`);
  if (mode === 'scenario') lines.push('  max_candidates: 36');
  if (mode === 'scenario') {
    lines.push(`nemotron: {hypothesis: ${form.nemotron}, explain: ${form.nemotron}}`);
  } else {
    lines.push('nemotron: {hypothesis: false, explain: false}');
  }
  if (backend) lines.push(backend);
  return `${lines.join('\n')}\n`;
}

/** Read a top-level or nested scalar from the spec text (used for the review summary, so YAML edits show). */
export function yamlValue(yaml: string, key: string): string | null {
  const match = new RegExp(`^\\s*${key}:\\s*(.+?)\\s*$`, 'm').exec(yaml);
  return match ? (match[1] as string).replace(/^["']|["']$/g, '') : null;
}

export type FieldKey = keyof FormState | 'file';

/** Which form field an error path belongs to; null when it only belongs to the YAML. */
export function fieldForPath(path: string): FieldKey | null {
  const p = path.toLowerCase();
  if (p === 'name') return 'name';
  if (p.startsWith('policy.suite') || p === 'policy') return 'suite';
  if (p.endsWith('.task')) return 'task';
  if (/\.(start)$/.test(p)) return 'start';
  if (p.includes('screen')) return 'range';
  if (p.endsWith('.import')) return 'file';
  if (p.includes('families')) return 'families';
  if (p.endsWith('.count')) return 'count';
  if (p.includes('max_spend_usd')) return 'spend';
  if (p.includes('max_hours')) return 'hours';
  if (p.startsWith('nemotron')) return 'nemotron';
  return null;
}

export function errorsByField(errors: FieldError[]): { byField: Partial<Record<FieldKey, string[]>>; other: FieldError[] } {
  const byField: Partial<Record<FieldKey, string[]>> = {};
  const other: FieldError[] = [];
  for (const error of errors) {
    const field = fieldForPath(error.path);
    if (field) (byField[field] ??= []).push(error.message);
    else other.push(error);
  }
  return { byField, other };
}

export interface ReplayForm {
  spend: string;
  hours: string;
  checkpointId: string;
  checkpointRevision: string;
}

export const REPLAY_DEFAULTS: ReplayForm = { spend: '1', hours: '1', checkpointId: '', checkpointRevision: '' };

/** A replay spec for `faultline replay`: budget, an optional checkpoint override and the template's backend. */
export function buildReplayYaml(caseName: string, form: ReplayForm, backend: string | null): string {
  const slug = `replay-${caseName}`.replace(/[^A-Za-z0-9._-]+/g, '-').replace(/-+$/, '');
  const lines = ['faultline: 1', `name: ${slug}`, 'mode: replay'];
  const id = form.checkpointId.trim();
  const revision = form.checkpointRevision.trim();
  if (id || revision) {
    lines.push('policy:', `  checkpoint: {id: ${JSON.stringify(id)}, revision: ${JSON.stringify(revision)}}`);
  }
  lines.push('budget:', `  max_spend_usd: ${num(form.spend, '0')}`, `  max_hours: ${num(form.hours, '0')}`);
  if (backend) lines.push(backend);
  return `${lines.join('\n')}\n`;
}
