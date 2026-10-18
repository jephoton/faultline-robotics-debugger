import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { IDS } from '../mocks/fixtures';
import { vi } from 'vitest';
import { makeHarness, renderApp } from '../test/utils';

async function openCase(id: string, options?: Parameters<typeof renderApp>[1]) {
  const view = renderApp(`/case/${id}`, options);
  await screen.findByRole('heading', { level: 1 });
  return view;
}

/** Open a case as if its stored report were missing, to exercise the structured view. */
async function openWithoutReport(id: string) {
  const harness = makeHarness();
  const base = await harness.api.detail(id);
  vi.spyOn(harness.api, 'detail').mockResolvedValue({ ...base, report_markdown: null });
  renderApp(`/case/${id}`, { harness });
  await screen.findByRole('heading', { level: 1 });
}

function h2Names(): string[] {
  const article = document.querySelector('main article') as HTMLElement;
  return within(article)
    .getAllByRole('heading', { level: 2 })
    .map((heading) => heading.textContent ?? '');
}

describe('case page header', () => {
  it('opens with the readout: fault code, verdict, kind, suite and task, instruction', async () => {
    await openCase(IDS.soup);
    const readout = await screen.findByRole('region', { name: 'Readout' });
    expect(within(readout).getByText('FL-S-AFB5')).toBeInTheDocument();
    expect(within(readout).getByText('Failure repeats')).toBeInTheDocument();
    expect(within(readout).getByText('Scenario reduction')).toBeInTheDocument();
    expect(within(readout).getByText(/LIBERO-10, task 0/)).toBeInTheDocument();
    expect(within(readout).getByText(/alphabet soup and the tomato sauce/)).toBeInTheDocument();
    expect(await screen.findByRole('heading', { level: 1, name: 'soup-start14' })).toBeInTheDocument();
    expect(document.title).toContain('FL-S-AFB5');
  });

  it('keeps the full case id visible beside the fault code', async () => {
    await openCase(IDS.soup);
    expect(screen.getByText(/^afb5[0-9a-f]{60}$/)).toBeInTheDocument();
  });

  it('explains a stop in plain words', async () => {
    await openCase(IDS.soup);
    const note = screen.getByRole('note');
    expect(note).toHaveTextContent('Stopped at the candidate budget; this is the smallest cause found so far.');
  });

  it('says what was not found for a missing case', async () => {
    renderApp('/case/d-nothing');
    expect(await screen.findByRole('heading', { name: 'Case not found' })).toBeInTheDocument();
    expect(screen.getByText('That case was not found.')).toBeInTheDocument();
  });
});

