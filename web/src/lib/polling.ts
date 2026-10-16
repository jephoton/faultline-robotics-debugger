import { useCallback, useEffect, useRef, useState } from 'react';

interface PollOptions<T> {
  enabled?: boolean;
  /** Re-start polling when this changes (for example the run being watched). */
  key?: unknown;
  /** Stop polling once this returns true for the latest data. */
  until?: (data: T) => boolean;
}

export interface PollResult<T> {
  data: T | null;
  error: Error | null;
  /** Fetch now (a no-op while a request is in flight). */
  refresh: () => void;
}

/**
 * Poll an async function on a timer. Requests never overlap (the next one is scheduled only after the
 * previous one settles) and polling pauses while the tab is hidden, resuming at once when it is shown again.
 */
export function usePoll<T>(fn: () => Promise<T>, intervalMs: number, options: PollOptions<T> = {}): PollResult<T> {
  const { enabled = true, key, until } = options;
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const fnRef = useRef(fn);
  const untilRef = useRef(until);
  const tickRef = useRef<() => void>(() => undefined);
  fnRef.current = fn;
  untilRef.current = until;

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    let inflight = false;
    let finished = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const tick = async () => {
      if (cancelled || inflight || finished) return;
      if (document.hidden) return; // the visibilitychange handler resumes us
      inflight = true;
      try {
        const next = await fnRef.current();
        if (cancelled) return;
        setData(next);
        setError(null);
        if (untilRef.current?.(next)) finished = true;
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught : new Error(String(caught)));
      } finally {
        inflight = false;
      }
      if (!cancelled && !finished && !document.hidden) {
        timer = setTimeout(() => void tick(), intervalMs);
      }
    };

    const onVisibility = () => {
      if (!document.hidden) {
        clearTimeout(timer);
        void tick();
      }
    };

    tickRef.current = () => {
      clearTimeout(timer);
      void tick();
    };
    document.addEventListener('visibilitychange', onVisibility);
    void tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [enabled, intervalMs, key]);

  const refresh = useCallback(() => tickRef.current(), []);
  return { data, error, refresh };
}
