import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { IDS } from '../mocks/fixtures';
import { renderApp } from '../test/utils';

describe('home, local', () => {
  it('shows all case cards in library order, the running run, and New diagnosis', async () => {
    renderApp('/');
    expect(await screen.findByRole('heading', { level: 1, name: 'Faultline' })).toBeInTheDocument();
    const running = await screen.findByRole('heading', { name: 'Running now' });
    const section = running.closest('section') as HTMLElement;
    expect(within(section).getByRole('link', { name: 'paraphrase-task1' })).toHaveAttribute('href', '/run/para-demo-20261017-093000');
    const cases = (await within(screen.getByRole('main')).findByRole('heading', { name: 'Cases' })).closest('section') as HTMLElement;
    await within(cases).findByRole('link', { name: 'soup-start14' });
    expect(within(cases).getAllByRole('link').map((link) => link.textContent)).toEqual([
      'soup-start14', 'my-failing-start', 'soup-screen', 'audit-task0', 'paraphrase-task0',
      'diagnose-obj0', 'diagnose-obj0 (wording)', 'paraphrase-task4', 'Occlusion case (M4)',
    ]);
    const intro = screen.getByRole('heading', { name: 'What Faultline does' }).closest('section') as HTMLElement;
    expect(intro.compareDocumentPosition(cases) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getAllByRole('link', { name: /new diagnosis/i }).length).toBeGreaterThan(1);
  });

  it('invites a first diagnosis when there are no cases', async () => {
    const { fetchSpy } = renderApp('/', { activeDemo: false });
    await screen.findByRole('heading', { level: 1, name: 'Faultline' });
    expect(fetchSpy).toHaveBeenCalled();
  });
});

describe('home, static gallery', () => {
  it('shows one mixed-kind case list in library order without kind labels or controls', async () => {
    renderApp('/', { mode: 'static' });
    expect(await screen.findByRole('heading', { name: 'What Faultline does' })).toBeInTheDocument();
    for (const step of ['Find.', 'Confirm.', 'Reduce.', 'Replay.']) {
      expect(screen.getByText(step)).toBeInTheDocument();
    }
    const main = screen.getByRole('main');
    const cases = await within(main).findByRole('heading', { name: 'Cases' });
    const caseSection = cases.closest('section') as HTMLElement;
    await within(caseSection).findByRole('link', { name: 'soup-start14' });
    const caseNames = within(caseSection).getAllByRole('link').map((link) => link.textContent);
    expect(caseNames).toEqual(['soup-start14', 'my-failing-start', 'soup-screen', 'audit-task0', 'paraphrase-task0', 'diagnose-obj0', 'diagnose-obj0 (wording)', 'paraphrase-task4', 'Occlusion case (M4)']);
    for (const heading of ['Scenario reductions', 'Stress tests', 'Language', 'Earlier']) {
      expect(within(main).queryByRole('heading', { name: heading })).not.toBeInTheDocument();
    }
    for (const label of ['Scenario reduction', 'Stress test', 'Language robustness']) {
      expect(within(caseSection).queryByText(label, { exact: true })).not.toBeInTheDocument();
    }
    expect(within(main).getByRole('link', { name: 'soup-start14' })).toHaveAttribute('href', `/case/${encodeURIComponent(IDS.soup)}`);
    expect(within(main).getByText(/not every failure mode/)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /new diagnosis/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Running now' })).not.toBeInTheDocument();
  });

  it('hides every local-only page', async () => {
    for (const [path, text] of [
      ['/setup', 'Setup'],
      ['/new', 'New diagnosis'],
    ] as const) {
      const view = renderApp(path, { mode: 'static' });
      expect(await screen.findByRole('heading', { level: 1, name: text })).toBeInTheDocument();
      expect(screen.getByText(/needs the local Faultline server/)).toBeInTheDocument();
      view.unmount();
    }
  });

  it('routes the removed evidence page to not found without requesting evidence', async () => {
    const { fetchSpy } = renderApp('/evidence', { mode: 'static' });
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
    expect(fetchSpy.mock.calls.map((call) => String(call[0]))).not.toContain('/api/evidence');
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
  it('separates offline inspection from paid operation and links detailed setup', async () => {
    renderApp('/guide');
    await screen.findByRole('heading', { level: 1, name: 'Run your own' });
    const main = screen.getByRole('main');
    await within(main).findByRole('heading', { name: /Preview without cloud access/ });
    expect(within(main).getByRole('link', { name: 'Detailed setup and CLI quickstart' })).toHaveAttribute(
      'href', 'https://github.com/jephoton/faultline-robotics-debugger/blob/main/docs/setup/diagnose.md',
    );
    expect(within(main).getByRole('link', { name: 'UI walkthrough and demo scenarios' })).toBeInTheDocument();
    expect(within(main).getByText(/Token Factory and storage are outside the Job cap/)).toBeInTheDocument();
    expect(within(main).queryByText(/never paying twice/)).not.toBeInTheDocument();
  });
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

describe('reference page', () => {
  it('renders the reference document with its sections and repository links', async () => {
    const { prepareReference, referenceSections } = await import('./ReferencePage');
    const body = prepareReference('# Title\n\nSee the [runbook](ui-runbook.md) and [web](https://example.com).\n\n## 1. What it is\n\n## 2. Glossary\n');
    expect(body.startsWith('# Title')).toBe(false);
    expect(body).toContain('](https://github.com/jephoton/faultline-robotics-debugger/blob/main/docs/ui-runbook.md)');
    expect(body).toContain('](https://example.com)');
    expect(referenceSections(body)).toEqual([
      { id: 'md-1-what-it-is', title: '1. What it is' },
      { id: 'md-2-glossary', title: '2. Glossary' },
    ]);
  });
});

describe('reference page in the app', () => {
  it('focuses on interpreting measured evidence rather than setup or marketing promises', async () => {
    renderApp('/reference');
    await screen.findByRole('heading', { level: 1, name: 'Reference' });
    const main = screen.getByRole('main');
    await within(main).findByRole('heading', { name: /What Faultline is for/ });
    expect(within(main).getByRole('heading', { name: /Repeatability and controls/ })).toBeInTheDocument();
    expect(within(main).getByRole('heading', { name: /Disturbance severity/ })).toBeInTheDocument();
    expect(within(main).getByRole('heading', { name: /Replay verdicts/ })).toBeInTheDocument();
    expect(main.textContent).not.toContain('pip install');
    expect(main.textContent).not.toContain('never runs twice');
    expect(main.textContent).toContain('81.25%');
    expect(main.textContent).toContain('0.0125');
  });
  it('is reachable from the sidebar and shows the documented sections', async () => {
    renderApp('/reference');
    expect(await screen.findByRole('heading', { level: 1, name: 'Reference' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: /What Faultline is for/ })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: /Reading a report/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Reference' })).toHaveAttribute('href', '/reference');
  });
});
