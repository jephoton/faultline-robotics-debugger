import { screen, within } from '@testing-library/react';
import { vi } from 'vitest';
import type { Detail, ReplayRow } from '../api/types';
import { measuredWords } from '../components/case/TeamSections';
import { replayGoneFamilies } from '../components/case/trust';
import { splitReport } from '../lib/reportSections';
import { IDS } from '../mocks/fixtures';
import { makeHarness, renderApp } from '../test/utils';

async function openCase(id: string, options?: Parameters<typeof renderApp>[1]) {
  const view = renderApp(`/case/${id}`, options);
  await screen.findByRole('heading', { level: 1 });
  return view;
}

async function openChanged(id: string, change: (base: Detail) => Partial<Detail>) {
  const harness = makeHarness();
  const base = await harness.api.detail(id);
  vi.spyOn(harness.api, 'detail').mockResolvedValue({ ...base, ...change(base) });
  renderApp(`/case/${id}`, { harness });
  await screen.findByRole('heading', { level: 1 });
}

function sectionOf(name: string): HTMLElement {
  return screen.getByRole('heading', { level: 2, name }).closest('section') as HTMLElement;
}

describe('Why it is trustworthy: a scenario case', () => {
  it('lists the gate, each kept shift alone and removing any one, citing the row numbers', async () => {
    await openCase(IDS.soup);
    const section = sectionOf("Why it's trustworthy");
    expect(within(section).getByText('The failing start (14) fails again: 4 of 4 attempts failed (row 0).')).toBeInTheDocument();
    expect(within(section).getByText('The reference (start 28) passes: 0 of 5 attempts failed (row 1).')).toBeInTheDocument();

    const alone = within(section).getByText(/^Each kept shift alone is not enough/).closest('li') as HTMLElement;
    const aloneLines = within(alone).getAllByRole('listitem').map((item) => item.textContent);
    expect(aloneLines).toEqual([
      'Alphabet soup alone: 0 of 2 attempts failed (row 2)',
      'Cream cheese alone: 0 of 2 attempts failed (row 3)',
      'Milk alone: 0 of 2 attempts failed (row 4)',
      'Orange juice alone: 0 of 2 attempts failed (row 5)',
      'Robot alone: 0 of 2 attempts failed (row 6)',
    ]);

    const without = within(section).getByText(/^Removing any one kept shift makes the policy pass again/).closest('li') as HTMLElement;
    expect(within(without).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      'Without Alphabet soup: 0 of 2 attempts failed (row 8)',
      'Without Cream cheese: 1 of 3 attempts failed (row 9)',
      'Without Milk: 0 of 2 attempts failed (row 10)',
      'Without Orange juice: 0 of 2 attempts failed (row 11)',
      'Without Robot: 0 of 2 attempts failed (row 12)',
    ]);
    // Every claim carries a word as well as an icon.
    const words = Array.from(section.querySelectorAll('.badge')).map((badge) => badge.textContent);
    expect(words).toEqual(['Fails', 'Passes', 'Passes', 'Passes']);
  });

  it('leaves out a claim whose rows cannot all be found, rather than guessing', async () => {
    await openChanged(IDS.soup, (base) => ({
      scenario: {
        ...base.scenario!,
        // Drop the probe of the milk alone and the ddmin row without the robot.
        reruns: base.scenario!.reruns.filter((rerun) => rerun.index !== 4 && rerun.index !== 12),
      },
    }));
    const section = sectionOf("Why it's trustworthy");
    expect(within(section).getByText(/^The failing start \(14\)/)).toBeInTheDocument();
    expect(within(section).queryByText(/^Each kept shift alone/)).not.toBeInTheDocument();
    expect(within(section).queryByText(/^Removing any one kept shift/)).not.toBeInTheDocument();
  });

  it('is left out when the case has no reruns', async () => {
    await openChanged(IDS.soup, (base) => ({ scenario: { ...base.scenario!, reruns: [] } }));
    expect(screen.queryByRole('heading', { name: "Why it's trustworthy" })).not.toBeInTheDocument();
  });

  it('does not use rows from a single kept shift for the alone and removal claims', async () => {
    await openChanged(IDS.imported, () => ({}));
    const section = sectionOf("Why it's trustworthy");
    expect(within(section).getByText(/^Your imported start fails again: 5 of 5 attempts failed \(row 0\)\./)).toBeInTheDocument();
    expect(within(section).queryByText(/^Each kept shift alone/)).not.toBeInTheDocument();
  });
});

