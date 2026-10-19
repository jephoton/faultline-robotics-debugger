import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import type { Detail, Environment } from '../api/types';
import { IDS } from '../mocks/fixtures';
import { mockDryRun } from '../mocks/handlers';
import { makeHarness, renderApp } from '../test/utils';

const READY: Environment = {
  checks: [
    { key: 'nebius_cli', ok: true, detail: 'signed in' },
    { key: 'token_factory_key', ok: true, detail: 'found' },
  ],
};

async function openCase(id: string, options?: Parameters<typeof renderApp>[1]) {
  const view = renderApp(`/case/${id}`, { activeDemo: false, environment: READY, ...options });
  await screen.findByRole('heading', { level: 1 });
  return view;
}

/** Open a case after changing what the server said about it. */
async function openChanged(id: string, change: (detail: Detail) => Detail) {
  const harness = makeHarness({ activeDemo: false, environment: READY });
  const base = await harness.api.detail(id);
  vi.spyOn(harness.api, 'detail').mockResolvedValue(change(base));
  renderApp(`/case/${id}`, { harness });
  await screen.findByRole('heading', { level: 1 });
}

function before(a: HTMLElement, b: HTMLElement): boolean {
  return Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
}

describe('findings of a diagnosis run', () => {
  it('lists both cases above the videos, marks the current one and links the other', async () => {
    await openCase(IDS.pipeAudit);
    const findings = screen.getByRole('heading', { level: 2, name: 'Findings of this diagnosis' });
    const list = findings.closest('section')?.querySelector('ul') as HTMLElement;
    const rows = within(list).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    // In route order: the audit case, then the wording case.
    expect(rows[0]).toHaveTextContent('FL-A-5A10');
    expect(rows[0]).toHaveTextContent('Stress test');
    expect(rows[0]).toHaveTextContent('This case');
    expect(rows[0]).toHaveAttribute('aria-current', 'true');
    expect(within(rows[0] as HTMLElement).queryByRole('link')).not.toBeInTheDocument();
    expect(rows[1]).toHaveTextContent('FL-L-6B21');
    expect(rows[1]).toHaveTextContent('Language test');
    expect(within(rows[1] as HTMLElement).getByRole('link', { name: 'FL-L-6B21' })).toHaveAttribute('href', `/case/${encodeURIComponent(IDS.pipeWording)}`);
    // The list comes before the videos.
    expect(before(findings, screen.getByRole('group', { name: 'Audit videos' }))).toBe(true);
  });

  it('shows each verdict as an icon, a word and a colour: red for a failure that repeats', async () => {
    await openCase(IDS.pipeAudit);
    const badges = screen.getAllByText('Failure repeats', { selector: '.badge' });
    expect(badges.length).toBeGreaterThanOrEqual(2);
    for (const badge of badges.slice(0, 2)) expect(badge).toHaveAttribute('data-tone', 'alarm');
  });

  it('follows a link to the other finding', async () => {
    const user = userEvent.setup();
    await openCase(IDS.pipeAudit);
    await user.click(screen.getByRole('link', { name: 'FL-L-6B21' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'diagnose-obj0 (wording)' })).toBeInTheDocument();
    // The wording page marks itself, and links back to the audit case.
    expect(screen.getByRole('link', { name: 'FL-A-5A10' })).toHaveAttribute('href', `/case/${encodeURIComponent(IDS.pipeAudit)}`);
  });

  it('leaves the list out when a run has one finding (the layout route)', async () => {
    await openCase(IDS.soup);
    expect(screen.queryByRole('heading', { name: 'Findings of this diagnosis' })).not.toBeInTheDocument();
  });

  it('leaves the list out for a case with no findings at all', async () => {
    await openCase(IDS.audit);
    expect(screen.queryByRole('heading', { name: 'Findings of this diagnosis' })).not.toBeInTheDocument();
  });

  it('shows a single finding when the run passed untouched, in green', async () => {
    await openChanged(IDS.quiet, (detail) => ({
      ...detail,
      route: 'passes',
      findings: [{ id: detail.id, fault_code: detail.fault_code, kind: detail.kind, verdict: 'no_failure', verdict_text: detail.verdict_text }],
    }));
    const section = screen.getByRole('heading', { name: 'Findings of this diagnosis' }).closest('section') as HTMLElement;
    expect(within(section).getByText('Each finding is its own case with its own report and replay.')).toBeInTheDocument();
    const badge = within(section).getByText('No failure found', { selector: '.badge' });
    expect(badge).toHaveAttribute('data-tone', 'pass');
  });

  it('shows a single finding when the start is flaky untouched, in amber', async () => {
    await openChanged(IDS.nominal, (detail) => ({
      ...detail,
      route: 'flaky',
      findings: [{ id: detail.id, fault_code: detail.fault_code, kind: detail.kind, verdict: 'stopped', verdict_text: detail.verdict_text }],
    }));
    const section = screen.getByRole('heading', { name: 'Findings of this diagnosis' }).closest('section') as HTMLElement;
    expect(within(section).getByText('Each finding is its own case with its own report and replay.')).toBeInTheDocument();
    expect(within(section).getByText('Stopped', { selector: '.badge' })).toHaveAttribute('data-tone', 'attention');
  });

  it('hides a one-item list for an older single-case run with no recorded route', async () => {
    await openChanged(IDS.quiet, (detail) => ({
      ...detail,
      route: undefined,
      findings: [{ id: detail.id, fault_code: detail.fault_code, kind: detail.kind, verdict: 'no_failure', verdict_text: detail.verdict_text }],
    }));
    expect(screen.queryByRole('heading', { name: 'Findings of this diagnosis' })).not.toBeInTheDocument();
  });

  it('uses the route when the server sends one', async () => {
    await openChanged(IDS.soup, (detail) => ({ ...detail, route: 'passes' }));
    expect(screen.getByRole('heading', { name: 'Findings of this diagnosis' })).toBeInTheDocument();
  });

  it('is part of the static gallery too, with links but no controls', async () => {
    await openCase(IDS.pipeAudit, { mode: 'static' });
    expect(screen.getByRole('heading', { name: 'Findings of this diagnosis' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'FL-L-6B21' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Test a policy' })).not.toBeInTheDocument();
  });
});

describe('replay of an audit case and a wording case', () => {
  function replayPosts(view: Awaited<ReturnType<typeof openCase>>) {
    return view.fetchSpy.mock.calls.filter((call) => String(call[0]).endsWith('/replay') && (call[1] as RequestInit | undefined)?.method === 'POST');
  }

  it('offers replay on an audit case with a purpose line about its disturbance', async () => {
    await openCase(IDS.pipeAudit);
    expect(screen.getByRole('heading', { level: 2, name: 'Regression test' })).toBeInTheDocument();
    expect(screen.getByText(/Reruns each disturbance that broke the policy at its threshold/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Test a policy' })).toBeInTheDocument();
  });

  it('offers replay on a wording case with a purpose line about its wording', async () => {
    await openCase(IDS.pipeWording);
    expect(screen.getByText(/Reruns the failing wording, five attempts, with the original wording as control/)).toBeInTheDocument();
  });

  it('dry-runs and starts a replay of an audit case against its own library id', async () => {
    const user = userEvent.setup();
    const view = await openCase(IDS.pipeAudit);
    const panel = screen.getByRole('heading', { name: 'Test a policy' }).closest('.panel') as HTMLElement;
    await user.click(within(panel).getByRole('button', { name: /estimate cost/i }));
    await within(panel).findByText('Total worst case');
    await user.click(within(panel).getByRole('button', { name: 'Run the test' }));
    await waitFor(() => expect(replayPosts(view)).toHaveLength(1));
    expect((replayPosts(view)[0] as [string, RequestInit])[0]).toBe(`/api/library/${encodeURIComponent(IDS.pipeAudit)}/replay`);
  });

  function dryRunPosts(view: Awaited<ReturnType<typeof openCase>>) {
    return view.fetchSpy.mock.calls
      .filter((call) => call[0] === '/api/specs/dry-run' && (call[1] as RequestInit | undefined)?.method === 'POST')
      .map((call) => JSON.parse((call[1] as RequestInit).body as string) as { case_id?: string; yaml: string });
  }

  it('plans the replay for the case: every dry run names it, and the review lists the case Jobs', async () => {
    const user = userEvent.setup();
    const view = await openCase(IDS.pipeAudit);
    const panel = screen.getByRole('heading', { name: 'Test a policy' }).closest('.panel') as HTMLElement;
    await user.click(within(panel).getByRole('button', { name: /estimate cost/i }));
    await within(panel).findByText('Total worst case');
    const posts = dryRunPosts(view);
    expect(posts.length).toBeGreaterThan(0);
    for (const post of posts) expect(post.case_id).toBe(IDS.pipeAudit);
    expect(within(panel).getAllByText('replay-2').length).toBeGreaterThan(0);
  });

  it('sets the default spend cap and hour limit from the plan so the first Job fits', async () => {
    await openCase(IDS.pipeAudit);
    const panel = screen.getByRole('heading', { name: 'Test a policy' }).closest('.panel') as HTMLElement;
    const spend = within(panel).getByLabelText('Spend cap (US$)') as HTMLInputElement;
    const plan = mockDryRun('mode: replay\n', undefined, IDS.pipeAudit);
    expect(plan.jobs[0]!.worst_case_usd).toBeGreaterThan(1.2);
    await waitFor(() => expect(Number(spend.value)).toBeGreaterThanOrEqual(plan.worst_case_total_usd));
    const hours = within(panel).getByLabelText('Hour limit') as HTMLInputElement;
    const needed = plan.jobs.reduce((sum, job) => sum + (job.deadline_seconds + 840) / 3600, 0);
    await waitFor(() => expect(Number(hours.value)).toBeGreaterThanOrEqual(needed));
  });

  it('does not overwrite a cap the person typed', async () => {
    const user = userEvent.setup();
    await openCase(IDS.pipeAudit);
    const panel = screen.getByRole('heading', { name: 'Test a policy' }).closest('.panel') as HTMLElement;
    const spend = within(panel).getByLabelText('Spend cap (US$)') as HTMLInputElement;
    await user.clear(spend);
    await user.type(spend, '9');
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(spend.value).toBe('9');
  });

  it('shows a replay of a wording case in words and colours, by the policy it tested', async () => {
    const original = { id: 'nvidia/gr00t17-lerobot-libero_object-640', revision: '5ee08ab09fac5c5ef2388a14c882ea825ac861db' };
    const retrained = { id: 'my-org/retrained', revision: 'abc1234def5678' };
    await openChanged(IDS.pipeWording, (detail) => ({
      ...detail,
      replays: [
        { run: 'replay-a', verdict: 'reproduces', verdict_text: 'the wording still fails', created: '2026-10-17T10:00:00Z', cost_usd: 0.3, checkpoint: original, original: true },
        { run: 'replay-b', verdict: 'fixed', verdict_text: 'no longer fails', created: '2026-10-18T10:00:00Z', cost_usd: 0.3, checkpoint: retrained, original: false },
        { run: 'replay-c', verdict: 'fixed', verdict_text: 'did not fail this time', created: '2026-10-19T10:00:00Z', cost_usd: 0.3, checkpoint: original, original: true },
        { run: 'replay-d', verdict: 'incomplete', verdict_text: 'stopped early', created: '2026-10-20T10:00:00Z', cost_usd: 0.1, checkpoint: retrained, original: false },
      ],
    }));
    expect(screen.getByText('Still fails', { selector: '.badge' })).toHaveClass('badge--alarm');
    expect(screen.getByText('Fixed', { selector: '.badge' })).toHaveClass('badge--pass');
    expect(screen.getByText('Did not repeat', { selector: '.badge' })).toHaveClass('badge--attention');
    expect(screen.getByText('Inconclusive', { selector: '.badge' })).toHaveClass('badge--attention');
    expect(screen.getByText('the wording still fails')).toBeInTheDocument();
    const fixed = screen.getByText('no longer fails').closest('li') as HTMLElement;
    expect(fixed).toHaveTextContent('Policy tested: a new checkpoint, my-org/retrained at abc1234');
    const kept = screen.getByText('did not fail this time').closest('li') as HTMLElement;
    expect(kept).toHaveTextContent('Policy tested: the original policy, nvidia/gr00t17-lerobot-libero_object-640 at 5ee08ab');
  });

  it('shows no replay section for an audit case without replay inputs or history', async () => {
    await openCase(IDS.audit);
    expect(screen.queryByRole('heading', { name: 'Regression test' })).not.toBeInTheDocument();
  });

  it('shows history, but no replay form, when an old audit case was replayed but cannot be again', async () => {
    await openChanged(IDS.audit, (detail) => ({
      ...detail,
      replays: [{ run: null, verdict: 'fixed', verdict_text: 'no longer fails', created: null, cost_usd: null }],
    }));
    expect(screen.getByRole('heading', { name: 'Regression test' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Test a policy' })).not.toBeInTheDocument();
  });
});

describe('videos on audit and wording cases', () => {
  it('puts the control first and labels each clip, with the outcome as a coloured word', async () => {
    await openCase(IDS.pipeAudit);
    const player = screen.getByRole('group', { name: 'Audit videos' });
    const captions = within(player).getAllByRole('figure').map((figure) => figure.querySelector('.player__label')?.textContent);
    expect(captions).toEqual(['Control: the start untouched (passed)', 'Blur at s = 0.50 (failed)', 'Contrast at s = 0.75 (failed)']);
    expect(within(player).getByLabelText('Blur at s = 0.50 (failed)')).toBeInTheDocument();
    const pass = within(player).getByText('passed', { selector: '.player__outcome' });
    expect(pass).toHaveClass('player__outcome--pass');
    for (const word of within(player).getAllByText('failed', { selector: '.player__outcome' })) expect(word).toHaveClass('player__outcome--fail');
    expect(screen.queryByText(/The control \(the start untouched\) first/)).not.toBeInTheDocument();
  });

  it('shows the control and the failing wording on a wording case', async () => {
    await openCase(IDS.pipeWording);
    const player = screen.getByRole('group', { name: 'Wording videos' });
    const figures = within(player).getAllByRole('figure');
    expect(figures).toHaveLength(2);
    expect(figures[0]).toHaveTextContent('Control: the original wording (passed)');
    expect(figures[1]).toHaveTextContent(/Failing wording/);
  });

  it('handles many clips: the control first, then the families, in a wrapping grid', async () => {
    const families = ['blur', 'noise', 'darken', 'contrast', 'jpeg', 'colour_cast', 'motion_blur', 'dead_pixels', 'viewpoint', 'lighting'];
    await openChanged(IDS.pipeAudit, (detail) => ({
      ...detail,
      videos: [
        ...families.map((family) => ({ role: `${family}@0.50`, label: `${family} at s = 0.50 (failed)`, url: '/media/placeholder.webm', outcome: 'policy_failure' })),
        { role: 'control', label: 'Control (passed)', url: '/media/placeholder.webm', outcome: 'success' },
      ],
    }));
    const player = screen.getByRole('group', { name: 'Audit videos' });
    const figures = within(player).getAllByRole('figure');
    expect(figures).toHaveLength(11);
    expect(figures[0]).toHaveTextContent('Control (passed)');
    expect(figures[1]).toHaveTextContent('blur at s = 0.50 (failed)');
    expect(player.querySelector('.player__videos')).toHaveAttribute('data-many', 'true');
    expect(within(player).getByRole('button', { name: /play all/i })).toBeInTheDocument();
  });

  it('does not mark a handful of clips as many', async () => {
    await openCase(IDS.pipeAudit);
    expect(screen.getByRole('group', { name: 'Audit videos' }).querySelector('.player__videos')).not.toHaveAttribute('data-many');
  });
});

describe('research context on a case', () => {
  it('keeps the older research record inside Full evidence, as context and not evidence', async () => {
    const user = userEvent.setup();
    await openCase(IDS.pipeAudit);
    // No standalone section in the main flow.
    expect(screen.queryByRole('heading', { level: 2, name: 'Research context' })).not.toBeInTheDocument();
    const fold = screen.getByText(/^Show the rest of the report and the research context/).closest('details') as HTMLDetailsElement;
    expect(fold.open).toBe(false);
    await user.click(screen.getByText(/^Show the rest of the report and the research context/));
    expect(within(fold).getByRole('heading', { level: 3, name: 'Research context' })).toBeInTheDocument();
    expect(within(fold).getByText(/Context, not evidence/)).toBeInTheDocument();
    expect(within(fold).getByRole('link', { name: /Robustness of vision-based policies/ })).toHaveAttribute('href', 'https://example.org/image-corruptions');
    // After the regression test, which comes after the summary.
    const replays = screen.getByRole('heading', { level: 2, name: 'Regression test' });
    expect(before(screen.getByRole('heading', { level: 2, name: 'Summary' }), replays)).toBe(true);
    expect(before(replays, fold)).toBe(true);
  });

  it('puts the research sources into the Nemotron box and drops the standalone block when the case has next steps', async () => {
    await openChanged(IDS.pipeAudit, (detail) => ({
      ...detail,
      next_steps: {
        model: 'nvidia/nemotron-3-ultra',
        status: 'ok',
        items: [{ text: 'Try blur at 0.4 to find where the failure starts.', cites: ['S1'] }],
        sources: [{ id: 'S1', title: 'Robustness of vision-based policies to image corruptions', url: 'https://example.org/image-corruptions' }],
      },
    }));
    expect(screen.getByRole('heading', { level: 2, name: 'Nemotron' })).toBeInTheDocument();
    expect(screen.queryByText(/Context, not evidence/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Show the rest of the report and the research context/)).not.toBeInTheDocument();
  });

  it("comes after Nemotron's full reading inside Full evidence when the case has one", async () => {
    await openChanged(IDS.pipeAudit, (detail) => ({
      ...detail,
      explanation: {
        status: 'review_required',
        model: 'nvidia/nemotron-3-super-120b-a12b',
        disclaimer: null,
        hypotheses: [],
        observations: [{ text: 'Blur from 0.5 broke the policy.', evidence_ids: ['c1'] }],
        limitations: [],
      },
    }));
    const reading = screen.getByRole('heading', { level: 3, name: "Nemotron's full reading" });
    const research = screen.getByRole('heading', { level: 3, name: 'Research context' });
    expect(before(reading, research)).toBe(true);
  });

  it('shows no research section when the case has none', async () => {
    await openCase(IDS.pipeWording);
    expect(screen.queryByRole('heading', { name: 'Research context' })).not.toBeInTheDocument();
  });
});

describe('pass and fail colours', () => {
  it('colours the readout verdict: green for no failure, red for a repeating failure', async () => {
    const view = await openCase(IDS.quiet);
    expect(within(screen.getByRole('region', { name: 'Readout' })).getByText('No failure found').closest('dd')).toHaveClass('readout__value--pass');
    view.unmount();
    await openCase(IDS.pipeAudit);
    expect(within(screen.getByRole('region', { name: 'Readout' })).getByText('Failure repeats').closest('dd')).toHaveClass('readout__value--alarm');
  });

  it('gives a no-failure case a green bar in the sidebar and a failing case a red one', async () => {
    renderApp('/', { activeDemo: false });
    const nav = await screen.findByRole('navigation', { name: 'Runs and cases' });
    const quiet = await within(nav).findByRole('link', { name: /paraphrase-task4/ });
    expect(quiet).toHaveClass('nav-item--pass');
    expect(within(nav).getByRole('link', { name: /audit-task0/ })).toHaveClass('nav-item--alarm');
  });
});
