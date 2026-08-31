# Fortrader AI — implementation plan

Read-only research application. No live execution is implemented, and none
is planned within these phases.

Last updated: 2026-08-29

---

## Phase A — Foundation · **DONE**

- [x] Preserve prototypes into `legacy/prototypes/` with supersession notes
- [x] Close the `.gitignore` gap that left a 62 MB Chrome profile
      (`Cookies`, `Login Data`) untracked but not ignored
- [x] Electron + TypeScript (strict) + React scaffold via electron-vite
- [x] Python backend: FastAPI on `127.0.0.1:8756`, typed, `mypy --strict`
- [x] SQLite with a versioned migration runner, auto-initialised
- [x] Redacting structured logging on both sides, unit tested
- [x] `npm run dev` starts Electron, which starts the backend automatically
- [x] 104 pytest + 21 vitest passing; ruff, mypy, eslint, tsc all clean
- [x] Docs: architecture, data-flow, security, development

## Phase B — Embedded Fortrade · **WORKING**

- [x] `WebContentsView` on `persist:fortrade`, not an iframe
- [x] Hardened: sandbox, contextIsolation, no preload, no nodeIntegration
- [x] Navigation restricted to Fortrade hosts; popups denied; permissions denied
- [x] Manual login works inside the app
- [x] Session persists across restarts
- [x] No external Chrome, no debugging port
- [ ] Confirm session survives a full machine reboot

## Phase C — Read account, quotes, positions · **DONE (one gap)**

- [x] `dom-probe.ts` — dev-only DOM discovery inside our own Electron view,
      replacing the external-Chrome discovery script
- [x] Read-only extraction script injected via `executeJavaScript`
      (`userGesture: false`)
- [x] Real semantic selectors, discovered not guessed:
      `.footerBalance`, `.footerEquity`, `.footerPnl`, `#footerUsedMargin`,
      `.footerAvailableMargin`, `.instrument`, `.symbolName`,
      `.sellValue` + `.sellValueBig`, `.spread`, `.chartSymbolTab`
- [x] Snapshots posted to `/internal/ingest/snapshot` every 2s
- [x] Account, quotes and chart selection rendered natively
- [x] `CONNECTED` driven by successful extraction, never by the URL
- [x] DEMO detected via the `switchtoreal` affordance; reports UNKNOWN
      rather than guessing LIVE
- [x] 22 jsdom tests running the real script against captured markup
- [ ] **Position row parsing** — blocked, see below

### Blocked: position rows

The account has never held an open position, so there was no row markup to
derive selectors from. Implemented instead:

* `.openPositionsCount` is read, so we know how many positions Fortrade
  believes exist
* an empty list is reported for a flat account, which is correct
* if the count is non-zero while we parse no rows, extraction emits a
  `positions_unparsed` warning rather than silently reporting "no positions"

To finish this, open a single position manually in the demo account and
re-run `FORTRADER_DUMP_DOM=1`. The row selectors can then be added to
`fortrade-script.ts` and covered by a fixture. **Do not** expect the
application to open one — it has no such capability.

## Phase D — Candle history · **DONE (collection is user-driven)**

- [x] `network-probe.ts` — dev-only passive observation via
      `webContents.debugger`
- [x] Found the source: Web Fortrader loads history over HTTP from
      `api/charts/{SYMBOL}/{MINUTES}/slim`, returning
      `{symbol, points:[{T,O,H,L,C}]}` with ISO-8601 UTC timestamps.
      ~507 bars per M1 request.
- [x] Live quotes additionally stream over a SignalR WebSocket
      (`SendMetaDataQuotes`) — not needed yet, noted for Phase E
- [x] `CandleCapture` reads those responses as they arrive; strictly
      passive, never issues or replays a request
- [x] Symbol resolution (`GBPUSD\`` → `GBP/USD`) from the DOM map, which
      also covers names like GOLD that no rule could derive
- [x] Forming bar marked `complete: false` by comparing bar open + interval
      against now
- [x] Malformed bars dropped (missing fields, unparseable time, high < low)
- [x] Persisted to SQLite via `CandleRepository`; survives restart
- [x] `/api/candles/coverage` + UI panel + `fortrade_candle_coverage` MCP tool
- [x] Verified: 500 GBP/USD M1 bars, ordered, unique, OHLC-consistent

### Collection is user-driven, by design

A series is captured only when that chart is opened, because the
constraint is observation of data the session already receives. We do not
call the chart endpoint ourselves.

Practically: **open M5, M15 and H1 once each** and they are captured and
kept. The UI names the missing timeframes, and `sufficient: false` is
reported honestly until enough bars exist.

Alternative, if this proves annoying: programmatically switching the
chart's timeframe would automate collection, but that is page interaction
rather than observation. It is not order entry and would be safe, but it
crosses the line this phase was scoped to — worth an explicit decision
before doing it.

