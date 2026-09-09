import { useEffect, useRef, useState, type JSX } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import type {
  Analysis,
  ChartSelection,
  Coverage,
  MultiTimeframe,
  PaperState,
  Position,
  Quote,
  Signal,
  SystemStatus,
} from '../../../shared/types';
import { BacktestPanel } from './BacktestPanel';
import { ChatPanel } from './ChatPanel';
import { StrategyPanel } from './StrategyPanel';
import { CoveragePanel } from './CoveragePanel';
import { IndicatorsPanel } from './IndicatorsPanel';
import { NextSteps } from './NextSteps';
import { PaperPanel } from './PaperPanel';
import { SetupPanel } from './SetupPanel';
import { SignalCard } from './SignalCard';
import { PositionsTable } from './PositionsTable';
import { QuotesTable } from './QuotesTable';
import { VIEW_ICONS } from './ViewIcons';
import { onCommand, VIEW_EVENT } from '../commands';

interface Props {
  status: SystemStatus | undefined;
  quotes: Quote[] | undefined;
  positions: Position[] | undefined;
  coverage: Coverage | undefined;
  analysis: Analysis | undefined;
  signal: Signal | undefined;
  multi: MultiTimeframe | undefined;
  chart: ChartSelection | undefined;
  paper: PaperState | undefined;
  pending: boolean;
}

