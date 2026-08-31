import type { JSX } from 'react';

import type { Coverage, Timeframe } from '../../../shared/types';

interface Props {
  coverage: Coverage | undefined;
}

/** Timeframes the multi-timeframe analyser will need. */
const TARGET_TIMEFRAMES: Timeframe[] = ['M1', 'M5', 'M15', 'H1'];

export function CoveragePanel({ coverage }: Props): JSX.Element {
  if (!coverage || coverage.series.length === 0) {
    return (
      <div className="empty-note">
        No candle history captured yet. History is collected as you open
        charts in Fortrade.
      </div>
    );
  }

  const bySymbol = new Map<string, Map<string, number>>();

  for (const series of coverage.series) {
    const existing = bySymbol.get(series.symbol) ?? new Map<string, number>();
    existing.set(series.timeframe, series.count);
    bySymbol.set(series.symbol, existing);
  }

  const missing = TARGET_TIMEFRAMES.filter(
    (tf) => !coverage.series.some((s) => s.timeframe === tf && s.sufficient),
  );

  return (
    <>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th>Symbol</th>
              {TARGET_TIMEFRAMES.map((tf) => (
                <th key={tf} className="num">
                  {tf}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[...bySymbol.entries()].map(([symbol, frames]) => (
              <tr key={symbol}>
                <td className="sym">{symbol}</td>
                {TARGET_TIMEFRAMES.map((tf) => {
                  const count = frames.get(tf) ?? 0;
                  const enough = count >= coverage.required;

                  return (
                    <td
                      key={tf}
                      className={`num ${
                        count === 0 ? 'muted' : enough ? 'is-positive' : 'is-partial'
                      }`}
                      title={
                        enough
                          ? `${count} bars — sufficient`
                          : `${count} of ${coverage.required} bars`
                      }
                    >
                      {count === 0 ? '—' : count}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {missing.length > 0 && (
        <div className="hint-note">
          Open{' '}
          <strong>{missing.join(', ')}</strong> on a Fortrade chart to collect
          {missing.length === 1 ? ' that timeframe' : ' those timeframes'}.
          History is captured from data your session already receives, so a
          series only appears once you have viewed it.
        </div>
      )}
    </>
  );
}
