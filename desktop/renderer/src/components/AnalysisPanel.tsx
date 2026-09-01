import { useState, type JSX } from 'react';
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
import { CoveragePanel } from './CoveragePanel';
import { IndicatorsPanel } from './IndicatorsPanel';
import { NextSteps } from './NextSteps';
import { PaperPanel } from './PaperPanel';
import { SetupPanel } from './SetupPanel';
import { SignalCard } from './SignalCard';
import { PositionsTable } from './PositionsTable';
import { QuotesTable } from './QuotesTable';

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
      <path d="M13.6 2.2v3.1h-3.1" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/**
 * A panel section with an optional manual refresh.
 *
 * Every section already polls, but the intervals differ (2–15s) and a
 * reading can be several seconds stale when you are actually looking at
 * it. `refreshKeys` names the TanStack query keys this section renders;
 * the button refetches exactly those and reports when it is done.
 */
function Section({
  title,
  meta,
  refreshKeys,
  children,
}: {
  title: string;
  meta?: string;
  refreshKeys?: readonly string[];
  children: React.ReactNode;
}): JSX.Element {
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    if (!refreshKeys?.length || busy) return;

    setBusy(true);

    try {
      // refetch rather than invalidate, so the spinner reflects the
      // request actually completing rather than merely being queued.
      await Promise.all(
        refreshKeys.map((key) => client.refetchQueries({ queryKey: [key] })),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel-section">
      <div className="panel-section__head">
        <h3>{title}</h3>

        <div className="panel-section__actions">
          {meta && <span className="panel-section__meta">{meta}</span>}

          {refreshKeys?.length ? (
            <button
              type="button"
              className={`icon-button${busy ? ' is-busy' : ''}`}
              onClick={() => void refresh()}
              disabled={busy}
              title={`Refresh ${title.toLowerCase()}`}
              aria-label={`Refresh ${title}`}
            >
              <RefreshIcon />
            </button>
          ) : null}
        </div>
      </div>
      {children}
    </section>
  );
}

/**
 * Right-hand panel.
 *
 * Phase C fills the market-data sections from our own extraction. The
 * scoring card stays empty until Phase F — placeholder numbers would be
 * indistinguishable from wrong ones.
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
  const chartMeta = status?.stale === false ? 'live' : undefined;

  return (
    <aside className="analysis-panel">
      {/* The signal is the headline output, so it leads. Supporting
          measurements and raw market data sit beneath it. */}
      <h2 className="panel-title">AI Market Analysis</h2>

      {/* `chart` is refreshed alongside the readings that depend on it,
          so switching chart in Fortrade and hitting refresh picks up the
          new instrument rather than re-fetching the old one. */}
      <Section
        title="Signal"
        meta={signal ? `${signal.symbol} · ${signal.timeframe}` : undefined}
        refreshKeys={['chart', 'signal', 'timeframes']}
      >
        <SignalCard signal={signal} multi={multi} pending={pending} />
      </Section>

      <Section
        title="What To Do Next"
        refreshKeys={['chart', 'signal', 'coverage', 'paper']}
      >
        <NextSteps
          status={status}
          signal={signal}
          coverage={coverage}
          paper={paper}
          chart={chart}
        />
      </Section>

      <Section
        title={
          analysis
            ? `Indicators · ${analysis.symbol} ${analysis.timeframe}`
            : 'Indicators'
        }
        meta={analysis ? `${analysis.bars_used} bars` : undefined}
        refreshKeys={['chart', 'analysis']}
      >
        <IndicatorsPanel analysis={analysis} pending={pending} />
      </Section>

      <Section title="Ask About This" meta="scoped">
        <ChatPanel chart={chart} />
      </Section>

      <Section title="Paper Trading" meta="simulated" refreshKeys={['paper']}>
        <PaperPanel paper={paper} />
      </Section>

      {/* No refresh control: a backtest is hundreds of signal
          evaluations, so it has its own explicit Run button instead. */}
      <Section title="Backtest">
        <BacktestPanel chart={chart} />
      </Section>

      <h2 className="panel-title">Market Data</h2>

      <Section
        title="Watchlist"
        meta={quotes ? `${quotes.length} instruments` : chartMeta}
        refreshKeys={['quotes', 'status']}
      >
        <QuotesTable quotes={quotes} pending={pending} />
      </Section>

      <Section title="Open Positions" refreshKeys={['positions']}>
        <PositionsTable positions={positions} pending={pending} />
      </Section>

      <Section
        title="Candle History"
        meta={coverage ? `${coverage.total_bars.toLocaleString()} bars` : undefined}
        refreshKeys={['coverage']}
      >
        <CoveragePanel coverage={coverage} />
      </Section>

      <h2 className="panel-title">Setup</h2>

      <Section title="Connect Claude Code">
        <SetupPanel />
      </Section>

      <div className="safety-note">
        <strong>Research only.</strong> This application reads market and
        account data. It cannot place, modify or close trades, and no
        execution capability exists in this build.
      </div>
    </aside>
  );
}
