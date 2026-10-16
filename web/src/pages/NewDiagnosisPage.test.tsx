import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { Environment } from '../api/types';
import { renderApp } from '../test/utils';

const READY: Environment = {
  checks: [
    { key: 'nebius_cli', ok: true, detail: 'signed in' },
    { key: 'token_factory_key', ok: true, detail: 'found' },
    { key: 'spec_template', ok: true, detail: 'ok' },
  ],
};

async function openNew(options?: Parameters<typeof renderApp>[1]) {
  const view = renderApp('/new', { activeDemo: false, environment: READY, ...options });
  await screen.findByRole('heading', { level: 1, name: 'New diagnosis' });
  return view;
}

function postsTo(view: Awaited<ReturnType<typeof openNew>>, path: string) {
  return view.fetchSpy.mock.calls.filter((call) => call[0] === path && (call[1] as RequestInit | undefined)?.method === 'POST');
}

describe('step 1: what to diagnose', () => {
  it('offers the three choices with the scenario sub-choice, and starts on step 1 of 3', async () => {
    const user = userEvent.setup();
    await openNew();
    expect(screen.getByRole('radio', { name: /find why a start fails/i })).toBeChecked();
    expect(screen.getByRole('radio', { name: /stress-test a passing start/i })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /test rewordings/i })).toBeInTheDocument();
    for (const name of [/a benchmark start i know fails/i, /search a range of starts/i, /a start file of my own/i]) {
      expect(screen.getByRole('radio', { name })).toBeInTheDocument();
    }
    expect(screen.getByRole('listitem', { current: 'step' })).toHaveTextContent('What to diagnose');
    await user.click(screen.getByRole('radio', { name: /test rewordings/i }));
    expect(screen.queryByRole('radio', { name: /search a range of starts/i })).not.toBeInTheDocument();
  });
});

