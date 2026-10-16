import { BrowserRouter, Route, Routes } from 'react-router-dom';
import type { LibraryItem, RunSummary, Session } from './api/types';
import { Shell } from './components/Shell';
import type { LoadState } from './components/Sidebar';

interface ShellData {
  session: Session;
  items: LibraryItem[];
  runs: RunSummary[];
  libraryState: LoadState;
}

export function AppRoutes(data: ShellData) {
  return (
    <Routes>
      <Route element={<Shell {...data} />}>
        <Route
          index
          element={
            <>
              <h1>Faultline</h1>
              <p>The control panel is loading.</p>
            </>
          }
        />
      </Route>
    </Routes>
  );
}

const PLACEHOLDER: ShellData = {
  session: { api_version: 1, mode: 'local', controls: true, token: null, version: '0' },
  items: [],
  runs: [],
  libraryState: 'loading',
};

export function App() {
  return (
    <BrowserRouter>
      <AppRoutes {...PLACEHOLDER} />
    </BrowserRouter>
  );
}
