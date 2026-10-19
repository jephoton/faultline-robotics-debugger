import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { Environment } from '../../api/types';
import { IDS } from '../../mocks/fixtures';
import { vi } from 'vitest';
import { makeHarness, renderApp } from '../../test/utils';

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

function panelOf() {
  return screen.getByRole('heading', { name: 'Test a policy' }).closest('.panel') as HTMLElement;
}

function bodyOf(view: Awaited<ReturnType<typeof openCase>>) {
  return JSON.parse((replayPosts(view)[0] as [string, RequestInit])[1].body as string) as Record<string, string>;
}

describe('regression test on a case page', () => {
  it('is titled Regression test and opens with what it checks', async () => {
    await openCase(IDS.soup);
    const section = screen.getByRole('heading', { level: 2, name: 'Regression test' }).closest('section') as HTMLElement;
    expect(within(section).getByText(/to check the failure still happens/)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Replays' })).not.toBeInTheDocument();
  });

  it('lists the history with the policy tested and a link to each run', async () => {
    await openCase(IDS.soup);
    expect(screen.getByText('Still fails', { selector: '.badge' })).toBeInTheDocument();
    expect(screen.getByText('Fixed', { selector: '.badge' })).toBeInTheDocument();
    const older = screen.getByText(/Still reproduces: 4 of 5/).closest('li') as HTMLElement;
    expect(older).toHaveTextContent('Policy tested: the original policy (checkpoint not recorded)');
    const retrained = screen.getByText(/No longer reproduces after the checkpoint change/).closest('li') as HTMLElement;
    expect(retrained).toHaveTextContent('Policy tested: a new checkpoint, my-org/retrained-libero_10 at 9f2c1d0');
    const links = screen.getAllByRole('link', { name: 'Open the run' });
    expect(links[0]).toHaveAttribute('href', '/run/replay-soup-20261011-153000');
  });

  it('asks which policy to test first, with the original policy chosen and its checkpoint shown', async () => {
    await openCase(IDS.soup);
    const panel = panelOf();
    const group = within(panel).getByRole('group', { name: 'Which policy do you want to test?' });
    expect(within(group).getByRole('radio', { name: /The original policy/ })).toBeChecked();
    expect(within(group).getByText('nvidia/gr00t17-lerobot-libero_10-640 at 5ee08ab')).toBeInTheDocument();
    expect(within(group).getByRole('radio', { name: /A new checkpoint/ })).not.toBeChecked();
    expect(within(panel).queryByLabelText('Hugging Face model id')).not.toBeInTheDocument();
    expect(within(panel).queryByLabelText('What do you expect?')).not.toBeInTheDocument();
  });

  it('states the worst-case cost and folds the limits away, with no script line', async () => {
    await openCase(IDS.soup);
    const panel = panelOf();
    expect(await within(panel).findByText(/Costs up to/)).toHaveTextContent('Costs up to US$0.70 on your Nebius account if you run it.');
    const limits = within(panel).getByText('Limits').closest('details') as HTMLDetailsElement;
    expect(limits.open).toBe(false);
    expect(within(limits).getByLabelText('Spend cap (US$)')).toBeInTheDocument();
    expect(within(limits).getByLabelText('Hour limit')).toBeInTheDocument();
    expect(panel).not.toHaveTextContent('faultline replay <case folder>');
  });

  it('estimates the cost for the original policy and starts the test without naming a checkpoint', async () => {
    const user = userEvent.setup();
    const view = await openCase(IDS.soup);
    const panel = panelOf();
    await waitFor(() => expect(view.fetchSpy.mock.calls.some((call) => call[0] === '/api/specs/template?mode=replay')).toBe(true));
    await user.click(within(panel).getByRole('button', { name: 'Estimate cost' }));
    expect(await within(panel).findByText('Total worst case')).toBeInTheDocument();
    expect(within(panel).getAllByText('US$0.70', { selector: 'td' })).toHaveLength(2);
    await user.click(within(panel).getByRole('button', { name: 'Run the test' }));
    await waitFor(() => expect(replayPosts(view)).toHaveLength(1));
    const [path, init] = replayPosts(view)[0] as [string, RequestInit];
    expect(path).toBe(`/api/library/${encodeURIComponent(IDS.soup)}/replay`);
    const body = bodyOf(view);
    expect(body.expect).toBeUndefined();
    expect(body.yaml).toContain('mode: replay');
    expect(body.yaml).not.toContain('checkpoint');
    expect(body.plan_hash).toMatch(/^[0-9a-f]{8}$/);
    expect((init.headers as Record<string, string>)['X-Faultline-Token']).toBeTruthy();
    expect(await screen.findByRole('heading', { level: 1, name: 'new-diagnosis' })).toBeInTheDocument();
  });

  it('tests a new checkpoint: both fields are needed before the estimate, and the spec carries them', async () => {
    const user = userEvent.setup();
    const view = await openCase(IDS.soup);
    const panel = panelOf();
    await user.click(within(panel).getByRole('radio', { name: /A new checkpoint/ }));
    const estimate = within(panel).getByRole('button', { name: 'Estimate cost' });
    expect(estimate).toBeDisabled();
    await user.type(within(panel).getByLabelText('Hugging Face model id'), 'my-org/retrained');
    expect(estimate).toBeDisabled();
    expect(within(panel).getByText('Fill in the checkpoint id and revision first.')).toBeInTheDocument();
    await user.type(within(panel).getByLabelText('Revision (commit hash)'), 'abc1234');
    expect(estimate).toBeEnabled();
    await waitFor(() => expect(view.fetchSpy.mock.calls.some((call) => call[0] === '/api/specs/template?mode=replay')).toBe(true));
    await user.click(estimate);
    await within(panel).findByText('Total worst case');
    await user.click(within(panel).getByRole('button', { name: 'Run the test' }));
    await waitFor(() => expect(replayPosts(view)).toHaveLength(1));
    expect(bodyOf(view).yaml).toContain('checkpoint: {id: "my-org/retrained", revision: "abc1234"}');
  });

  it('explains the two checkpoint fields and what kind of checkpoint fits', async () => {
    const user = userEvent.setup();
    await openCase(IDS.soup);
    const panel = panelOf();
    await user.click(within(panel).getByRole('radio', { name: /A new checkpoint/ }));
    expect(
      within(panel).getByText(/A GR00T N1\.7 checkpoint in LeRobot format, trained for this LIBERO suite\. A private repository needs read access/),
    ).toBeInTheDocument();
    const model = within(panel).getByLabelText('Hugging Face model id');
    expect(model).toHaveAccessibleDescription('e.g. the one this case used: nvidia/gr00t17-lerobot-libero_10-640');
    const revision = within(panel).getByLabelText('Revision (commit hash)');
    expect(revision).toHaveAccessibleDescription(
      "From the model repository's history on Hugging Face; it pins exactly which version ran.",
    );
  });

  it('leaves out the "this case used" example when the case recorded no checkpoint', async () => {
    const user = userEvent.setup();
    const harness = makeHarness({ activeDemo: false, environment: READY });
    const base = await harness.api.detail(IDS.soup);
    vi.spyOn(harness.api, 'detail').mockResolvedValue({ ...base, checkpoint: null });
    renderApp(`/case/${IDS.soup}`, { harness });
    await screen.findByRole('heading', { level: 1 });
    const panel = panelOf();
    await user.click(within(panel).getByRole('radio', { name: /A new checkpoint/ }));
    expect(within(panel).getByLabelText('Hugging Face model id')).toHaveAccessibleDescription('');
  });

  it('goes back to the case checkpoint when the original policy is chosen again', async () => {
    const user = userEvent.setup();
    const view = await openCase(IDS.soup);
    const panel = panelOf();
    await user.click(within(panel).getByRole('radio', { name: /A new checkpoint/ }));
    await user.type(within(panel).getByLabelText('Hugging Face model id'), 'my-org/retrained');
    await user.type(within(panel).getByLabelText('Revision (commit hash)'), 'abc1234');
    await user.click(within(panel).getByRole('radio', { name: /The original policy/ }));
    await waitFor(() => expect(view.fetchSpy.mock.calls.some((call) => call[0] === '/api/specs/template?mode=replay')).toBe(true));
    await user.click(within(panel).getByRole('button', { name: 'Estimate cost' }));
    await within(panel).findByText('Total worst case');
    await user.click(within(panel).getByRole('button', { name: 'Run the test' }));
    await waitFor(() => expect(replayPosts(view)).toHaveLength(1));
    expect(bodyOf(view).yaml).not.toContain('retrained');
  });

  it('makes the person estimate again after changing the settings', async () => {
    const user = userEvent.setup();
    await openCase(IDS.soup);
    const panel = panelOf();
    await user.click(within(panel).getByRole('button', { name: 'Estimate cost' }));
    await within(panel).findByText('Total worst case');
    await user.clear(within(panel).getByLabelText('Spend cap (US$)'));
    await user.type(within(panel).getByLabelText('Spend cap (US$)'), '2');
    expect(within(panel).queryByText('Total worst case')).not.toBeInTheDocument();
    expect(within(panel).getByRole('button', { name: 'Estimate cost' })).toBeInTheDocument();
  });

  it('shows the server sentence when another run is active', async () => {
    const user = userEvent.setup();
    const view = await openCase(IDS.soup, { activeDemo: true });
    const panel = panelOf();
    await user.click(within(panel).getByRole('button', { name: 'Estimate cost' }));
    await within(panel).findByText('Total worst case');
    await user.click(within(panel).getByRole('button', { name: 'Run the test' }));
    expect(await within(panel).findByRole('alert')).toHaveTextContent('A run is already active. Wait for it to finish or stop it first.');
    expect(replayPosts(view)).toHaveLength(1);
  });

  it('says a case cannot be replayed when its inputs were not saved', async () => {
    await openCase(IDS.nominal);
    expect(screen.getByText(/cannot be replayed/)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Test a policy' })).not.toBeInTheDocument();
  });

  it('has no regression test section on an audit case', async () => {
    await openCase(IDS.audit);
    expect(screen.queryByRole('heading', { name: 'Regression test' })).not.toBeInTheDocument();
  });

  it('shows history but no controls in the static gallery', async () => {
    await openCase(IDS.soup, { mode: 'static' });
    expect(screen.getByRole('heading', { level: 2, name: 'Regression test' })).toBeInTheDocument();
    expect(screen.getByText('Still fails', { selector: '.badge' })).toBeInTheDocument();
    expect(screen.getByText('Fixed', { selector: '.badge' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Test a policy' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Open the run' })).not.toBeInTheDocument();
  });
});
