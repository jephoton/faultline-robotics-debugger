import { screen, within } from '@testing-library/react';
import { RUN_IDS } from '../mocks/fixtures';
import { renderApp } from '../test/utils';

async function openRun(run: string) {
  const view = renderApp(`/run/${run}`, { activeDemo: false });
  await screen.findByRole('article');
  return view;
}

describe('the route of a diagnosis run', () => {
  it('says the start passed and the probes are running, in green with a tick', async () => {
    await openRun(RUN_IDS.probing);
    const note = screen.getByTestId('run-route');
    expect(note).toHaveTextContent('The start passed: probing');
    expect(note).toHaveClass('notice--pass');
    expect(within(screen.getByRole('region', { name: 'Readout' })).getByText('FL-A-····')).toBeInTheDocument();
    // The step labels come from the server.
    const steps = screen.getByRole('list', { name: 'Steps of this run' });
    expect(within(steps).getByText('Probe image disturbances (1 of 2)')).toBeInTheDocument();
    expect(within(steps).getByText('Screen rewordings')).toBeInTheDocument();
  });

  it('says the start failed untouched and the layout is being diagnosed, in red', async () => {
    await openRun(RUN_IDS.layoutRoute);
    const note = screen.getByTestId('run-route');
    expect(note).toHaveTextContent('The start failed untouched: finding the smallest layout change');
    expect(note).toHaveClass('notice--alarm');
    expect(within(screen.getByRole('region', { name: 'Readout' })).getByText('FL-S-····')).toBeInTheDocument();
  });

  it('says a flaky start skipped the rewordings, in amber', async () => {
    await openRun(RUN_IDS.flaky);
    const note = screen.getByTestId('run-route');
    expect(note).toHaveTextContent('The start is flaky untouched');
    expect(note).toHaveClass('notice--attention');
    expect(within(screen.getByRole('list', { name: 'Steps of this run' })).getByText('Screen rewordings')).toBeInTheDocument();
  });

  it('says "Passes untouched" for a start that never failed', async () => {
    await openRun(RUN_IDS.passes);
    expect(screen.getByTestId('run-route')).toHaveTextContent('Passes untouched');
    expect(screen.getByTestId('run-route')).toHaveClass('notice--pass');
  });

  it('shows no route for a run that is not a diagnosis, or before the check has decided', async () => {
    await openRun(RUN_IDS.running);
    expect(screen.queryByTestId('run-route')).not.toBeInTheDocument();
  });
});
