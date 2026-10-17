import { useCallback, useEffect, useRef, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import type { LibraryItem, RunSummary, Session } from '../api/types';
import { Icon, Mark } from './Icon';
import { Sidebar, type LoadState } from './Sidebar';

interface Props {
  session: Session;
  items: LibraryItem[];
  runs: RunSummary[];
  libraryState: LoadState;
}

/** The workspace: a persistent sidebar (a drawer on narrow screens) and the main area. */
export function Shell({ session, items, runs, libraryState }: Props) {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const menuButton = useRef<HTMLButtonElement>(null);
  const sidebar = useRef<HTMLElement>(null);
  const main = useRef<HTMLElement>(null);
  const firstRender = useRef(true);

  const close = useCallback(() => {
    setOpen(false);
    menuButton.current?.focus();
  }, []);

  // After a route change, move focus to the main area so keyboard and screen-reader users
  // start at the new page, and close the drawer.
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    setOpen(false);
    main.current?.focus({ preventScroll: false });
  }, [location.pathname]);

  useEffect(() => {
    if (!open) return undefined;
    const link = sidebar.current?.querySelector<HTMLElement>('a, button');
    link?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, close]);

  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <button
          type="button"
          className="btn btn--secondary btn--small"
          ref={menuButton}
          aria-expanded={open}
          aria-controls="sidebar"
          onClick={() => setOpen((value) => !value)}
        >
          <Icon name={open ? 'close' : 'menu'} />
          Menu
        </button>
        <span className="topbar__title">
          <Mark size={22} /> Faultline
        </span>
      </header>
      <div className="scrim" data-open={open} onClick={close} aria-hidden="true" />
      <aside className="sidebar" id="sidebar" ref={sidebar} data-open={open} aria-label="Workspace">
        <Sidebar session={session} items={items} runs={runs} libraryState={libraryState} onNavigate={() => setOpen(false)} />
      </aside>
      <main className="main" id="main" tabIndex={-1} ref={main}>
        <div className="main__inner">
          {location.pathname !== '/' && (
            <button
              type="button"
              className="btn btn--secondary btn--small main__back"
              onClick={() => navigate('/')}
            >
              <span aria-hidden="true">←</span> Back
            </button>
          )}
          <Outlet />
        </div>
      </main>
    </div>
  );
}