## Phase E — Indicators · **DONE**

- [x] EMA 9/21/50/200 (SMA-seeded, platform convention), RSI 14 and ATR 14
      (Wilder smoothing), MACD triple, rolling realised volatility
- [x] Implemented directly over pandas behind our own interfaces, so tests
      exercise our code rather than a third-party library's
- [x] Swing detection (fractal), level clustering, support/resistance
- [x] Trend classification from EMA stack ordering + EMA50 slope
- [x] Momentum from RSI magnitude + MACD histogram + rate of change
- [x] Volatility regime relative to the instrument's own ATR median
- [x] `/api/analysis` endpoint, `analyse_market` MCP tool, UI panel
- [x] 90 tests, including Wilder's own worked RSI example (70.46)

### Verified on real captured data

GBP/USD, 500 bars per timeframe, all four collected:

| TF | Trend | Momentum | RSI | ATR | EMA200 |
|---|---|---|---|---|---|
| M1 | BEARISH | FALLING | 34.2 | 0.000161 | 1.35341 |
| M5 | BEARISH | FALLING | 37.9 | 0.000259 | 1.35577 |
| M15 | BEARISH | NEUTRAL | 34.5 | 0.000695 | 1.35803 |
| H1 | BEARISH | FALLING | 26.3 | 0.001359 | 1.35899 |

ATR scales monotonically with bar size and EMA200 rises with timeframe —
both are what a genuine downtrend should produce, and neither was fitted.
Range low/high (1.35251 / 1.35389) matched the chart axis.

### Decisions worth remembering

* **EMA is SMA-seeded**, not seeded from the first observation as pandas
  defaults to. With 500 bars and EMA200 the difference is material.
* **RSI/ATR use Wilder's RMA** (alpha = 1/n), not an EMA of the same
  period. These are different smoothings and mixing them is a common bug.
* **Momentum weights RSI by magnitude** rather than counting three equal
  votes. Equal voting let a marginally negative MACD histogram cancel an
  RSI of 90, which read as NEUTRAL when it plainly was not.
* **Deadbands on the histogram and ROC votes.** On a smoothly trending
  series the histogram converges to zero and its residual is float dust
  (~1e-16 of price); without a deadband that dust cast a full directional
  vote.
* **VWAP is genuinely unavailable** — Fortrade's chart feed carries no
  volume. It is reported as null with a stated reason, never approximated.
* Values are null when history is too short. EMA200 needs 200 bars, and
  a missing EMA200 must never be read as bearish.

## Phase F — Signals · **DONE**

- [x] Five components scored 0–20, summing exactly to the 0–100 score
- [x] `LONG` / `SHORT` / `WAIT` with reasons and warnings
- [x] Multi-timeframe analyser with configurable weights, not a flat mean
- [x] Score presented as a heuristic, never as a calibrated probability
- [x] `/api/signal`, `/api/signal/timeframes`, `get_latest_signal` and
      `analyse_multiple_timeframes` MCP tools, signal card in the UI
- [x] 42 signal tests

### Design decisions

* **Four components are directional, one is not.** Trend, momentum,
  structure and multi-timeframe yield a value in [-1, 1] and determine the
  bias. Volatility grades *tradeability* and is deliberately excluded from
  the bias vote — letting it push a direction would manufacture one for a
  reason unrelated to direction.
* **Components score agreement with the chosen bias**, so full agreement
  is 20, neutral 10, full opposition 0. They therefore sum to the score
  exactly, which a test enforces.
* **Absent multi-timeframe data scores neutral (10), never as support**,
  and emits a warning.
* **Momentum is damped when RSI is stretched** in the direction of the
  move: entering an already-extended run carries worse reward-to-risk.
* **Timeframe weights are not a flat average** — M15 0.35, M5 0.30,
  H1 0.25, M1 0.10. M1 is the noisiest horizon and is damped so it cannot
  flip a view the other three share. Configurable in `signals/config.py`.
* **Per-timeframe readings are computed independently** before being
  combined; passing the combined agreement down would double-count it.

### Verified on real captured data

GBP/USD, 500 bars per timeframe:

```
BIAS: SHORT                    SCORE: 76 / 100
  Trend       ████████████████████  20/20
  Momentum    █████████████████     17/20
  Structure   ███████████████       15/20
  Volatility  ████████               8/20
  Timeframe   ████████████████      16/20

M1   70/100 SHORT ×0.10    M5   74/100 SHORT ×0.30
M15  69/100 SHORT ×0.35    H1   81/100 SHORT ×0.25
Combined: SHORT 78/100 · consensus 100%
```

### The score is not a probability

