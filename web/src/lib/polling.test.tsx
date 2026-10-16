import { act, render, screen } from '@testing-library/react';
import { usePoll } from './polling';

function setHidden(hidden: boolean) {
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden });
  document.dispatchEvent(new Event('visibilitychange'));
}

function Probe({ fn, until }: { fn: () => Promise<number>; until?: (n: number) => boolean }) {
  const { data } = usePoll(fn, 5000, { until });
  return <p>value: {data ?? 'none'}</p>;
}

beforeEach(() => {
  vi.useFakeTimers();
  setHidden(false);
});
afterEach(() => {
  vi.useRealTimers();
  setHidden(false);
});

describe('usePoll', () => {
  it('fetches at once and then on the interval', async () => {
    let n = 0;
    const fn = vi.fn(async () => ++n);
    render(<Probe fn={fn} />);
    await act(async () => {});
    expect(fn).toHaveBeenCalledTimes(1);
    expect(screen.getByText('value: 1')).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fn).toHaveBeenCalledTimes(2);
    expect(screen.getByText('value: 2')).toBeInTheDocument();
  });

  it('never overlaps requests: the next one is scheduled only after the previous settles', async () => {
    const resolvers: ((n: number) => void)[] = [];
    const fn = vi.fn(() => new Promise<number>((resolve) => resolvers.push(resolve)));
    render(<Probe fn={fn} />);
    await act(async () => {});
    expect(fn).toHaveBeenCalledTimes(1);
    // A slow request: several intervals pass without a second call.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(fn).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolvers[0]?.(7);
    });
    expect(screen.getByText('value: 7')).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it('pauses while the tab is hidden and resumes immediately when it is shown', async () => {
    let n = 0;
    const fn = vi.fn(async () => ++n);
    render(<Probe fn={fn} />);
    await act(async () => {});
    expect(fn).toHaveBeenCalledTimes(1);
    act(() => setHidden(true));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(fn).toHaveBeenCalledTimes(1);
    await act(async () => {
      setHidden(false);
    });
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it('stops once the data satisfies `until`', async () => {
    let n = 0;
    const fn = vi.fn(async () => ++n);
    render(<Probe fn={fn} until={(value) => value >= 2} />);
    await act(async () => {});
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fn).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it('keeps polling after an error', async () => {
    let calls = 0;
    const fn = vi.fn(async () => {
      calls += 1;
      if (calls === 1) throw new Error('temporary');
      return calls;
    });
    render(<Probe fn={fn} />);
    await act(async () => {});
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(screen.getByText('value: 2')).toBeInTheDocument();
  });
});
