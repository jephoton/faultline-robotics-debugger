import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { IDS, RUN_IDS } from '../mocks/fixtures';
import { makeHarness, renderApp } from '../test/utils';

async function openRun(run: string, options?: Parameters<typeof renderApp>[1]) {
  const view = renderApp(`/run/${run}`, { activeDemo: false, ...options });
  await screen.findByRole('article');
  return view;
}

function posts(view: { fetchSpy: { mock: { calls: unknown[][] } } }, path: string) {
  return view.fetchSpy.mock.calls.filter((call) => call[0] === path && (call[1] as RequestInit | undefined)?.method === 'POST');
}

describe('a run waiting for a GPU', () => {
  it('opens with the readout and says in words what is happening', async () => {
    await openRun(RUN_IDS.waiting);
    const readout = screen.getByRole('region', { name: 'Readout' });
    expect(within(readout).getByText('FL-L-····')).toBeInTheDocument();
    expect(within(readout).getByText('Waiting for a GPU')).toBeInTheDocument();
    expect(within(readout).getByText('US$0.04 of US$4.00')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'paraphrase-task1' })).toBeInTheDocument();
    expect(screen.getByText(/No GPU is free yet/)).toHaveTextContent('2 waits so far');
    expect(screen.getByText(/2 capacity waits/)).toBeInTheDocument();
  });

  it('shows spend and time as meters with a text equivalent', async () => {
    await openRun(RUN_IDS.waiting);
    const spend = screen.getByRole('meter', { name: 'Spend against the cap' });
    expect(spend).toHaveAttribute('aria-valuemax', '4');
    expect(spend).toHaveAttribute('aria-valuetext', 'US$0.04 spent and US$0.82 reserved of a US$4.00 cap');
    const time = screen.getByRole('meter', { name: 'Time against the limit' });
    expect(time).toHaveAttribute('aria-valuetext', '21 min 00 s of 3 hours');
  });

  it('shows the log tail', async () => {
    await openRun(RUN_IDS.waiting);
    expect(screen.getByLabelText('Last lines of the run log')).toHaveTextContent('screen: no GPU yet (capacity wait 2 of 6)');
  });

  it('asks before stopping, in words, and a cancel sends nothing', async () => {
    const user = userEvent.setup();
    const view = await openRun(RUN_IDS.waiting);
    await user.click(screen.getByRole('button', { name: /^stop$/i }));
    const dialog = screen.getByRole('alertdialog', { name: 'Stop this run?' });
    expect(dialog).toHaveTextContent('The current Job is cancelled and charged for the time it ran. You can resume later.');
    expect(within(dialog).getByRole('button', { name: /stop the run/i })).toHaveFocus();
    await user.click(within(dialog).getByRole('button', { name: 'Keep running' }));
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /^stop$/i }));
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(posts(view, `/api/runs/${RUN_IDS.waiting}/stop`)).toHaveLength(0);
  });

  it('sends the stop request with the session token once confirmed', async () => {
    const user = userEvent.setup();
    const view = await openRun(RUN_IDS.waiting);
    await user.click(screen.getByRole('button', { name: /^stop$/i }));
    await user.click(screen.getByRole('button', { name: /stop the run/i }));
    await waitFor(() => expect(posts(view, `/api/runs/${RUN_IDS.waiting}/stop`)).toHaveLength(1));
    const init = posts(view, `/api/runs/${RUN_IDS.waiting}/stop`)[0]?.[1] as RequestInit;
    expect((init.headers as Record<string, string>)['X-Faultline-Token']).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
  });
});

