import type { JSX } from 'react';
import { useMutation } from '@tanstack/react-query';

import type { BacktestResult, ChartSelection } from '../../../shared/types';
import { backend } from '../services/backend';

interface Props {
  chart: ChartSelection | undefined;
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}): JSX.Element {
  return (
    <div className="metric">
      <span className="metric__label">{label}</span>
      <span className={`metric__value${tone ? ` ${tone}` : ''}`}>{value}</span>
    </div>
  );
}

function Results({ result }: { result: BacktestResult }): JSX.Element {
  const m = result.metrics;

  if (!result.ran) {
    return (
      <div className="warning-note">
        {result.warnings[0] ?? 'Not enough history to run a backtest.'}
      </div>
    );
  }

  return (
    <>
      <div className="metric-grid">
        <Metric label="Trades" value={String(m.trades)} />
        <Metric label="Bars tested" value={String(result.bars_tested)} />
        <Metric label="Wins" value={String(m.wins)} tone="is-positive" />
        <Metric label="Losses" value={String(m.losses)} tone="is-negative" />
      </div>

      {m.sufficient ? (
        <div className="metric-grid">
          <Metric label="Win rate" value={`${m.win_rate?.toFixed(1)}%`} />
          <Metric
            label="Expectancy"
            value={`${(m.expectancy_r ?? 0) > 0 ? '+' : ''}${m.expectancy_r?.toFixed(2)}R`}
            tone={(m.expectancy_r ?? 0) > 0 ? 'is-positive' : 'is-negative'}
          />
          <Metric label="Avg win" value={`+${m.average_win_r?.toFixed(2)}R`} />
          <Metric label="Avg loss" value={`${m.average_loss_r?.toFixed(2)}R`} />
          <Metric
            label="Profit factor"
            value={m.profit_factor?.toFixed(2) ?? '—'}
          />
          <Metric
            label="Max drawdown"
            value={`${m.max_drawdown_pct?.toFixed(1)}%`}
          />
          <Metric
            label="Max consec. L"
            value={String(m.max_consecutive_losses)}
          />
          <Metric
            label="Total"
            value={`${m.total_r > 0 ? '+' : ''}${m.total_r.toFixed(2)}R`}
          />
        </div>
      ) : (
        <div className="warning-note">
          Statistics withheld: {m.trades} trades, {m.minimum_trades} needed
          before a win rate or expectancy means anything. Counts above are
          the raw facts.
        </div>
      )}

      {result.warnings.length > 0 && (
        <ul className="warnings">
          {result.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
    </>
  );
}

/**
 * A backtest costs hundreds of signal evaluations, so it runs only when
 * asked — never on a polling interval.
 */
export function BacktestPanel({ chart }: Props): JSX.Element {
  const run = useMutation({
    mutationFn: () => backend.backtest(chart!.symbol, chart!.timeframe),
  });

  if (!chart) {
    return <div className="empty-note">Waiting for a chart selection.</div>;
  }

  return (
    <div className="backtest">
      <div className="backtest__head">
        <span className="muted">
          {chart.symbol} · {chart.timeframe}
        </span>
        <button
          type="button"
          className="button"
          onClick={() => run.mutate()}
          disabled={run.isPending}
        >
          {run.isPending ? 'Running…' : 'Run backtest'}
        </button>
      </div>

      {run.isPending && (
        <div className="empty-note">
          Walking the history forward — this takes a few seconds.
        </div>
      )}

      {run.isError && (
        <div className="warning-note">
          Backtest failed: {String(run.error)}
        </div>
      )}

      {run.data && !run.isPending && <Results result={run.data} />}

      {!run.data && !run.isPending && !run.isError && (
        <div className="empty-note">
          Simulates the signal engine over stored history. Results are a
          small-sample simulation, not evidence of an edge.
        </div>
      )}
    </div>
  );
}
