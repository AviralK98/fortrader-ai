/**
 * Runs the real injected extraction script against a reproduction of the
 * live Fortrade DOM.
 *
 * This is the regression net for the selectors: if Fortrade renames a
 * class, these fail rather than the app quietly showing blank fields.
 */

import { JSDOM } from 'jsdom';
import { describe, expect, it } from 'vitest';

import { EXTRACTION_SCRIPT } from '../main/extraction/fortrade-script';
import {
  CHART_TABS,
  NO_POSITIONS,
  WITH_POSITIONS,
  fullPage,
} from './fixtures/fortrade-dom';

interface Extracted {
  account: {
    balance: number;
    equity: number;
    open_pnl: number;
    used_margin: number;
    available_margin: number;
    currency: string;
    account_type: string;
  } | null;
  quotes: {
    symbol: string;
    sell: number;
    buy: number;
    spread_points: number | null;
    change_percent: number | null;
    quoted_at: string | null;
  }[];
  positions: unknown[];
  chart: { symbol: string; timeframe: string } | null;
  diagnostics: {
    quoteRows: number;
    reportedPositionCount: number | null;
    emptyPositionsNotice: boolean;
    warnings: string[];
  };
}

function extract(html: string): Extracted {
  // 'outside-only' gives us window.eval executing inside the document's
  // context, without letting fixture markup run scripts of its own.
  const dom = new JSDOM(html, {
    url: 'https://ready.fortrade.com/#chartticket',
    runScripts: 'outside-only',
  });

  const result = dom.window.eval(EXTRACTION_SCRIPT) as string;

  return JSON.parse(result) as Extracted;
}

describe('account extraction', () => {
  it('reads every field from semantic selectors', () => {
    const { account } = extract(fullPage());

    expect(account).not.toBeNull();
    expect(account?.balance).toBe(10000);
    expect(account?.equity).toBe(9876.54);
    expect(account?.used_margin).toBe(250);
    expect(account?.available_margin).toBe(9626.54);
  });

  it('keeps a negative P&L negative', () => {
    expect(extract(fullPage()).account?.open_pnl).toBe(-123.46);
  });

  it('derives currency from the rendered symbol', () => {
    expect(extract(fullPage()).account?.currency).toBe('GBP');

    const usd = fullPage({
      account: '<span class="footerBalance">$5,000.00</span>' +
        '<span class="footerEquity">$5,000.00</span>' +
        '<span class="footerPnl">$0.00</span>' +
        '<span id="footerUsedMargin">$0.00</span>' +
        '<span class="footerAvailableMargin">$5,000.00</span>',
    });

    expect(extract(usd).account?.currency).toBe('USD');
  });

  it('infers DEMO from the switch-to-real affordance', () => {
    expect(extract(fullPage()).account?.account_type).toBe('DEMO');
  });

  it('reports UNKNOWN rather than guessing LIVE when absent', () => {
    // Absence of "switch to real" is not proof of a live account.
    const html = fullPage().replace(/data-nav="switchtoreal"/, 'data-nav="other"');

    expect(extract(html).account?.account_type).toBe('UNKNOWN');
  });

  it('returns null and warns when the panel is missing', () => {
    const result = extract(fullPage({ account: '<div>nothing</div>' }));

    expect(result.account).toBeNull();
    expect(result.diagnostics.warnings.join(' ')).toContain('account panel');
  });

  it('warns rather than half-reporting when a field is unreadable', () => {
    const html = fullPage({
      account:
        '<span class="footerBalance">£10,000.00</span>' +
        '<span class="footerEquity">n/a</span>',
    });

    const result = extract(html);

    expect(result.account).toBeNull();
    expect(result.diagnostics.warnings.join(' ')).toContain('unreadable');
  });
});

