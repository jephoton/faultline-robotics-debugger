import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import type { LibraryItem, RunSummary, Session } from '../api/types';
import { ReadoutHeader } from './ReadoutHeader';
import { Shell } from './Shell';
import { StatusBadge } from './StatusBadge';

const local: Session = { api_version: 1, mode: 'local', controls: true, token: 't', version: '0.0.0' };
const staticMode: Session = { api_version: 1, mode: 'static', controls: false, token: null, version: '0.0.0' };

function item(over: Partial<LibraryItem>): LibraryItem {
  return {
    id: 'd-1',
    fault_code: 'FL-S-0001',
    kind: 'scenario',
    name: 'Soup start 14',
    verdict: 'reproduces',
    verdict_text: 'x',
    attention: false,
    suite: 'libero_10',
    task_id: 0,
    instruction: null,
    created: null,
    case_id: null,
    run: null,
    ...over,
  };
}

const items = [
  item({ id: 'd-a', fault_code: 'FL-S-AFB5', name: 'Soup start 14' }),
  item({ id: 'd-b', fault_code: 'FL-A-1C20', kind: 'audit', name: 'Object audit', verdict: 'no_failure' }),
  item({ id: 'd-c', fault_code: 'FL-L-77D1', kind: 'paraphrase', name: 'Wording', verdict: 'stopped', attention: true }),
  item({ id: 'm-d', fault_code: 'FL-M-0042', kind: 'occlusion', name: 'Occlusion M4', verdict: 'reproduces' }),
];
const runs: RunSummary[] = [
  { run: 'run-1', name: 'paraphrase-task0', mode: 'paraphrase', status: 'running', step: 'screen', spent_usd: 0.3, cap_usd: 4, attention: false },
];

function renderShell(session: Session, path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<Shell session={session} items={items} runs={runs} libraryState="ready" />}>
          <Route index element={<h1>Home page</h1>} />
          <Route path="case/:id" element={<h1>A case</h1>} />
          <Route path="setup" element={<h1>Setup page</h1>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe('Shell in local mode', () => {
  it('shows New diagnosis, Running and the case groups with fault codes', () => {
    renderShell(local);
    const nav = screen.getByRole('navigation', { name: 'Runs and cases' });
    expect(screen.getByRole('link', { name: /new diagnosis/i })).toHaveAttribute('href', '/new');
    for (const heading of ['Running', 'Scenario reductions', 'Stress tests', 'Language', 'Earlier']) {
      expect(within(nav).getByRole('heading', { name: heading })).toBeInTheDocument();
    }
    expect(within(nav).getByText('FL-S-AFB5')).toBeInTheDocument();
    expect(within(nav).getByText('paraphrase-task0')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /setup/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /run your own/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /all evidence/i })).toBeInTheDocument();
  });

  it('marks status with a word and an icon, and only abnormal rows get a colour bar', () => {
    renderShell(local);
    const soup = screen.getByRole('link', { name: /Soup start 14/ });
    expect(soup).toHaveClass('nav-item--alarm');
    expect(within(soup).getByText('Repeats')).toBeInTheDocument();
    const audit = screen.getByRole('link', { name: /Object audit/ });
    expect(audit).not.toHaveClass('nav-item--alarm');
    expect(audit).not.toHaveClass('nav-item--attention');
    expect(within(audit).getByText('No failure')).toBeInTheDocument();
    const wording = screen.getByRole('link', { name: /Wording/ });
    expect(wording).toHaveClass('nav-item--attention');
    expect(within(wording).getByText('Stopped')).toBeInTheDocument();
  });

  it('opens and closes the drawer from the menu button and with Escape', async () => {
    const user = userEvent.setup();
    renderShell(local);
    const menu = screen.getByRole('button', { name: /menu/i });
    const sidebar = document.getElementById('sidebar') as HTMLElement;
    expect(menu).toHaveAttribute('aria-expanded', 'false');
    expect(sidebar).toHaveAttribute('data-open', 'false');
    await user.click(menu);
    expect(menu).toHaveAttribute('aria-expanded', 'true');
    expect(sidebar).toHaveAttribute('data-open', 'true');
    await user.keyboard('{Escape}');
    expect(sidebar).toHaveAttribute('data-open', 'false');
    expect(menu).toHaveFocus();
  });

  it('moves focus to the main area when the route changes', async () => {
    const user = userEvent.setup();
    renderShell(local);
    await user.click(screen.getByRole('link', { name: /setup/i }));
    expect(screen.getByRole('heading', { name: 'Setup page' })).toBeInTheDocument();
    expect(document.getElementById('main')).toHaveFocus();
  });

  it('offers a skip link to the main content', () => {
    renderShell(local);
    expect(screen.getByRole('link', { name: /skip to content/i })).toHaveAttribute('href', '#main');
  });
});

describe('Shell in static mode', () => {
  it('hides New diagnosis, Running, Setup and All evidence but keeps the cases', () => {
    renderShell(staticMode);
    expect(screen.queryByRole('link', { name: /new diagnosis/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Running' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /^setup/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /all evidence/i })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Scenario reductions' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /run your own/i })).toBeInTheDocument();
  });
});

describe('ReadoutHeader and StatusBadge', () => {
  it('shows the fault code and fields', () => {
    render(
      <ReadoutHeader
        code="FL-S-AFB5"
        fields={[
          { label: 'Verdict', value: 'Failure repeats' },
          { label: 'Kind', value: 'Scenario reduction' },
        ]}
        foot="put both the alphabet soup and the tomato sauce in the basket"
      />,
    );
    expect(screen.getByText('FL-S-AFB5')).toBeInTheDocument();
    expect(screen.getByText('Verdict')).toBeInTheDocument();
    expect(screen.getByText(/alphabet soup/)).toBeInTheDocument();
  });

  it('uses red only for a repeating failure and amber for attention', () => {
    const { rerender } = render(<StatusBadge verdict="reproduces" attention={false} />);
    expect(screen.getByText('Failure repeats').closest('span')).toHaveAttribute('data-tone', 'alarm');
    rerender(<StatusBadge verdict="stopped" attention />);
    expect(screen.getByText('Stopped').closest('span')).toHaveAttribute('data-tone', 'attention');
    rerender(<StatusBadge verdict="no_failure" attention={false} />);
    expect(screen.getByText('No failure found').closest('span')).toHaveAttribute('data-tone', 'neutral');
  });
});