function RefreshIcon(): JSX.Element {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <path
        d="M13.6 2.2v3.1h-3.1"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ChevronIcon(): JSX.Element {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M4 6.5 8 10.5l4-4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

interface View {
  id: string;
  label: string;
  group: string;
  meta?: string | undefined;
  /** TanStack query keys this view renders, for the refresh control. */
  refreshKeys?: readonly string[];
  body: React.ReactNode;
}

const STORAGE_KEY = 'fortrader.view';

function storedView(fallback: string): string {
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? fallback;
  } catch {
    return fallback;
  }
}

/**
 * Right-hand panel: one view at a time, chosen from a menu.
 *
 * Every view stays mounted and only the active one is shown. That is
 * deliberate rather than lazy. The market queries live in App and keep
 * polling regardless of what is on screen, but Strategy and Ask hold
 * their own queries and their own state, and unmounting them would
 * restart a request and discard a conversation every time you looked at
 * something else. Switching views therefore reveals data that is
 * already there rather than starting to fetch it.
 *
 * The cost is that hidden views re-render when their data changes. At
 * eleven small views that is not measurable, and it buys instant
 * switching.
 */
export function AnalysisPanel({
  status,
  quotes,
  positions,
  coverage,
  analysis,
  signal,
  multi,
  chart,
  paper,
  pending,
}: Props): JSX.Element {
  const client = useQueryClient();

  const [activeId, setActiveId] = useState(() => storedView('signal'));
  const [busy, setBusy] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!menuOpen) return;

    const dismiss = (event: MouseEvent): void => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false);
    };

    const escape = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setMenuOpen(false);
    };

    document.addEventListener('mousedown', dismiss);
    document.addEventListener('keydown', escape);

    return () => {
      document.removeEventListener('mousedown', dismiss);
      document.removeEventListener('keydown', escape);
    };
  }, [menuOpen]);

  const chartMeta = status?.stale === false ? 'live' : undefined;

  const views: View[] = [
    {
      id: 'signal',
      label: 'Signal',
      group: 'Analysis',
      meta: signal ? `${signal.symbol} · ${signal.timeframe}` : undefined,
      refreshKeys: ['chart', 'signal', 'timeframes'],
      body: <SignalCard signal={signal} multi={multi} pending={pending} />,
    },
    {
      id: 'next',
      label: 'What To Do Next',
      group: 'Analysis',
      refreshKeys: ['chart', 'signal', 'coverage', 'paper'],
      body: (
        <NextSteps
          status={status}
          signal={signal}
          coverage={coverage}
          paper={paper}
          chart={chart}
        />
      ),
    },
    {
      id: 'indicators',
      label: 'Indicators',
      group: 'Analysis',
      meta: analysis
        ? `${analysis.symbol} ${analysis.timeframe} · ${analysis.bars_used} bars`
        : undefined,
      refreshKeys: ['chart', 'analysis'],
      body: <IndicatorsPanel analysis={analysis} pending={pending} />,
    },
    {
      id: 'ask',
      label: 'Ask About This',
      group: 'Analysis',
      meta: 'scoped',
      body: <ChatPanel chart={chart} />,
    },
    {
      id: 'paper',
      label: 'Paper Trading',
      group: 'Trading',
      meta: 'simulated',
      refreshKeys: ['paper'],
      body: <PaperPanel paper={paper} />,
    },
    {
      id: 'positions',
      label: 'Open Positions',
      group: 'Trading',
      refreshKeys: ['positions'],
      body: <PositionsTable positions={positions} pending={pending} />,
    },
    {
      // No refresh control: a backtest is hundreds of signal
      // evaluations, so it has its own explicit Run button instead.
      id: 'backtest',
      label: 'Backtest',
      group: 'Trading',
      body: <BacktestPanel chart={chart} />,
    },
    {
      id: 'strategy',
      label: 'Strategy',
      group: 'Engine',
      meta: 'engine',
      body: <StrategyPanel />,
    },
    {
      id: 'quotes',
      label: 'Watchlist',
      group: 'Market Data',
      meta: quotes ? `${quotes.length} instruments` : chartMeta,
      refreshKeys: ['quotes', 'status'],
      body: <QuotesTable quotes={quotes} pending={pending} />,
    },
    {
      id: 'candles',
      label: 'Candle History',
      group: 'Market Data',
      meta: coverage
        ? `${coverage.total_bars.toLocaleString()} bars`
        : undefined,
      refreshKeys: ['coverage'],
      body: <CoveragePanel coverage={coverage} />,
    },
    {
      id: 'setup',
      label: 'Connect Claude Code',
      group: 'Setup',
      body: <SetupPanel />,
    },
  ];

  const active = views.find((view) => view.id === activeId) ?? views[0];

  const select = (id: string): void => {
    setActiveId(id);
    setMenuOpen(false);

    try {
      window.localStorage.setItem(STORAGE_KEY, id);
    } catch {
      // The choice still applies; only the memory of it is lost.
    }
  };

  // Declared after `select` so it can call it. The palette asks; this
  // panel stays the owner of its own selection.
  useEffect(() => onCommand<string>(VIEW_EVENT, (id) => select(id)), []);

  const refresh = async (): Promise<void> => {
    const keys = active?.refreshKeys;

    if (!keys?.length || busy) return;

    setBusy(true);

    try {
      // refetch rather than invalidate, so the spinner reflects the
      // request actually completing rather than merely being queued.
      await Promise.all(
        keys.map((key) => client.refetchQueries({ queryKey: [key] })),
      );
    } finally {
      setBusy(false);
    }
  };

  const groups = [...new Set(views.map((view) => view.group))];

  return (
    <aside className="analysis-panel">

      <header className="panel-head" ref={menuRef}>
        <button
          type="button"
          className="view-picker"
          onClick={() => setMenuOpen((open) => !open)}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
        >
          <span className="view-picker__icon">
            {active ? VIEW_ICONS[active.id] : null}
          </span>
          <span className="view-picker__label">{active?.label}</span>
          <ChevronIcon />
        </button>

        <div className="panel-head__actions">
          {active?.meta && (
            <span className="panel-section__meta">{active.meta}</span>
          )}

          {active?.refreshKeys?.length ? (
            <button
              type="button"
              className={`icon-button${busy ? ' is-busy' : ''}`}
              onClick={() => void refresh()}
              disabled={busy}
              title={`Refresh ${active.label.toLowerCase()}`}
              aria-label={`Refresh ${active.label}`}
            >
              <RefreshIcon />
            </button>
          ) : null}
        </div>

        {menuOpen && (
          <div className="view-menu" role="menu">
            {groups.map((group) => (
              <div key={group} className="view-menu__group">
                <span className="view-menu__heading">{group}</span>
                {views
                  .filter((view) => view.group === group)
                  .map((view) => (
                    <button
                      key={view.id}
                      type="button"
                      role="menuitemradio"
                      aria-checked={view.id === activeId}
                      className={`view-menu__item${
                        view.id === activeId ? ' view-menu__item--on' : ''
                      }`}
                      onClick={() => select(view.id)}
                    >
                      <span className="view-menu__icon">
                        {VIEW_ICONS[view.id]}
                      </span>
                      {view.label}
                    </button>
                  ))}
              </div>
            ))}
          </div>
        )}
      </header>

      {/* Every view is rendered; only one is shown. Hiding rather than
          unmounting is what keeps the data and the state already there
          when you come back to it. */}
      <div className="panel-views">
        {views.map((view) => (
          <div
            key={view.id}
            className="view"
            hidden={view.id !== activeId}
            role="tabpanel"
            aria-label={view.label}
          >
            {view.body}
          </div>
        ))}
      </div>

      <div className="safety-note">
        <strong>Research only.</strong> This application reads market and
        account data. It cannot place, modify or close trades, and no
        execution capability exists in this build.
      </div>
    </aside>
  );
}
