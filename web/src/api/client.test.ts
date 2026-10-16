import { createMockServer, mockFetch, MOCK_TOKEN } from '../mocks/handlers';
import { IDS } from '../mocks/fixtures';
import { ApiError, FaultlineApi } from './client';

function makeApi(options?: Parameters<typeof createMockServer>[0]) {
  const server = createMockServer(options);
  const fetchSpy = vi.fn(mockFetch(server));
  return { api: new FaultlineApi(fetchSpy as unknown as typeof fetch), fetchSpy };
}

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

describe('session', () => {
  it('reads /api/session in local mode', async () => {
    const { api } = makeApi();
    const session = await api.loadSession();
    expect(session.mode).toBe('local');
    expect(session.controls).toBe(true);
    expect(api.token).toBe(MOCK_TOKEN);
    expect(api.isStatic).toBe(false);
  });

  it('falls back to data/session.json when /api/session answers with index.html', async () => {
    const { api, fetchSpy } = makeApi({ mode: 'static' });
    const session = await api.loadSession();
    expect(session.mode).toBe('static');
    expect(session.token).toBeNull();
    expect(api.isStatic).toBe(true);
    const paths = fetchSpy.mock.calls.map((call) => call[0]);
    expect(paths).toEqual(['/api/session', '/data/session.json']);
  });

  it('falls back when /api/session is a 404 or the network fails', async () => {
    const fallback = { api_version: 1, mode: 'static', controls: false, token: null, version: '1' };
    const notFound = new FaultlineApi((async (input: RequestInfo | URL) =>
      String(input).startsWith('/api') ? new Response('nope', { status: 404 }) : jsonResponse(200, fallback)) as typeof fetch);
    expect((await notFound.loadSession()).mode).toBe('static');
    const offline = new FaultlineApi((async (input: RequestInfo | URL) => {
      if (String(input).startsWith('/api')) throw new TypeError('network down');
      return jsonResponse(200, fallback);
    }) as typeof fetch);
    expect((await offline.loadSession()).mode).toBe('static');
  });

  it('fails with a plain sentence when neither source answers', async () => {
    const api = new FaultlineApi((async () => {
      throw new TypeError('network down');
    }) as typeof fetch);
    await expect(api.loadSession()).rejects.toMatchObject({ name: 'ApiError', status: 0 });
  });
});

describe('static data paths', () => {
  it('reads the exported files instead of /api', async () => {
    const { api, fetchSpy } = makeApi({ mode: 'static' });
    await api.loadSession();
    const library = await api.library();
    expect(library.items.length).toBeGreaterThan(0);
    const detail = await api.detail(IDS.audit);
    expect(detail.audit).toBeDefined();
    const paths = fetchSpy.mock.calls.map((call) => call[0]);
    expect(paths).toContain('/data/library.json');
    expect(paths).toContain(`/data/library/${encodeURIComponent(IDS.audit)}.json`);
    expect(paths.some((path) => String(path).startsWith('/api/library'))).toBe(false);
  });
});

describe('local reads', () => {
  it('reads the library, a case, progress and the environment', async () => {
    const { api } = makeApi();
    await api.loadSession();
    expect((await api.library()).items.map((item) => item.fault_code)).toContain('FL-S-AFB5');
    expect((await api.detail(IDS.soup)).scenario?.failing_start).toBe(14);
    expect((await api.activeRuns())[0]?.status).toBe('running');
    expect((await api.progress('para-done-20261017-084500')).library_id).toBe(IDS.wording);
    expect((await api.environment()).checks.length).toBeGreaterThan(0);
    expect((await api.evidence()).episodes.length).toBeGreaterThan(0);
    expect(await api.specTemplate('audit')).toContain('mode: audit');
  });

  it('turns a 404 into an ApiError carrying the server sentence', async () => {
    const { api } = makeApi();
    await api.loadSession();
    await expect(api.detail('d-missing')).rejects.toMatchObject({ status: 404, message: 'That case was not found.' });
  });
});

describe('controls', () => {
  it('sends the session token and JSON on POSTs', async () => {
    const { api, fetchSpy } = makeApi();
    await api.loadSession();
    const result = await api.validateSpec('faultline: 1\nmode: audit\nbudget:\n  max_spend_usd: 2\n  max_hours: 1\n');
    expect(result.ok).toBe(true);
    const call = fetchSpy.mock.calls.find((entry) => entry[0] === '/api/specs/validate');
    const init = call?.[1] as RequestInit;
    expect(init.method).toBe('POST');
    const headers = init.headers as Record<string, string>;
    expect(headers['X-Faultline-Token']).toBe(MOCK_TOKEN);
    expect(headers['Content-Type']).toBe('application/json');
    expect(JSON.parse(init.body as string)).toEqual({ yaml: expect.any(String) });
  });

  it('is refused without a token and reports the server sentence', async () => {
    const { api } = makeApi();
    // no loadSession: no token
    await expect(api.validateSpec('x')).rejects.toMatchObject({ status: 403 });
  });

  it('carries field errors from a 422', async () => {
    const { api } = makeApi({ activeDemo: false });
    await api.loadSession();
    const error = await api.dryRun('faultline: 1\nmode: audit\nbudget:\n  max_spend_usd: -1\n  max_hours: 1\n').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.status).toBe(422);
    expect(apiError.errors).toEqual([{ path: 'budget.max_spend_usd', message: 'must be a positive number' }]);
  });

  it('refuses to start a run when the plan hash is stale (412) or a run is active (409)', async () => {
    const { api } = makeApi({ activeDemo: false });
    await api.loadSession();
    const yaml = await api.specTemplate('audit');
    await expect(api.startRun({ yaml, plan_hash: 'stale' })).rejects.toMatchObject({ status: 412 });
    const plan = await api.dryRun(yaml);
    const started = await api.startRun({ yaml, plan_hash: plan.plan_hash });
    expect(started.run).toMatch(/^new-diagnosis-/);
    await expect(api.startRun({ yaml, plan_hash: plan.plan_hash })).rejects.toMatchObject({ status: 409 });
  });

  it('uses a generic sentence for non-JSON server errors', async () => {
    const api = new FaultlineApi((async () => new Response('<html>boom</html>', { status: 500 })) as typeof fetch);
    api.setSession({ api_version: 1, mode: 'local', controls: true, token: 't', version: '1' });
    await expect(api.environment()).rejects.toMatchObject({
      status: 500,
      message: 'The Faultline server hit a problem. Check its log.',
    });
  });

  it('never exposes raw network error text', async () => {
    const api = new FaultlineApi((async () => {
      throw new TypeError('connect ECONNREFUSED 127.0.0.1:8765');
    }) as typeof fetch);
    const error = (await api.environment().catch((e: unknown) => e)) as ApiError;
    expect(error.message).toBe('Could not reach the Faultline server. Check that it is still running.');
  });
});
