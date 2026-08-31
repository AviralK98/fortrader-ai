/**
 * The read-only extraction script injected into the Fortrade view.
 *
 * Selectors below were derived from the live DOM using `dom-probe.ts`, not
 * guessed. They are semantic class hooks rather than `body.innerText`
 * regex, so a layout change degrades one field instead of everything.
 *
 * SAFETY: this script only reads. It never clicks, focuses, types,
 * submits, or dispatches an event. It touches no element related to order
 * entry. It is executed with `userGesture: false`, so it cannot satisfy a
 * user-activation gate even accidentally.
 *
 * It returns a JSON string; the main process validates before forwarding.
 */

/** Selectors, isolated here so a Fortrade UI change has one place to fix. */
export const FORTRADE_SELECTORS = {
  account: {
    balance: '.footerBalance',
    equity: '.footerEquity',
    openPnl: '.footerPnl',
    usedMargin: '#footerUsedMargin',
    availableMargin: '.footerAvailableMargin',
    panel: '.accountFinanceState',
  },
  quotes: {
    row: '.instrument',
    symbol: '.symbolName',
    symbolAttr: '[data-symbol]',
    changePercent: '.changePercentage',
    time: '.symbolTime',
    sellSmall: '.sellValue',
    sellBig: '.sellValueBig',
    buySmall: '.buyValue',
    buyBig: '.buyValueBig',
    spread: '.spread',
    dailyLow: '.dailyLow span',
    dailyHigh: '.dailyHigh span',
  },
  positions: {
    zone: '#TradesZone',
    view: '#tradesView',
    count: '.openPositionsCount',
    emptyNotice: '.notradesmessage',
    scrollContainer: '.tradesScrollContainer',
  },
  accountType: {
    switchToReal: '[data-nav="switchtoreal"]',
  },
  chart: {
    tab: '.chartSymbolTab',
    timeframe: '.timeframe',
    /** Fortrade marks the selected chart tab with this class. */
    activeClass: 'clicked',
  },
} as const;

