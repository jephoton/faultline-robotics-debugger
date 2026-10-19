import type { FieldError } from '../api/types';
import { AUDIT_FAMILIES } from '../data/tasks';

/**
 * What to check in step 1: one benchmark start (the untouched check, then layout or probes), a range of
 * starts to search for a failure, or the person's own start file. The last two look for a failure and
 * never probe. All three make one `mode: diagnose` spec (ADR 0035).
 */
export type DiagnosisChoice = 'start' | 'screen' | 'import';

export interface FormState {
  name: string;
  suite: string;
  task: string;
  start: string;
  range: string;
  confirm: string;
  /** Probe a start that passes untouched (the master toggle). */
  probes: boolean;
  families: string[];
  /** Rewordings to ask Nemotron for; 0 skips the wording probe. */
  rewordings: string;
  spend: string;
  hours: string;
  nemotron: boolean;
  /** Find related public research (Tavily), summarised by Nemotron; context, not evidence. */
  research: boolean;
  importFile: { name: string; content: string } | null;
}

/** Every disturbance family, in the order the server lists them. */
export const ALL_FAMILIES: string[] = AUDIT_FAMILIES.map((family) => family.key);

/** The families ticked by default: where the policy has failed before. */
export const DEFAULT_FAMILIES: string[] = ['blur', 'noise', 'darken', 'contrast'];

/** Families in their canonical order, so ticking and unticking never reorders the YAML. */
export function sortFamilies(families: string[]): string[] {
  const rank = (key: string) => {
    const index = ALL_FAMILIES.indexOf(key);
    return index === -1 ? ALL_FAMILIES.length : index;
  };
  return [...families].sort((a, b) => rank(a) - rank(b));
}

/**
 * The form's starting values for a kind of start. `research` follows the machine: related research needs a
 * Tavily key, so it starts ticked only when the key is there (or not known to be missing).
 */
