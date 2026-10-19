import type {
  Detail,
  DryRun,
  Environment,
  Evidence,
  FieldError,
  ImportFile,
  Library,
  Progress,
  RunSummary,
  Session,
  SpecMode,
  ValidateResult,
} from './types';

/** An API failure. `message` is a plain sentence that is safe to show; `errors` are per-field problems. */
export class ApiError extends Error {
  readonly status: number;
  readonly errors: FieldError[];

  constructor(message: string, status: number, errors: FieldError[] = []) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.errors = errors;
  }
}

const GENERIC: Record<number, string> = {
  0: 'Could not reach the Faultline server. Check that it is still running.',
  400: 'The request was not accepted.',
  403: 'The control panel refused this request. Reload the page and try again.',
  404: 'That was not found.',
  409: 'A run is already active. Wait for it to finish or stop it first.',
  412: 'The plan changed since the dry run. Run the dry run again.',
  413: 'That is too large to send.',
  422: 'The spec has problems; fix them and try again.',
};

function genericMessage(status: number): string {
  return GENERIC[status] ?? (status >= 500 ? 'The Faultline server hit a problem. Check its log.' : 'The request failed.');
}

function asFieldErrors(value: unknown): FieldError[] {
  if (!Array.isArray(value)) return [];
  const out: FieldError[] = [];
  for (const entry of value) {
    if (entry && typeof entry === 'object' && 'message' in entry) {
      const e = entry as { path?: unknown; message?: unknown };
      out.push({ path: typeof e.path === 'string' ? e.path : '', message: String(e.message) });
    }
  }
  return out;
}

type Fetch = typeof fetch;

export interface RunRequest {
  yaml: string;
  plan_hash: string;
  import_file?: ImportFile;
  no_llm?: boolean;
}

export interface ReplayRequest {
  yaml: string;
  plan_hash: string;
  expect?: 'reproduces' | 'fixed';
}

/**
 * Typed access to the control-panel API (contract version 1).
 *
 * Local mode reads /api/*. A static gallery has no /api, so the session falls back to
 * data/session.json and the read calls use the files `faultline export` writes.
 */
export class FaultlineApi {
  private readonly fetchImpl: Fetch;
  private session: Session | null = null;

  constructor(fetchImpl?: Fetch) {
    this.fetchImpl = fetchImpl ?? ((input, init) => fetch(input, init));
  }

  get isStatic(): boolean {
    return this.session?.mode === 'static';
  }

  get token(): string | null {
    return this.session?.token ?? null;
  }

  async loadSession(): Promise<Session> {
    let found: Session | null = null;
    try {
      found = await this.getJson<Session>('/api/session');
      if (!found || typeof found !== 'object' || !('mode' in found)) found = null;
    } catch {
      found = null;
    }
    if (!found) {
      // A static host answers /api/session with index.html or a 404, so read the exported file.
      found = await this.getJson<Session>('/data/session.json');
    }
    this.session = found;
    return found;
  }

  setSession(session: Session): void {
    this.session = session;
  }

  // ---- reads ------------------------------------------------------------------

  library(): Promise<Library> {
    return this.getJson<Library>(this.isStatic ? '/data/library.json' : '/api/library');
  }

  detail(id: string): Promise<Detail> {
    const safe = encodeURIComponent(id);
    return this.getJson<Detail>(this.isStatic ? `/data/library/${safe}.json` : `/api/library/${safe}`);
  }

  async activeRuns(): Promise<RunSummary[]> {
    const body = await this.getJson<{ runs: RunSummary[] }>('/api/runs/active');
    return body.runs ?? [];
  }

  progress(run: string): Promise<Progress> {
    return this.getJson<Progress>(`/api/runs/${encodeURIComponent(run)}/progress`);
  }

  environment(): Promise<Environment> {
    return this.getJson<Environment>('/api/environment');
  }

  evidence(): Promise<Evidence> {
    return this.getJson<Evidence>('/api/evidence');
  }

  async specTemplate(mode: SpecMode): Promise<string> {
    const body = await this.getJson<{ yaml: string }>(`/api/specs/template?mode=${encodeURIComponent(mode)}`);
    return body.yaml;
  }

  // ---- controls (POST, local mode only, token required) ------------------------

  validateSpec(yaml: string): Promise<ValidateResult> {
    return this.post<ValidateResult>('/api/specs/validate', { yaml });
  }

  /** `caseId` names the saved case a replay spec replays: its kind decides which Jobs the plan lists. */
  dryRun(yaml: string, importFile?: ImportFile, caseId?: string): Promise<DryRun> {
    return this.post<DryRun>('/api/specs/dry-run', {
      yaml,
      ...(importFile ? { import_file: importFile } : {}),
      ...(caseId ? { case_id: caseId } : {}),
    });
  }

  startRun(request: RunRequest): Promise<{ run: string; library_id: string | null }> {
    return this.post('/api/runs', { ...request });
  }

  stopRun(run: string): Promise<{ status: string }> {
    return this.post(`/api/runs/${encodeURIComponent(run)}/stop`, {});
  }

  /** Continue a stopped run; a run stopped at its cap or hour limit may be given larger limits (never smaller). */
  resumeRun(run: string, limits: { max_spend_usd?: number; max_hours?: number } = {}): Promise<{ run: string }> {
    return this.post(`/api/runs/${encodeURIComponent(run)}/resume`, { ...limits });
  }

  startReplay(id: string, request: ReplayRequest): Promise<{ run: string }> {
    return this.post(`/api/library/${encodeURIComponent(id)}/replay`, { ...request });
  }

  // ---- plumbing -------------------------------------------------------------------

  private async getJson<T>(path: string): Promise<T> {
    return this.request<T>(path, { method: 'GET', headers: { Accept: 'application/json' } });
  }

  private post<T>(path: string, body: unknown): Promise<T> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json', Accept: 'application/json' };
    if (this.token) headers['X-Faultline-Token'] = this.token;
    return this.request<T>(path, { method: 'POST', headers, body: JSON.stringify(body) });
  }

  private async request<T>(path: string, init: RequestInit): Promise<T> {
    let response: Response;
    try {
      response = await this.fetchImpl(path, { ...init, cache: 'no-store' });
    } catch {
      throw new ApiError(genericMessage(0), 0);
    }
    const text = await response.text();
    let parsed: unknown = null;
    let isJson = true;
    try {
      parsed = text ? JSON.parse(text) : null;
    } catch {
      isJson = false;
    }
    if (!response.ok) {
      const payload = (isJson && parsed && typeof parsed === 'object' ? parsed : {}) as { error?: unknown; errors?: unknown };
      const message = typeof payload.error === 'string' && payload.error ? payload.error : genericMessage(response.status);
      throw new ApiError(message, response.status, asFieldErrors(payload.errors));
    }
    if (!isJson) {
      // For example a static host answering an /api path with index.html.
      throw new ApiError('The server did not answer with data.', response.status);
    }
    return parsed as T;
  }
}

/** The app-wide client. Tests build their own with a mock fetch. */
export const defaultApi = new FaultlineApi();
