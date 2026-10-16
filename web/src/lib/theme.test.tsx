import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeToggle } from '../components/ThemeToggle';
import { applyStoredTheme, readStoredTheme } from './theme';

function stubMatchMedia(dark: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: dark && query.includes('dark'),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  })) as unknown as typeof window.matchMedia;
}

beforeEach(() => {
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe('theme', () => {
  it('follows the system setting until a choice is made', () => {
    stubMatchMedia(true);
    render(<ThemeToggle />);
    expect(screen.getByRole('button', { name: /use light theme/i })).toBeInTheDocument();
    expect(document.documentElement.dataset.theme).toBeUndefined();
  });

  it('toggles, applies and stores the choice', async () => {
    stubMatchMedia(false);
    const user = userEvent.setup();
    render(<ThemeToggle />);
    await user.click(screen.getByRole('button', { name: /use dark theme/i }));
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(readStoredTheme()).toBe('dark');
    expect(screen.getByRole('button', { name: /use light theme/i })).toBeInTheDocument();
  });

  it('restores a saved choice', () => {
    window.localStorage.setItem('faultline-theme', 'dark');
    applyStoredTheme();
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('keeps working when storage throws', async () => {
    stubMatchMedia(false);
    const user = userEvent.setup();
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(readStoredTheme()).toBeNull();
    render(<ThemeToggle />);
    await act(async () => {
      await user.click(screen.getByRole('button', { name: /use dark theme/i }));
    });
    expect(document.documentElement.dataset.theme).toBe('dark');
    getItem.mockRestore();
    setItem.mockRestore();
  });
});