export function defaultsFor(choice: DiagnosisChoice, research = true): FormState {
  const base: FormState = {
    name: '',
    // LIBERO-Object task 0: its four default families fit one probe Job (the policy has failed there before).
    suite: 'libero_object',
    task: '0',
    start: '0',
    range: '10-49',
    confirm: '4',
    probes: true,
    // The four families where the policy has failed before; the other six are unticked but one tick away.
    families: [...DEFAULT_FAMILIES],
    // Rewordings are opt-in (0 skips the wording probe); 1 to 12 asks Nemotron for that many.
    rewordings: '0',
    // A small default cap: the check plus a four-family probe. The review shows when the worst case is above it.
    spend: '2.5',
    hours: '1.5',
    nemotron: true,
    research,
    importFile: null,
  };
  switch (choice) {
    case 'start':
      return { ...base, name: 'object-start0' };
    case 'screen':
      return { ...base, name: 'soup-screen', spend: '4', hours: '3' };
    case 'import':
      return { ...base, name: 'my-failing-start', spend: '3', hours: '2' };
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
  const lines: string[] = ['faultline: 1', `name: ${name}`, 'mode: diagnose', `policy: {suite: ${form.suite}}`];
  lines.push('diagnose:', `  task: ${num(form.task, '0')}`);
  if (choice === 'start') lines.push(`  start: ${num(form.start, '0')}`);
  if (choice === 'screen') lines.push(`  screen: {starts: ${JSON.stringify(form.range.trim())}, confirm: ${num(form.confirm, '4')}}`);
  if (choice === 'import') lines.push(`  import: ${form.importFile ? form.importFile.name : 'my-failing-start.candidate.json'}`);
  // Probes follow the untouched check of one benchmark start; a range and a file only look for a failure.
  if (choice === 'start') {
    lines.push(
      '  probes:',
      `    families: [${sortFamilies(form.families).join(', ')}]`,
      `    rewordings: ${num(form.rewordings, '0')}`,
      `    enabled: ${form.probes}`,
    );
  }
  // "Probe only" (layout: false) is set in the YAML panel; the form keeps the default.
  lines.push('  layout: true');
  lines.push('budget:', `  max_spend_usd: ${num(form.spend, '0')}`, `  max_hours: ${num(form.hours, '0')}`, '  max_candidates: 36');
  lines.push(`nemotron: {hypothesis: ${form.nemotron}, explain: ${form.nemotron}}`);
  lines.push(`research: ${form.research}`);
  if (backend) lines.push(backend);
  return `${lines.join('\n')}\n`;
}

/** Read a top-level or nested scalar from the spec text (used for the review summary, so YAML edits show). */
export function yamlValue(yaml: string, key: string): string | null {
  const match = new RegExp(`^\\s*${key}:\\s*(.+?)\\s*$`, 'm').exec(yaml);
  return match ? (match[1] as string).replace(/^["']|["']$/g, '') : null;
}

/** True when a run of this spec would ask Nemotron to write rewordings (it then needs a Token Factory key). */
export function asksForRewordings(yaml: string): boolean {
  const mode = yamlValue(yaml, 'mode');
  if (mode === 'paraphrase') return true;
  if (mode !== 'diagnose') return false;
  // Probes follow the untouched check of a single start; a range or a file never probe.
  if (yamlValue(yaml, 'start') === null) return false;
  if (yamlValue(yaml, 'enabled') === 'false') return false;
  const count = yamlValue(yaml, 'rewordings');
  // The server's default is 0 rewordings: a spec without the line asks for none.
  return count === null ? false : Number(count) !== 0;
}

/** True when the spec asks for related research (a Tavily search, summarised by Nemotron). */
export function asksForResearch(yaml: string): boolean {
  return /^research:\s*true\s*$/m.test(yaml);
}

/**
 * True when a run of this spec would call Nemotron: a layout reading, rewordings, or the research summary.
 * `researchRuns` is false when the research will be skipped (no Tavily key), so it needs no Nemotron.
 */
export function usesNemotron(yaml: string, researchRuns = true): boolean {
  return (
    /nemotron:\s*\{[^}]*(hypothesis|explain):\s*true/.test(yaml) ||
    asksForRewordings(yaml) ||
    (researchRuns && asksForResearch(yaml))
  );
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
  if (p.endsWith('.rewordings') || p.endsWith('.count')) return 'rewordings';
  if (p.includes('max_spend_usd')) return 'spend';
  if (p.includes('max_hours')) return 'hours';
  if (p.startsWith('nemotron')) return 'nemotron';
  if (p === 'research') return 'research';
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

export const REPLAY_DEFAULTS: ReplayForm = { spend: '1.2', hours: '1', checkpointId: '', checkpointRevision: '' };

/**
 * The spend cap and hour limit that fit a replay's plan: the plan's worst case rounded up to 10 cents (every
 * Job of the case, so a stress test with two probe groups is covered) and the time the Jobs may take
 * (deadline plus the provider's ten-minute timeout and four-minute start allowance), rounded up to a quarter hour.
 */
export function suggestedReplayLimits(plan: { jobs: { deadline_seconds: number }[]; worst_case_total_usd: number }): {
  spend: string;
  hours: string;
} {
  const hours = plan.jobs.reduce((sum, job) => sum + (job.deadline_seconds + 840) / 3600, 0);
  return {
    spend: String(Math.ceil(plan.worst_case_total_usd * 10 - 1e-9) / 10),
    hours: String(Math.max(1, Math.ceil(hours * 4 - 1e-9) / 4)),
  };
}

/** A replay spec for `faultline replay`: budget, an optional checkpoint override and the template's backend. */
export function buildReplayYaml(caseName: string, form: ReplayForm, backend: string | null): string {
  const slug = `replay-${caseName}`
    .replace(/[^A-Za-z0-9._-]+/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^-+|-+$/g, '');
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
