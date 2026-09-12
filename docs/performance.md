# Performance

Measured on 12 September 2026 against **v0.5.1**, using real stored market
data (19,032 bars across 18 series), on an Intel Core i7-8750H (6 cores /
12 threads) with 16 GB RAM running Windows 11.

No competing application was benchmarked side by side, apart from
MetaTrader 5's install size, measured on the same machine. Other
comparisons are against perception thresholds and how similar apps are
built, not invented figures. For AI trading tools specifically, see
[ai-tools-comparison.md](ai-tools-comparison.md).

| Area | What | Fortrader AI | Compared with similar apps |
|---|---|---|---|
| **Speed** | Reading analysis that is already computed | 2–4 ms | Better or equal — far below the ~100 ms at which a response stops feeling instant |
| | Full panel refresh (10 requests, every 2 s) | 26 ms | Instant |
| | First analysis on a new chart or new bar | 57–256 ms | Instant to a brief pause |
| | User strategy script | 268 ms (first run 446 ms) | Brief pause |
| | Backend startup (installed build) | 3.1 s | Normal |
| | AI chat answer | 6 s simple, 14–22 s with market data | Comparable — the time is the model thinking |
| | Backtest, 4,750 one-minute bars | **58 s** (range 50–90 s) | **Weak spot** — see below |
| **Resources** | Memory, window visible | 426 MB | Heavier than a native terminal such as MT5; typical of an Electron app |
| | ↳ Fortrade's web terminal page | ~187 MB | A browser tab runs the same page |
| | ↳ Electron runtime (main, GPU, network) | 117 MB | |
| | ↳ Python analysis backend | 69 MB | |
| | ↳ Interface | 53 MB | |
| | CPU, window visible | 0.3% of the machine (3.9% of one core) | Comparable |
| | CPU, minimised | ~0% | Comparable |
| | Installer | 137 MB Windows, 154 MB macOS | Heavier |
| | Installed on disk | 470 MB | Heavier — MetaTrader 5 is 313 MB |
| **Data** | Price delay behind Fortrade | Up to 2 s (1.2 s measured) | Behind native terminals, which react to every tick. Fine for analysis on one-minute charts and up; not for scalping |

**Verdict.** Comparable for everyday use: fast where it is noticed, and
heavier on memory and disk than a native terminal, as expected for an
Electron app with a Python backend. Backtesting is the one area that is
genuinely poor.

**Why backtesting is slow.** For every bar, the engine rebuilds every
indicator from the start of the history — about 55 ms per bar, and all of
the runtime. The cost grows linearly: doubling the history took 2.3× as
long. Computing the indicators once over the whole series would remove
most of that repeated work. Platforms such as MT5 update indicators
incrementally in compiled code.

**Limits of these numbers**

- Memory and CPU were measured on the development build. The installed
  build uses a production bundle and no dev server, so it should be the
  same or lighter.
- Measured on a Saturday with the market closed. On a weekday, live prices
  and a new bar each minute add some CPU; that is not yet measured.
- Windows under-counts millisecond-long requests, so polling may add up to
  ~1.3% of one core to the CPU figure.
- Which renderer process is Fortrade's page is inferred from its size.
- "First" figures are the first request after the data changes; later
  requests reuse the result until a new bar arrives.
