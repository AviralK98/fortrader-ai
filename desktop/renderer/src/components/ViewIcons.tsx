import type { JSX } from 'react';

/**
 * Line icons for the view menu.
 *
 * One geometric idea each, drawn on the same 16px grid at the same
 * stroke weight, in currentColor. A menu of eleven text rows is read
 * word by word; a consistent set of shapes is read at a glance, which is
 * the whole point of putting them there.
 */

function Svg({ children }: { children: React.ReactNode }): JSX.Element {
  return (
    <svg
      viewBox="0 0 16 16"
      aria-hidden="true"
      focusable="false"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  );
}

/** Keyed by view id; the menu falls back to a dot for anything unlisted. */
export const VIEW_ICONS: Record<string, JSX.Element> = {
  // A reading being taken: a pulse.
  signal: (
    <Svg>
      <path d="M1.5 8.5h3l2-5 2.5 9 2-4h3.5" />
    </Svg>
  ),

  // A direction to head in.
  next: (
    <Svg>
      <path d="M2.5 8h10" />
      <path d="M9 4.5 12.5 8 9 11.5" />
    </Svg>
  ),

  // Measurements, at different magnitudes.
  indicators: (
    <Svg>
      <path d="M3 13V7" />
      <path d="M8 13V3" />
      <path d="M13 13v-4" />
    </Svg>
  ),

  // A question.
  ask: (
    <Svg>
      <path d="M13.5 9.5a2 2 0 0 1-2 2H6l-3 2.5v-2.5H4.5a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2Z" />
    </Svg>
  ),

  // A copy of the real thing, offset behind it.
  paper: (
    <Svg>
      <rect x="2.5" y="2.5" width="8" height="8" rx="1.5" />
      <path d="M5.5 13.5h6a2 2 0 0 0 2-2v-6" />
    </Svg>
  ),

  // Rows that are currently open.
  positions: (
    <Svg>
      <path d="M2.5 4.5h11" />
      <path d="M2.5 8h11" />
      <path d="M2.5 11.5h7" />
    </Svg>
  ),

  // Running the clock backwards.
  backtest: (
    <Svg>
      <path d="M2.5 8a5.5 5.5 0 1 0 1.7-4" />
      <path d="M2.2 2.5v3.2h3.2" />
      <path d="M8 5.5V8l2 1.3" />
    </Svg>
  ),

  // Parameters being set.
  strategy: (
    <Svg>
      <path d="M3 3v10M8 3v10M13 3v10" />
      <circle cx="3" cy="6" r="1.6" />
      <circle cx="8" cy="10.5" r="1.6" />
      <circle cx="13" cy="5" r="1.6" />
    </Svg>
  ),

  // Things being watched.
  quotes: (
    <Svg>
      <path d="M1.5 8s2.4-4 6.5-4 6.5 4 6.5 4-2.4 4-6.5 4-6.5-4-6.5-4Z" />
      <circle cx="8" cy="8" r="1.8" />
    </Svg>
  ),

  // Bars of price history.
  candles: (
    <Svg>
      <path d="M5 2.5v11M11 2.5v11" />
      <rect x="3.2" y="5" width="3.6" height="5" rx="1" />
      <rect x="9.2" y="4" width="3.6" height="6.5" rx="1" />
    </Svg>
  ),

  // A connection being made.
  setup: (
    <Svg>
      <path d="M6.5 9.5 4 12a2.5 2.5 0 0 1-3.5-3.5L3 6" />
      <path d="M9.5 6.5 12 4a2.5 2.5 0 0 1 3.5 3.5L13 10" />
      <path d="M6 10 10 6" />
    </Svg>
  ),
};