It is a conviction summary where 50 means no directional conviction and
100 means every component agrees. Calling it a win rate would require
calibration against outcomes, which needs the Phase H backtester and has
**not** been done. The caveat is rendered next to the number in the UI and
stated in the MCP tool description, not buried in a footnote.

## Phase G — Persistence · **DONE**

- [x] `SignalRepository`, `SnapshotRepository`, `QuoteRepository`,
      `BacktestRepository` over the existing schema
- [x] `Retention` with per-table policies
- [x] Wired into ingest and the signal endpoint
- [x] `/api/signals/recent` + `get_recent_signals` MCP tool

### Write-rate decisions

Naive persistence would have made the database useless:

* **Quotes are sampled**, at most once per symbol per 60s. Ingest runs
  every 2 seconds — storing all of it would add tens of thousands of
  near-identical rows per instrument per day for no analytical benefit.
* **Signals are stored only when the bias or score changes.** The UI polls
  every 10 seconds; recording each poll would bury the actual decisions.
* **Snapshots are written on a 5-minute interval**, not per ingest.
* **Candles are never pruned.** They are expensive to collect — only
  captured when the user opens a chart — and are the input to backtesting.
  Quotes keep 14 days, snapshots 7, signals 90.
* **Persistence failures never break live data.** The ingest path catches
  and logs; a full disk degrades history, not the dashboard.

## Phase H — Backtesting · **DONE**

- [x] Walk-forward engine testing the *actual* signal engine
- [x] Trades, wins, losses, win rate, average win/loss in R, expectancy,
      profit factor, max drawdown %, max consecutive losses
- [x] Runs and metrics persisted; `/api/backtest`, `/api/backtest/runs`
- [x] `run_backtest`, `get_backtest_result`, `list_backtest_runs` MCP tools
- [x] UI panel with an explicit trigger (a run is hundreds of signal
      evaluations, so it is never polled)

### Three rules that keep the result honest

1. **No lookahead.** A signal computed on bars `[0..i]` is acted on at the
   open of bar `i+1`. No indicator sees the bar that fills the order. A
   test asserts every fill price equals that bar's open.
2. **Pessimistic intrabar resolution.** When a bar's range contains both
   the stop and the target, the stop is assumed hit first. Bar data cannot
   say which came first, and the optimistic reading is exactly how
   backtests flatter themselves.
3. **Small samples yield withheld statistics.** Below 20 closed trades the
   counts are reported — they are facts — but win rate, expectancy and
   profit factor are `None` and `sufficient` is false.

Also: profit factor is `None` rather than infinity when there are no
losing trades (a sample-size artefact, not an infinitely good strategy),
and a zero spread is flagged as a frictionless test whose real results
would be worse.

### First run on real data

GBP/USD, 500 captured bars, 250 tested per timeframe:

```
M1   trades=17  -> withheld  [w=5  l=12  total −1.05R]
M5   trades=17  -> withheld  [w=4  l=13  total −6.38R]
M15  trades=16  -> withheld  [w=5  l=11  total −0.43R]
H1   trades=16  -> withheld  [w=7  l=9   total +5.72R]
```

Every timeframe fell below the 20-trade floor, so no win rate was
reported. The spread of outcomes — −6.4R to +5.7R over 16–17 trades — is
itself the argument for that floor.

**This does not yet tell us whether a score of 76 means anything.** That
needs far more history than 500 bars per timeframe. Collecting it is the
practical next step, and it is gated on chart-viewing.

## Phase I — Paper trading · **DONE**

- [x] Simulated positions with entry, stop, target, size, R multiple,
      opened/closed time, P&L and entry reason
- [x] Signal snapshot attached via `signal_id` foreign key
- [x] Schema migration 2 adds `timeframe` to `paper_trades`
- [x] Exits evaluated on every ingest; entries on a 60s interval
- [x] Positions persist across restart
- [x] `get_paper_positions` MCP tool, UI panel with manual close
- [x] **No mapping to Fortrade order controls.** The backend has no
      outbound channel to Fortrade at all, and a test asserts no Fortrade
      hostname appears anywhere in `backend/`.

### Spread realism, and what it exposed

Entries and exits use the correct side of the book — a long buys at the
ask and sells at the bid — so a paper trade pays the real spread rather
than a synthetic estimate.

That immediately surfaced a genuine problem. On the first live run the
engine opened a GBP/USD M1 short and booked **−5.15R instantly**:

```
stop distance  0.000241   (1.5 x ATR)
spread         0.00124    (124 points, out of hours)
```

The spread was **five times wider than the stop**. The position entered at
the bid and could only close at the ask, which was already far past the
stop. The arithmetic was right; the missing piece was refusing to open
such a trade at all.

`min_stop_spread_multiple` (default 2.0) now declines any entry whose stop
sits inside twice the spread, logging the numbers. Verified live: three
declines, zero positions opened, paper account untouched at 10,000.

