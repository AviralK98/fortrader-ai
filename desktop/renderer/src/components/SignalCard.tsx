import type { JSX } from 'react';

import type { Bias, MultiTimeframe, Signal } from '../../../shared/types';

interface Props {
  signal: Signal | undefined;
  multi: MultiTimeframe | undefined;
  pending: boolean;
}

const BIAS_TONE: Record<Bias, string> = {
  LONG: 'is-positive',
  SHORT: 'is-negative',
  WAIT: 'is-partial',
};

const COMPONENTS = [
  ['Trend', 'trend_score'],
  ['Momentum', 'momentum_score'],
  ['Structure', 'structure_score'],
  ['Volatility', 'volatility_score'],
  ['Timeframe', 'timeframe_score'],
] as const;

function Bar({ label, value }: { label: string; value: number }): JSX.Element {
  const pct = Math.max(0, Math.min(100, (value / 20) * 100));

  return (
    <div className="score-row">
      <span className="score-row__label">{label}</span>
      <span className="score-row__track">
        <span className="score-row__fill" style={{ width: `${pct}%` }} />
      </span>
      <span className="score-row__value">{value}/20</span>
    </div>
  );
}

export function SignalCard({ signal, multi, pending }: Props): JSX.Element {
  if (!signal) {
    return (
      <div className="empty-note">
        {pending ? 'Computing signal…' : 'No signal available.'}
      </div>
    );
  }

  if (signal.bars_used === 0) {
    return (
      <div className="empty-note">
        No history for {signal.symbol} {signal.timeframe}. Open that chart in
        Fortrade to collect it.
      </div>
    );
  }

  return (
    <div className="signal-card">
      <div className="signal-head">
        <div>
          <span className="signal-head__label">Bias</span>
          <span className={`signal-head__bias ${BIAS_TONE[signal.bias]}`}>
            {signal.bias}
          </span>
        </div>
        <div className="signal-head__score">
          <span className="signal-head__label">Score</span>
          <span className="signal-head__value">{signal.score} / 100</span>
        </div>
      </div>

      <div className="score-bars">
        {COMPONENTS.map(([label, key]) => (
          <Bar key={key} label={label} value={signal[key]} />
        ))}
      </div>

      {multi && multi.included_timeframes.length > 0 && (
        <div className="mtf">
          <div className="mtf__head">
            <span>Multi-timeframe</span>
            <span className="muted">
              {multi.overall_bias} · {multi.combined_score}/100
            </span>
          </div>

          {multi.readings.map((reading) => (
            <div key={reading.timeframe} className="mtf__row">
              <span className="mtf__tf">{reading.timeframe}</span>
              {reading.included ? (
                <>
                  <span className="mtf__score">{reading.score}/100</span>
                  <span className={`mtf__bias ${BIAS_TONE[reading.bias]}`}>
                    {reading.bias}
                  </span>
                  <span className="mtf__weight muted">
                    ×{reading.weight.toFixed(2)}
                  </span>
                </>
              ) : (
                <span className="mtf__missing muted">
                  no history — open this chart
                </span>
              )}
            </div>
          ))}

          {multi.consensus > 0 && (
            <div className="mtf__consensus muted">
              Consensus {Math.round(multi.consensus * 100)}% of weighted
              timeframes
            </div>
          )}
        </div>
      )}

      <p className="score-caveat">
        Score is a conviction summary, not a probability or win rate. No
        calibration against outcomes has been performed. Research only — this
        is not advice.
      </p>

      {signal.warnings.length > 0 && (
        <ul className="warnings">
          {signal.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}

      {signal.reasons.length > 0 && (
        <ul className="reasons">
          {signal.reasons.slice(0, 6).map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
