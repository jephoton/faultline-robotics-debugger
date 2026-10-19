// A small in-memory implementation of the API contract, shared by the Vite dev middleware
// (VITE_MOCK=1) and the tests. It is never imported by the production bundle.
import type { Branch, DryRun, DryRunBranch, DryRunJob, Environment as EnvironmentChecks, FieldError, Progress, ValidateResult } from '../api/types';
import { AUDIT_FAMILIES } from '../data/tasks';
import {
  IDS,
  RUN_IDS,
  activeRunSummaries,
  detailById,
  environment,
  evidence,
  library,
  progressById,
  sessionLocal,
  sessionStatic,
  specTemplates,
} from './fixtures';

export interface MockRequest {
  method: string;
  /** Path plus query, for example /api/specs/template?mode=audit */
  url: string;
  headers: Record<string, string>;
  body?: unknown;
}

export interface MockResponse {
  status: number;
  body: unknown;
  contentType?: string;
}

export interface MockOptions {
  /** "static" mimics a deployed gallery: only data/*.json exists and /api/* falls through to index.html. */
  mode?: 'local' | 'static';
  /** Show one active run (the waiting-for-GPU fixture) in the sidebar. */
  activeDemo?: boolean;
  /** Replace the environment checks (tests). */
  environment?: EnvironmentChecks;
  /** Answer POST /api/runs with this error status (tests of an ambiguous start, such as a 504). */
  launchStatus?: number;
}

export const MOCK_TOKEN = sessionLocal.token as string;

function djb2(text: string): string {
  let hash = 5381;
  for (let i = 0; i < text.length; i += 1) hash = ((hash << 5) + hash + text.charCodeAt(i)) | 0;
  return (hash >>> 0).toString(16).padStart(8, '0');
}

