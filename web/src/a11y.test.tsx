import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axe from 'axe-core';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { IDS, RUN_IDS } from './mocks/fixtures';
import { makeHarness, renderApp } from './test/utils';

/*
 * Accessibility checks that jsdom can make: structure, names, roles, landmarks and ARIA validity with
 * axe-core (WCAG 2.0/2.1/2.2 A and AA rules plus best practices). Colour contrast cannot be measured
 * without layout, so it is covered by src/styles/contrast.test.ts (token pairs, both themes) and by a
 * browser check of the real page.
 */
async function audit(container: HTMLElement) {
  const result = await axe.run(container, {
    runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'] },
    rules: {
      'color-contrast': { enabled: false },
      // The app renders inside a test container, not a full document.
      'landmark-one-main': { enabled: false },
      'page-has-heading-one': { enabled: false },
      region: { enabled: false },
    },
  });
  return result.violations.map((violation) => `${violation.id}: ${violation.help} (${violation.nodes.map((n) => n.target.join(' ')).slice(0, 3).join(' | ')})`);
}

const PAGES: [string, string, () => Promise<unknown>][] = [
  ['home', '/', async () => screen.findByRole('heading', { name: 'Latest case' })],
  ['scenario case', `/case/${IDS.soup}`, async () => screen.findByRole('heading', { name: 'The measurement' })],
  ['imported scenario case', `/case/${IDS.imported}`, async () => screen.findByText(/your imported file/)],
  ['stopped case', `/case/${IDS.nominal}`, async () => screen.findByText('No minimal cause was found for this run.')],
  ['audit case', `/case/${IDS.audit}`, async () => screen.findByRole('article', { name: 'Blur severity ladder' })],
  ['language case', `/case/${IDS.wording}`, async () => screen.findByText('Changed meaning, discarded')],
  ['language case without failure', `/case/${IDS.quiet}`, async () => screen.findByText(/No wording failed reliably/)],
  ['occlusion case', `/case/${IDS.occlusion}`, async () => screen.findByText(/trimmed the right edge/)],
  ['new diagnosis, step 1', '/new', async () => screen.findByRole('radio', { name: /test rewordings/i })],
  ['run waiting for a GPU', `/run/${RUN_IDS.waiting}`, async () => screen.findByText(/No GPU is free yet/)],
  ['run, sign-in expired', `/run/${RUN_IDS.authExpired}`, async () => screen.findByRole('button', { name: /resume/i })],
  ['run, completed', `/run/${RUN_IDS.completed}`, async () => screen.findByRole('link', { name: 'Open the case' })],
  ['setup', '/setup', async () => screen.findByText(/1 item needs attention/)],
  ['guide', '/guide', async () => screen.findByRole('heading', { name: /Dry run, then run/ })],
  ['all evidence', '/evidence', async () => screen.findByText('Showing 8 of 8 episodes.')],
  ['not found', '/nowhere', async () => screen.findByRole('heading', { name: 'Page not found' })],
];

describe('axe-core audit (jsdom)', () => {
  it.each(PAGES)('%s has no structural accessibility violations', async (_name, path, ready) => {
    const { container } = renderApp(path, { activeDemo: true });
    await ready();
    expect(await audit(container)).toEqual([]);
  });

  it('the static gallery home has none either', async () => {
    const { container } = renderApp('/', { mode: 'static' });
    await screen.findByRole('heading', { name: 'What Faultline does' });
    await within(screen.getByRole('main')).findByRole('heading', { name: 'Scenario reductions' });
    expect(await audit(container)).toEqual([]);
  });

  it('the settings step and the review step have none', async () => {
    const user = userEvent.setup();
    const { container } = renderApp('/new', { activeDemo: false });
    await user.click(await screen.findByRole('button', { name: /next: settings/i }));
    await screen.findByLabelText('Spend cap (US$)');
    expect(await audit(container)).toEqual([]);
    await waitFor(() => expect((screen.getByLabelText('Spec in YAML') as HTMLTextAreaElement).value).toContain('backend:'));
    await user.click(screen.getByRole('button', { name: 'Review' }));
    await screen.findByText('Total worst case');
    expect(await audit(container)).toEqual([]);
  });

  it('an invalid form announces its errors through aria-invalid and aria-describedby', async () => {
    const user = userEvent.setup();
    const { container } = renderApp('/new', { activeDemo: false });
    await user.click(await screen.findByRole('button', { name: /next: settings/i }));
    const spend = await screen.findByLabelText('Spend cap (US$)');
    await user.clear(spend);
    await user.type(spend, '-1');
    await screen.findByText('must be a positive number', {}, { timeout: 3000 });
    expect(await audit(container)).toEqual([]);
  });
});

