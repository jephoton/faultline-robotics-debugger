import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { Environment } from '../../api/types';
import { IDS } from '../../mocks/fixtures';
import { renderApp } from '../../test/utils';

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

function replayPosts(view: Awaited<ReturnType<typeof openCase>>) {
  return view.fetchSpy.mock.calls.filter(
    (call) => String(call[0]).endsWith('/replay') && (call[1] as RequestInit | undefined)?.method === 'POST',
  );
}

describe('replay on a case page', () => {
  it('lists the replay history with a link to each run and shows verdicts as words', async () => {
    await openCase(IDS.soup);
    expect(screen.getByText('Still reproduces', { selector: '.badge' })).toBeInTheDocument();
    expect(screen.getByText('Fixed', { selector: '.badge' })).toBeInTheDocument();
    const links = screen.getAllByRole('link', { name: 'Open the run' });
    expect(links[0]).toHaveAttribute('href', '/run/replay-soup-20261011-153000');
  });

  it('dry-runs the replay, shows the plan, and starts it with the expectation and checkpoint', async () => {
    const user = userEvent.setup();
    const view = await openCase(IDS.soup);
    const panel = screen.getByRole('heading', { name: 'Replay this case' }).closest('.panel') as HTMLElement;
    await user.selectOptions(within(panel).getByLabelText('What do you expect?'), 'fixed');
    await user.type(within(panel).getByLabelText('Checkpoint id'), 'my-org/retrained');
    await user.type(within(panel).getByLabelText('Revision'), 'abc1234');
    await waitFor(() => expect(view.fetchSpy.mock.calls.some((call) => call[0] === '/api/specs/template?mode=replay')).toBe(true));
    await user.click(within(panel).getByRole('button', { name: /dry run the replay/i }));
    expect(await within(panel).findByText('Total worst case')).toBeInTheDocument();
    expect(within(panel).getAllByText('US$0.70', { selector: 'td' })).toHaveLength(2);
    await user.click(within(panel).getByRole('button', { name: 'Start replay' }));
    await waitFor(() => expect(replayPosts(view)).toHaveLength(1));
    const [path, init] = replayPosts(view)[0] as [string, RequestInit];
    expect(path).toBe(`/api/library/${encodeURIComponent(IDS.soup)}/replay`);
    const body = JSON.parse(init.body as string);
    expect(body.expect).toBe('fixed');
    expect(body.yaml).toContain('mode: replay');
    expect(body.yaml).toContain('checkpoint: {id: "my-org/retrained", revision: "abc1234"}');
    expect(body.plan_hash).toMatch(/^[0-9a-f]{8}$/);
    expect((init.headers as Record<string, string>)['X-Faultline-Token']).toBeTruthy();
    expect(await screen.findByRole('heading', { level: 1, name: 'new-diagnosis' })).toBeInTheDocument();
  });

  it('makes the person dry-run again after changing the settings', async () => {
    const user = userEvent.setup();
    await openCase(IDS.soup);
    const panel = screen.getByRole('heading', { name: 'Replay this case' }).closest('.panel') as HTMLElement;
    await user.click(within(panel).getByRole('button', { name: /dry run the replay/i }));
    await within(panel).findByText('Total worst case');
    await user.clear(within(panel).getByLabelText('Spend cap (US$)'));
    await user.type(within(panel).getByLabelText('Spend cap (US$)'), '2');
    expect(within(panel).queryByText('Total worst case')).not.toBeInTheDocument();
    expect(within(panel).getByRole('button', { name: /dry run the replay/i })).toBeInTheDocument();
  });

  it('shows the server sentence when another run is active', async () => {
    const user = userEvent.setup();
    const view = await openCase(IDS.soup, { activeDemo: true });
    const panel = screen.getByRole('heading', { name: 'Replay this case' }).closest('.panel') as HTMLElement;
    await user.click(within(panel).getByRole('button', { name: /dry run the replay/i }));
    await within(panel).findByText('Total worst case');
    await user.click(within(panel).getByRole('button', { name: 'Start replay' }));
    expect(await within(panel).findByRole('alert')).toHaveTextContent('A run is already active. Wait for it to finish or stop it first.');
    expect(replayPosts(view)).toHaveLength(1);
  });

  it('says a case cannot be replayed when its inputs were not saved', async () => {
    await openCase(IDS.nominal);
    expect(screen.getByText(/cannot be replayed/)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Replay this case' })).not.toBeInTheDocument();
  });

  it('has no replay section on an audit case', async () => {
    await openCase(IDS.audit);
    expect(screen.queryByRole('heading', { name: 'Replays' })).not.toBeInTheDocument();
  });

  it('shows history but no controls in the static gallery', async () => {
    await openCase(IDS.soup, { mode: 'static' });
    expect(screen.getByText('Still reproduces', { selector: '.badge' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Replay this case' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Open the run' })).not.toBeInTheDocument();
  });
});
