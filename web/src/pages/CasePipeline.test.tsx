import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import type { Detail, Environment } from '../api/types';
import { IDS } from '../mocks/fixtures';
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
    expect(within(section).getByText(/The start passed untouched/)).toBeInTheDocument();
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
    expect(within(section).getByText(/flaky untouched/)).toBeInTheDocument();
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
    expect(screen.queryByRole('heading', { name: 'Replay this case' })).not.toBeInTheDocument();
  });
});

describe('replay of an audit case and a wording case', () => {
  function replayPosts(view: Awaited<ReturnType<typeof openCase>>) {
    return view.fetchSpy.mock.calls.filter((call) => String(call[0]).endsWith('/replay') && (call[1] as RequestInit | undefined)?.method === 'POST');
  }

  it('offers replay on an audit case with a purpose line about its disturbance', async () => {
    await openCase(IDS.pipeAudit);
    expect(screen.getByRole('heading', { level: 2, name: 'Replays' })).toBeInTheDocument();
    expect(screen.getByText(/Replay reruns this disturbance at its threshold on the start, with its control, to check whether it still breaks the policy/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Replay this case' })).toBeInTheDocument();
    expect(screen.getByText(/reruns each disturbance that broke the policy at its threshold/)).toBeInTheDocument();
  });

  it('offers replay on a wording case with a purpose line about its wording', async () => {
    await openCase(IDS.pipeWording);
    expect(screen.getByText(/Replay reruns this wording on the start, with the original instruction as its control, to check whether it still breaks the policy/)).toBeInTheDocument();
    expect(screen.getByText(/reruns the failing wording on the start five times/)).toBeInTheDocument();
  });

  it('dry-runs and starts a replay of an audit case against its own library id', async () => {
    const user = userEvent.setup();
    const view = await openCase(IDS.pipeAudit);
    const panel = screen.getByRole('heading', { name: 'Replay this case' }).closest('.panel') as HTMLElement;
    await user.click(within(panel).getByRole('button', { name: /dry run the replay/i }));
    await within(panel).findByText('Total worst case');
    await user.click(within(panel).getByRole('button', { name: 'Start replay' }));
    await waitFor(() => expect(replayPosts(view)).toHaveLength(1));
    expect((replayPosts(view)[0] as [string, RequestInit])[0]).toBe(`/api/library/${encodeURIComponent(IDS.pipeAudit)}/replay`);
  });

  it('shows a replay of a wording case in words and colours: fixed is green, still failing is red', async () => {
    await openChanged(IDS.pipeWording, (detail) => ({
      ...detail,
      replays: [
        { run: 'replay-a', verdict: 'reproduces', verdict_text: 'the wording still fails', created: '2026-10-17T10:00:00Z', cost_usd: 0.3 },
        { run: 'replay-b', verdict: 'fixed', verdict_text: 'no longer fails', created: '2026-10-18T10:00:00Z', cost_usd: 0.3 },
      ],
    }));
    expect(screen.getByText('Still reproduces', { selector: '.badge' })).toHaveClass('badge--alarm');
    expect(screen.getByText('Fixed', { selector: '.badge' })).toHaveClass('badge--pass');
    expect(screen.getByText('the wording still fails')).toBeInTheDocument();
  });

  it('shows no replay section for an audit case without replay inputs or history', async () => {
    await openCase(IDS.audit);
    expect(screen.queryByRole('heading', { name: 'Replays' })).not.toBeInTheDocument();
  });

  it('shows history, but no replay form, when an old audit case was replayed but cannot be again', async () => {
    await openChanged(IDS.audit, (detail) => ({
      ...detail,
      replays: [{ run: null, verdict: 'fixed', verdict_text: 'no longer fails', created: null, cost_usd: null }],
    }));
    expect(screen.getByRole('heading', { name: 'Replays' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Replay this case' })).not.toBeInTheDocument();
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
    expect(screen.getByText(/The control \(the start untouched\) first/)).toBeInTheDocument();
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
  it('shows the research as context, not evidence, whenever the case has it', async () => {
    await openCase(IDS.pipeAudit);
    const section = screen.getByRole('heading', { level: 2, name: 'Research context' }).closest('section') as HTMLElement;
    expect(within(section).getByText(/Context, not evidence/)).toBeInTheDocument();
    expect(within(section).getByRole('link', { name: /Robustness of vision-based policies/ })).toHaveAttribute('href', 'https://example.org/image-corruptions');
    // After the report and before the replays.
    expect(before(screen.getByRole('heading', { level: 2, name: 'Report' }), section)).toBe(true);
    expect(before(section, screen.getByRole('heading', { level: 2, name: 'Replays' }))).toBe(true);
  });

  it('comes after Nemotron\'s reading when the case has one', async () => {
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
    const reading = screen.getByRole('heading', { level: 2, name: "Nemotron's reading" });
    const research = screen.getByRole('heading', { level: 2, name: 'Research context' });
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
