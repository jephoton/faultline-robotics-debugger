import { screen, within } from '@testing-library/react';
import { FaultlineApi } from './api/client';
import { makeHarness, renderApp } from './test/utils';

describe('App bootstrap', () => {
  it('loads the session, the case list and the running list in local mode', async () => {
    renderApp('/');
    const nav = await screen.findByRole('navigation', { name: 'Runs and cases' });
    expect(await within(nav).findByText('FL-S-AFB5')).toBeInTheDocument();
    expect(within(nav).getByText('FL-A-1C20')).toBeInTheDocument();
    expect(within(nav).getByText('FL-M-0F42')).toBeInTheDocument();
    expect(await within(nav).findByText('paraphrase-task1', { selector: '.nav-item__name' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /new diagnosis/i })).toBeInTheDocument();
  });

  it('works as a static gallery: reads the data files and hides the controls', async () => {
    const { fetchSpy } = renderApp('/', { mode: 'static' });
    const nav = await screen.findByRole('navigation', { name: 'Runs and cases' });
    expect(await within(nav).findByText('FL-S-AFB5')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /new diagnosis/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Running' })).not.toBeInTheDocument();
    const paths = fetchSpy.mock.calls.map((call) => String(call[0]));
    expect(paths).toContain('/data/library.json');
    expect(paths).not.toContain('/api/runs/active');
  });

  it('shows a plain error with a retry when the server cannot be reached', async () => {
    const harness = makeHarness();
    const broken = new FaultlineApi((async () => {
      throw new TypeError('ECONNREFUSED');
    }) as typeof fetch);
    renderApp('/', { harness: { ...harness, api: broken } });
    expect(await screen.findByRole('heading', { name: 'Faultline could not start' })).toBeInTheDocument();
    expect(screen.getByText(/could not reach the faultline server/i)).toBeInTheDocument();
    expect(screen.queryByText(/ECONNREFUSED/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('shows a not-found page for unknown addresses', async () => {
    renderApp('/nowhere');
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  });
});