function line(yaml: string, key: string): string | null {
  const match = new RegExp(`^\\s*${key}:\\s*(.+?)\\s*$`, 'm').exec(yaml);
  return match ? (match[1] as string).replace(/^["']|["']$/g, '') : null;
}

export function mockValidate(yaml: string): ValidateResult {
  const errors: FieldError[] = [];
  if (!/^faultline:\s*1\s*$/m.test(yaml)) errors.push({ path: 'faultline', message: 'must be 1' });
  const mode = line(yaml, 'mode');
  if (!mode || !['diagnose', 'scenario', 'audit', 'paraphrase', 'replay'].includes(mode)) {
    errors.push({ path: 'mode', message: 'must be diagnose, scenario, audit, paraphrase or replay' });
  }
  const spend = Number(line(yaml, 'max_spend_usd'));
  if (!Number.isFinite(spend) || spend <= 0) {
    errors.push({ path: 'budget.max_spend_usd', message: 'must be a positive number' });
  }
  const hours = Number(line(yaml, 'max_hours'));
  if (!Number.isFinite(hours) || hours <= 0) {
    errors.push({ path: 'budget.max_hours', message: 'must be a positive number' });
  }
  const start = line(yaml, 'start');
  if ((mode === 'scenario' || mode === 'diagnose') && start !== null && /^\d+$/.test(start) && Number(start) > 49) {
    errors.push({ path: `${mode}.start`, message: 'must be between 0 and 49' });
  }
  const families = /families:\s*\[(.*?)\]/.exec(yaml);
  const probing = mode === 'diagnose' && line(yaml, 'enabled') !== 'false';
  if ((mode === 'audit' || probing) && families && (families[1] as string).trim() === '') {
    errors.push({ path: mode === 'audit' ? 'audit.families' : 'diagnose.probes.families', message: 'choose at least one family' });
  }
  if (mode === 'diagnose') {
    const rewordings = line(yaml, 'rewordings');
    if (rewordings !== null && (!/^\d+$/.test(rewordings) || Number(rewordings) > 12)) {
      errors.push({ path: 'diagnose.probes.rewordings', message: 'must be a whole number from 0 to 12' });
    }
    // Like the server: probes follow the untouched check of one start, so a range or a file cannot have them.
    if (start === null && /^\s*probes:/m.test(yaml)) {
      errors.push({ path: 'diagnose.probes', message: 'applies only to a single start, not to a range or a start file' });
    }
  }
  return { ok: errors.length === 0, errors, summary: { name: line(yaml, 'name'), mode } };
}

const round = (value: number) => Math.round(value * 100) / 100;

function job(name: string, deadline_seconds: number, worst_case_usd: number, branch?: Branch): DryRunJob {
  return branch ? { name, deadline_seconds, worst_case_usd, branch } : { name, deadline_seconds, worst_case_usd };
}

/** A diagnose plan: the check, then the layout and probe branches (only one of which runs). */
function diagnoseJobs(yaml: string): { jobs: DryRunJob[]; branches: DryRunBranch[]; total: number } {
  const single = line(yaml, 'start') !== null;
  const jobs: DryRunJob[] = [single ? job('check', 1800, 0.98, 'check') : job('screen', 1800, 0.98, 'check')];
  if (line(yaml, 'layout') !== 'false') {
    jobs.push(job('reference', 1500, 0.84, 'layout'), job('reduce', 3000, 1.27, 'layout'));
  }
  if (single && line(yaml, 'enabled') !== 'false') {
    const chosen = /families:\s*\[(.*?)\]/.exec(yaml)?.[1]?.split(',').map((key) => key.trim()).filter(Boolean) ?? [];
    const group = (kind: 'image' | 'scene') => chosen.filter((key) => AUDIT_FAMILIES.find((family) => family.key === key)?.group === kind);
    // One audit Job holds at most four image families (the 40 minute limit), scene families share one Job.
    for (let index = 0; index * 4 < group('image').length; index += 1) jobs.push(job(`probe-images-${index + 1}`, 2400, 1.3, 'probes'));
    if (group('scene').length > 0) jobs.push(job('probe-scene', 2000, 1.2, 'probes'));
    if (Number(line(yaml, 'rewordings') ?? '0') > 0) jobs.push(job('rewordings-screen', 1800, 0.98, 'probes'), job('rewordings-reduce', 2400, 1.22, 'probes'));
  }
  const worst = (branch: Branch) => round(jobs.filter((entry) => entry.branch === branch).reduce((sum, entry) => sum + entry.worst_case_usd, 0));
  const present = (['check', 'layout', 'probes'] as Branch[]).filter((branch) => jobs.some((entry) => entry.branch === branch));
  // Like the server: about half the worst case for a measured Job; unknown (null) cost for the layout branch.
  const minutes: Record<Branch, number> = { check: 15, layout: 25, probes: 25 };
  const branches: DryRunBranch[] = present.map((branch) => ({
    branch,
    worst_case_usd: worst(branch),
    typical_usd: branch === 'layout' ? null : round(worst(branch) * 0.5),
    typical_minutes: minutes[branch],
  }));
  return { jobs, branches, total: round(worst('check') + Math.max(worst('layout'), worst('probes'))) };
}

/** The Jobs of a replay, by the kind of case replayed (a stress test runs one Job per probe group). */
function replayJobs(caseId: string | undefined): DryRunJob[] {
  const kind = caseId ? detailById[caseId]?.kind : undefined;
  if (kind === 'audit') {
    return [
      { name: 'replay', deadline_seconds: 2400, worst_case_usd: 1.62 },
      { name: 'replay-2', deadline_seconds: 2000, worst_case_usd: 1.38 },
    ] as DryRunJob[];
  }
  if (kind === 'paraphrase') return [{ name: 'replay', deadline_seconds: 1200, worst_case_usd: 0.9 }] as DryRunJob[];
  return [{ name: 'replay', deadline_seconds: 1500, worst_case_usd: 0.7 }] as DryRunJob[];
}

export function mockDryRun(yaml: string, importContent?: string, caseId?: string): DryRun {
  const mode = line(yaml, 'mode') ?? 'scenario';
  if (mode === 'diagnose') {
    const plan = diagnoseJobs(yaml);
    return {
      plan_hash: djb2(`${yaml}
${importContent ?? ''}`),
      jobs: plan.jobs,
      branches: plan.branches,
      worst_case_total_usd: plan.total,
      cap_usd: Number(line(yaml, 'max_spend_usd')) || 0,
      max_hours: Number(line(yaml, 'max_hours')) || 0,
      lines: plan.jobs.map((entry) => `${entry.branch}: ${entry.name}, deadline ${entry.deadline_seconds} s, worst case US$${entry.worst_case_usd.toFixed(2)}`),
    };
  }
  const jobs =
    mode === 'audit'
      ? [{ name: 'audit', deadline_seconds: 3000, worst_case_usd: 1.46 }]
      : mode === 'paraphrase'
        ? [
            { name: 'screen', deadline_seconds: 1800, worst_case_usd: 0.98 },
            { name: 'reduce', deadline_seconds: 2400, worst_case_usd: 1.22 },
          ]
        : mode === 'replay'
          ? replayJobs(caseId)
          : [
              { name: 'screen', deadline_seconds: 1800, worst_case_usd: 0.98 },
              { name: 'reference', deadline_seconds: 1500, worst_case_usd: 0.84 },
              { name: 'reduce', deadline_seconds: 3000, worst_case_usd: 1.27 },
            ];
  const total = Math.round(jobs.reduce((sum, job) => sum + job.worst_case_usd, 0) * 100) / 100;
  return {
    plan_hash: djb2(`${yaml}\n${importContent ?? ''}${mode === 'replay' ? `\n${jobs.map((entry) => entry.name).join()}` : ''}`),
    jobs,
    worst_case_total_usd: total,
    cap_usd: Number(line(yaml, 'max_spend_usd')) || 0,
    max_hours: Number(line(yaml, 'max_hours')) || 0,
    lines: jobs.map((job) => `${job.name}: deadline ${job.deadline_seconds} s, worst case US$${job.worst_case_usd.toFixed(2)}`),
  };
}

function json(status: number, body: unknown): MockResponse {
  return { status, body };
}

function failure(status: number, error: string, errors: FieldError[] = []): MockResponse {
  return json(status, { error, errors });
}

export function createMockServer(options: MockOptions = {}) {
  const mode = options.mode ?? 'local';
  const activeDemo = options.activeDemo ?? true;
  const launchStatus = options.launchStatus;
  const started = new Map<string, number>();
  const stopped = new Set<string>();
  let counter = 0;

  function progressFor(run: string, advance = true): Progress | null {
    const poll = started.get(run);
    if (poll !== undefined) {
      if (advance) started.set(run, poll + 1);
      const template = progressById[RUN_IDS.waiting] as Progress;
      if (stopped.has(run)) {
        return { ...template, run, status: 'stopped', stop_reason: 'stopped_by_user', stop_text: 'Stopped from the control panel or `faultline stop`.', job: null, resumable: true, stoppable: false, attention: true };
      }
      if (poll < 2) return { ...template, run, name: 'new-diagnosis', job: { name: 'screen-attempt-1', phase: poll === 0 ? 'submitting' : 'waiting_for_gpu' } };
      if (poll < 4) {
        return {
          ...template,
          run,
          name: 'new-diagnosis',
          attention: false,
          job: { name: 'screen-attempt-1', phase: 'running' },
          steps: template.steps.map((step) => (step.key === 'screen' ? { ...step, state: 'running', capacity_waits: 0 } : step)),
        };
      }
      const done = progressById[RUN_IDS.completed] as Progress;
      return { ...done, run, name: 'new-diagnosis' };
    }
    return progressById[run] ?? null;
  }

  function guard(req: MockRequest): MockResponse | null {
    if (mode === 'static') return failure(404, 'Controls are not available in the gallery.');
    if (req.headers['x-faultline-token'] !== MOCK_TOKEN) {
      return failure(403, 'The control panel refused this request. Reload the page and try again.');
    }
    return null;
  }

  function handle(req: MockRequest): MockResponse | null {
    const parsed = new URL(req.url, 'http://mock.local');
    const path = parsed.pathname;
    const method = req.method.toUpperCase();

    // Static gallery data files, as `faultline export` writes them.
    if (path === '/data/session.json') return json(200, sessionStatic);
    if (path === '/data/library.json') return json(200, library);
    const dataDetail = /^\/data\/library\/([^/]+)\.json$/.exec(path);
    if (dataDetail) {
      const found = detailById[decodeURIComponent(dataDetail[1] as string)];
      return found ? json(200, found) : failure(404, 'That case was not found.');
    }

    if (!path.startsWith('/api/')) return null;
    if (mode === 'static') return { status: 200, body: '<!doctype html><title>Faultline</title>', contentType: 'text/html' };

    if (method === 'GET') {
      if (path === '/api/session') return json(200, sessionLocal);
      if (path === '/api/library') return json(200, library);
      const detail = /^\/api\/library\/([^/]+)$/.exec(path);
      if (detail) {
        const found = detailById[decodeURIComponent(detail[1] as string)];
        return found ? json(200, found) : failure(404, 'That case was not found.');
      }
      if (path === '/api/runs/active') {
        const live = [...started.keys()].filter((run) => (started.get(run) ?? 0) < 4 && !stopped.has(run));
        if (live.length > 0) {
          return json(200, {
            runs: live.map((run) => {
              const p = progressFor(run, false) as Progress;
              return { run, name: p.name, mode: p.mode, status: 'running', step: p.step, spent_usd: p.spent_usd, cap_usd: p.cap_usd, attention: p.attention };
            }),
          });
        }
        return json(200, { runs: activeDemo ? activeRunSummaries() : [] });
      }
      const progress = /^\/api\/runs\/([^/]+)\/progress$/.exec(path);
      if (progress) {
        const found = progressFor(decodeURIComponent(progress[1] as string));
        return found ? json(200, found) : failure(404, 'That run was not found.');
      }
      if (path === '/api/environment') return json(200, options.environment ?? environment);
      if (path === '/api/evidence') return json(200, evidence);
      if (path === '/api/specs/template') {
        const template = specTemplates[parsed.searchParams.get('mode') ?? ''];
        return template ? json(200, { yaml: template }) : failure(400, 'Unknown spec template.');
      }
      return failure(404, 'Not found.');
    }

    if (method === 'POST') {
      const refused = guard(req);
      if (refused) return refused;
      const body = (req.body ?? {}) as Record<string, unknown>;
      if (path === '/api/specs/validate') return json(200, mockValidate(String(body.yaml ?? '')));
      if (path === '/api/specs/dry-run') {
        const yaml = String(body.yaml ?? '');
        const result = mockValidate(yaml);
        if (!result.ok) return failure(422, 'The spec has problems; fix them before the dry run.', result.errors);
        const file = body.import_file as { content?: string } | undefined;
        return json(200, mockDryRun(yaml, file?.content, typeof body.case_id === 'string' ? body.case_id : undefined));
      }
      if (path === '/api/runs') {
        if (launchStatus) return failure(launchStatus, 'The run did not report its folder in time.');
        const yaml = String(body.yaml ?? '');
        const file = body.import_file as { content?: string } | undefined;
        const fresh = mockDryRun(yaml, file?.content);
        if (body.plan_hash !== fresh.plan_hash) {
          return failure(412, 'The plan changed since the dry run. Run the dry run again.');
        }
        if (activeDemo || [...started.values()].some((poll) => poll < 4)) {
          return failure(409, 'A run is already active. Wait for it to finish or stop it first.');
        }
        counter += 1;
        const run = `new-diagnosis-20261017-12000${counter}`;
        started.set(run, 0);
        return json(202, { run, library_id: null });
      }
      const stop = /^\/api\/runs\/([^/]+)\/stop$/.exec(path);
      if (stop) {
        const run = decodeURIComponent(stop[1] as string);
        if (started.has(run)) stopped.add(run);
        return json(202, { status: 'stopping' });
      }
      const resume = /^\/api\/runs\/([^/]+)\/resume$/.exec(path);
      if (resume) {
        if (activeDemo) return failure(409, 'A run is already active. Wait for it to finish or stop it first.');
        // Like the real server: a resume continues the same run folder.
        const run = decodeURIComponent(resume[1] as string);
        const base = progressById[run];
        if (base && typeof body.max_spend_usd === 'number' && body.max_spend_usd < base.cap_usd) {
          return failure(400, 'The spend cap can be raised on a resume, never lowered.');
        }
        stopped.delete(run);
        started.set(run, 0);
        return json(202, { run });
      }
      const replay = /^\/api\/library\/([^/]+)\/replay$/.exec(path);
      if (replay) {
        const yaml = String(body.yaml ?? '');
        if (body.plan_hash !== mockDryRun(yaml, undefined, decodeURIComponent(replay[1] as string)).plan_hash) {
          return failure(412, 'The plan changed since the dry run. Run the dry run again.');
        }
        if (activeDemo) return failure(409, 'A run is already active. Wait for it to finish or stop it first.');
        counter += 1;
        const run = `replay-soup-20261017-13000${counter}`;
        started.set(run, 0);
        return json(202, { run });
      }
      return failure(404, 'Not found.');
    }
    return failure(405, 'Method not allowed.');
  }

  return { handle, library: () => library, ids: IDS };
}

export type MockServer = ReturnType<typeof createMockServer>;

/** A fetch implementation backed by a mock server, for tests. */
export function mockFetch(server: MockServer): typeof fetch {
  return (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.pathname + input.search : input.url;
    const headers: Record<string, string> = {};
    new Headers(init?.headers).forEach((value, key) => {
      headers[key.toLowerCase()] = value;
    });
    let body: unknown;
    if (typeof init?.body === 'string') {
      try {
        body = JSON.parse(init.body);
      } catch {
        body = undefined;
      }
    }
    const result = server.handle({ method: init?.method ?? 'GET', url, headers, body });
    if (!result) return new Response('Not found', { status: 404 });
    const isText = typeof result.body === 'string';
    return new Response(isText ? (result.body as string) : JSON.stringify(result.body), {
      status: result.status,
      headers: { 'Content-Type': result.contentType ?? 'application/json' },
    });
  }) as typeof fetch;
}
