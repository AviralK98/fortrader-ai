/**
 * Captures OHLC history from the Fortrade session.
 *
 * Web Fortrader loads its chart data over HTTP:
 *
 *   GET https://api.fortrade.com/.../api/charts/{SYMBOL}/{MINUTES}/slim
 *   -> { "symbol": "GBPUSD`",
 *        "points": [ { "T": "...Z", "O": .., "H": .., "L": .., "C": .. } ] }
 *
 * This class attaches `webContents.debugger` to the view we already host
 * and reads those responses as they arrive.
 *
 * STRICTLY PASSIVE. It never issues, replays, crafts or modifies a
 * request, and never touches an endpoint the page did not call itself. We
 * observe data the user's authenticated session has already been given.
 *
 * The practical consequence: a series is captured when the user opens that
 * chart. Coverage is therefore reported honestly rather than assumed — see
 * `/api/candles/coverage`.
 */

import type { WebContents } from 'electron';

import { createLogger } from './logging';

const log = createLogger('candle-capture');

/** Matches the chart endpoint and pulls out symbol and interval. */
const CHART_URL = /\/api\/charts\/([^/]+)\/(\d+)\//i;

/** Fortrade expresses the interval in minutes. */
const MINUTES_TO_TIMEFRAME: Record<string, string> = {
  '1': 'M1',
  '5': 'M5',
  '15': 'M15',
  '30': 'M30',
  '60': 'H1',
  '240': 'H4',
  '1440': 'D1',
};

const TIMEFRAME_MINUTES: Record<string, number> = {
  M1: 1,
  M5: 5,
  M15: 15,
  M30: 30,
  H1: 60,
  H4: 240,
  D1: 1440,
};

interface RawPoint {
  T?: string;
  O?: number;
  H?: number;
  L?: number;
  C?: number;
  V?: number;
}

export interface NormalisedCandle {
  symbol: string;
  timeframe: string;
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
  complete: boolean;
  source: 'network';
}

/**
 * Resolve Fortrade's internal symbol to the displayed name.
 *
 * Prefers the map read from the DOM; falls back to splitting a six-letter
 * forex code. Anything else is passed through unchanged rather than
 * mangled.
 */
