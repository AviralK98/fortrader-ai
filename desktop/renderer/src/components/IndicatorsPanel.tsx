import type { JSX } from 'react';

import type { Analysis } from '../../../shared/types';

interface Props {
  analysis: Analysis | undefined;
  pending: boolean;
}

function fmt(value: number | null, digits = 5): string {
  return value === null ? '—' : value.toFixed(digits);
}

function Row({
  label,
  value,
  tone,
  title,
}: {
  label: string;
  value: string;
  tone?: string;
  title?: string;
}): JSX.Element {
  return (
    <div className="metric" title={title}>
      <span className="metric__label">{label}</span>
      <span className={`metric__value${tone ? ` ${tone}` : ''}`}>{value}</span>
    </div>
  );
}

const TREND_TONE: Record<string, string> = {
  BULLISH: 'is-positive',
  BEARISH: 'is-negative',
  MIXED: 'is-partial',
  UNKNOWN: 'muted',
};

const MOMENTUM_TONE: Record<string, string> = {
  RISING: 'is-positive',
  FALLING: 'is-negative',
  NEUTRAL: 'muted',
  UNKNOWN: 'muted',
};

/** RSI colouring reflects the conventional 30/70 bands. */
function rsiTone(value: number | null): string {
  if (value === null) return 'muted';
  if (value >= 70) return 'is-negative';
  if (value <= 30) return 'is-positive';
  return '';
}

export function IndicatorsPanel({ analysis, pending }: Props): JSX.Element {
  if (!analysis) {
    return (
      <div className="empty-note">
        {pending
          ? 'Computing…'
          : 'No analysis available. Open a chart to collect history.'}
      </div>
    );
  }

  if (analysis.bars_used === 0) {
    return (
      <div className="empty-note">
        No candle history for {analysis.symbol} {analysis.timeframe} yet.
      </div>
    );
  }

  const { indicators: ind, structure: st } = analysis;

  return (
    <div className="indicator-readout">
      <div className="verdict">
        <div className="verdict__item">
          <span className="verdict__label">Trend</span>
          <span className={`verdict__value ${TREND_TONE[analysis.trend] ?? ''}`}>
            {analysis.trend}
          </span>
        </div>
        <div className="verdict__item">
          <span className="verdict__label">Momentum</span>
          <span
            className={`verdict__value ${MOMENTUM_TONE[analysis.momentum] ?? ''}`}
          >
            {analysis.momentum}
          </span>
        </div>
        <div className="verdict__item">
          <span className="verdict__label">Volatility</span>
          <span className="verdict__value">{analysis.volatility_regime}</span>
        </div>
      </div>

      {!analysis.reliable && (
        <div className="warning-note">
          Provisional — {analysis.bars_used} bars. Readings firm up as more
          history is captured.
        </div>
      )}

      <div className="metric-grid">
        <Row label="EMA 9" value={fmt(ind.ema9)} />
        <Row label="EMA 21" value={fmt(ind.ema21)} />
        <Row label="EMA 50" value={fmt(ind.ema50)} />
        <Row
          label="EMA 200"
          value={fmt(ind.ema200)}
          title={ind.ema200 === null ? 'Needs 200 bars' : undefined}
        />
        <Row
          label="RSI 14"
          value={ind.rsi14 === null ? '—' : ind.rsi14.toFixed(1)}
          tone={rsiTone(ind.rsi14)}
        />
        <Row
          label="ATR 14"
          value={ind.atr14 === null ? '—' : ind.atr14.toFixed(6)}
          title={
            ind.atr_percent === null
              ? undefined
              : `${ind.atr_percent.toFixed(3)}% of price`
          }
        />
        <Row
          label="MACD"
          value={ind.macd === null ? '—' : ind.macd.toFixed(6)}
        />
        <Row
          label="Histogram"
          value={
            ind.macd_histogram === null ? '—' : ind.macd_histogram.toFixed(6)
          }
          tone={
            ind.macd_histogram === null
              ? 'muted'
              : ind.macd_histogram > 0
                ? 'is-positive'
                : 'is-negative'
          }
        />
        <Row label="Support" value={fmt(st.support)} />
        <Row label="Resistance" value={fmt(st.resistance)} />
        <Row label="Range low" value={fmt(st.recent_low)} />
        <Row label="Range high" value={fmt(st.recent_high)} />
      </div>

      {analysis.reasons.length > 0 && (
        <ul className="reasons">
          {analysis.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
