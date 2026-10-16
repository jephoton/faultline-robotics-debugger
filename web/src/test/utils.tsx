import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ApiContext } from '../api/context';
import { FaultlineApi } from '../api/client';
import { Bootstrap, ROUTER_FUTURE } from '../App';
import { createMockServer, mockFetch, type MockOptions, type MockServer } from '../mocks/handlers';

export interface Harness {
  api: FaultlineApi;
  server: MockServer;
  fetchSpy: ReturnType<typeof vi.fn>;
}

export function makeHarness(options?: MockOptions): Harness {
  const server = createMockServer(options);
  const fetchSpy = vi.fn(mockFetch(server));
  const api = new FaultlineApi(fetchSpy as unknown as typeof fetch);
  return { api, server, fetchSpy };
}

/** Render the whole app at a path, backed by the in-memory mock API. */
export function renderApp(path = '/', options?: MockOptions & { harness?: Harness }) {
  const harness = options?.harness ?? makeHarness(options);
  const view = render(
    <ApiContext.Provider value={harness.api}>
      <MemoryRouter initialEntries={[path]} future={ROUTER_FUTURE}>
        <Bootstrap />
      </MemoryRouter>
    </ApiContext.Provider>,
  );
  return { ...view, ...harness };
}
