import { createContext, useContext } from 'react';
import type { LibraryItem, RunSummary, Session } from './types';
import { FaultlineApi, defaultApi } from './client';
import type { LoadState } from '../components/Sidebar';

export const ApiContext = createContext<FaultlineApi>(defaultApi);

export function useApi(): FaultlineApi {
  return useContext(ApiContext);
}

export interface AppData {
  session: Session;
  items: LibraryItem[];
  libraryState: LoadState;
  runs: RunSummary[];
  /** Reload the case list (after a run finishes). */
  refreshLibrary: () => void;
  /** Reload the running list now (after a start, stop or resume). */
  refreshRuns: () => void;
}

export const AppDataContext = createContext<AppData | null>(null);

export function useAppData(): AppData {
  const value = useContext(AppDataContext);
  if (!value) throw new Error('useAppData must be used inside the app');
  return value;
}

/** True when the page may show controls: local mode with controls enabled. */
export function useControls(): boolean {
  const { session } = useAppData();
  return session.mode === 'local' && session.controls;
}