export function resolveSymbol(
  raw: string,
  map: Record<string, string>,
): string {
  if (map[raw]) return map[raw];

  const stripped = raw.replace(/[`.f]+$/u, '');

  if (map[stripped]) return map[stripped];

  if (/^[A-Z]{6}$/.test(stripped)) {
    return `${stripped.slice(0, 3)}/${stripped.slice(3)}`;
  }

  return stripped;
}

export function parseChartPayload(
  body: string,
  timeframe: string,
  symbolMap: Record<string, string>,
  now: number = Date.now(),
): NormalisedCandle[] {
  let payload: { symbol?: string; points?: RawPoint[] };

  try {
    payload = JSON.parse(body) as { symbol?: string; points?: RawPoint[] };
  } catch {
    return [];
  }

  if (!payload.symbol || !Array.isArray(payload.points)) return [];

  const symbol = resolveSymbol(payload.symbol, symbolMap);
  const durationMs = (TIMEFRAME_MINUTES[timeframe] ?? 1) * 60_000;

  const candles: NormalisedCandle[] = [];

  for (const point of payload.points) {
    if (
      typeof point.T !== 'string' ||
      typeof point.O !== 'number' ||
      typeof point.H !== 'number' ||
      typeof point.L !== 'number' ||
      typeof point.C !== 'number'
    ) {
      continue;
    }

    const openedAt = Date.parse(point.T);

    if (Number.isNaN(openedAt)) continue;

    // Guard against a malformed bar reaching the indicator pipeline.
    if (point.H < point.L) continue;

    candles.push({
      symbol,
      timeframe,
      timestamp: point.T,
      open: point.O,
      high: point.H,
      low: point.L,
      close: point.C,
      volume: typeof point.V === 'number' ? point.V : null,
      // The final bar is still forming until its interval has elapsed.
      complete: openedAt + durationMs <= now,
      source: 'network',
    });
  }

  return candles;
}

export interface CaptureOptions {
  backendUrl: string;
  ingestToken: string;
  getSymbolMap: () => Record<string, string>;
  onCaptured?: (symbol: string, timeframe: string, count: number) => void;
}

export class CandleCapture {
  private attached = false;
  private readonly pending = new Map<string, { symbol: string; timeframe: string }>();

  constructor(
    private readonly contents: WebContents,
    private readonly options: CaptureOptions,
  ) {}

  start(): void {
    if (this.attached) return;

    try {
      this.contents.debugger.attach('1.3');
      this.attached = true;
    } catch (error) {
      // Most commonly: DevTools already has the debugger.
      log.error('Could not attach debugger; candle capture disabled', {
        error: String(error),
      });
      return;
    }

    this.contents.debugger.on('message', (_event, method, params) => {
      void this.handle(method, params as Record<string, unknown>);
    });

    this.contents.debugger.on('detach', (_event, reason) => {
      log.warn('Debugger detached', { reason });
      this.attached = false;
    });

    void this.contents.debugger.sendCommand('Network.enable', {
      maxTotalBufferSize: 64 * 1024 * 1024,
      maxResourceBufferSize: 16 * 1024 * 1024,
    });

    log.info('Candle capture attached (observation only)');
  }

  private async handle(
    method: string,
    params: Record<string, unknown>,
  ): Promise<void> {
    try {
      if (method === 'Network.responseReceived') {
        const requestId = params.requestId as string | undefined;
        const response = params.response as { url?: string } | undefined;

        if (!requestId || !response?.url) return;

        const match = CHART_URL.exec(response.url);

        if (!match) return;

        const timeframe = MINUTES_TO_TIMEFRAME[match[2] ?? ''];

        if (!timeframe) {
          log.debug('Unmapped chart interval', { minutes: match[2] });
          return;
        }

        this.pending.set(requestId, {
          symbol: decodeURIComponent(match[1] ?? ''),
          timeframe,
        });

        return;
      }

      if (method === 'Network.loadingFinished') {
        const requestId = params.requestId as string | undefined;

        if (!requestId) return;

        const meta = this.pending.get(requestId);
        this.pending.delete(requestId);

        if (!meta) return;

        await this.ingestResponse(requestId, meta.timeframe);
      }

      if (method === 'Network.loadingFailed') {
        const requestId = params.requestId as string | undefined;
        if (requestId) this.pending.delete(requestId);
      }
    } catch (error) {
      log.error('Capture handler failed', { method, error: String(error) });
    }
  }

  private async ingestResponse(
    requestId: string,
    timeframe: string,
  ): Promise<void> {
    const result = (await this.contents.debugger.sendCommand(
      'Network.getResponseBody',
      { requestId },
    )) as { body?: string; base64Encoded?: boolean };

    if (!result.body || result.base64Encoded) return;

    const candles = parseChartPayload(
      result.body,
      timeframe,
      this.options.getSymbolMap(),
    );

    if (!candles.length) return;

    const response = await fetch(
      `${this.options.backendUrl}/internal/ingest/candles`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Ingest-Token': this.options.ingestToken,
        },
        body: JSON.stringify({ candles }),
        signal: AbortSignal.timeout(10_000),
      },
    );

    if (!response.ok) {
      log.error('Candle ingest rejected', { status: response.status });
      return;
    }

    const body = (await response.json()) as { stored?: number };

    const symbol = candles[0]?.symbol ?? 'unknown';

    log.info('Captured candles', {
      symbol,
      timeframe,
      received: candles.length,
      stored: body.stored ?? 0,
    });

    this.options.onCaptured?.(symbol, timeframe, candles.length);
  }

  stop(): void {
    if (!this.attached) return;

    try {
      this.contents.debugger.detach();
    } catch {
      // Already detached.
    }

    this.attached = false;
  }
}
