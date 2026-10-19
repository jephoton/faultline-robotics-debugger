import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { useMemo } from 'react';
import { ApiContext, AppDataContext, useApi, type AppData } from './api/context';
import { FaultlineApi, defaultApi } from './api/client';
import type { Session } from './api/types';
import { Shell } from './components/Shell';
import { usePoll } from './lib/polling';
import { useAsync } from './lib/useAsync';
import { CasePage } from './pages/CasePage';
import { HomePage } from './pages/HomePage';
import { GuidePage } from './pages/GuidePage';
import { ReferencePage } from './pages/ReferencePage';
import { NewDiagnosisPage } from './pages/NewDiagnosisPage';
import { SetupPage } from './pages/SetupPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { RunPage } from './pages/RunPage';

export const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true } as const;

const RUNS_POLL_MS = 10_000;

export function AppRoutes({ data }: { data: AppData }) {
  return (
    <AppDataContext.Provider value={data}>
      <Routes>
        <Route element={<Shell session={data.session} items={data.items} runs={data.runs} libraryState={data.libraryState} />}>
          <Route index element={<HomePage />} />
          <Route path="case/:id" element={<CasePage />} />
          <Route path="new" element={<NewDiagnosisPage />} />
          <Route path="run/:run" element={<RunPage />} />
          <Route path="setup" element={<SetupPage />} />
          <Route path="guide" element={<GuidePage />} />
          <Route path="reference" element={<ReferencePage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </AppDataContext.Provider>
  );
}

/** Loads the case list and the running list, and provides them to every page. */
export function AppFrame({ session }: { session: Session }) {
  const api = useApi();
  const library = useAsync(() => api.library(), [api, session.mode]);
  const local = session.mode === 'local';
  const active = usePoll(() => api.activeRuns(), RUNS_POLL_MS, { enabled: local });

  const { reload: refreshLibrary } = library;
  const { refresh: refreshRuns } = active;

  const data = useMemo<AppData>(
    () => ({
      session,
      items: library.data?.items ?? [],
      libraryState: library.loading && !library.data ? 'loading' : library.error && !library.data ? 'error' : 'ready',
      runs: active.data ?? [],
      refreshLibrary,
      refreshRuns,
    }),
    [session, library.data, library.loading, library.error, active.data, refreshLibrary, refreshRuns],
  );
  return <AppRoutes data={data} />;
}

/** Reads the session (local, or the exported file for a static gallery), then renders the workspace. */
export function Bootstrap() {
  const api = useApi();
  const { data: session, error, loading, reload } = useAsync(() => api.loadSession(), [api]);
  if (loading) {
    return (
      <main className="boot" aria-busy="true">
        <p>Loading Faultline.</p>
      </main>
    );
  }
  if (error || !session) {
    return (
      <main className="boot">
        <h1>Faultline could not start</h1>
        <p>{error?.message ?? 'The session could not be read.'}</p>
        <button type="button" className="btn" onClick={reload}>
          Try again
        </button>
      </main>
    );
  }
  return <AppFrame session={session} />;
}

export function App({ api = defaultApi }: { api?: FaultlineApi }) {
  return (
    <ApiContext.Provider value={api}>
      <BrowserRouter future={ROUTER_FUTURE}>
        <Bootstrap />
      </BrowserRouter>
    </ApiContext.Provider>
  );
}
