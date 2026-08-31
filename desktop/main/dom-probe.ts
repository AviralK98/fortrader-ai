/**
 * Development-only DOM discovery for the Fortrade view.
 *
 * Enabled with `FORTRADER_DUMP_DOM=1`. Runs a strictly read-only script in
 * the Fortrade page, walks the elements around known labels, and writes a
 * structural report to disk so real selectors can be derived instead of
 * guessed.
 *
 * This is the successor to `legacy/prototypes/inspect_fortrade.py`: it
 * inspects the exact Chromium we ship, with the session we actually use,
 * and needs no external browser or debugging port.
 *
 * It never clicks, types, submits or dispatches events.
 */

import { writeFileSync } from 'node:fs';
import type { WebContents } from 'electron';

import { createLogger } from './logging';

const log = createLogger('dom-probe');

/** Labels whose surrounding markup we want to understand. */
const PROBE_LABELS = [
  'Balance',
  'Equity',
  'Open P&L',
  'Used Margin',
  'Available Margin',
  'SELL',
  'BUY',
  'Instrument',
  'Open Trades',
  'Symbol / ID',
];

/**
 * Serialised in full to the page. Must be self-contained — it cannot close
 * over anything in the main process.
 */
const PROBE_SCRIPT = `
(() => {
  const LABELS = ${JSON.stringify(PROBE_LABELS)};
  const MAX_NODES_PER_LABEL = 4;

  const describe = (el) => {
    if (!el || !el.tagName) return null;

    const dataAttrs = {};
    for (const attr of el.attributes || []) {
      if (attr.name.startsWith('data-') || attr.name.startsWith('aria-')) {
        dataAttrs[attr.name] = attr.value.slice(0, 80);
      }
    }

    return {
      tag: el.tagName.toLowerCase(),
      id: el.id || undefined,
      cls: (el.className && typeof el.className === 'string')
        ? el.className.slice(0, 200)
        : undefined,
      role: el.getAttribute ? (el.getAttribute('role') || undefined) : undefined,
      attrs: Object.keys(dataAttrs).length ? dataAttrs : undefined,
      text: (el.textContent || '').trim().slice(0, 60) || undefined,
    };
  };

  const ancestry = (el, depth) => {
    const chain = [];
    let node = el;
    for (let i = 0; i < depth && node; i += 1) {
      chain.push(describe(node));
      node = node.parentElement;
    }
    return chain;
  };

  // --- elements whose own text is exactly one of our labels -------------
  const byLabel = {};

  for (const label of LABELS) {
    const hits = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);

    while (walker.nextNode() && hits.length < MAX_NODES_PER_LABEL) {
      const el = walker.currentNode;
      const own = Array.from(el.childNodes)
        .filter((n) => n.nodeType === 3)
        .map((n) => n.textContent.trim())
        .join(' ')
        .trim();

      if (own === label) {
        hits.push({
          self: describe(el),
          parents: ancestry(el.parentElement, 3),
          nextSibling: describe(el.nextElementSibling),
          parentChildren: el.parentElement
            ? Array.from(el.parentElement.children).slice(0, 6).map(describe)
            : [],
        });
      }
    }

    byLabel[label] = hits;
  }

  // --- every data-* attribute name present, with example values --------
  const dataAttrNames = {};
  for (const el of document.querySelectorAll('*')) {
    for (const attr of el.attributes || []) {
      if (attr.name.startsWith('data-')) {
        if (!dataAttrNames[attr.name]) dataAttrNames[attr.name] = [];
        if (dataAttrNames[attr.name].length < 3) {
          dataAttrNames[attr.name].push(attr.value.slice(0, 60));
        }
      }
    }
  }

  // --- likely watchlist rows: elements containing both SELL and BUY ----
  const quoteRows = [];
  for (const el of document.querySelectorAll('*')) {
    const t = el.textContent || '';
    if (t.includes('SELL') && t.includes('BUY') && t.length < 400) {
      const kids = Array.from(el.children);
      if (kids.length >= 2 && kids.length <= 12) {
        quoteRows.push({ self: describe(el), children: kids.slice(0, 10).map(describe) });
      }
    }
    if (quoteRows.length >= 6) break;
  }

  // --- anything that looks like an account-type chip -------------------
  const accountChips = [];
  for (const el of document.querySelectorAll('*')) {
    const t = (el.textContent || '').trim();
    if ((t === 'DEMO' || t === 'REAL' || t === 'LIVE') && el.children.length === 0) {
      accountChips.push({ self: describe(el), parents: ancestry(el.parentElement, 2) });
    }
    if (accountChips.length >= 5) break;
  }

  // --- full subtree of representative containers -----------------------
  const subtree = (el, depth) => {
    if (!el || depth < 0) return null;

    const node = describe(el);
    if (!node) return null;

    if (depth > 0 && el.children.length) {
      node.children = Array.from(el.children)
        .slice(0, 14)
        .map((c) => subtree(c, depth - 1))
        .filter(Boolean);
    }

    return node;
  };

  const deep = {};
  for (const [name, sel, depth] of [
    ['instrumentRow', '.instrument', 4],
    ['openTrades', '.openTradesTable, #openTrades, [data-role="openpositions"]', 4],
    ['accountPanel', '.accountFinanceState', 3],
    ['switchToReal', '[data-nav="switchtoreal"]', 1],
  ]) {
    const el = document.querySelector(sel);
    deep[name] = el ? subtree(el, depth) : null;
  }

  // Locate the open-positions region even when it is empty.
  const positionsProbe = { emptyNotice: null, classHits: [] };

  for (const el of document.querySelectorAll('*')) {
    const t = (el.textContent || '').trim();
    if (el.children.length === 0 && /don't have any open trade/i.test(t)) {
      positionsProbe.emptyNotice = {
        self: describe(el),
        parents: ancestry(el.parentElement, 5),
      };
      break;
    }
  }

  const seen = new Set();
  for (const el of document.querySelectorAll('*')) {
    const cls = typeof el.className === 'string' ? el.className : '';
    if (/(openTrade|openPosition|positionsList|tradesList|blotter|dealsList)/i.test(cls)) {
      const key = cls.slice(0, 60);
      if (!seen.has(key)) {
        seen.add(key);
        positionsProbe.classHits.push(describe(el));
      }
    }
    if (positionsProbe.classHits.length >= 12) break;
  }

  // Tables anywhere on the page, to locate the positions grid.
  const tables = Array.from(document.querySelectorAll('table'))
    .slice(0, 5)
    .map((t) => ({
      self: describe(t),
      headers: Array.from(t.querySelectorAll('th')).slice(0, 10).map((h) =>
        (h.textContent || '').trim().slice(0, 40),
      ),
      firstRowCells: Array.from(t.querySelectorAll('tbody tr'))
        .slice(0, 1)
        .flatMap((r) => Array.from(r.children).slice(0, 10).map(describe)),
    }));

  return JSON.stringify({
    url: location.href,
    title: document.title,
    byLabel,
    dataAttrNames,
    quoteRows,
    accountChips,
    deep,
    tables,
    positionsProbe,
  });
})()
`;

export async function dumpFortradeDom(
  contents: WebContents,
  outputPath: string,
): Promise<void> {
  try {
    const raw: unknown = await contents.executeJavaScript(PROBE_SCRIPT, true);

    if (typeof raw !== 'string') {
      log.error('Probe returned unexpected type', { type: typeof raw });
      return;
    }

    writeFileSync(outputPath, raw, 'utf8');

    log.info('DOM probe written', { path: outputPath, bytes: raw.length });
  } catch (error) {
    log.error('DOM probe failed', { error: String(error) });
  }
}

export function isDomProbeEnabled(): boolean {
  return process.env.FORTRADER_DUMP_DOM === '1';
}
