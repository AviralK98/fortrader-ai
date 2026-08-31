/**
 * Read-only client for the local backend.
 *
 * There is no mutating method here, and none may be added while the
 * application is in its research-only phase.
 */

import type {
  Account,
  Analysis,
  BacktestResult,
  ChartSelection,
  Coverage,
  MultiTimeframe,
  PaperState,
  Position,
  Quote,
  Signal,
  SystemStatus,
} from '../../../shared/types';

const BASE_URL = 'http://127.0.0.1:8756';

export class BackendNotReadyError extends Error {}

async function get<T>(path: string, timeoutMs = 5_000): Promise<T> {
  let response: Response;

  try {
    response = await fetch(`${BASE_URL}${path}`, {
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    throw new BackendNotReadyError(`Backend unreachable: ${String(error)}`);
  }

  if (response.status === 503) {
    // Data genuinely not observed yet — not an error worth surfacing loudly.
    throw new BackendNotReadyError('Awaiting Fortrade data');
  }

  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }

  return (await response.json()) as T;
}

export const backend = {
  status: () => get<{ status: SystemStatus }>('/api/status').then((r) => r.status),
  account: () => get<Account>('/api/account'),
  quotes: () => get<{ quotes: Quote[] }>('/api/quotes').then((r) => r.quotes),
  positions: () =>
    get<{ positions: Position[] }>('/api/positions').then((r) => r.positions),
  coverage: () => get<Coverage>('/api/candles/coverage'),
  chart: () => get<ChartSelection>('/api/chart'),
  analysis: (symbol: string, timeframe: string) =>
    get<Analysis>(
      `/api/analysis?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}`,
    ),
  signal: (symbol: string, timeframe: string) =>
    get<Signal>(
      `/api/signal?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}`,
    ),
  timeframes: (symbol: string) =>
    get<MultiTimeframe>(
      `/api/signal/timeframes?symbol=${encodeURIComponent(symbol)}`,
    ),
  paper: () => get<PaperState>('/api/paper/positions'),
  closePaper: async (tradeId: number) => {
    const response = await fetch(`${BASE_URL}/api/paper/close/${tradeId}`, {
      method: 'POST',
      signal: AbortSignal.timeout(5_000),
    });

    if (!response.ok) throw new Error(`Close failed: ${response.status}`);

    return (await response.json()) as { closed: number };
  },
  // Expensive: hundreds of signal evaluations. Triggered explicitly,
  // never polled.
  backtest: (symbol: string, timeframe: string, minScore = 65) =>
    get<BacktestResult>(
      `/api/backtest?symbol=${encodeURIComponent(symbol)}` +
        `&timeframe=${timeframe}&min_score=${minScore}`,
      60_000,
    ),
};
