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

  it('puts the branch headings one level under the section heading', () => {
    render(<DryRunTable plan={plan()} headingLevel={4} />);
    expect(screen.getByRole('heading', { name: 'First: check the start untouched' }).tagName).toBe('H5');
  });
});