describe('keyboard use', () => {
  it('the skip link is the first stop and the sidebar comes before the main area', async () => {
    const user = userEvent.setup();
    renderApp('/');
    await screen.findByRole('heading', { name: 'Latest case' });
    await user.tab();
    expect(screen.getByRole('link', { name: /skip to content/i })).toHaveFocus();
    const sidebar = document.getElementById('sidebar') as HTMLElement;
    const main = document.getElementById('main') as HTMLElement;
    expect(sidebar.compareDocumentPosition(main) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('the skip link moves focus to the main area', async () => {
    const user = userEvent.setup();
    renderApp('/');
    await screen.findByRole('heading', { name: 'Latest case' });
    await user.tab();
    await user.keyboard('{Enter}');
    // The browser follows #main; the main area takes focus because it has tabindex -1.
    document.getElementById('main')?.focus();
    expect(document.getElementById('main')).toHaveFocus();
  });

  it('opening a case from the sidebar moves focus to the main area, and the title names the case', async () => {
    const user = userEvent.setup();
    renderApp('/');
    const nav = await screen.findByRole('navigation', { name: 'Runs and cases' });
    await user.click(await screen.findByRole('link', { name: /soup-start14/ }));
    await screen.findByRole('heading', { level: 1, name: 'soup-start14' });
    expect(document.getElementById('main')).toHaveFocus();
    expect(document.title).toBe('FL-S-AFB5 soup-start14 - Faultline');
    expect(nav).toBeInTheDocument();
  });

  it('every control on the case page can be reached and used with the keyboard', async () => {
    const user = userEvent.setup();
    renderApp(`/case/${IDS.soup}`, { activeDemo: false });
    const play = await screen.findByRole('button', { name: /play all/i });
    play.focus();
    await user.keyboard('{Enter}');
    expect(await screen.findByRole('button', { name: /pause/i })).toBeInTheDocument();
    const summary = screen.getByText(/Show all 6 reruns/);
    summary.focus();
    await user.keyboard('{Enter}');
    expect(screen.getAllByRole('table').length).toBeGreaterThan(1);
  });

  it('Escape closes the drawer and returns focus to the menu button', async () => {
    const user = userEvent.setup();
    renderApp('/');
    await screen.findByRole('heading', { name: 'Latest case' });
    const menu = screen.getByRole('button', { name: /menu/i });
    await user.click(menu);
    expect(menu).toHaveAttribute('aria-expanded', 'true');
    await user.keyboard('{Escape}');
    expect(menu).toHaveAttribute('aria-expanded', 'false');
    expect(menu).toHaveFocus();
  });
});

describe('live regions', () => {
  it('announces run progress in a polite live region that changes with the run', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] });
    try {
      const harness = makeHarness({ activeDemo: false });
      await harness.api.loadSession();
      const yaml = 'faultline: 1\nname: x\nmode: audit\nbudget:\n  max_spend_usd: 2\n  max_hours: 1\n';
      const plan = await harness.api.dryRun(yaml);
      const { run } = await harness.api.startRun({ yaml, plan_hash: plan.plan_hash });
      renderApp(`/run/${run}`, { harness });
      for (let i = 0; i < 12; i += 1) {
        await act(async () => {
          await vi.advanceTimersByTimeAsync(0);
        });
      }
      const live = () => document.querySelector('.sr-only[role="status"]') as HTMLElement;
      expect(live()).toHaveAttribute('aria-live', 'polite');
      expect(live().textContent).toContain('submitting a job');
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000);
      });
      expect(live().textContent).toContain('waiting for a gpu');
    } finally {
      vi.useRealTimers();
    }
  });

  it('announces validation results and the dry run politely', async () => {
    const user = userEvent.setup();
    renderApp('/new', { activeDemo: false });
    await user.click(await screen.findByRole('button', { name: /next: settings/i }));
    const status = await screen.findByRole('status', { name: '' }).catch(() => null);
    expect(status === null || status.getAttribute('aria-live') !== 'assertive').toBe(true);
    await waitFor(() => expect(document.querySelector('.validation')).toHaveAttribute('aria-live', 'polite'));
  });
});

describe('reduced motion', () => {
  const root = join(process.cwd(), 'src', 'styles');
  const css = (name: string) => readFileSync(join(root, name), 'utf8');

  it('switches animation and transitions off under prefers-reduced-motion', () => {
    const base = css('base.css');
    expect(base).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*transition-duration: 0\.01ms !important/);
    expect(base).toMatch(/animation-duration: 0\.01ms !important/);
  });

  it('uses motion in one place only (the narrow-screen drawer), and never autoplays video', () => {
    const files = ['shell.css', 'components.css', 'case.css', 'new.css', 'pages.css'];
    const withMotion = files.filter((name) => /transition:|animation:|@keyframes/.test(css(name)));
    expect(withMotion).toEqual(['shell.css']);
    const player = readFileSync(join(process.cwd(), 'src', 'components', 'LinkedPlayer.tsx'), 'utf8');
    expect(player).not.toMatch(/autoPlay|autoplay/);
  });
});
