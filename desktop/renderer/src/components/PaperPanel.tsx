import type { JSX } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import type { PaperState, PaperTrade } from '../../../shared/types';
import { backend } from '../services/backend';

interface Props {
  paper: PaperState | undefined;
}

function money(value: number): string {
  return `${value < 0 ? '-' : ''}${Math.abs(value).toFixed(2)}`;
}

function rTone(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'muted';

  return value > 0 ? 'is-positive' : value < 0 ? 'is-negative' : '';
}

function OpenRow({ trade }: { trade: PaperTrade }): JSX.Element {
  const client = useQueryClient();

  const close = useMutation({
    mutationFn: () => backend.closePaper(trade.id),
    onSuccess: () => client.invalidateQueries({ queryKey: ['paper'] }),
  });

  return (
    <tr>
      <td className="sym">{trade.symbol}</td>
      <td className={trade.direction === 'LONG' ? 'is-positive' : 'is-negative'}>
        {trade.direction}
      </td>
      <td className="num">{trade.entry.toFixed(5)}</td>
      <td className={`num ${rTone(trade.unrealised_r)}`}>
        {trade.unrealised_r === null
          ? '—'
          : `${trade.unrealised_r > 0 ? '+' : ''}${trade.unrealised_r.toFixed(2)}R`}
      </td>
      <td className="num">
        <button
          type="button"
          className="button button--small"
          onClick={() => close.mutate()}
          disabled={close.isPending}
        >
          {close.isPending ? '…' : 'Close'}
        </button>
      </td>
    </tr>
  );
}

/**
 * Simulated positions.
 *
 * Nothing here reaches Fortrade. The wording is deliberately explicit so
 * these can never be mistaken for executed trades.
 */
export function PaperPanel({ paper }: Props): JSX.Element {
  if (!paper) {
    return <div className="empty-note">Loading paper account…</div>;
  }

  const { summary, metrics } = paper;

  const netPnl = summary.realised_pnl + summary.unrealised_pnl;

  return (
    <div className="paper">
      <div className="paper__head">
        <div>
          <span className="metric__label">Simulated equity</span>
          <span className="paper__equity">{money(summary.equity)}</span>
        </div>
        <div className="paper__pl">
          <span className="metric__label">Net P&amp;L</span>
          <span className={rTone(netPnl)}>{money(netPnl)}</span>
        </div>
      </div>

      <div className="metric-grid">
        <div className="metric">
          <span className="metric__label">Open</span>
          <span className="metric__value">{summary.open_positions}</span>
        </div>
        <div className="metric">
          <span className="metric__label">Closed</span>
          <span className="metric__value">{summary.closed_trades}</span>
        </div>
        <div className="metric">
          <span className="metric__label">Total R</span>
          <span className={`metric__value ${rTone(summary.total_r)}`}>
            {summary.total_r > 0 ? '+' : ''}
            {summary.total_r.toFixed(2)}R
          </span>
        </div>
        <div className="metric">
          <span className="metric__label">Auto-entry</span>
          <span className="metric__value">
            {summary.auto_open ? 'on' : 'off'}
          </span>
        </div>
      </div>

      {paper.open.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th className="num">Entry</th>
                <th className="num">Open R</th>
                <th className="num" />
              </tr>
            </thead>
            <tbody>
              {paper.open.map((trade) => (
                <OpenRow key={trade.id} trade={trade} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {paper.open.length === 0 && (
        <div className="empty-note">
          No open simulated positions. One opens automatically when a signal
          clears the score threshold.
        </div>
      )}

      {metrics.trades > 0 && !metrics.sufficient && (
        <div className="warning-note">
          {metrics.trades} of {metrics.minimum_trades} trades needed before a
          win rate means anything. Building the record takes time — that is
          the point of paper trading.
        </div>
      )}

      {metrics.sufficient && (
        <div className="metric-grid">
          <div className="metric">
            <span className="metric__label">Win rate</span>
            <span className="metric__value">
              {metrics.win_rate?.toFixed(1)}%
            </span>
          </div>
          <div className="metric">
            <span className="metric__label">Expectancy</span>
            <span className={`metric__value ${rTone(metrics.expectancy_r)}`}>
              {metrics.expectancy_r?.toFixed(2)}R
            </span>
          </div>
        </div>
      )}

      <p className="score-caveat">
        Simulated positions only. Nothing here is placed with Fortrade and
        the live account is unaffected.
      </p>
    </div>
  );
}