describe('quote extraction', () => {
  it('parses every visible row', () => {
    const { quotes } = extract(fullPage());

    expect(quotes.map((q) => q.symbol)).toEqual([
      'EUR/USD',
      'GBP/USD',
      'USD/JPY',
    ]);
  });

  it('rejoins prices split across the emphasised digits', () => {
    // ".sellValue" holds 1.352 and ".sellValueBig" holds 84.
    const gbp = extract(fullPage()).quotes.find((q) => q.symbol === 'GBP/USD');

    expect(gbp?.sell).toBe(1.35284);
    expect(gbp?.buy).toBe(1.35408);
  });

  it('reads the broker spread in points', () => {
    const gbp = extract(fullPage()).quotes.find((q) => q.symbol === 'GBP/USD');

    expect(gbp?.spread_points).toBe(124);
  });

  it('preserves the sign of the daily change', () => {
    const quotes = extract(fullPage()).quotes;

    expect(quotes.find((q) => q.symbol === 'GBP/USD')?.change_percent).toBe(-0.5);
    expect(quotes.find((q) => q.symbol === 'USD/JPY')?.change_percent).toBe(0.49);
  });

  it('converts the day-first timestamp without asserting a timezone', () => {
    const gbp = extract(fullPage()).quotes.find((q) => q.symbol === 'GBP/USD');

    expect(gbp?.quoted_at).toBe('2026-08-28T21:58:58');
  });

  it('warns when no rows parse', () => {
    const result = extract('<!doctype html><html><body></body></html>');

    expect(result.quotes).toEqual([]);
    expect(result.diagnostics.warnings.join(' ')).toContain('no quote rows');
  });
});

describe('chart selection', () => {
  it('picks the tab Fortrade marks as clicked', () => {
    const { chart } = extract(fullPage());

    expect(chart).toEqual({ symbol: 'GBP/USD', timeframe: 'M1' });
  });

  it('separates symbol from timeframe despite no delimiter', () => {
    // The tab label renders as "GBP/USDM1".
    expect(extract(fullPage()).chart?.symbol).not.toContain('M1');
  });

  it('follows the active tab when it changes', () => {
    const swapped = CHART_TABS.replace('clicked', 'notclicked').replace(
      'lastItem',
      'lastItem clicked',
    );

    expect(extract(fullPage({ chart: swapped }))?.chart).toEqual({
      symbol: 'EUR/USD',
      timeframe: 'M5',
    });
  });

  it('falls back to the first tab and says so', () => {
    const none = CHART_TABS.replace('clicked', 'inactive');
    const result = extract(fullPage({ chart: none }));

    expect(result.chart?.symbol).toBe('GBP/USD');
    expect(result.diagnostics.warnings.join(' ')).toContain('no chart tab marked active');
  });

  it('warns when no tabs exist', () => {
    const result = extract(fullPage({ chart: '' }));

    expect(result.chart).toBeNull();
    expect(result.diagnostics.warnings.join(' ')).toContain('chart selection not found');
  });
});

describe('positions', () => {
  it('reports a flat account without warning', () => {
    const result = extract(fullPage({ positions: NO_POSITIONS }));

    expect(result.positions).toEqual([]);
    expect(result.diagnostics.reportedPositionCount).toBe(0);
    expect(result.diagnostics.emptyPositionsNotice).toBe(true);
    expect(result.diagnostics.warnings).toEqual([]);
  });

  it('flags unparsed rows instead of silently reporting none', () => {
    // Row markup is still unknown; when Fortrade says positions exist and
    // we produce none, that discrepancy must surface.
    const result = extract(fullPage({ positions: WITH_POSITIONS }));

    expect(result.diagnostics.reportedPositionCount).toBe(2);
    expect(result.diagnostics.warnings.join(' ')).toContain('positions_unparsed');
  });
});

describe('safety', () => {
  it('contains no interaction calls', () => {
    // The script must only read. Guard against a careless edit.
    for (const forbidden of [
      '.click(',
      '.submit(',
      'dispatchEvent',
      '.focus(',
      '.value =',
      'requestSubmit',
    ]) {
      expect(EXTRACTION_SCRIPT).not.toContain(forbidden);
    }
  });

  it('does not mutate the page', () => {
    const dom = new JSDOM(fullPage(), {
      url: 'https://ready.fortrade.com/',
      runScripts: 'outside-only',
    });
    const before = dom.window.document.body.innerHTML;

    dom.window.eval(EXTRACTION_SCRIPT);

    expect(dom.window.document.body.innerHTML).toBe(before);
  });
});
