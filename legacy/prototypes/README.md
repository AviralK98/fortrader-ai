# Preserved prototypes

These scripts are the proof-of-concept work that established what is
possible. They are kept for reference and are **not** part of the shipped
application. Nothing in `backend/`, `desktop/` or `mcp_bridge/` imports
them.

They still require an external Chrome on `--remote-debugging-port=9222`,
which is exactly the dependency the real application removes.

| File | What it proved | Superseded by |
|---|---|---|
| `browser_test.py` | A persistent Chrome profile keeps the Fortrade session across restarts | Electron's `persist:fortrade` partition — `desktop/main/fortrade-view.ts` |
| `inspect_fortrade.py` | The authenticated DOM can be read | Still useful for DOM discovery; run it when Fortrade's markup changes |
| `fortrade_browser.py` | Account, quotes and the visible chart parse out of the rendered page | `backend/fortrade/parser.py` — same regexes, now pure functions over text with fixtures and tests |
| `test_fortrade.py` | Manual smoke check | `tests/python/` |
| `mcp_server_dom.py` | Read-only MCP tools over the browser | `mcp_bridge/server.py` — same tool surface, forwarding to the backend |
| `mcp_server_twelvedata.py` | EMA/RSI/MACD/ATR, trend classification and 20-bar support/resistance over pandas | Recovered from git history; the maths is the starting point for `backend/analysis/` in Phase E |

## Why `mcp_server_twelvedata.py` is here

It was deleted from the working tree when the project pivoted from the
Twelve Data API to reading Fortrade directly, but it contains the only
working indicator pipeline the project has had. It was recovered from
`HEAD:server.py` rather than rewritten.

The Twelve Data *transport* is gone — the application reads Fortrade's own
data now. The *calculations* are the reference for Phase E, which
reimplements them behind our own interfaces so the test suite exercises our
code rather than a third-party library's.

## What changed in the parsers

`fortrade_browser.py` opened and tore down a full Playwright CDP connection
on **every call**, so reading account plus quotes plus chart cost three
round trips. It also hardcoded `"currency": "GBP"` and identified the chart
by taking the last regex match on the page.

`backend/fortrade/parser.py` keeps the pattern knowledge, drops the I/O,
parses currency from the rendered symbol, and raises `FortradeParseError`
with the available symbols listed when a lookup fails.

## Running them

Not recommended, but if you need to re-discover DOM structure:

```bash
# 1. Start Chrome with remote debugging and log into Fortrade
# 2. Then:
python legacy/prototypes/inspect_fortrade.py
```

Requires `playwright` (in `requirements-dev.txt`, retained solely for
these scripts).

To refresh the test fixture after a Fortrade UI change, capture the page
text with `inspect_fortrade.py` and update
`tests/fixtures/fortrade_page.txt`.
