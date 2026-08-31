import type { JSX } from 'react';

import type { Position } from '../../../shared/types';

interface Props {
  positions: Position[] | undefined;
  pending: boolean;
}

export function PositionsTable({ positions, pending }: Props): JSX.Element {
  if (pending && !positions) {
    return <div className="empty-note">Waiting for position data…</div>;
  }

  if (!positions || positions.length === 0) {
    // A flat account is a real observation, not missing data.
    return <div className="empty-note">No open positions.</div>;
  }

  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Side</th>
            <th className="num">Amount</th>
            <th className="num">Open</th>
            <th className="num">P&L</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((position, index) => (
            <tr key={`${position.symbol}-${index}`}>
              <td className="sym">{position.symbol}</td>
              <td
                className={
                  position.direction === 'BUY' ? 'is-positive' : 'is-negative'
                }
              >
                {position.direction}
              </td>
              <td className="num">{position.amount.toLocaleString('en-GB')}</td>
              <td className="num">{position.open_rate}</td>
              <td
                className={`num ${
                  (position.pnl ?? 0) > 0
                    ? 'is-positive'
                    : (position.pnl ?? 0) < 0
                      ? 'is-negative'
                      : ''
                }`}
              >
                {position.pnl?.toFixed(2) ?? '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