describe('step 2: settings', () => {
  it('shows the task instruction from the static table and follows the suite', async () => {
    const user = userEvent.setup();
    await openNew();
    await user.click(screen.getByRole('button', { name: /next: settings/i }));
    expect(await screen.findByLabelText('Task')).toBeInTheDocument();
    expect(screen.getByText(/put both the alphabet soup and the tomato sauce in the basket/, { selector: '.field__hint' })).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Suite'), 'libero_goal');
    expect(screen.getByText(/open the middle drawer of the cabinet/, { selector: '.field__hint' })).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Task'), '7');
    expect(screen.getByText(/turn on the stove/, { selector: '.field__hint' })).toBeInTheDocument();
  });

  it('generates the YAML from the form with the template backend block', async () => {
    const user = userEvent.setup();
    await openNew();
    await user.click(screen.getByRole('button', { name: /next: settings/i }));
    await screen.findByLabelText('Spend cap (US$)');
    const yaml = screen.getByLabelText('Spec in YAML') as HTMLTextAreaElement;
    await waitFor(() => expect(yaml.value).toContain('backend:'));
    expect(yaml.value).toContain('mode: scenario');
    await user.clear(screen.getByLabelText('Start'));
    await user.type(screen.getByLabelText('Start'), '21');
    expect(yaml.value).toContain('  start: 21');
  });

  it('shows validation errors inline, beside the right field, and explains why Review stopped', async () => {
    const user = userEvent.setup();
    const view = await openNew();
    await user.click(screen.getByRole('button', { name: /next: settings/i }));
    const spend = await screen.findByLabelText('Spend cap (US$)');
    await user.clear(spend);
    await user.type(spend, '-1');
    const message = await screen.findByText('must be a positive number', {}, { timeout: 3000 });
    expect(spend).toHaveAttribute('aria-invalid', 'true');
    expect(spend.getAttribute('aria-describedby')).toContain(message.closest('span')?.id as string);
    expect(screen.getByRole('status')).toHaveTextContent('1 problem');
    // The button stays enabled and says why it cannot go on.
    await user.click(screen.getByRole('button', { name: 'Review' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/1 problem/);
    expect(screen.queryByRole('heading', { name: 'Dry run' })).not.toBeInTheDocument();
    expect(postsTo(view, '/api/specs/dry-run')).toHaveLength(0);
  });

  it('lets the YAML be edited and then treats it as the source of truth', async () => {
    const user = userEvent.setup();
    await openNew();
    await user.click(screen.getByRole('button', { name: /next: settings/i }));
    const yaml = (await screen.findByLabelText('Spec in YAML')) as HTMLTextAreaElement;
    await waitFor(() => expect(yaml.value).toContain('backend:'));
    fireEvent.change(yaml, { target: { value: `${yaml.value}# my note\n` } });
    expect(await screen.findByText('Your YAML edits take priority')).toBeInTheDocument();
    await user.clear(screen.getByLabelText('Start'));
    await user.type(screen.getByLabelText('Start'), '33');
    expect(yaml.value).not.toContain('  start: 33');
    await user.click(screen.getByRole('button', { name: /discard yaml edits/i }));
    expect(yaml.value).toContain('  start: 33');
    expect(yaml.value).not.toContain('# my note');
  });

  it('shows errors that belong to no field in the YAML panel', async () => {
    const user = userEvent.setup();
    await openNew();
    await user.click(screen.getByRole('button', { name: /next: settings/i }));
    const yaml = (await screen.findByLabelText('Spec in YAML')) as HTMLTextAreaElement;
    await waitFor(() => expect(yaml.value).toContain('backend:'));
    fireEvent.change(yaml, { target: { value: yaml.value.replace('faultline: 1', 'faultline: 2') } });
    expect(await screen.findByText('must be 1', {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByText('faultline')).toBeInTheDocument();
  });

  it('reads an imported start file and rejects one that is not JSON', async () => {
    const user = userEvent.setup();
    await openNew();
    await user.click(screen.getByRole('radio', { name: /a start file of my own/i }));
    await user.click(screen.getByRole('button', { name: /next: settings/i }));
    const input = (await screen.findByLabelText('Start file')) as HTMLInputElement;
    await user.upload(input, new File(['not json'], 'bad.json', { type: 'application/json' }));
    expect(await screen.findByText('That file is not valid JSON.')).toBeInTheDocument();
    await user.upload(input, new File(['{"suite":"libero_10"}'], 'mine.json', { type: 'application/json' }));
    expect(await screen.findByText(/mine\.json \(/)).toBeInTheDocument();
    const yaml = screen.getByLabelText('Spec in YAML') as HTMLTextAreaElement;
    expect(yaml.value).toContain('import: mine.json');
  });

  it('asks for the start file before the review', async () => {
    const user = userEvent.setup();
    await openNew();
    await user.click(screen.getByRole('radio', { name: /a start file of my own/i }));
    await user.click(screen.getByRole('button', { name: /next: settings/i }));
    await screen.findByLabelText('Start file');
    await user.click(screen.getByRole('button', { name: 'Review' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose your start file first.');
  });

  it('lets audit families be picked', async () => {
    const user = userEvent.setup();
    await openNew();
    await user.click(screen.getByRole('radio', { name: /stress-test a passing start/i }));
    await user.click(screen.getByRole('button', { name: /next: settings/i }));
    await screen.findByRole('group', { name: 'Disturbance families' });
    await user.click(screen.getByRole('checkbox', { name: 'Lighting' }));
    const yaml = screen.getByLabelText('Spec in YAML') as HTMLTextAreaElement;
    expect(yaml.value).toContain('families: [blur, noise, darken, contrast, lighting]');
  });
});

describe('step 3: review and start', () => {
  async function toReview(user: ReturnType<typeof userEvent.setup>, kind: RegExp = /stress-test a passing start/i) {
    await user.click(screen.getByRole('radio', { name: kind }));
    await user.click(screen.getByRole('button', { name: /next: settings/i }));
    await screen.findByLabelText('Spend cap (US$)');
    await waitFor(() => expect((screen.getByLabelText('Spec in YAML') as HTMLTextAreaElement).value).toContain('backend:'));
    await user.click(screen.getByRole('button', { name: 'Review' }));
    await screen.findByRole('heading', { name: 'Dry run' });
  }

  it('shows the dry-run table, the total against the cap and the environment', async () => {
    const user = userEvent.setup();
    await openNew();
    await toReview(user);
    expect(await screen.findByText('Total worst case')).toBeInTheDocument();
    expect(screen.getAllByText('US$1.46').length).toBeGreaterThan(0);
    expect(screen.getByText('US$2.00')).toBeInTheDocument();
    expect(await screen.findByText(/Nebius sign-in/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /start diagnosis/i })).toBeEnabled();
  });

  it('posts the plan hash of the same spec and keeps the token header', async () => {
    const user = userEvent.setup();
    const view = await openNew();
    await toReview(user);
    await screen.findByText('Total worst case');
    await user.click(screen.getByRole('button', { name: /start diagnosis/i }));
    await waitFor(() => expect(postsTo(view, '/api/runs')).toHaveLength(1));
    const [, init] = postsTo(view, '/api/runs')[0] as [string, RequestInit];
    const body = JSON.parse(init.body as string);
    expect(body.plan_hash).toMatch(/^[0-9a-f]{8}$/);
    expect(body.yaml).toContain('mode: audit');
    expect(body.no_llm).toBeUndefined();
    expect((init.headers as Record<string, string>)['X-Faultline-Token']).toBeTruthy();
    const dry = postsTo(view, '/api/specs/dry-run')[0] as [string, RequestInit];
    expect(JSON.parse(dry[1].body as string).yaml).toBe(body.yaml);
  });

  it('does not start a Nemotron run without a key, and says what to do', async () => {
    const user = userEvent.setup();
    const missing: Environment = {
      checks: [
        { key: 'nebius_cli', ok: true, detail: 'signed in' },
        { key: 'token_factory_key', ok: false, detail: 'NEBIUS_API_KEY not found in .env', fix: 'Add NEBIUS_API_KEY to .env.' },
      ],
    };
    const view = await openNew({ environment: missing });
    await toReview(user, /test rewordings/i);
    await screen.findByText('Total worst case');
    await screen.findByText(/NEBIUS_API_KEY not found/);
    await user.click(screen.getByRole('button', { name: /start diagnosis/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/Rewordings are written by Nemotron/);
    expect(postsTo(view, '/api/runs')).toHaveLength(0);
  });

  it('does not start when the Nebius sign-in is missing', async () => {
    const user = userEvent.setup();
    const signedOut: Environment = { checks: [{ key: 'nebius_cli', ok: false, detail: 'not signed in' }] };
    const view = await openNew({ environment: signedOut });
    await toReview(user);
    await screen.findByText('Total worst case');
    await screen.findByText(/not signed in/);
    await user.click(screen.getByRole('button', { name: /start diagnosis/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/not signed in to Nebius/i);
    expect(postsTo(view, '/api/runs')).toHaveLength(0);
  });

  it('shows the server sentence when a run is already active (409)', async () => {
    const user = userEvent.setup();
    await openNew({ activeDemo: true });
    await toReview(user);
    await screen.findByText('Total worst case');
    await user.click(screen.getByRole('button', { name: /start diagnosis/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent('A run is already active. Wait for it to finish or stop it first.');
  });

  it('goes back to the settings without losing them', async () => {
    const user = userEvent.setup();
    await openNew();
    await toReview(user);
    await user.click(screen.getByRole('button', { name: /back to settings/i }));
    expect(await screen.findByLabelText('Spend cap (US$)')).toHaveValue('2');
    const view = within(screen.getByRole('list', { name: 'Steps' }));
    expect(view.getByText('Settings')).toBeInTheDocument();
  });
});

describe('where the controls do not exist', () => {
  it('shows no form in a static gallery', async () => {
    renderApp('/new', { mode: 'static' });
    expect(await screen.findByText(/needs the local Faultline server/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /next: settings/i })).not.toBeInTheDocument();
  });
});