Four artefact trades from the unguarded path were deleted from
`paper_trades`; candles and all other data were left intact.

**This matters beyond paper trading.** Out-of-hours GBP/USD carried a
12.4-pip spread against an M1 ATR of 1.6 pips. Any ATR-based stop on short
timeframes is inside the spread while the market is closed. The backtester
defaults to a zero spread and therefore does not model this — its
`spread` parameter should be set to a realistic figure before any result
is taken seriously.

## Security note added in this phase

`TestNoExecutionSurface` previously asserted that no route contained
order-shaped words and that every `/api/` route was GET-only. Paper
trading legitimately needs `POST /api/paper/open` and `/close`.

The guard was **narrowed rather than relaxed**: order-shaped routes are
permitted only under the explicitly simulated `/api/paper/` namespace,
plus new structural tests that the backend contains no Fortrade hostname
and the paper modules export no execution-shaped helpers.

## Phase J — MCP

- [x] stdio bridge forwarding to the backend
- [x] Clean "not running" error, fails in ~1s rather than hanging
- [x] Runtime discovery via `runtime.json`
- [x] Read-only tools: status, account, symbols, quote(s), positions, candles
- [ ] `analyse_market`, `analyse_multiple_timeframes` (after E/F)
- [ ] `get_latest_signal`, `get_recent_signals` (after G)
- [ ] `run_backtest`, `get_backtest_result` (after H)
- [ ] `get_paper_positions` (after I)
- [ ] UI action to configure Claude Code's MCP entry, with explicit consent

Never: `open_trade`, `close_trade`, `modify_trade`, `place_order`, `buy`,
`sell`.

## Phase K — Windows packaging · **DONE (unsigned)**

- [x] PyInstaller sidecar `fortrader-backend.exe` (one-directory, 73.7 MB)
- [x] electron-builder NSIS installer,
      `release/Fortrader AI Setup 0.1.0.exe` (132.9 MB)
- [x] End user needs neither Python nor Node — verified: the packaged app
      launched, started its own sidecar, reached `CONNECTED`, and served
      2,503 stored bars
- [x] `npm run package:all` builds all three stages with a sidecar smoke
      test between them
- [ ] **Code signing** — requires a certificate, see below

### Decisions

* **One-directory, not one-file.** A one-file bundle unpacks pandas and
  numpy to a temp directory on every launch, adding seconds to each
  startup.
* **Electron pinned exactly**, not as a range: electron-builder downloads
  platform binaries for a specific release and cannot resolve `^44.0.0`.
* **`deleteAppDataOnUninstall: false`.** The browser session and captured
  candles live there; an uninstall/reinstall cycle would otherwise force a
  fresh login and re-collection of every chart.
* **Per-user install** (`perMachine: false`), so no admin prompt.

### Two things that are not finished

**The installer is unsigned.** Windows SmartScreen will warn on first run.
Signing needs a real code-signing certificate; set `CSC_LINK` and
`CSC_KEY_PASSWORD` before building. This cannot be completed here.

**Dev and installed builds share one data directory.** Electron derives it
from the package `name`, so both use `%APPDATA%\fortrader-ai-desktop`
rather than `%APPDATA%\Fortrader AI`.

Left as-is deliberately — an installed build inherits the session,
candles and paper record already collected, and candle history is
expensive to re-gather. The costs: the folder carries the npm package
name, and a dev instance and an installed instance **cannot run
simultaneously** (same SQLite file, same port 8756). Changing it means
`app.setName('Fortrader AI')` plus renaming the folder, or the existing
data is orphaned.

### Not done, and deliberately so

No auto-update. It would give the application a channel to fetch and
execute new code on a machine holding a live brokerage session, which
deserves its own review rather than being switched on for convenience.

---

## Known issues

- Position row extraction is unimplemented; see the Phase C gap above.
- Quote timestamps are emitted naive. Fortrade renders a wall-clock time
  with no timezone, so none is asserted rather than guessed.
- SPA route changes are debounced by 750 ms. Now only a fallback: once
  extraction succeeds it owns the state and a URL cannot override it.

## Decisions worth remembering

- `mcp_bridge/`, not `mcp/` — a top-level `mcp/` would shadow the Python
  MCP SDK whenever the repo root is on `sys.path`.
- Indicators are implemented in pandas behind our own interfaces rather
  than delegating to `ta`, so tests exercise our code.
- Plain `sqlite3` with a hand-rolled migration runner; SQLAlchemy and
  Alembic are not earned by a fixed local schema.
- TypeScript pinned to 5.9 — typescript-eslint does not yet support 7.x.
- No `"type": "module"` in `desktop/package.json`: a sandboxed preload
  cannot be ESM.