describe('report-first scenario case', () => {
  it('orders the page: videos, the report, the folded reading, replays, run details, files', async () => {
    await openCase(IDS.soup);
    expect(h2Names()).toEqual(['Videos', 'Report', "Nemotron's reading", 'Replays', 'Files']);
    const order = [
      screen.getByRole('group', { name: 'Original, minimal and reference videos' }),
      screen.getByRole('heading', { level: 2, name: 'Report' }),
      screen.getByRole('heading', { level: 2, name: "Nemotron's reading" }),
      screen.getByRole('heading', { level: 2, name: 'Replays' }),
      screen.getByText('Run details'),
      screen.getByRole('heading', { level: 2, name: 'Files' }),
    ];
    for (let index = 1; index < order.length; index += 1) {
      expect((order[index - 1] as HTMLElement).compareDocumentPosition(order[index] as HTMLElement) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
  });

  it('renders the stored report as the body, opening with its summary', async () => {
    await openCase(IDS.soup);
    const title = screen.getByRole('heading', { name: /Scenario reduction: put both the alphabet soup/ });
    expect(title.tagName).toBe('H3');
    const summary = screen.getByRole('heading', { name: 'Summary' });
    expect(summary.tagName).toBe('H4');
    expect(summary).toHaveAttribute('id', 'md-summary');
    expect(screen.getByText(/Verdict: Reproduces\./)).toBeInTheDocument();
    expect(screen.getByText(/Kept shift: alphabet_soup_1 position, 2\.5 cm \(87\.5% of the full difference\)\./)).toBeInTheDocument();
    expect(screen.getByText(/Stopped at the candidate budget: entity-minimal/)).toBeInTheDocument();
    expect(title.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('folds the long Candidates table behind "Show all n rows" and opens it on request', async () => {
    const user = userEvent.setup();
    await openCase(IDS.soup);
    const toggle = screen.getByText('Show all 26 rows');
    const fold = toggle.closest('details') as HTMLDetailsElement;
    expect(fold.open).toBe(false);
    expect(within(fold).getByRole('table', { hidden: true })).toBeInTheDocument();
    await user.click(toggle);
    expect(fold.open).toBe(true);
    expect(within(fold).getAllByRole('row')).toHaveLength(27);
  });

  it('shows the videos above the report in the linked player', async () => {
    await openCase(IDS.soup);
    const player = screen.getByRole('group', { name: 'Original, minimal and reference videos' });
    expect(within(player).getByLabelText('Original failing start')).toBeInTheDocument();
    expect(within(player).getByLabelText('Passing reference')).toBeInTheDocument();
    expect(within(player).getByRole('button', { name: /play all/i })).toBeInTheDocument();
    const report = screen.getByRole('heading', { level: 2, name: 'Report' });
    expect(player.compareDocumentPosition(report) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps Nemotron's reading collapsed, labelled as interpretation, and opens it on request", async () => {
    const user = userEvent.setup();
    await openCase(IDS.soup);
    expect(screen.getByText(/It is not evidence and needs human review/)).toBeInTheDocument();
    const summary = screen.getByText('Show the reading (interpretation, not evidence)');
    const fold = summary.closest('details') as HTMLDetailsElement;
    expect(fold.open).toBe(false);
    await user.click(summary);
    expect(fold.open).toBe(true);
    expect(within(fold).getByText('Review required')).toBeInTheDocument();
    expect(within(fold).getByText('nvidia/nemotron-3-super-120b-a12b')).toBeInTheDocument();
    expect(within(fold).getByText('c12')).toBeInTheDocument();
    expect(within(fold).getByText(/there is no causal proof/)).toBeInTheDocument();
  });

  it('states what a replay is for, above the replay history', async () => {
    await openCase(IDS.soup);
    const purpose = screen.getByText(
      'Replay re-runs the minimal scene and its reference to check whether the failure still reproduces, for example after you change the policy.',
    );
    const replays = screen.getByRole('heading', { level: 2, name: 'Replays' }).closest('section') as HTMLElement;
    expect(replays).toContainElement(purpose);
    expect(screen.getByText('Still reproduces', { selector: '.badge' })).toBeInTheDocument();
    expect(screen.getByText('Fixed', { selector: '.badge' })).toBeInTheDocument();
    expect(purpose.compareDocumentPosition(screen.getByText('Fixed', { selector: '.badge' })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('folds the run details (steps, Jobs, cost, time) away until asked for', async () => {
    const user = userEvent.setup();
    await openCase(IDS.soup);
    const summary = screen.getByText('Run details');
    const fold = summary.closest('details') as HTMLDetailsElement;
    expect(fold.open).toBe(false);
    await user.click(summary);
    expect(fold.open).toBe(true);
    expect(within(fold).getByText('Reduce the difference')).toBeInTheDocument();
    expect(within(fold).getByText(/stopped, budget exhausted \(partial\)/)).toBeInTheDocument();
    expect(within(fold).getByText(/US\$3\.09 of a US\$3\.50 cap/)).toBeInTheDocument();
  });

  it('no longer repeats what the report already says', async () => {
    await openCase(IDS.soup);
    for (const gone of [
      'What changed between the passing and failing start',
      "Nemotron's guess and what was measured",
      'Reruns',
      'How it was made',
    ]) {
      expect(screen.queryByRole('heading', { name: gone })).not.toBeInTheDocument();
    }
    expect(screen.queryByRole('heading', { name: 'The guess' })).not.toBeInTheDocument();
    expect(screen.queryByText(/Show all 6 reruns/)).not.toBeInTheDocument();
  });

  it('shows an imported start in the report, with an empty video slot and no Nemotron section', async () => {
    await openCase(IDS.imported);
    expect(screen.getByText(/Failing start: imported file f00dfeedf00d \(from benchmark start 3\)\./)).toBeInTheDocument();
    expect(screen.getByText('No video recorded')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: "Nemotron's reading" })).not.toBeInTheDocument();
    expect(screen.queryByText('Show all 5 rows')).not.toBeInTheDocument();
    expect(screen.getByText(/Fully reduced: every kept shift/)).toBeInTheDocument();
  });
});

describe('scenario case without a stored report', () => {
  it('falls back to the structured view: minimal cause, the guess against the measurement, reruns, videos', async () => {
    await openWithoutReport(IDS.soup);
    expect(screen.getAllByText('alphabet_soup_1').length).toBeGreaterThan(0);
    expect(screen.getByText('2.5 cm')).toBeInTheDocument();
    expect(screen.getByText('6 joints, up to 2.3°')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'The guess' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'The measurement' })).toBeInTheDocument();
    expect(screen.getByText(/ranked the orange juice first/)).toBeInTheDocument();
    expect(screen.getByText('Show all 6 reruns')).toBeInTheDocument();
    const player = screen.getByRole('group', { name: 'Original, minimal and reference videos' });
    expect(within(player).getByLabelText('Original failing start')).toBeInTheDocument();
    expect(screen.getByText('No report was saved for this case.')).toBeInTheDocument();
    expect(screen.queryByText('Run details')).not.toBeInTheDocument();
  });

  it('labels Nemotron output as needing review, with evidence ids and the model', async () => {
    await openWithoutReport(IDS.soup);
    expect(screen.getByText('Review required')).toBeInTheDocument();
    expect(screen.getByText('nvidia/nemotron-3-super-120b-a12b')).toBeInTheDocument();
    expect(screen.getByText('c12')).toBeInTheDocument();
  });

  it('shows how it was made with cost and a partial step', async () => {
    await openWithoutReport(IDS.soup);
    expect(screen.getByRole('heading', { name: 'How it was made' })).toBeInTheDocument();
    expect(screen.getByText('Reduce the difference')).toBeInTheDocument();
    expect(screen.getByText(/stopped, budget exhausted \(partial\)/)).toBeInTheDocument();
    expect(screen.getByText(/US\$3\.09 of a US\$3\.50 cap/)).toBeInTheDocument();
  });

  it('shows an imported start by its file hash prefix and an empty video slot', async () => {
    await openWithoutReport(IDS.imported);
    expect(screen.getByText(/your imported file/)).toBeInTheDocument();
    expect(screen.getByText('f00dfeedf00d')).toBeInTheDocument();
    expect(screen.getByText('No video recorded')).toBeInTheDocument();
    expect(screen.getByText(/Nemotron was not asked for a hypothesis/)).toBeInTheDocument();
  });

  it('shows empty states for a stopped case with nothing saved', async () => {
    await openCase(IDS.nominal);
    expect(screen.getByRole('note')).toHaveTextContent('The unperturbed policy did not pass reliably');
    expect(screen.getByText('No minimal cause was found for this run.')).toBeInTheDocument();
    expect(screen.getByText('No videos were saved for this case.')).toBeInTheDocument();
    expect(screen.getByText('No Nemotron reading was made for this case.')).toBeInTheDocument();
    expect(screen.getByText('No report was saved for this case.')).toBeInTheDocument();
  });
});

describe('audit case', () => {
  it('opens with the report and its summary, with no severity ladders', async () => {
    await openCase(IDS.audit);
    expect(screen.getByRole('heading', { name: 'Summary' })).toBeInTheDocument();
    expect(screen.getByText('Unperturbed control: 0 of 5 attempts failed.')).toBeInTheDocument();
    expect(screen.getByText('Blur: fails from s = 0.50.')).toBeInTheDocument();
    expect(screen.getByText('Noise: no failure up to s = 1.00.')).toBeInTheDocument();
    expect(screen.queryByRole('article', { name: 'Blur severity ladder' })).not.toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Audit videos' })).toBeInTheDocument();
    // An audit has nothing to replay.
    expect(screen.queryByRole('heading', { name: 'Replays' })).not.toBeInTheDocument();
    expect(screen.getByText('Run details')).toBeInTheDocument();
  });

  it('shows a severity ladder per family with the threshold marked when there is no stored report', async () => {
    await openWithoutReport(IDS.audit);
    const blur = screen.getByRole('article', { name: 'Blur severity ladder' });
    expect(within(blur).getByText('Fails from severity 0.50')).toBeInTheDocument();
    expect(within(blur).getByText('Threshold')).toBeInTheDocument();
    expect(within(blur).getByRole('img', { name: '4 of 5 attempts failed at severity 0.50' })).toBeInTheDocument();
    const noise = screen.getByRole('article', { name: 'Noise severity ladder' });
    expect(within(noise).getByText('No failure up to severity 1.00')).toBeInTheDocument();
    expect(within(noise).queryByText('Threshold')).not.toBeInTheDocument();
    const contrast = screen.getByRole('article', { name: 'Contrast severity ladder' });
    expect(within(contrast).getByText('Fails from severity 0.75')).toBeInTheDocument();
    expect(screen.getByText('0 of 5 attempts failed')).toBeInTheDocument();
  });

  it('marks a threshold found beside a flaky control as unconfirmed', async () => {
    const harness = makeHarness();
    const base = await harness.api.detail(IDS.audit);
    const families = base.audit!.families.map((family) => ({ ...family, threshold_unconfirmed: true }));
    vi.spyOn(harness.api, 'detail').mockResolvedValue({ ...base, report_markdown: null, audit: { ...base.audit!, families } });
    renderApp(`/case/${IDS.audit}`, { harness });
    const blur = await screen.findByRole('article', { name: 'Blur severity ladder' });
    expect(within(blur).getByText(/Unconfirmed: failed from severity 0.50 beside a flaky control/)).toBeInTheDocument();
    expect(within(blur).queryByText('Fails from severity 0.50')).not.toBeInTheDocument();
  });

  it('never calls a family the run did not search "no failure"', async () => {
    const harness = makeHarness();
    const base = await harness.api.detail(IDS.audit);
    const families = [
      { family: 'viewpoint', label: 'Camera viewpoint', threshold_severity: null, stop_reason: 'nominal_failed', levels: [] },
      {
        family: 'lighting', label: 'Scene lighting', threshold_severity: null, stop_reason: 'infrastructure_error',
        levels: [{ severity: 0.2, failures: 0, attempts: 5 }, { severity: 0.4, failures: 0, attempts: 5 }],
      },
    ];
    vi.spyOn(harness.api, 'detail').mockResolvedValue({ ...base, report_markdown: null, audit: { ...base.audit!, families } });
    renderApp(`/case/${IDS.audit}`, { harness });
    const viewpoint = await screen.findByRole('article', { name: 'Camera viewpoint severity ladder' });
    expect(within(viewpoint).getByText(/Not tested: the run stopped before this family was searched/)).toBeInTheDocument();
    const lighting = screen.getByRole('article', { name: 'Scene lighting severity ladder' });
    expect(within(lighting).getByText(/Incomplete: searched up to severity 0.40, then stopped/)).toBeInTheDocument();
    expect(screen.queryByText(/No failure up to severity/)).not.toBeInTheDocument();
  });
});

describe('language case', () => {
  it('opens with the report and its summary instead of the wording table', async () => {
    await openCase(IDS.wording);
    expect(screen.getByRole('heading', { name: 'Summary' })).toBeInTheDocument();
    expect(screen.getByText(/Rewordings: 5 screened; 4 kept by the meaning check, 1 dropped/)).toBeInTheDocument();
    expect(screen.queryByText('Changed meaning, discarded')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Wordings tried' })).not.toBeInTheDocument();
  });

  it('shows the control wording, each rewording with its meaning check and the minimal edit without a stored report', async () => {
    await openWithoutReport(IDS.wording);
    expect(screen.getByText('Original')).toBeInTheDocument();
    expect(screen.getByText('put the alphabet soup in the basket')).toBeInTheDocument();
    expect(screen.getByText('Changed meaning, discarded')).toBeInTheDocument();
    expect(screen.getByText('remove "up"')).toBeInTheDocument();
    expect(screen.getByText('replace "place" with "put"')).toBeInTheDocument();
  });

  it('explains a run that found no failing wording', async () => {
    await openCase(IDS.quiet);
    expect(screen.getByRole('heading', { level: 1, name: 'paraphrase-task4' })).toBeInTheDocument();
    expect(screen.getByRole('note')).toHaveTextContent('No failure repeated 4 of 5 times.');
    expect(screen.getByText(/No wording failed reliably/)).toBeInTheDocument();
    const readout = screen.getByRole('region', { name: 'Readout' });
    expect(within(readout).getByText('No failure found')).toBeInTheDocument();
    expect(screen.getByRole('note')).not.toHaveClass('notice--attention');
  });
});

describe('occlusion case (M4)', () => {
  it('keeps the structured view: the episodes, the rectangle lineage and the research context', async () => {
    await openCase(IDS.occlusion);
    expect(within(screen.getByRole('region', { name: 'Readout' })).getByText('FL-M-0F42')).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Occlusion episodes' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /Rectangle shrinking from 25% to 6\.3% of the image/ })).toBeInTheDocument();
    expect(screen.getByText(/Starting rectangle/)).toBeInTheDocument();
    expect(screen.getByText(/Trimmed the right edge/)).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'LIBERO benchmark' });
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.getByText('No run record is stored for this case.')).toBeInTheDocument();
    expect(screen.queryByText('Run details')).not.toBeInTheDocument();
  });
});

describe('static mode', () => {
  it('renders the report-first case from the exported data files with no action buttons', async () => {
    const { fetchSpy } = await openCase(IDS.soup, { mode: 'static' });
    expect(within(screen.getByRole('region', { name: 'Readout' })).getByText('FL-S-AFB5')).toBeInTheDocument();
    const paths = fetchSpy.mock.calls.map((call) => String(call[0]));
    expect(paths.some((path) => path.startsWith('/data/library/'))).toBe(true);
    expect(screen.getByRole('heading', { name: 'Summary' })).toBeInTheDocument();
    expect(screen.getByText('Show all 26 rows')).toBeInTheDocument();
    // The replay history and its purpose are shown, but nothing can be started from a static page.
    expect(screen.getByText(/Replay re-runs the minimal scene/)).toBeInTheDocument();
    expect(screen.getByText('Still reproduces', { selector: '.badge' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Replay this case' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^(replay|stop|resume|start)/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /dry run/i })).not.toBeInTheDocument();
  });
});

describe('readout verdict colours', () => {
  it('marks the verdict by tone inside the readout, unlike the descriptive fields', async () => {
    renderApp(`/case/${IDS.soup}`);
    const readout = await screen.findByRole('region', { name: 'Readout' });
    const verdict = within(readout).getByText('Failure repeats').closest('dd');
    expect(verdict).toHaveClass('readout__value--alarm');
    const kind = within(readout).getByText('Scenario reduction').closest('dd');
    expect(kind).not.toHaveClass('readout__value');
  });
});
