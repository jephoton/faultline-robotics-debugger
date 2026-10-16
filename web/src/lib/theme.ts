import { useCallback, useEffect, useState } from 'react';

export type Theme = 'light' | 'dark';
const KEY = 'faultline-theme';

// Browser storage can be missing or throw (private windows, blocked site data): never rely on it.
export function readStoredTheme(): Theme | null {
  try {
    const value = window.localStorage.getItem(KEY);
    return value === 'light' || value === 'dark' ? value : null;
  } catch {
    return null;
  }
}

function writeStoredTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(KEY, theme);
  } catch {
    /* the choice then lasts for this page view only */
  }
}

export function systemTheme(): Theme {
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  } catch {
    return 'light';
  }
}

/** Apply the saved choice, if any; with none, CSS follows prefers-color-scheme. */
export function applyStoredTheme(): void {
  const stored = readStoredTheme();
  if (stored) document.documentElement.dataset.theme = stored;
  else delete document.documentElement.dataset.theme;
}

export function useTheme(): { theme: Theme; toggle: () => void } {
  const [theme, setTheme] = useState<Theme>(() => readStoredTheme() ?? systemTheme());

  useEffect(() => {
    if (readStoredTheme()) return undefined;
    // Follow the system setting until the person chooses.
    let query: MediaQueryList | null = null;
    try {
      query = window.matchMedia('(prefers-color-scheme: dark)');
    } catch {
      return undefined;
    }
    const onChange = () => {
      if (!readStoredTheme()) setTheme(query?.matches ? 'dark' : 'light');
    };
    query.addEventListener?.('change', onChange);
    return () => query?.removeEventListener?.('change', onChange);
  }, []);

  const toggle = useCallback(() => {
    setTheme((current) => {
      const next: Theme = current === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = next;
      writeStoredTheme(next);
      return next;
    });
  }, []);

  return { theme, toggle };
}
