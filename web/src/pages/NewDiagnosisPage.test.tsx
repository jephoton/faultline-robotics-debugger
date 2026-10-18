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

type User = ReturnType<typeof userEvent.setup>;

const PROMISE =
  'Faultline runs your start untouched. If it fails, it finds the smallest change that triggers it. If it passes, it looks for the smallest disturbance or rewording that breaks it.';

const PROBE_GROUP = 'If the start passes untouched, also probe';

/** Step 1 to step 2 for a kind of start, waiting until the template's backend block has arrived. */
async function toSettings(user: User, source: RegExp = /a benchmark start/i) {
  await user.click(screen.getByRole('radio', { name: source }));
  await user.click(screen.getByRole('button', { name: /next: settings/i }));
  await screen.findByLabelText('Spend cap (US$)');
  await waitFor(() => expect(yamlBox().value).toContain('backend:'));
}

function yamlBox() {
  return screen.getByLabelText('Spec in YAML') as HTMLTextAreaElement;
}

describe('step 1: what to check', () => {
  it('states the promise and offers three sources, a benchmark start first, on step 1 of 3', async () => {
    const user = userEvent.setup();
    await openNew();
    expect(screen.getByText(PROMISE)).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /a benchmark start/i })).toBeChecked();
    for (const name of [/search a range of starts/i, /a start file of my own/i]) {
      expect(screen.getByRole('radio', { name })).toBeInTheDocument();
    }
    expect(screen.getAllByRole('radio')).toHaveLength(3);
    expect(screen.getByRole('listitem', { current: 'step' })).toHaveTextContent('What to check');
    // The old three-card choice (scenario, stress test, rewordings) is gone from the main flow.
    expect(screen.queryByRole('radio', { name: /stress-test a passing start/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('radio', { name: /test rewordings/i })).not.toBeInTheDocument();
    await user.click(screen.getByRole('radio', { name: /search a range of starts/i }));
    expect(screen.getByRole('radio', { name: /search a range of starts/i })).toBeChecked();
  });

  it('says plainly that a range and a file look for a failure and do not probe', async () => {
    await openNew();
    const range = screen.getByRole('radio', { name: /search a range of starts/i }).closest('label') as HTMLElement;
    const file = screen.getByRole('radio', { name: /a start file of my own/i }).closest('label') as HTMLElement;
    expect(range).toHaveTextContent('It looks for a failure and does not probe.');
    expect(file).toHaveTextContent('It looks for a failure and does not probe.');
    const start = screen.getByRole('radio', { name: /a benchmark start/i }).closest('label') as HTMLElement;
    expect(start).not.toHaveTextContent('does not probe');
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

  it('generates the diagnose YAML with probes on, all ten families, 10 rewordings and the template backend', async () => {
    const user = userEvent.setup();
    await openNew();
    await toSettings(user);
    const yaml = yamlBox().value;
    expect(yaml).toContain('mode: diagnose');
    expect(yaml).toContain('  start: 14');
    expect(yaml).toContain('families: [blur, noise, darken, contrast, jpeg, colour_cast, motion_blur, dead_pixels, viewpoint, lighting]');
    expect(yaml).toContain('rewordings: 10');
    expect(yaml).toContain('enabled: true');
    expect(yaml).not.toContain('mode: scenario');
    await user.clear(screen.getByLabelText('Start'));
    await user.type(screen.getByLabelText('Start'), '21');
    expect(yamlBox().value).toContain('  start: 21');
  });

  it('groups the probes under "If the start passes untouched, also probe", every family ticked, image and scene apart', async () => {
    const user = userEvent.setup();
    await openNew();
    await toSettings(user);
    const probes = screen.getByRole('group', { name: PROBE_GROUP });
    expect(within(probes).getByRole('checkbox', { name: /probe with disturbances and rewordings/i })).toBeChecked();
    const families = within(probes).getByRole('group', { name: 'Disturbance families' });
    const boxes = within(families).getAllByRole('checkbox');
    expect(boxes).toHaveLength(10);
    for (const box of boxes) expect(box).toBeChecked();
    expect(within(families).getByText('Image, both cameras')).toBeInTheDocument();
    expect(within(families).getByText('Scene, applied when the simulator resets')).toBeInTheDocument();
    expect(within(probes).getByLabelText('Rewordings to ask for')).toHaveValue('10');
  });

  it('lets families and the number of rewordings be changed', async () => {
    const user = userEvent.setup();
    await openNew();
    await toSettings(user);
    await user.click(screen.getByRole('checkbox', { name: 'Lighting' }));
    await user.click(screen.getByRole('checkbox', { name: 'JPEG compression' }));
    expect(yamlBox().value).toContain('families: [blur, noise, darken, contrast, colour_cast, motion_blur, dead_pixels, viewpoint]');
    // Ticking one again keeps the server's order.
    await user.click(screen.getByRole('checkbox', { name: 'Lighting' }));
    expect(yamlBox().value).toContain('dead_pixels, viewpoint, lighting]');
    await user.clear(screen.getByLabelText('Rewordings to ask for'));
    await user.type(screen.getByLabelText('Rewordings to ask for'), '4');
    expect(yamlBox().value).toContain('rewordings: 4');
  });

  it('offers "Find related research", on by default, and writes it as a top-level key', async () => {
    const user = userEvent.setup();
    await openNew();
    await toSettings(user);
    const box = screen.getByRole('checkbox', { name: 'Find related research' });
    expect(box).toBeChecked();
    expect(screen.getByText(/Searches public sources with Tavily and summarises them with Nemotron 3 Nano\. Context, not evidence\. Needs a Tavily key in \.env\./)).toBeInTheDocument();
    expect(yamlBox().value).toMatch(/^research: true$/m);
    await user.click(box);
    expect(yamlBox().value).toMatch(/^research: false$/m);
  });

  it('turns the probes off with one toggle and greys the choices under it', async () => {
    const user = userEvent.setup();
    await openNew();
    await toSettings(user);
    await user.click(screen.getByRole('checkbox', { name: /probe with disturbances and rewordings/i }));
    expect(yamlBox().value).toContain('enabled: false');
    expect(screen.getByRole('checkbox', { name: 'Blur' })).toBeDisabled();
    expect(screen.getByLabelText('Rewordings to ask for')).toBeDisabled();
    // The choices are kept for when the toggle comes back on.
    await user.click(screen.getByRole('checkbox', { name: /probe with disturbances and rewordings/i }));
    expect(yamlBox().value).toContain('enabled: true');
    expect(screen.getByRole('checkbox', { name: 'Blur' })).toBeEnabled();
  });

  it('offers no probe group for a range of starts, and asks for the range', async () => {
    const user = userEvent.setup();
    await openNew();
    await toSettings(user, /search a range of starts/i);
    expect(screen.queryByRole('group', { name: PROBE_GROUP })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Rewordings to ask for')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Starts to search')).toHaveValue('10-49');
    expect(screen.getByLabelText('Confirmation attempts')).toHaveValue('4');
    expect(yamlBox().value).toContain('screen: {starts: "10-49", confirm: 4}');
    expect(yamlBox().value).not.toContain('probes:');
  });

  it('offers no probe group for a start file either', async () => {
    const user = userEvent.setup();
    await openNew();
    await toSettings(user, /a start file of my own/i);
    expect(screen.queryByRole('group', { name: PROBE_GROUP })).not.toBeInTheDocument();
    expect(await screen.findByLabelText('Start file')).toBeInTheDocument();
    expect(yamlBox().value).not.toContain('probes:');
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

  it('shows the rewordings and family errors beside their own fields', async () => {
    const user = userEvent.setup();
    await openNew();
    await toSettings(user);
    const rewordings = screen.getByLabelText('Rewordings to ask for');
    await user.clear(rewordings);
    await user.type(rewordings, '40');
    expect(await screen.findByText('must be a whole number from 0 to 12', {}, { timeout: 3000 })).toBeInTheDocument();
    expect(rewordings).toHaveAttribute('aria-invalid', 'true');
    const families = screen.getByRole('group', { name: 'Disturbance families' });
    for (const box of within(families).getAllByRole('checkbox')) await user.click(box);
    expect(await screen.findByText('choose at least one family', {}, { timeout: 3000 })).toBeInTheDocument();
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

  it('still lets the YAML hold any mode, such as the CLI audit mode', async () => {
    const user = userEvent.setup();
    await openNew();
    await toSettings(user);
    fireEvent.change(yamlBox(), { target: { value: yamlBox().value.replace('mode: diagnose', 'mode: audit') } });
    expect(await screen.findByText('Your YAML edits take priority')).toBeInTheDocument();
    expect(yamlBox().value).toContain('mode: audit');
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
    expect(yamlBox().value).toContain('import: mine.json');
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
});

describe('step 3: review and start', () => {
  async function toReview(user: User, source: RegExp = /a benchmark start/i) {
    await toSettings(user, source);
    await user.click(screen.getByRole('button', { name: 'Review' }));
    await screen.findByRole('heading', { name: 'Dry run' });
    await screen.findByText('Total worst case');
  }

  it('states the promise and what is being checked', async () => {
    const user = userEvent.setup();
    await openNew();
    await toReview(user);
    const what = screen.getByRole('heading', { name: 'What will run' }).closest('section') as HTMLElement;
    expect(within(what).getByText(PROMISE)).toBeInTheDocument();
    expect(within(what).getByText('Diagnosis')).toBeInTheDocument();
    expect(within(what).getByText('benchmark start 14')).toBeInTheDocument();
  });

  it('shows the three branches in order, each with its Jobs, worst case and a labelled typical estimate', async () => {
    const user = userEvent.setup();
    await openNew();
    await toReview(user);
    const first = screen.getByRole('region', { name: 'First: check the start untouched' });
    const fails = screen.getByRole('region', { name: 'If it fails: find the smallest layout change' });
    const passes = screen.getByRole('region', { name: 'If it passes: probe' });
    expect(first.compareDocumentPosition(fails) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(fails.compareDocumentPosition(passes) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    expect(within(first).getByText('check')).toBeInTheDocument();
    expect(within(first).getByText('US$0.98', { selector: 'dd' })).toBeInTheDocument();

    expect(within(fails).getByText('reference')).toBeInTheDocument();
    expect(within(fails).getByText('reduce')).toBeInTheDocument();
    expect(within(fails).getByText('US$2.11', { selector: 'dd' })).toBeInTheDocument();
    expect(within(fails).getByText(/not known yet \(typical, an estimate\)/)).toBeInTheDocument();

    // Ten families make three audit Jobs (four image, four image, two scene), then the rewordings.
    for (const name of ['probe-images-1', 'probe-images-2', 'probe-scene', 'rewordings-screen', 'rewordings-reduce']) {
      expect(within(passes).getByText(name)).toBeInTheDocument();
    }
    expect(within(passes).getByText('US$6.00', { selector: 'dd' })).toBeInTheDocument();
    const typical = within(passes).getByText('Typical').nextElementSibling as HTMLElement;
    expect(typical).toHaveTextContent('about US$3.00');
    expect(typical).toHaveTextContent('(typical, an estimate)');
  });

  it('totals the check plus the larger branch, not the sum, and applies the cap rule', async () => {
    const user = userEvent.setup();
    await openNew();
    await toReview(user);
    const total = screen.getByText('Total worst case').nextElementSibling as HTMLElement;
    // 0.98 for the check plus 6.00 for the probes, since only one branch runs.
    expect(total).toHaveTextContent('US$6.98');
    expect(total).toHaveTextContent('only one of them runs');
    expect(screen.getByText('Spend cap').nextElementSibling).toHaveTextContent('US$7.00');
    expect(await screen.findByText(/Nebius sign-in/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /start diagnosis/i })).toBeEnabled();
  });

  it('plans no probe branch when the probes are off', async () => {
    const user = userEvent.setup();
    await openNew();
    await toSettings(user);
    await user.click(screen.getByRole('checkbox', { name: /probe with disturbances and rewordings/i }));
    await user.click(screen.getByRole('button', { name: 'Review' }));
    await screen.findByText('Total worst case');
    expect(screen.getByRole('region', { name: 'First: check the start untouched' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'If it fails: find the smallest layout change' })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'If it passes: probe' })).not.toBeInTheDocument();
    expect(screen.getByText('Total worst case').nextElementSibling).toHaveTextContent('US$3.09');
  });

  it('plans only the check and the layout for a range of starts, named for the search', async () => {
    const user = userEvent.setup();
    await openNew();
    await toReview(user, /search a range of starts/i);
    expect(screen.getByRole('region', { name: 'First: search the range for a start that fails reliably' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Then: find the smallest layout change' })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'If it passes: probe' })).not.toBeInTheDocument();
    expect(screen.getByText('a range of starts (10-49)')).toBeInTheDocument();
  });

  it('posts the plan hash of the same spec and keeps the token header', async () => {
    const user = userEvent.setup();
    const view = await openNew();
    await toReview(user);
    await user.click(screen.getByRole('button', { name: /start diagnosis/i }));
    await waitFor(() => expect(postsTo(view, '/api/runs')).toHaveLength(1));
    const [, init] = postsTo(view, '/api/runs')[0] as [string, RequestInit];
    const body = JSON.parse(init.body as string);
    expect(body.plan_hash).toMatch(/^[0-9a-f]{8}$/);
    expect(body.yaml).toContain('mode: diagnose');
    expect(body.no_llm).toBeUndefined();
    expect((init.headers as Record<string, string>)['X-Faultline-Token']).toBeTruthy();
    const dry = postsTo(view, '/api/specs/dry-run')[0] as [string, RequestInit];
    expect(JSON.parse(dry[1].body as string).yaml).toBe(body.yaml);
    // ...and lands on the live run page.
    expect(await screen.findByRole('heading', { level: 1, name: 'new-diagnosis' })).toBeInTheDocument();
  });

  it('does not start without a Token Factory key while rewordings are asked for, and says what to do', async () => {
    const user = userEvent.setup();
    const missing: Environment = {
      checks: [
        { key: 'nebius_cli', ok: true, detail: 'signed in' },
        { key: 'token_factory_key', ok: false, detail: 'NEBIUS_API_KEY not found in .env', fix: 'Add NEBIUS_API_KEY to .env.' },
      ],
    };
    const view = await openNew({ environment: missing });
    await toReview(user);
    await screen.findByText(/NEBIUS_API_KEY not found/);
    await user.click(screen.getByRole('button', { name: /start diagnosis/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/Rewordings are written by Nemotron/);
    expect(postsTo(view, '/api/runs')).toHaveLength(0);
  });

  it('starts without a key when nothing asks Nemotron, and tells the run so', async () => {
    const user = userEvent.setup();
    const missing: Environment = {
      checks: [
        { key: 'nebius_cli', ok: true, detail: 'signed in' },
        { key: 'token_factory_key', ok: false, detail: 'NEBIUS_API_KEY not found in .env', fix: 'Add NEBIUS_API_KEY to .env.' },
      ],
    };
    const view = await openNew({ environment: missing });
    await toSettings(user);
    await user.clear(screen.getByLabelText('Rewordings to ask for'));
    await user.type(screen.getByLabelText('Rewordings to ask for'), '0');
    await user.click(screen.getByRole('checkbox', { name: /ask nemotron for a hypothesis/i }));
    await user.click(screen.getByRole('checkbox', { name: 'Find related research' }));
    await user.click(screen.getByRole('button', { name: 'Review' }));
    await screen.findByText('Total worst case');
    await user.click(screen.getByRole('button', { name: /start diagnosis/i }));
    await waitFor(() => expect(postsTo(view, '/api/runs')).toHaveLength(1));
    const body = JSON.parse((postsTo(view, '/api/runs')[0]?.[1] as RequestInit).body as string);
    expect(body.no_llm).toBe(true);
  });

  it('asks for a Tavily key before related research, and the research summary needs Nemotron too', async () => {
    const user = userEvent.setup();
    const noTavily: Environment = {
      checks: [
        { key: 'nebius_cli', ok: true, detail: 'signed in' },
        { key: 'token_factory_key', ok: true, detail: 'found' },
        { key: 'tavily_key', ok: false, detail: 'TAVILY_API_KEY not found in .env', fix: 'Add TAVILY_API_KEY to .env.' },
      ],
    };
    const view = await openNew({ environment: noTavily });
    await toReview(user);
    await screen.findByText(/TAVILY_API_KEY not found/);
    await user.click(screen.getByRole('button', { name: /start diagnosis/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/Related research needs a Tavily key/);
    expect(postsTo(view, '/api/runs')).toHaveLength(0);
  });

  it('does not tell the run to skip Nemotron while related research is on', async () => {
    const user = userEvent.setup();
    const view = await openNew();
    await toSettings(user);
    await user.clear(screen.getByLabelText('Rewordings to ask for'));
    await user.type(screen.getByLabelText('Rewordings to ask for'), '0');
    await user.click(screen.getByRole('checkbox', { name: /ask nemotron for a hypothesis/i }));
    await user.click(screen.getByRole('button', { name: 'Review' }));
    await screen.findByText('Total worst case');
    await user.click(screen.getByRole('button', { name: /start diagnosis/i }));
    await waitFor(() => expect(postsTo(view, '/api/runs')).toHaveLength(1));
    const body = JSON.parse((postsTo(view, '/api/runs')[0]?.[1] as RequestInit).body as string);
    expect(body.no_llm).toBeUndefined();
  });

  it('does not start when the Nebius sign-in is missing', async () => {
    const user = userEvent.setup();
    const signedOut: Environment = { checks: [{ key: 'nebius_cli', ok: false, detail: 'not signed in' }] };
    const view = await openNew({ environment: signedOut });
    await toReview(user);
    await screen.findByText(/not signed in/);
    await user.click(screen.getByRole('button', { name: /start diagnosis/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/not signed in to Nebius/i);
    expect(postsTo(view, '/api/runs')).toHaveLength(0);
  });

  it('shows the server sentence when a run is already active (409)', async () => {
    const user = userEvent.setup();
    await openNew({ activeDemo: true });
    await toReview(user);
    await user.click(screen.getByRole('button', { name: /start diagnosis/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent('A run is already active. Wait for it to finish or stop it first.');
  });

  it('never offers Start again after a start that may have launched the run (504)', async () => {
    const user = userEvent.setup();
    const view = await openNew({ launchStatus: 504 });
    await toReview(user);
    await user.click(screen.getByRole('button', { name: /start diagnosis/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/may have started/);
    expect(screen.queryByRole('button', { name: /start diagnosis/i })).not.toBeInTheDocument();
    expect(postsTo(view, '/api/runs')).toHaveLength(1);
  });

  it('sends one start for a double click', async () => {
    const user = userEvent.setup();
    const view = await openNew();
    await toReview(user);
    const button = screen.getByRole('button', { name: /start diagnosis/i });
    await user.dblClick(button);
    await waitFor(() => expect(postsTo(view, '/api/runs')).toHaveLength(1));
  });

  async function toReviewWithCap(user: User, cap: string) {
    await toSettings(user);
    fireEvent.change(screen.getByLabelText('Spend cap (US$)'), { target: { value: cap } });
    await waitFor(() => expect(yamlBox().value).toContain(`max_spend_usd: ${cap}`));
    await user.click(screen.getByRole('button', { name: 'Review' }));
    await screen.findByText('Total worst case');
  }

  it('starts when the first Job fits the cap even if a later one would not, and says so', async () => {
    const user = userEvent.setup();
    const view = await openNew();
    await toReviewWithCap(user, '1'); // mock plan: the check is US$0.98, the probes US$6.00
    expect(screen.getByText(/The first Job fits, but not all of them/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /start diagnosis/i }));
    await waitFor(() => expect(postsTo(view, '/api/runs')).toHaveLength(1));
  });

  it('refuses to start when even the first Job is over the cap', async () => {
    const user = userEvent.setup();
    const view = await openNew();
    await toReviewWithCap(user, '0.5');
    expect(screen.getByText(/Even the first Job could cost more than the cap/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /start diagnosis/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/nothing could run/);
    expect(postsTo(view, '/api/runs')).toHaveLength(0);
  });

  it('goes back to the settings without losing them', async () => {
    const user = userEvent.setup();
    await openNew();
    await toReview(user);
    await user.click(screen.getByRole('button', { name: /back to settings/i }));
    expect(await screen.findByLabelText('Spend cap (US$)')).toHaveValue('7');
    expect(screen.getByRole('checkbox', { name: 'Blur' })).toBeChecked();
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
