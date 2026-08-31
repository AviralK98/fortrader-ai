import type { JSX } from 'react';

import type {
  ChartSelection,
  Coverage,
  PaperState,
  Signal,
  SystemStatus,
} from '../../../shared/types';

interface Props {
  status: SystemStatus | undefined;
  signal: Signal | undefined;
  coverage: Coverage | undefined;
  paper: PaperState | undefined;
  chart: ChartSelection | undefined;
}

type Urgency = 'blocked' | 'collect' | 'wait' | 'setup';

interface Guidance {
  urgency: Urgency;
  headline: string;
  body: JSX.Element;
}

const TARGET_TIMEFRAMES = ['M1', 'M5', 'M15', 'H1'] as const;

function missingTimeframes(
  coverage: Coverage | undefined,
  symbol: string | undefined,
): string[] {
  if (!coverage || !symbol) return [];

  return TARGET_TIMEFRAMES.filter(
    (tf) =>
      !coverage.series.some(
        (s) => s.symbol === symbol && s.timeframe === tf && s.sufficient,
      ),
  );
}

/**
 * Derives the next action from actual state.
 *
 * The ordering is deliberate: connection problems before data gaps, data
 * gaps before readings, and readings before anything resembling a setup.
 * A signal computed on thin history is not worth explaining.
 */
function decide({ status, signal, coverage, paper, chart }: Props): Guidance {
  const symbol = chart?.symbol ?? signal?.symbol;

  if (!status || status.state !== 'CONNECTED') {
    return {
      urgency: 'blocked',
      headline: 'Wait for Fortrade to connect',
      body: (
        <p>
          The header shows <strong>{status?.state ?? 'STARTING'}</strong>. If
          it asks you to log in, do that in the left pane — nothing else works
          until account data is being read.
        </p>
      ),
    };
  }

  if (status.stale) {
    return {
      urgency: 'blocked',
      headline: 'Data has gone stale',
      body: (
        <p>
          Nothing has been read for{' '}
          {Math.round(status.data_age_seconds ?? 0)}s. The market may be
          closed, or the Fortrade pane may need a reload. Do not act on
          readings while this says stale.
        </p>
      ),
    };
  }

  const missing = missingTimeframes(coverage, symbol);

  if (missing.length > 0) {
    return {
      urgency: 'collect',
      headline: `Collect ${missing.join(', ')} for ${symbol}`,
      body: (
        <p>
          Open the {symbol} chart on the left and click through{' '}
          <strong>{missing.join(', ')}</strong> once each. History is only
          captured from charts you actually view, and the multi-timeframe
          score is incomplete without them. Ten seconds, kept forever.
        </p>
      ),
    };
  }

  if (signal && !signal.reliable) {
    return {
      urgency: 'collect',
      headline: 'Not enough history to trust this reading',
      body: (
        <p>
          Only {signal.bars_used} bars. Leave the chart open so more are
          captured — anything the panel shows before then is provisional.
        </p>
      ),
    };
  }

  if (!signal || signal.bias === 'WAIT') {
    return {
      urgency: 'wait',
      headline: 'Nothing to do — no side has the edge',
      body: (
        <p>
          The components disagree, so no direction is called. This is the
          normal state most of the time. Waiting is a position: doing nothing
          here is the system working, not failing.
        </p>
      ),
    };
  }

  const closed = paper?.metrics.trades ?? 0;
  const needed = paper?.metrics.minimum_trades ?? 20;

  return {
    urgency: 'setup',
    headline: `${signal.bias} setup on ${signal.symbol} ${signal.timeframe}`,
    body: (
      <>
        <p>
          The engine leans <strong>{signal.bias}</strong> with{' '}
          {signal.score}/100 agreement. In plain terms: the moving averages,
          momentum and structure mostly point{' '}
          {signal.bias === 'LONG' ? 'up' : 'down'} on this timeframe.
        </p>

        <p className="next-steps__levels">
          {signal.support !== null && (
            <span>
              support <code>{signal.support.toFixed(5)}</code>
            </span>
          )}
          {signal.resistance !== null && (
            <span>
              resistance <code>{signal.resistance.toFixed(5)}</code>
            </span>
          )}
        </p>

        <p>
          <strong>Your move: watch it, don&apos;t take it.</strong> A paper
          position is being tracked automatically. Compare what it does
          against what the panel said — that is how you learn to read this,
          and it costs nothing.
        </p>

        <p className="next-steps__gate">
          {closed} of {needed} paper trades closed. Until that fills, this
          system has no measured track record, and {signal.score}/100 is a
          statement about agreement — not about odds.
        </p>
      </>
    ),
  };
}

/**
 * "What to do next", derived from state rather than written as advice.
 *
 * This deliberately never says "enter here". The application has no
 * execution capability, its score has not been calibrated against
 * outcomes, and the reader may be new to this — so guidance points at
 * observation and data collection, not at orders.
 */
export function NextSteps(props: Props): JSX.Element {
  const { urgency, headline, body } = decide(props);

  return (
    <div className={`next-steps next-steps--${urgency}`}>
      <h3 className="next-steps__headline">{headline}</h3>

      <div className="next-steps__body">{body}</div>

      <p className="next-steps__footer">
        Research only. This app reads and analyses — it cannot place trades.
        Anything you act on, you place yourself in Fortrade, and only with
        money you accept losing.
      </p>
    </div>
  );
}
