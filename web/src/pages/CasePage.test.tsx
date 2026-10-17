import { screen, within } from '@testing-library/react';
import { IDS } from '../mocks/fixtures';
import { vi } from 'vitest';
import { makeHarness, renderApp } from '../test/utils';

async function openCase(id: string, options?: Parameters<typeof renderApp>[1]) {
  const view = renderApp(`/case/${id}`, options);
  await screen.findByRole('heading', { level: 1 });
  return view;
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

describe('scenario case', () => {
  it('shows the minimal cause, the guess against the measurement, reruns and videos', async () => {
    await openCase(IDS.soup);
    expect(screen.getAllByText('alphabet_soup_1').length).toBeGreaterThan(0);
    expect(screen.getByText('2.5 cm')).toBeInTheDocument();
    expect(screen.getByText('6 joints, up to 2.3°')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'The guess' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'The measurement' })).toBeInTheDocument();
    expect(screen.getByText(/ranked the orange juice first/)).toBeInTheDocument();
    expect(screen.getByText('Show all 6 reruns')).toBeInTheDocument();
    const player = screen.getByRole('group', { name: 'Original, minimal and reference videos' });
    expect(within(player).getByLabelText('Original failing start')).toBeInTheDocument();
    expect(within(player).getByLabelText('Passing reference')).toBeInTheDocument();
    expect(within(player).getByRole('button', { name: /play all/i })).toBeInTheDocument();
  });

  it('shows an imported start by its file hash prefix and an empty video slot', async () => {
    await openCase(IDS.imported);
    expect(screen.getByText(/your imported file/)).toBeInTheDocument();
    expect(screen.getByText('f00dfeedf00d')).toBeInTheDocument();
    expect(screen.getByText('No video recorded')).toBeInTheDocument();
    expect(screen.getByText(/Nemotron was not asked for a hypothesis/)).toBeInTheDocument();
  });

  it('labels Nemotron output as needing review, with evidence ids and the model', async () => {
    await openCase(IDS.soup);
    expect(screen.getByText('Review required')).toBeInTheDocument();
    expect(screen.getByText('nvidia/nemotron-3-super-120b-a12b')).toBeInTheDocument();
    expect(screen.getByText('c12')).toBeInTheDocument();
    expect(screen.getByText(/there is no causal proof/)).toBeInTheDocument();
  });

  it('lists the replay history and renders the report', async () => {
    await openCase(IDS.soup);
    expect(screen.getByText('Still reproduces', { selector: '.badge' })).toBeInTheDocument();
    expect(screen.getByText('Fixed', { selector: '.badge' })).toBeInTheDocument();
    const report = screen.getByRole('heading', { name: /Scenario reduction: put both the alphabet soup/ });
    expect(report.tagName).toBe('H3');
  });

  it('shows how it was made with cost and a partial step', async () => {
    await openCase(IDS.soup);
    expect(screen.getByText('Reduce the difference')).toBeInTheDocument();
    expect(screen.getByText(/stopped, budget exhausted \(partial\)/)).toBeInTheDocument();
    expect(screen.getByText(/US\$3\.09 of a US\$3\.50 cap/)).toBeInTheDocument();
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
  it('shows a severity ladder per family with the threshold marked and others robust', async () => {
    await openCase(IDS.audit);
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
    vi.spyOn(harness.api, 'detail').mockResolvedValue({ ...base, audit: { ...base.audit!, families } });
    renderApp(`/case/${IDS.audit}`, { harness });
    const viewpoint = await screen.findByRole('article', { name: 'Camera viewpoint severity ladder' });
    expect(within(viewpoint).getByText(/Not tested: the run stopped before this family was searched/)).toBeInTheDocument();
    const lighting = screen.getByRole('article', { name: 'Scene lighting severity ladder' });
    expect(within(lighting).getByText(/Incomplete: searched up to severity 0.40, then stopped/)).toBeInTheDocument();
    expect(screen.queryByText(/No failure up to severity/)).not.toBeInTheDocument();
  });
});

describe('language case', () => {
  it('shows the control wording, each rewording with its meaning check and the minimal edit', async () => {
    await openCase(IDS.wording);
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
  it('shows the episodes, the rectangle lineage and the research context', async () => {
    await openCase(IDS.occlusion);
    expect(within(screen.getByRole('region', { name: 'Readout' })).getByText('FL-M-0F42')).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Occlusion episodes' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /Rectangle shrinking from 25% to 6\.3% of the image/ })).toBeInTheDocument();
    expect(screen.getByText(/Starting rectangle/)).toBeInTheDocument();
    expect(screen.getByText(/Trimmed the right edge/)).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'LIBERO benchmark' });
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.getByText('No run record is stored for this case.')).toBeInTheDocument();
  });
});

describe('static mode', () => {
  it('renders a case from the exported data files with no action buttons', async () => {
    const { fetchSpy } = await openCase(IDS.soup, { mode: 'static' });
    expect(within(screen.getByRole('region', { name: 'Readout' })).getByText('FL-S-AFB5')).toBeInTheDocument();
    const paths = fetchSpy.mock.calls.map((call) => String(call[0]));
    expect(paths.some((path) => path.startsWith('/data/library/'))).toBe(true);
    expect(screen.queryByRole('button', { name: /^(replay|stop|resume|start)/i })).not.toBeInTheDocument();
  });
});
