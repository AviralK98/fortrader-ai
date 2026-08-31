import type { JSX } from 'react';

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
import { CoveragePanel } from './CoveragePanel';
import { IndicatorsPanel } from './IndicatorsPanel';
import { PaperPanel } from './PaperPanel';
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

function Section({
  title,
  meta,
  children,
}: {
  title: string;
  meta?: string;
  children: React.ReactNode;
}): JSX.Element {
  return (
    <section className="panel-section">
      <div className="panel-section__head">
        <h3>{title}</h3>
        {meta && <span className="panel-section__meta">{meta}</span>}
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

      <Section
        title="Signal"
        meta={signal ? `${signal.symbol} · ${signal.timeframe}` : undefined}
      >
        <SignalCard signal={signal} multi={multi} pending={pending} />
      </Section>

      <Section
        title={
          analysis
            ? `Indicators · ${analysis.symbol} ${analysis.timeframe}`
            : 'Indicators'
        }
        meta={analysis ? `${analysis.bars_used} bars` : undefined}
      >
        <IndicatorsPanel analysis={analysis} pending={pending} />
      </Section>

      <Section title="Paper Trading" meta="simulated">
        <PaperPanel paper={paper} />
      </Section>

      <Section title="Backtest">
        <BacktestPanel chart={chart} />
      </Section>

      <h2 className="panel-title">Market Data</h2>

      <Section
        title="Watchlist"
        meta={quotes ? `${quotes.length} instruments` : chartMeta}
      >
        <QuotesTable quotes={quotes} pending={pending} />
      </Section>

      <Section title="Open Positions">
        <PositionsTable positions={positions} pending={pending} />
      </Section>

      <Section
        title="Candle History"
        meta={coverage ? `${coverage.total_bars.toLocaleString()} bars` : undefined}
      >
        <CoveragePanel coverage={coverage} />
      </Section>

      <div className="safety-note">
        <strong>Research only.</strong> This application reads market and
        account data. It cannot place, modify or close trades, and no
        execution capability exists in this build.
      </div>
    </aside>
  );
}