export const EXTRACTION_SCRIPT = `
(() => {
  const S = ${JSON.stringify(FORTRADE_SELECTORS)};
  const warnings = [];

  const text = (el) => (el && el.textContent ? el.textContent.trim() : '');

  const num = (raw) => {
    if (!raw) return null;
    let s = String(raw).replace(/[£$€¥,\\s%]/g, '').trim();
    if (s.startsWith('(') && s.endsWith(')')) s = '-' + s.slice(1, -1);
    if (!s || !/^-?\\d*\\.?\\d+$/.test(s)) return null;
    const v = Number(s);
    return Number.isFinite(v) ? v : null;
  };

  const pick = (root, sel) => (root || document).querySelector(sel);

  // --- currency --------------------------------------------------------
  const CURRENCY = { '£': 'GBP', '$': 'USD', '€': 'EUR', '¥': 'JPY' };

  const currencyFrom = (raw) => {
    for (const sym of Object.keys(CURRENCY)) {
      if (raw && raw.includes(sym)) return CURRENCY[sym];
    }
    return null;
  };

  // --- account ---------------------------------------------------------
  let account = null;

  const balanceRaw = text(pick(document, S.account.balance));

  if (balanceRaw) {
    const fields = {
      balance: num(balanceRaw),
      equity: num(text(pick(document, S.account.equity))),
      open_pnl: num(text(pick(document, S.account.openPnl))),
      used_margin: num(text(pick(document, S.account.usedMargin))),
      available_margin: num(text(pick(document, S.account.availableMargin))),
    };

    const missing = Object.keys(fields).filter((k) => fields[k] === null);

    if (missing.length) {
      warnings.push('account fields unreadable: ' + missing.join(','));
    } else {
      // A "switch to real" affordance only exists on a demo account.
      // Absence proves nothing, so we report UNKNOWN rather than LIVE.
      const demo = !!pick(document, S.accountType.switchToReal);

      account = Object.assign(fields, {
        currency: currencyFrom(balanceRaw) || 'GBP',
        account_type: demo ? 'DEMO' : 'UNKNOWN',
      });
    }
  } else {
    warnings.push('account panel not found');
  }

  // --- quotes ----------------------------------------------------------
  // Price is rendered split: ".sellValue" holds the leading digits and
  // ".sellValueBig" the emphasised trailing digits.
  const joinPrice = (row, smallSel, bigSel) => {
    const small = text(pick(row, smallSel));
    const big = text(pick(row, bigSel));
    if (!small && !big) return null;
    return num(small + big);
  };

  const parseUiTime = (raw) => {
    const m = /^(\\d{2})\\/(\\d{2})\\/(\\d{4})\\s+(\\d{2}):(\\d{2}):(\\d{2})$/.exec(raw || '');
    if (!m) return null;
    // Day-first, as rendered. Emitted naive; no timezone is asserted.
    return m[3] + '-' + m[2] + '-' + m[1] + 'T' + m[4] + ':' + m[5] + ':' + m[6];
  };

  const quotes = [];

  for (const row of document.querySelectorAll(S.quotes.row)) {
    const symbol = text(pick(row, S.quotes.symbol));
    if (!symbol) continue;

    const sell = joinPrice(row, S.quotes.sellSmall, S.quotes.sellBig);
    const buy = joinPrice(row, S.quotes.buySmall, S.quotes.buyBig);

    if (sell === null || buy === null) continue;

    quotes.push({
      symbol: symbol,
      sell: sell,
      buy: buy,
      spread_points: num(text(pick(row, S.quotes.spread))),
      change_percent: num(text(pick(row, S.quotes.changePercent))),
      quoted_at: parseUiTime(text(pick(row, S.quotes.time))),
    });
  }

  if (!quotes.length) warnings.push('no quote rows parsed');

  // Authoritative mapping from Fortrade's internal symbol ("GBPUSD\`") to
  // the displayed name ("GBP/USD"). Both live on the same row, so this is
  // read rather than inferred — which also covers names like GOLD that no
  // rule could derive.
  const symbolMap = {};

  for (const row of document.querySelectorAll(S.quotes.row)) {
    const name = text(pick(row, S.quotes.symbol));
    const iconEl = pick(row, S.quotes.symbolAttr);
    const raw = iconEl ? iconEl.getAttribute('data-symbol') : null;

    if (name && raw) symbolMap[raw] = name;
  }

  // --- positions -------------------------------------------------------
  // The row markup is unknown: this account has never held an open
  // position, so there was nothing to derive selectors from. We report the
  // count Fortrade itself renders and flag the gap rather than guessing a
  // structure and silently returning wrong trades.
  const countEl = pick(document, S.positions.count);
  const reportedCount = countEl ? num(text(countEl)) : null;
  const emptyNotice = !!pick(document, S.positions.emptyNotice);

  const positions = [];

  if (reportedCount !== null && reportedCount > 0 && !positions.length) {
    warnings.push(
      'positions_unparsed: Fortrade reports ' + reportedCount +
      ' open position(s) but row extraction is not implemented'
    );
  }

  // --- chart selection -------------------------------------------------
  // Tab markup is "<div class='chartSymbolTab clicked'>GBP/USD<span
  // class='timeframe'>M1</span></div>" — the label concatenates without a
  // separator, so the timeframe suffix is removed rather than regexed out
  // of the middle. That also keeps non-forex names like GOLD working.
  let chart = null;
  const TF_ONLY = /^(M1|M5|M15|M30|H1|H4|D1)$/;

  const chartCandidates = [];

  for (const tab of document.querySelectorAll(S.chart.tab)) {
    const cls = typeof tab.className === 'string' ? tab.className : '';
    const tfText = text(pick(tab, S.chart.timeframe));

    if (!TF_ONLY.test(tfText)) continue;

    const label = text(tab).replace(/\\s+/g, ' ').trim();

    let symbol = label.endsWith(tfText)
      ? label.slice(0, label.length - tfText.length).trim()
      : label;

    // Strip a trailing close affordance if one is rendered inline.
    symbol = symbol.replace(/[×✕✖x]\\s*$/i, '').trim();

    if (!symbol) continue;

    const active = cls.split(/\\s+/).indexOf(S.chart.activeClass) !== -1;

    chartCandidates.push({ cls: cls.slice(0, 90), text: label, active: active });

    if (active && !chart) chart = { symbol: symbol, timeframe: tfText };
  }

  if (!chart && chartCandidates.length) {
    warnings.push('no chart tab marked active; using the first tab');

    const first = chartCandidates[0];
    const tf = /(M1|M5|M15|M30|H1|H4|D1)$/.exec(first.text);

    if (tf) {
      chart = {
        symbol: first.text.slice(0, first.text.length - tf[1].length).trim(),
        timeframe: tf[1],
      };
    }
  }

  if (!chart) warnings.push('chart selection not found');

  return JSON.stringify({
    account: account,
    quotes: quotes,
    positions: positions,
    chart: chart,
    symbolMap: symbolMap,
    diagnostics: {
      url: location.href,
      quoteRows: quotes.length,
      reportedPositionCount: reportedCount,
      emptyPositionsNotice: emptyNotice,
      chartCandidates: chartCandidates.slice(0, 6),
      warnings: warnings,
    },
  });
})()
`;
