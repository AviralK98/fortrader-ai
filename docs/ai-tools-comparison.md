# Compared with AI trading tools

Written on 12 September 2026 for **v0.5.1**. The Fortrader AI figures are
measured and come from [performance.md](performance.md). No competing AI
tool was benchmarked: each row sets those measurements against how such
tools are built, not against measurements of them.

**In short:** on par or better for everyday use, behind on how the chat
feels and on backtesting, and unknown on prediction quality — for
Fortrader AI and for them.

| Area | Fortrader AI | Typical AI trading tools | On par? |
|---|---|---|---|
| Getting analysis or a signal | 2–4 ms, calculated on your PC | Calculated on their servers, so every request makes a trip over the internet | **Yes, faster.** Nothing sent over the internet can match 2–4 ms on your own PC |
| AI chat | 6–22 s, with nothing on screen until the whole answer is ready | Similar total time, but words appear as they are written | **Behind in feel.** A blank wait feels much slower than watching the answer type out |
| Backtesting (replaying a strategy on past prices) | 58 s for 4,750 bars | Their testers do not rebuild every indicator on every bar, so a test this size is light work | **No.** The clear weak spot |
| Live prices | Up to 2 s behind Fortrade | Tools with a direct market data feed update on every price change | **Behind** for fast trading; fine on one-minute charts and slower |
| Memory and disk | 426 MB memory, 470 MB installed | Web tools run in a browser tab; desktop tools are similar | **On par** for a desktop app |
| How good the predictions are | Not proven; the 0–100 score is not a win rate | Many advertise win rates, usually from their own tests | **Unknown for both.** Fortrader AI claims no win rate, and there is no fair side-by-side test yet |

## Gaps worth closing

Neither is built yet.

1. **Backtesting.** Calculate the indicators once over the whole price
   history instead of again for every bar.
2. **Chat.** Show the answer as it is written, along with the lookup in
   progress (for example, "Checking the EUR/USD signal…"). The total time
   stays the same, but the wait is no longer blank. The Claude CLI already
   supports streaming its output.
