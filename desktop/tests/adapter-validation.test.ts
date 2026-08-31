/**
 * The adapter's `validate` is the trust boundary: everything past it is
 * treated as real market data. A page under Fortrade's control produced
 * the input, so malformed or hostile shapes must not get through.
 */

import { describe, expect, it } from 'vitest';

import { validate } from '../main/fortrade-adapter';

const DIAGNOSTICS = {
  url: 'https://ready.fortrade.com/',
  quoteRows: 1,
  reportedPositionCount: 0,
  emptyPositionsNotice: true,
  warnings: [],
};

const ACCOUNT = {
  balance: 10000,
  equity: 10000,
  open_pnl: 0,
  used_margin: 0,
  available_margin: 10000,
  currency: 'GBP',
  account_type: 'DEMO',
};

const QUOTE = {
  symbol: 'GBP/USD',
  sell: 1.35284,
  buy: 1.35408,
  spread_points: 124,
  change_percent: -0.5,
  quoted_at: '2026-08-28T21:58:58',
};

function payload(overrides: Record<string, unknown> = {}) {
  return {
    account: ACCOUNT,
    quotes: [QUOTE],
    positions: [],
    chart: { symbol: 'GBP/USD', timeframe: 'M1' },
    diagnostics: DIAGNOSTICS,
    ...overrides,
  };
}

describe('validate', () => {
  it('accepts a well-formed payload', () => {
    const result = validate(payload());

    expect(result?.account?.balance).toBe(10000);
    expect(result?.quotes).toHaveLength(1);
  });

  it.each([null, undefined, 'string', 42, []])(
    'rejects non-object input %p',
    (input) => {
      expect(validate(input)).toBeNull();
    },
  );

  it('rejects a payload with no diagnostics', () => {
    expect(validate({ account: ACCOUNT, quotes: [] })).toBeNull();
  });

  it('accepts a null account (page not yet authenticated)', () => {
    expect(validate(payload({ account: null }))?.account).toBeNull();
  });

  it.each([
    'balance',
    'equity',
    'open_pnl',
    'used_margin',
    'available_margin',
  ])('rejects an account missing %s', (field) => {
    const account = { ...ACCOUNT } as Record<string, unknown>;
    delete account[field];

    expect(validate(payload({ account }))).toBeNull();
  });

  it.each([NaN, Infinity, -Infinity, '10000', null])(
    'rejects a non-finite balance %p',
    (balance) => {
      expect(validate(payload({ account: { ...ACCOUNT, balance } }))).toBeNull();
    },
  );

  it('rejects a non-string currency', () => {
    expect(validate(payload({ account: { ...ACCOUNT, currency: 7 } }))).toBeNull();
  });

  it('drops malformed quotes rather than failing the batch', () => {
    const result = validate(
      payload({
        quotes: [
          QUOTE,
          { symbol: 'BAD', sell: 'x', buy: 1 },
          { symbol: '', sell: 1, buy: 2 },
          { sell: 1, buy: 2 },
          { ...QUOTE, symbol: 'EUR/USD' },
        ],
      }),
    );

    expect(result?.quotes.map((q) => q.symbol)).toEqual(['GBP/USD', 'EUR/USD']);
  });

  it('tolerates quotes not being an array', () => {
    expect(validate(payload({ quotes: 'nope' }))?.quotes).toEqual([]);
  });

  it('keeps only string entries in the symbol map', () => {
    const result = validate(
      payload({
        symbolMap: { 'GBPUSD`': 'GBP/USD', bad: 42, 7: 'ignored-key-type' },
      }),
    );

    expect(result?.symbolMap['GBPUSD`']).toBe('GBP/USD');
    expect(result?.symbolMap.bad).toBeUndefined();
  });

  it('tolerates a missing or non-object symbol map', () => {
    expect(validate(payload({ symbolMap: undefined }))?.symbolMap).toEqual({});
    expect(validate(payload({ symbolMap: 'nope' }))?.symbolMap).toEqual({});
  });

  it('always forces positions to empty', () => {
    // Row parsing is unimplemented; anything claiming to be a position
    // must not reach the pipeline.
    const result = validate(
      payload({ positions: [{ symbol: 'GBP/USD', direction: 'BUY' }] }),
    );

    expect(result?.positions).toEqual([]);
  });

  it('does not let a rogue field through', () => {
    const result = validate(payload({ injected: 'value' }));

    expect(result).not.toBeNull();
    expect(Object.keys(result ?? {}).sort()).toEqual([
      'account',
      'chart',
      'diagnostics',
      'positions',
      'quotes',
      'symbolMap',
    ]);
  });
});
