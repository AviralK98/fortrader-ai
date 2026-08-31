/**
 * Minimal reproduction of the real Fortrade DOM.
 *
 * Class names and nesting were captured from the live application with
 * `dom-probe.ts` — notably that prices are split across `.sellValue` and
 * `.sellValueBig`, and that a chart tab's label concatenates the symbol
 * and timeframe with no separator ("GBP/USDM1").
 *
 * Keep this in step with the live markup: if Fortrade changes, these tests
 * should fail before users see empty fields.
 */

export const ACCOUNT_PANEL = `
<div class="accountFinanceState">
  <div class="headerBlock">
    <span>Balance</span><br><span class="footerBalance">£10,000.00</span>
  </div>
  <div class="headerBlock">
    <span>Equity</span><br><span class="footerEquity">£9,876.54</span>
  </div>
  <div class="headerBlock" id="pnlPrimary">
    <span>Open P&amp;L</span><br><span class="footerPnl">-£123.46</span>
  </div>
  <div class="marginsContainer">
    <div class="headerBlock">
      <span>Used Margin</span><br><span id="footerUsedMargin">£250.00</span>
    </div>
    <div class="headerBlock">
      <span>Available Margin</span><br>
      <span class="footerAvailableMargin">£9,626.54</span>
    </div>
  </div>
</div>
<div class="depsoitButton" data-nav="switchtoreal">SWITCH TO REAL</div>
`;

function instrumentRow(
  symbol: string,
  sellSmall: string,
  sellBig: string,
  spread: string,
  buySmall: string,
  buyBig: string,
  change: string,
  time: string,
): string {
  return `
<div class="instrument boxSizing">
  <div class="symbolChart minChartInstrument">
    <div class="dailyLow"><strong>L:</strong><span>1.35247</span></div>
    <div class="dailyHigh"><strong>H:</strong><span>1.35980</span></div>
  </div>
  <div class="symbolDynamicBackground symbolIcon" data-symbol="${symbol.replace('/', '')}\`"></div>
  <div class="nameColumn">
    <div class="symbolTradesCount">0</div>
    <div class="symbolName">${symbol}</div>
    <div class="changePercentage col-change">${change}</div>
    <div class="symbolTime">${time}</div>
  </div>
  <div class="instrumentRow buttonsContainer grayNumbers">
    <div class="sellButtonContainer">
      <div class="sellValue">${sellSmall}</div>
      <div class="sellValueBig">${sellBig}</div>
      <div class="orderCaption">SELL</div>
    </div>
    <div class="spread">${spread}</div>
    <div class="buyButtonContainer">
      <div class="buyValue">${buySmall}</div>
      <div class="buyValueBig">${buyBig}</div>
      <div class="orderCaption">BUY</div>
    </div>
  </div>
</div>`;
}

export const WATCHLIST = [
  instrumentRow('EUR/USD', '1.158', '11', '25', '1.158', '36', '-0.61%', '28/08/2026 21:58:56'),
  instrumentRow('GBP/USD', '1.352', '84', '124', '1.354', '08', '-0.50%', '28/08/2026 21:58:58'),
  instrumentRow('USD/JPY', '160.0', '91', '21', '160.1', '12', '0.49%', '28/08/2026 21:58:57'),
].join('\n');

export const CHART_TABS = `
<div class="chartTabsWrapper">
  <div class="chartSymbolTab clicked">GBP/USD<span class="timeframe">M1</span></div>
  <div class="chartSymbolTab lastItem">EUR/USD<span class="timeframe">M5</span></div>
</div>
`;

export const NO_POSITIONS = `
<div id="TradesZone" class="TradesZone">
  <span class="openPositionsCount">0</span>
  <div id="tradesView">
    <div class="tradesScrollContainer tradesSection boxSizing">
      <div class="tradesScrollEmulator">
        <div class="notradesmessage">You don't have any open trade(s).</div>
      </div>
    </div>
  </div>
</div>
`;

export const WITH_POSITIONS = `
<div id="TradesZone" class="TradesZone">
  <span class="openPositionsCount">2</span>
  <div id="tradesView"><div class="tradesScrollContainer"></div></div>
</div>
`;

export function fullPage(
  parts: { positions?: string; chart?: string; account?: string } = {},
): string {
  return `<!doctype html><html><body>
    ${parts.account ?? ACCOUNT_PANEL}
    <div class="instrumentsList">${WATCHLIST}</div>
    ${parts.chart ?? CHART_TABS}
    ${parts.positions ?? NO_POSITIONS}
  </body></html>`;
}