describe('other run states', () => {
  it('shows a running Job with no capacity warning', async () => {
    await openRun(RUN_IDS.running);
    expect(within(screen.getByRole('region', { name: 'Readout' })).getByText('Running')).toBeInTheDocument();
    expect(screen.getByText('Running on the GPU')).toBeInTheDocument();
    expect(screen.queryByText(/No GPU is free yet/)).not.toBeInTheDocument();
  });

  it('shows stopping without a Stop button', async () => {
    await openRun(RUN_IDS.stopping);
    expect(screen.getAllByText('Stopping').length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: /^stop$/i })).not.toBeInTheDocument();
    expect(screen.getByText(/being cancelled/)).toBeInTheDocument();
  });

  it('explains an expired sign-in in plain words with a way to resume', async () => {
    await openRun(RUN_IDS.authExpired);
    expect(screen.getByRole('note')).toHaveTextContent('Your Nebius sign-in expired. Sign in, then resume.');
    expect(screen.getByRole('link', { name: 'Open Setup' })).toHaveAttribute('href', '/setup');
    expect(screen.getByRole('button', { name: /resume/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^stop$/i })).not.toBeInTheDocument();
  });

  it('shows the server sentence when Resume is refused because a run is active', async () => {
    const user = userEvent.setup();
    await openRun(RUN_IDS.authExpired, { activeDemo: true });
    await user.click(screen.getByRole('button', { name: /resume/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent('A run is already active. Wait for it to finish or stop it first.');
  });

  it('resumes onto the new run page', async () => {
    const user = userEvent.setup();
    const view = await openRun(RUN_IDS.authExpired);
    await user.click(screen.getByRole('button', { name: /resume/i }));
    await waitFor(() => expect(posts(view, `/api/runs/${RUN_IDS.authExpired}/resume`)).toHaveLength(1));
    expect(await screen.findByRole('heading', { level: 1, name: 'new-diagnosis' })).toBeInTheDocument();
  });

  it('offers the case for a run that already finished, without redirecting', async () => {
    await openRun(RUN_IDS.completed);
    const link = screen.getByRole('link', { name: 'Open the case' });
    expect(link).toHaveAttribute('href', `/case/${encodeURIComponent(IDS.wording)}`);
    expect(screen.queryByText(/Opening it in/)).not.toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Readout' })).getByText('Completed')).toBeInTheDocument();
  });

  it('says plainly when the run is unknown', async () => {
    renderApp('/run/nothing-here', { activeDemo: false });
    expect(await screen.findByRole('heading', { name: 'Run not found' })).toBeInTheDocument();
  });

  it('is not part of the static gallery', async () => {
    renderApp(`/run/${RUN_IDS.waiting}`, { mode: 'static' });
    expect(await screen.findByText(/needs the local Faultline server/)).toBeInTheDocument();
  });
});

async function flush() {
  for (let i = 0; i < 12; i += 1) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
  }
}

describe('watching a run', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: false, toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('polls every five seconds, never overlaps, and opens the case when it finishes', async () => {
    const harness = makeHarness({ activeDemo: false });
    await harness.api.loadSession();
    const started = await harness.api.startRun({ yaml: 'x', plan_hash: 'bad' }).catch(() => null);
    expect(started).toBeNull();
    // Start a run in the mock directly (valid hash for the same yaml).
    const yaml = 'faultline: 1\nname: x\nmode: audit\nbudget:\n  max_spend_usd: 2\n  max_hours: 1\n';
    const plan = await harness.api.dryRun(yaml);
    const { run } = await harness.api.startRun({ yaml, plan_hash: plan.plan_hash });

    renderApp(`/run/${run}`, { harness });
    await flush();
    expect(screen.getByRole('article')).toBeInTheDocument();
    const progressCalls = () => harness.fetchSpy.mock.calls.filter((call) => String(call[0]).endsWith('/progress')).length;
    expect(progressCalls()).toBe(1);
    expect(screen.getByText('Submitting the Job')).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(progressCalls()).toBe(2);
    expect(screen.getByText('Waiting for a GPU', { selector: 'strong' })).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(screen.getByText('Running on the GPU')).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(screen.getByText(/Opening it in 3 seconds/)).toBeInTheDocument();
    const callsAtEnd = progressCalls();
    // Finished runs stop polling.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(screen.getByText(/Opening it in 2 seconds/)).toBeInTheDocument();
    expect(progressCalls()).toBe(callsAtEnd);
    for (let i = 0; i < 3; i += 1) {
      // One tick per render: React flushes the countdown state when each act scope ends.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
    }
    await flush();
    expect(screen.getByRole('heading', { level: 1, name: 'paraphrase-task0' })).toBeInTheDocument();
  });

  it('lets the person stay on the run page', async () => {
    const harness = makeHarness({ activeDemo: false });
    await harness.api.loadSession();
    const yaml = 'faultline: 1\nname: x\nmode: audit\nbudget:\n  max_spend_usd: 2\n  max_hours: 1\n';
    const plan = await harness.api.dryRun(yaml);
    const { run } = await harness.api.startRun({ yaml, plan_hash: plan.plan_hash });
    renderApp(`/run/${run}`, { harness });
    await flush();
    for (let i = 0; i < 5; i += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000);
      });
    }
    const stay = screen.getByRole('button', { name: 'Stay here' });
    // userEvent waits on timers, so click through the DOM directly.
    await act(async () => {
      stay.click();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(screen.getByRole('link', { name: 'Open the case' })).toBeInTheDocument();
    expect(screen.queryByText(/Opening it in/)).not.toBeInTheDocument();
  });
});

describe('the sidebar list of running runs', () => {
  it('shows the active run and keeps it fresh every ten seconds', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] });
    try {
      const view = renderApp('/', { activeDemo: true });
      await flush();
      const nav = screen.getByRole('navigation', { name: 'Runs and cases' });
      expect(within(nav).getByText('paraphrase-task1')).toBeInTheDocument();
      const calls = () => view.fetchSpy.mock.calls.filter((call) => call[0] === '/api/runs/active').length;
      const before = calls();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(calls()).toBe(before + 1);
    } finally {
      vi.useRealTimers();
    }
  });
});
