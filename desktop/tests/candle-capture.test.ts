import { describe, expect, it } from 'vitest';

import { parseChartPayload, resolveSymbol } from '../main/candle-capture';

/** Shape captured from the live chart endpoint. */
function payload(points: unknown[], symbol = 'GBPUSD`'): string {
  return JSON.stringify({ symbol, points });
}

const POINT = {
  T: '2026-08-28T12:39:00Z',
  O: 1.35755,
  H: 1.35761,
  L: 1.35731,
  C: 1.35731,
};

// Well after the fixture bars, so they all count as closed.
const NOW = Date.parse('2026-08-29T00:00:00Z');

describe('resolveSymbol', () => {
  const map = { 'GBPUSD`': 'GBP/USD', 'XAUUSD`': 'GOLD' };

  it('prefers the mapping read from the DOM', () => {
    expect(resolveSymbol('GBPUSD`', map)).toBe('GBP/USD');
  });

  it('resolves names no rule could derive', () => {
    // Nothing about "XAUUSD" implies "GOLD"; only the DOM knows.
    expect(resolveSymbol('XAUUSD`', map)).toBe('GOLD');
  });

  it('falls back to splitting a six-letter forex code', () => {
    expect(resolveSymbol('EURJPY`', {})).toBe('EUR/JPY');
  });

  it('matches after stripping the venue suffix', () => {
    expect(resolveSymbol('GBPUSD', map)).toBe('GBP/USD');
  });

  it('passes an unknown symbol through rather than mangling it', () => {
    expect(resolveSymbol('UK100', {})).toBe('UK100');
  });
});

describe('parseChartPayload', () => {
  it('normalises a well-formed response', () => {
    const candles = parseChartPayload(
      payload([POINT]),
      'M1',
      { 'GBPUSD`': 'GBP/USD' },
      NOW,
    );

    expect(candles).toHaveLength(1);
    expect(candles[0]).toMatchObject({
      symbol: 'GBP/USD',
      timeframe: 'M1',
      timestamp: '2026-08-28T12:39:00Z',
      open: 1.35755,
      high: 1.35761,
      low: 1.35731,
      close: 1.35731,
      source: 'network',
    });
  });

  it('preserves every bar in order', () => {
    const points = Array.from({ length: 500 }, (_, i) => ({
      ...POINT,
      T: new Date(Date.parse(POINT.T) + i * 60_000).toISOString(),
    }));

    const candles = parseChartPayload(payload(points), 'M1', {}, NOW);

    expect(candles).toHaveLength(500);
    expect(candles[0]?.timestamp).toBe(points[0]?.T);
    expect(candles[499]?.timestamp).toBe(points[499]?.T);
  });

  describe('completeness', () => {
    it('marks a bar closed once its interval has elapsed', () => {
      const [candle] = parseChartPayload(
        payload([POINT]),
        'M1',
        {},
        Date.parse('2026-08-28T12:40:00Z'),
      );

      expect(candle?.complete).toBe(true);
    });

    it('marks the forming bar incomplete', () => {
      // Indicators computed over a half-formed bar are misleading.
      const [candle] = parseChartPayload(
        payload([POINT]),
        'M1',
        {},
        Date.parse('2026-08-28T12:39:30Z'),
      );

      expect(candle?.complete).toBe(false);
    });

    it('uses the interval length for the timeframe', () => {
      const at = Date.parse('2026-08-28T13:00:00Z');

      // 21 minutes after open: closed on M1/M15, still forming on H1.
      expect(parseChartPayload(payload([POINT]), 'M15', {}, at)[0]?.complete).toBe(true);
      expect(parseChartPayload(payload([POINT]), 'H1', {}, at)[0]?.complete).toBe(false);
    });
  });

  describe('malformed input', () => {
    it('returns nothing for invalid JSON', () => {
      expect(parseChartPayload('not json', 'M1', {}, NOW)).toEqual([]);
    });

    it('returns nothing when points are missing', () => {
      expect(parseChartPayload('{"symbol":"X"}', 'M1', {}, NOW)).toEqual([]);
    });

    it('returns nothing when the symbol is missing', () => {
      expect(
        parseChartPayload(JSON.stringify({ points: [POINT] }), 'M1', {}, NOW),
      ).toEqual([]);
    });

    it.each([
      ['missing close', { ...POINT, C: undefined }],
      ['non-numeric open', { ...POINT, O: '1.35' }],
      ['missing timestamp', { ...POINT, T: undefined }],
      ['unparseable timestamp', { ...POINT, T: 'yesterday' }],
    ])('drops a point with %s', (_label, bad) => {
      const candles = parseChartPayload(payload([POINT, bad]), 'M1', {}, NOW);

      expect(candles).toHaveLength(1);
    });

    it('drops a bar whose high is below its low', () => {
      // Would silently corrupt ATR and range calculations.
      const inverted = { ...POINT, H: 1.0, L: 2.0 };

      expect(parseChartPayload(payload([inverted]), 'M1', {}, NOW)).toEqual([]);
    });

    it('keeps valid bars when some are malformed', () => {
      const candles = parseChartPayload(
        payload([POINT, { junk: true }, { ...POINT, T: '2026-08-28T12:40:00Z' }]),
        'M1',
        {},
        NOW,
      );

      expect(candles).toHaveLength(2);
    });
  });

  it('carries volume through when present', () => {
    const [candle] = parseChartPayload(
      payload([{ ...POINT, V: 1842 }]),
      'M1',
      {},
      NOW,
    );

    expect(candle?.volume).toBe(1842);
  });

  it('reports volume as null when absent rather than zero', () => {
    // Zero volume is a claim; absent volume is not.
    expect(parseChartPayload(payload([POINT]), 'M1', {}, NOW)[0]?.volume).toBeNull();
  });
});
