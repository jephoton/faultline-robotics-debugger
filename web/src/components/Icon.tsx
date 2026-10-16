import type { ReactNode } from 'react';

// Small outline icon set (24px grid, stroke follows currentColor). Always decorative:
// the meaning is carried by an adjacent word.
const PATHS: Record<string, ReactNode> = {
  alarm: (
    <>
      <path d="M8.2 3h7.6L21 8.2v7.6L15.8 21H8.2L3 15.8V8.2z" />
      <path d="M12 7.5v5.5M12 16.2v.3" />
    </>
  ),
  attention: (
    <>
      <path d="M12 3.5 21.5 20h-19z" />
      <path d="M12 10v4.5M12 17.2v.3" />
    </>
  ),
  check: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m7.8 12.4 2.9 2.9 5.6-6" />
    </>
  ),
  dash: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M8 12h8" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5.5M12 7.7v.3" />
    </>
  ),
  tick: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  minus: <path d="M6 12h12" />,
  stop: <rect x="5" y="5" width="14" height="14" rx="1.5" />,
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5.2l3.4 2" />
    </>
  ),
  play: <path d="M8 5.5v13l11-6.5z" />,
  pause: <path d="M8 5v14M16 5v14" />,
  restart: (
    <>
      <path d="M4 12a8 8 0 1 0 2.6-5.9" />
      <path d="M4 4v4.5h4.5" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8" />
    </>
  ),
  moon: <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z" />,
  setup: (
    <>
      <circle cx="12" cy="12" r="3.2" />
      <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" />
    </>
  ),
  guide: (
    <>
      <path d="M5 4.5h10.5a3 3 0 0 1 3 3V20H8a3 3 0 0 1-3-3z" />
      <path d="M5 17a3 3 0 0 1 3-3h10.5" />
    </>
  ),
  evidence: (
    <>
      <rect x="3.5" y="5" width="17" height="14" rx="1.5" />
      <path d="m10 9.5 5 2.5-5 2.5z" />
    </>
  ),
  chevron: <path d="m7 10 5 5 5-5" />,
  external: (
    <>
      <path d="M14 4h6v6M20 4l-9 9" />
      <path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
    </>
  ),
  replay: (
    <>
      <path d="M4 12a8 8 0 0 1 14-5.3M20 12a8 8 0 0 1-14 5.3" />
      <path d="M18.5 3v4h-4M5.5 21v-4h4" />
    </>
  ),
  upload: <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M4 16v3.5h16V16" />,
  file: (
    <>
      <path d="M6 3h8l5 5v13H6z" />
      <path d="M14 3v5h5" />
    </>
  ),
  trace: <path d="M3 17h5l3-9 4 13 3-8h3" />,
};

export type IconName = keyof typeof PATHS;

export function Icon({ name, className }: { name: IconName; className?: string }) {
  return (
    <svg
      className={className ? `icon ${className}` : 'icon'}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}

/** The product mark: a fault line trace. */
export function Mark({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <rect width="32" height="32" rx="4" fill="#0e1a12" />
      <path
        d="M3 18h7l3-9 5 15 3-9h8"
        fill="none"
        stroke="#8ef0a8"
        strokeWidth="2.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
