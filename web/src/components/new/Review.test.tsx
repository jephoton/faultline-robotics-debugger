import { render, screen, within } from '@testing-library/react';
import type { DryRun } from '../../api/types';
import { DryRunTable } from './Review';

function plan(over: Partial<DryRun> = {}): DryRun {
  return {
    plan_hash: 'abcd1234',
    jobs: [
      { name: 'check', deadline_seconds: 1800, worst_case_usd: 1, branch: 'check' },
      { name: 'reduce', deadline_seconds: 3000, worst_case_usd: 2, branch: 'layout' },
      { name: 'probe-images-1', deadline_seconds: 2400, worst_case_usd: 1.5, branch: 'probes' },
    ],
    branches: [
      { branch: 'check', worst_case_usd: 1, typical_usd: 0.5, typical_minutes: 15 },
      { branch: 'layout', worst_case_usd: 2, typical_usd: 1, typical_minutes: 25 },
      { branch: 'probes', worst_case_usd: 1.5, typical_usd: 0.75, typical_minutes: 20 },
    ],
    worst_case_total_usd: 3,
    cap_usd: 5,
    max_hours: 3,
    lines: [],
    ...over,
  };
}

describe('the branched dry run', () => {
  it('labels every typical figure as an estimate, with its time, and totals the check plus each branch', () => {
    render(<DryRunTable plan={plan()} />);
    const probes = screen.getByRole('region', { name: 'If it passes: probe' });
    const typical = within(probes).getByText('Typical').nextElementSibling as HTMLElement;
    expect(typical).toHaveTextContent('about US$0.75 and 20 minutes');
    expect(typical).toHaveTextContent('(typical, an estimate; GPU waits can add more)');
    expect(screen.getByText('Total worst case').nextElementSibling).toHaveTextContent('US$3.00');
    // The check (0.50, 15 min) plus the layout (1.00, 25 min) or the probes (0.75, 20 min).
    expect(screen.getByText('Typical total if it fails').nextElementSibling).toHaveTextContent('about US$1.50 and 40 minutes');
    expect(screen.getByText('Typical total if it passes').nextElementSibling).toHaveTextContent('about US$1.25 and 35 minutes');
  });

  it('says which typical figure is not known yet instead of inventing one', () => {
    const unknown = plan({
      branches: [
        { branch: 'check', worst_case_usd: 1, typical_usd: 0.5, typical_minutes: 15 },
        { branch: 'layout', worst_case_usd: 2, typical_usd: null, typical_minutes: 25 },
        { branch: 'probes', worst_case_usd: 1.5, typical_usd: 0.75, typical_minutes: null },
      ],
    });
    render(<DryRunTable plan={unknown} />);
    const layout = screen.getByRole('region', { name: 'If it fails: find the smallest layout change' });
    expect(within(layout).getByText('Typical').nextElementSibling).toHaveTextContent('about 25 minutes, cost not known yet');
    const probes = screen.getByRole('region', { name: 'If it passes: probe' });
    expect(within(probes).getByText('Typical').nextElementSibling).toHaveTextContent('about US$0.75, time not known yet');
    expect(screen.getByText('Typical total if it fails').nextElementSibling).toHaveTextContent('about 40 minutes, cost not known yet');
    expect(screen.getByText('Typical total if it passes').nextElementSibling).toHaveTextContent('about US$1.25, time not known yet');
  });

  it('says "not known yet" when the server has no estimate at all', () => {
    const none = plan({
      branches: [
        { branch: 'check', worst_case_usd: 1, typical_usd: null },
        { branch: 'layout', worst_case_usd: 2, typical_usd: null },
        { branch: 'probes', worst_case_usd: 1.5, typical_usd: null },
      ],
    });
    render(<DryRunTable plan={none} />);
    expect(screen.getByText('Typical total if it passes').nextElementSibling).toHaveTextContent('not known yet');
  });

  it('keeps a plan with no branches as the flat table of Jobs', () => {
    render(
      <DryRunTable
        plan={plan({ branches: undefined, jobs: [{ name: 'audit', deadline_seconds: 3000, worst_case_usd: 1.46 }], worst_case_total_usd: 1.46 })}
      />,
    );
    expect(screen.queryByRole('region')).not.toBeInTheDocument();
    expect(screen.getByText('Total worst case')).toBeInTheDocument();
    expect(screen.queryByText(/typical/i)).not.toBeInTheDocument();
  });

  describe('the cap rule names the Job that would not fit', () => {
    const capText = () => (screen.getByText('Spend cap').nextElementSibling as HTMLElement).textContent ?? '';

    it('names the required probe Job, not "a reduction"', () => {
      // check 1 + probe-images-1 1.5 + probe-images-2 1.5 = 4 > 3.5; the layout path (1 + 2 = 3) fits.
      const jobs = [
        { name: 'check', deadline_seconds: 1800, worst_case_usd: 1, branch: 'check' as const },
        { name: 'reduce', deadline_seconds: 3000, worst_case_usd: 2, branch: 'layout' as const },
        { name: 'probe-images-1', deadline_seconds: 2400, worst_case_usd: 1.5, branch: 'probes' as const },
        { name: 'probe-images-2', deadline_seconds: 2400, worst_case_usd: 1.5, branch: 'probes' as const },
      ];
      render(<DryRunTable plan={plan({ jobs, cap_usd: 3.5, worst_case_total_usd: 4 })} />);
      expect(capText()).toContain('The first Job fits, but not all of them');
      expect(capText()).toContain('probe-images-2');
      expect(capText()).not.toContain('reduce');
      expect(capText()).not.toMatch(/a reduction/i);
    });

    it('names the layout Job and leaves out the optional continuations, which run only if needed', () => {
      const jobs = [
        { name: 'check', deadline_seconds: 1800, worst_case_usd: 1, branch: 'check' as const },
        { name: 'reduce', deadline_seconds: 3000, worst_case_usd: 2, branch: 'layout' as const },
        { name: 'reduce2', deadline_seconds: 3000, worst_case_usd: 2, branch: 'layout' as const, optional: true },
      ];
      render(<DryRunTable plan={plan({ jobs, cap_usd: 2.5, worst_case_total_usd: 3 })} />);
      expect(capText()).toContain('reduce (layout branch)');
      expect(capText()).not.toContain('reduce2');
    });

    it('names a Job of a flat plan by running total', () => {
      const jobs = [
        { name: 'screen', deadline_seconds: 1800, worst_case_usd: 1 },
        { name: 'reference', deadline_seconds: 1500, worst_case_usd: 1 },
        { name: 'reduce', deadline_seconds: 3000, worst_case_usd: 1 },
      ];
      render(<DryRunTable plan={plan({ branches: undefined, jobs, cap_usd: 2.5, worst_case_total_usd: 3 })} />);
      expect(capText()).toContain('reduce');
      expect(capText()).not.toContain('reference');
    });
  });

  it('puts the branch headings one level under the section heading', () => {
    render(<DryRunTable plan={plan()} headingLevel={4} />);
    expect(screen.getByRole('heading', { name: 'First: check the start untouched' }).tagName).toBe('H5');
  });
});
