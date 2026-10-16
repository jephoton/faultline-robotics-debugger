import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { IDS } from '../mocks/fixtures';
import { renderApp } from '../test/utils';

describe('home, local', () => {
  it('shows the latest case, the running run, and New diagnosis', async () => {
    renderApp('/');
    expect(await screen.findByRole('heading', { level: 1, name: 'Faultline' })).toBeInTheDocument();
    const running = await screen.findByRole('heading', { name: 'Running now' });
    const section = running.closest('section') as HTMLElement;
    expect(within(section).getByRole('link', { name: 'paraphrase-task1' })).toHaveAttribute('href', '/run/para-demo-20261017-093000');
    const latest = (await screen.findByRole('heading', { name: 'Latest case' })).closest('section') as HTMLElement;
    // The newest case by date is the quiet language run from October 16.
    expect(await within(latest).findByRole('link', { name: 'paraphrase-task4' })).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /new diagnosis/i }).length).toBeGreaterThan(1);
  });

  it('invites a first diagnosis when there are no cases', async () => {
    const { fetchSpy } = renderApp('/', { activeDemo: false });
    await screen.findByRole('heading', { level: 1, name: 'Faultline' });
    expect(fetchSpy).toHaveBeenCalled();
  });
});

describe('home, static gallery', () => {
  it('shows an intro panel of the loop and the cases grouped by kind, with no controls', async () => {
    renderApp('/', { mode: 'static' });
    expect(await screen.findByRole('heading', { name: 'What Faultline does' })).toBeInTheDocument();
    for (const step of ['Find.', 'Confirm.', 'Reduce.', 'Replay.']) {
      expect(screen.getByText(step)).toBeInTheDocument();
    }
    const main = screen.getByRole('main');
    expect(await within(main).findByRole('heading', { name: 'Scenario reductions' })).toBeInTheDocument();
    expect(within(main).getByRole('link', { name: 'soup-start14' })).toHaveAttribute('href', `/case/${encodeURIComponent(IDS.soup)}`);
    expect(within(main).getByText(/does not claim every failure mode/)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /new diagnosis/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Running now' })).not.toBeInTheDocument();
  });

  it('hides every local-only page', async () => {
    for (const [path, text] of [
      ['/setup', 'Setup'],
      ['/evidence', 'All evidence'],
      ['/new', 'New diagnosis'],
    ] as const) {
      const view = renderApp(path, { mode: 'static' });
      expect(await screen.findByRole('heading', { level: 1, name: text })).toBeInTheDocument();
      expect(screen.getByText(/needs the local Faultline server/)).toBeInTheDocument();
      view.unmount();
    }
  });
});

describe('setup', () => {
  it('lists each check with a word, and the fix for the one that fails', async () => {
    renderApp('/setup');
    expect(await screen.findByRole('heading', { level: 1, name: 'Setup' })).toBeInTheDocument();
    expect(await screen.findByText(/1 item needs attention/)).toBeInTheDocument();
    expect(screen.getAllByText('Ready').length).toBe(3);
    expect(screen.getByText('Needs attention')).toBeInTheDocument();
    expect(screen.getByText(/Add a line NEBIUS_API_KEY=/)).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Read the guide' })[0]).toHaveAttribute('href', '/guide#prerequisites');
  });

  it('checks again on request', async () => {
    const user = userEvent.setup();
    const { fetchSpy } = renderApp('/setup');
    await screen.findByText(/1 item needs attention/);
    const count = () => fetchSpy.mock.calls.filter((call) => call[0] === '/api/environment').length;
    expect(count()).toBe(1);
    await user.click(screen.getByRole('button', { name: /check again/i }));
    await waitFor(() => expect(count()).toBe(2));
  });
});

describe('guide', () => {
  it('is a page of the quickstart with a table of contents, in both modes', async () => {
    renderApp('/guide', { mode: 'static' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Run your own' })).toBeInTheDocument();
    const toc = screen.getByRole('navigation', { name: 'On this page' });
    expect(within(toc).getByRole('link', { name: /Hugging Face/ })).toHaveAttribute('href', '#huggingface');
    expect(screen.getByRole('heading', { name: /Dry run, then run/ })).toBeInTheDocument();
    expect(screen.getByText(/faultline diagnose my-spec.yaml --dry-run/)).toBeInTheDocument();
  });

  it('does not contain anything that looks like a real id or a local path', async () => {
    renderApp('/guide');
    await screen.findByRole('heading', { level: 1, name: 'Run your own' });
    const text = screen.getByRole('main').textContent ?? '';
    expect(text).not.toMatch(/\be00[0-9a-z]{8,}/);
    expect(text).not.toMatch(/aijob-|project-e/);
    expect(text).not.toMatch(/C:\\Users|\/home\/|\/Users\//);
  });

  it('scrolls to the section named in the address', async () => {
    const scroll = vi.spyOn(window.HTMLElement.prototype, 'scrollIntoView');
    renderApp('/guide#image');
    await screen.findByRole('heading', { level: 1, name: 'Run your own' });
    await waitFor(() => expect(scroll).toHaveBeenCalled());
    scroll.mockRestore();
  });
});

describe('all evidence', () => {
  it('lists episodes with outcome words and loads a video only when asked', async () => {
    const user = userEvent.setup();
    renderApp('/evidence');
    expect(await screen.findByRole('heading', { level: 1, name: 'All evidence' })).toBeInTheDocument();
    expect(await screen.findByText('Showing 8 of 8 episodes.')).toBeInTheDocument();
    expect(document.querySelectorAll('video').length).toBe(0);
    await user.click(screen.getByRole('button', { name: 'Show video of ep-000' }));
    const video = document.querySelector('video') as HTMLVideoElement;
    expect(video.getAttribute('src')).toBe('/media/placeholder.webm');
    expect(screen.getAllByText('failed').length).toBeGreaterThan(0);
    expect(screen.getAllByText('passed').length).toBeGreaterThan(0);
  });

  it('filters by outcome and by text', async () => {
    const user = userEvent.setup();
    renderApp('/evidence');
    await screen.findByText('Showing 8 of 8 episodes.');
    await user.selectOptions(screen.getByLabelText('Outcome'), 'failed');
    expect(screen.getByText(/Showing 3 of 3 episodes/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Outcome'), 'all');
    await user.type(screen.getByLabelText('Search'), 'baseline');
    expect(screen.getByText(/Showing 2 of 2 episodes/)).toBeInTheDocument();
    await user.clear(screen.getByLabelText('Search'));
    await user.type(screen.getByLabelText('Search'), 'zzzz');
    expect(screen.getByText('No episodes match.')).toBeInTheDocument();
  });
});