describe('the Nemotron box: a scenario case', () => {
  it('compares its guess with the reruns in plain words', async () => {
    await openCase(IDS.soup);
    const box = sectionOf('Nemotron');
    expect(within(box).getByRole('heading', { level: 3, name: 'Its guess vs the reruns' })).toBeInTheDocument();
    const guesses = Array.from(box.querySelectorAll('.ranked--measured li')).map((item) => item.textContent?.replace(/\s+/g, ' ').trim());
    expect(guesses).toEqual([
      'Orange juice not enough alone',
      'Robot needed but not enough alone',
      'Alphabet soup needed but not enough alone',
    ]);
  });

  it('lists the suggested next steps, labelled as suggestions from the model, with cites as source links', async () => {
    await openCase(IDS.soup);
    const box = sectionOf('Nemotron');
    expect(within(box).getByRole('heading', { level: 3, name: 'Suggested next steps' })).toBeInTheDocument();
    expect(box).toHaveTextContent('Suggestions from nvidia/nemotron-3-ultra, not evidence.');
    const items = within(box).getAllByRole('listitem').filter((item) => item.closest('ol.steps'));
    expect(items).toHaveLength(3);
    const first = items[0] as HTMLElement;
    expect(within(first).getByText(/^Move the milk and the orange juice/)).toBeInTheDocument();
    const link = within(first).getByRole('link', { name: '[S1]' });
    expect(link).toHaveAttribute('href', 'https://example.org/placement-sensitivity');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    // An evidence id is a plain tag, not a link.
    expect(within(first).getByText('c32').tagName).toBe('CODE');
    expect(within(first).queryByRole('link', { name: /c32/ })).not.toBeInTheDocument();
    const sources = within(box).getByRole('heading', { level: 4, name: 'Sources' }).nextElementSibling as HTMLElement;
    expect(within(sources).getAllByRole('link').map((anchor) => anchor.getAttribute('href'))).toEqual([
      'https://example.org/placement-sensitivity',
      'https://example.org/libero',
      'https://example.org/robustness-eval',
    ]);
  });

  it('shows only the guess when next_steps is missing or null', async () => {
    await openChanged(IDS.soup, () => ({ next_steps: undefined }));
    let box = sectionOf('Nemotron');
    expect(within(box).getByRole('heading', { name: 'Its guess vs the reruns' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Suggested next steps' })).not.toBeInTheDocument();
    expect(box).not.toHaveTextContent('not evidence');
    document.body.innerHTML = '';
    await openChanged(IDS.soup, () => ({ next_steps: null }));
    box = sectionOf('Nemotron');
    expect(within(box).queryByRole('heading', { name: 'Suggested next steps' })).not.toBeInTheDocument();
  });

  it('has no Nemotron box at all when there is neither a hypothesis nor next steps', async () => {
    await openChanged(IDS.imported, () => ({}));
    expect(screen.queryByRole('heading', { level: 2, name: 'Nemotron' })).not.toBeInTheDocument();
  });

  it('shows next steps without the guess for a stress test', async () => {
    await openChanged(IDS.audit, () => ({
      next_steps: {
        model: 'nvidia/nemotron-3-ultra',
        status: 'ok',
        items: [{ text: 'Try blur at 0.4.', cites: ['S9'] }],
        sources: [],
      },
    }));
    const box = sectionOf('Nemotron');
    expect(within(box).queryByRole('heading', { name: 'Its guess vs the reruns' })).not.toBeInTheDocument();
    // A cite with no matching source is shown as a plain tag.
    expect(within(box).getByText('S9').tagName).toBe('CODE');
    expect(within(box).queryByRole('heading', { name: 'Sources' })).not.toBeInTheDocument();
  });

  it('never makes a link from a source that is not http or https', async () => {
    await openChanged(IDS.audit, () => ({
      next_steps: {
        model: 'm',
        status: 'ok',
        items: [{ text: 'Try something.', cites: ['S1'] }],
        sources: [{ id: 'S1', title: 'Bad', url: 'javascript:alert(1)' }],
      },
    }));
    const box = sectionOf('Nemotron');
    expect(within(box).queryByRole('link')).not.toBeInTheDocument();
    expect(within(box).getByText('S1').tagName).toBe('CODE');
  });
});

const REPLAY_BASE: ReplayRow = {
  run: 'replay-a',
  verdict: 'still_reproduces',
  verdict_text: '',
  created: '2026-10-18T10:00:00Z',
  cost_usd: 0.3,
  checkpoint: null,
  original: true,
};

describe('Why it is trustworthy: a stress-test case', () => {
  it('gives the control and the counts at the threshold and just below it', async () => {
    await openCase(IDS.audit);
    const section = sectionOf("Why it's trustworthy");
    expect(within(section).getByText('The untouched start (the control): 0 of 5 attempts failed.')).toBeInTheDocument();
    const blur = within(section).getByText('Blur fails from s = 0.5.').closest('li') as HTMLElement;
    expect(within(blur).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      'At s = 0.5, the threshold: 4 of 5 attempts failed',
      'At s = 0.25, the highest level below it that did not reproduce: 0 of 5 attempts failed',
    ]);
    const contrast = within(section).getByText('Contrast fails from s = 0.75.').closest('li') as HTMLElement;
    expect(within(contrast).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      'At s = 0.75, the threshold: 5 of 5 attempts failed',
      'At s = 0.5, the highest level below it that did not reproduce: 1 of 5 attempts failed',
    ]);
    // Families with no failure have no threshold to explain.
    expect(within(section).queryByText(/Noise/)).not.toBeInTheDocument();
    expect(within(section).queryByText('Borderline')).not.toBeInTheDocument();
  });

  it('flags a family the latest replay on the original policy no longer reproduced as borderline', async () => {
    await openChanged(IDS.audit, () => ({
      replayable: true,
      replays: [
        { ...REPLAY_BASE, verdict_text: 'still fails at s = 0.5 (blur), s = 0.75 (contrast)' },
        { ...REPLAY_BASE, run: 'replay-b', created: '2026-10-19T10:00:00Z', verdict_text: 'still fails at s = 0.75 (contrast); no longer fails at s = 0.50 (blur)' },
        // A later replay of a new checkpoint says nothing about how firm the original failure was.
        { ...REPLAY_BASE, run: 'replay-c', created: '2026-10-20T10:00:00Z', original: false, verdict: 'no_longer_reproduces', verdict_text: 'no longer fails at s = 0.75 (contrast)' },
      ],
    }));
    const section = sectionOf("Why it's trustworthy");
    const blur = within(section).getByText(/^Blur met the gate, but the latest replay did not repeat it at s = 0\.5/).closest('li') as HTMLElement;
    expect(within(blur).getByText('Borderline')).toBeInTheDocument();
    expect(blur).toHaveClass('trust__item--attention');
    const contrast = within(section).getByText('Contrast fails from s = 0.75.').closest('li') as HTMLElement;
    expect(within(contrast).getByText('Fails')).toBeInTheDocument();
    expect(contrast).not.toHaveClass('trust__item--attention');
  });

  it('reports a flaky control as such', async () => {
    await openChanged(IDS.audit, (base) => ({ audit: { ...base.audit!, nominal: { failures: 2, attempts: 5 } } }));
    const section = sectionOf("Why it's trustworthy");
    const control = within(section).getByText('The untouched start (the control): 2 of 5 attempts failed.').closest('li') as HTMLElement;
    expect(within(control).getByText('Flaky')).toBeInTheDocument();
  });
});

describe('cases that keep their layout', () => {
  it('keeps the report and its folded reading for a wording case', async () => {
    await openCase(IDS.wording);
    expect(screen.getByRole('heading', { level: 2, name: 'Report' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: "Why it's trustworthy" })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Full evidence' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 2, name: 'Nemotron' })).not.toBeInTheDocument();
  });

  it('keeps the structured view for a scenario or stress test with no stored report', async () => {
    await openChanged(IDS.audit, () => ({ report_markdown: null }));
    expect(screen.getByRole('article', { name: 'Blur severity ladder' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: "Why it's trustworthy" })).not.toBeInTheDocument();
  });

  it('keeps the report as it is when the report has no Summary section', async () => {
    await openChanged(IDS.soup, () => ({ report_markdown: '# A report\n\n## Result\n\n- Nothing summarised.\n' }));
    expect(screen.getByRole('heading', { level: 2, name: 'Report' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Full evidence' })).not.toBeInTheDocument();
  });
});

describe('static gallery', () => {
  it('shows the same sections, with the cites as links and nothing to start', async () => {
    await openCase(IDS.soup, { mode: 'static' });
    expect(screen.getByRole('heading', { level: 2, name: 'Summary' })).toBeInTheDocument();
    expect(within(sectionOf("Why it's trustworthy")).getByText(/^Each kept shift alone is not enough/)).toBeInTheDocument();
    expect(within(sectionOf('Nemotron')).getByRole('link', { name: '[S2]' })).toHaveAttribute('href', 'https://example.org/libero');
    const fold = screen.getByText(/^Show the rest of the report/).closest('details') as HTMLDetailsElement;
    expect(fold.tagName).toBe('DETAILS');
    expect(fold.open).toBe(false);
    expect(screen.queryByRole('heading', { name: 'Test a policy' })).not.toBeInTheDocument();
  });

  it('still renders a stress test exported before next_steps existed', async () => {
    await openCase(IDS.audit, { mode: 'static' });
    expect(within(sectionOf("Why it's trustworthy")).getByText('The untouched start (the control): 0 of 5 attempts failed.')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 2, name: 'Nemotron' })).not.toBeInTheDocument();
  });
});

describe('splitReport', () => {
  it('pulls out the Summary body and keeps every other section, without the title', () => {
    const parts = splitReport('# Title\n\n## Summary\n\n- a\n- b\n\n## Result\n\ntext\n\n### Inner\n\nmore\n\n## Effort\n\n- c\n');
    expect(parts.summary).toBe('- a\n- b');
    expect(parts.rest).toBe('## Result\n\ntext\n\n### Inner\n\nmore\n\n## Effort\n\n- c');
    expect(parts.restSections).toBe(2);
  });

  it('does not split on a ## line inside a code fence', () => {
    const parts = splitReport('## Summary\n\n- a\n\n## Result\n\n```\n## not a heading\n```\n');
    expect(parts.restSections).toBe(1);
    expect(parts.rest).toContain('## not a heading');
  });

  it('has no summary when the report has none', () => {
    expect(splitReport('# T\n\n## Result\n\nx').summary).toBeNull();
  });
});

describe('plain-word helpers', () => {
  it('reads what the reruns measured for an entity', () => {
    const entity = (necessary: boolean | null, sufficient: boolean | null) => ({ entity: 'e', label: 'E', necessary, sufficient });
    expect(measuredWords(entity(true, false)).text).toBe('needed but not enough alone');
    expect(measuredWords(entity(false, false)).text).toBe('not needed');
    expect(measuredWords(entity(false, true)).text).toBe('enough alone');
    expect(measuredWords(entity(true, true)).text).toBe('needed and enough alone');
    expect(measuredWords(entity(null, false)).text).toBe('not enough alone');
    expect(measuredWords(entity(null, null)).text).toBe('not measured');
    expect(measuredWords(undefined).text).toBe('not measured');
  });

  it('reads the families a replay sentence says no longer failed', () => {
    expect(replayGoneFamilies('still fails at s = 0.75 (contrast); no longer fails at s = 0.50 (blur), s = 0.60 (noise; fails only at higher s = 0.80); not tested: viewpoint')).toEqual([
      { family: 'blur', severity: 0.5, higher: null },
      { family: 'noise', severity: 0.6, higher: 0.8 },
    ]);
    expect(replayGoneFamilies('still fails at s = 0.5 (blur)')).toEqual([]);
  });
});
