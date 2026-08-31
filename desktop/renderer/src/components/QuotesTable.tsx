import type { JSX } from 'react';

import type { Quote } from '../../../shared/types';

interface Props {
  quotes: Quote[] | undefined;
  pending: boolean;
}

/** Price precision differs by instrument; derive it from the value itself. */
function formatPrice(value: number): string {
  const decimals = value >= 100 ? 2 : value >= 10 ? 3 : 5;

  return value.toFixed(decimals);
}

function ChangeCell({ value }: { value: number | null }): JSX.Element {
  if (value === null) return <span className="muted">—</span>;

  const tone = value > 0 ? 'is-positive' : value < 0 ? 'is-negative' : '';

  return (
    <span className={tone}>
      {value > 0 ? '+' : ''}
      {value.toFixed(2)}%
    </span>
  );
}

export function QuotesTable({ quotes, pending }: Props): JSX.Element {
  if (!quotes || quotes.length === 0) {
    return (
      <div className="empty-note">
        {pending
          ? 'Waiting for quotes from the Fortrade watchlist…'
          : 'No quotes visible in the watchlist.'}
      </div>
    );
  }

  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th>Instrument</th>
            <th className="num">Sell</th>
            <th className="num">Buy</th>
            <th className="num">Spread</th>
            <th className="num">Change</th>
          </tr>
        </thead>
        <tbody>
          {quotes.map((quote) => (
            <tr key={quote.symbol}>
              <td className="sym">{quote.symbol}</td>
              <td className="num">{formatPrice(quote.sell)}</td>
              <td className="num">{formatPrice(quote.buy)}</td>
              <td className="num muted">{quote.spread_points ?? '—'}</td>
              <td className="num">
                <ChangeCell value={quote.change_percent} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
