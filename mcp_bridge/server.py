"""Read-only MCP bridge exposing Fortrader AI to Claude Code.

This server is a forwarding layer. It performs no calculations of its own —
indicators and signals are computed deterministically in the backend, so
that the model consumes numbers rather than producing them.

Every tool here is read-only. There is intentionally no tool to open,
close, or modify a position, and no code path in this process can reach
one.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar, cast

from mcp.server import MCPServer

from mcp_bridge.client import (
    BackendClient,
    BackendError,
    BackendUnavailableError,
)

JsonObject = dict[str, Any]

mcp = MCPServer(
    "fortrader-ai",
    instructions=(
        "Read-only research access to a Fortrade DEMO account through the "
        "Fortrader AI desktop application. Provides account state, quotes, "
        "positions and OHLC candles. This server cannot place, modify or "
        "close trades, and must not be described as able to do so. "
        "Indicator and signal values are computed deterministically by the "
        "backend; do not recalculate them yourself."
    ),
)

client = BackendClient()


T = TypeVar("T")


def _safe(fn: Callable[[], T]) -> T:
    """Convert transport failures into readable tool errors.

    Claude Code sees a plain sentence rather than a stack trace, and a
    missing desktop application never becomes a hanging tool call.
    """
    try:
        return fn()
    except BackendUnavailableError as exc:
        raise RuntimeError(str(exc)) from exc
    except BackendError as exc:
        raise RuntimeError(str(exc)) from exc


@mcp.tool()
def fortrade_system_status() -> JsonObject:
    """
    Get Fortrader AI's connection state, component health, and how old the
    market data currently is. Check this first if other tools return no data.
    """
    return cast(JsonObject, _safe(lambda: client.get("/api/status")))


@mcp.tool()
def fortrade_get_account() -> JsonObject:
    """
    Get the Fortrade account balance, equity, open P&L, used margin,
    available margin, currency and account type (DEMO or LIVE).
    """
    return cast(JsonObject, _safe(lambda: client.get("/api/account")))


@mcp.tool()
def fortrade_list_symbols() -> list[str]:
    """
    List the instrument symbols currently visible in the Fortrade watchlist.
    """
    body = cast(JsonObject, _safe(lambda: client.get("/api/symbols")))

    return cast("list[str]", body.get("symbols", []))


@mcp.tool()
def fortrade_get_quote(symbol: str) -> JsonObject:
    """
    Get the current bid/ask quote for one instrument, such as GBP/USD.

    Args:
        symbol: Instrument symbol as shown in Fortrade, e.g. "GBP/USD".
    """
    return cast(
        JsonObject, _safe(lambda: client.get(f"/api/quotes/{symbol}"))
    )


@mcp.tool()
def fortrade_get_quotes() -> list[JsonObject]:
    """
    Get every quote currently visible in the Fortrade watchlist.
    """
    body = cast(JsonObject, _safe(lambda: client.get("/api/quotes")))

    return cast("list[JsonObject]", body.get("quotes", []))


@mcp.tool()
def fortrade_get_positions() -> list[JsonObject]:
    """
    Get the currently open positions on the Fortrade account.
    Returns an empty list when the account is flat.
    """
    body = cast(JsonObject, _safe(lambda: client.get("/api/positions")))

    return cast("list[JsonObject]", body.get("positions", []))


@mcp.tool()
def analyse_market(
    symbol: str,
    timeframe: str = "M5",
    limit: int = 500,
) -> JsonObject:
    """
    Run deterministic technical analysis on an instrument.

    Returns EMA 9/21/50/200, RSI 14, MACD, ATR 14, realised volatility,
    support/resistance, and trend/momentum/volatility classifications, plus
    plain-language `reasons`.

    All values are computed in Python. Do not recalculate them yourself,
    and do not infer indicator values from raw candles — use these.

    Check `reliable` and `warnings` before drawing conclusions: when
    history is short the readings are provisional, and unavailable values
    are null rather than estimated.

    Args:
        symbol: Instrument symbol, e.g. "GBP/USD".
        timeframe: One of M1, M5, M15, M30, H1, H4, D1.
        limit: Maximum bars to analyse.
    """
    return cast(
        JsonObject,
        _safe(
            lambda: client.get(
                "/api/analysis",
                symbol=symbol,
                timeframe=timeframe.upper(),
                limit=limit,
            )
        ),
    )


@mcp.tool()
def get_latest_signal(
    symbol: str,
    timeframe: str = "M5",
) -> JsonObject:
    """
    Get the deterministic LONG / SHORT / WAIT signal for an instrument.

    Returns `bias`, a 0-100 `score`, the five component scores
    (trend, momentum, structure, volatility, timeframe), support and
    resistance, indicator values, `reasons` and `warnings`.

    IMPORTANT: `score` is a conviction summary on an arbitrary scale where
    50 means no directional conviction. It is NOT a probability and NOT a
    win rate — no calibration against outcomes has been performed. Do not
    present it as one, and do not describe the signal as advice.

    The bias is computed deterministically in Python. Do not recompute or
    override it; explain it.

    Args:
        symbol: Instrument symbol, e.g. "GBP/USD".
        timeframe: One of M1, M5, M15, M30, H1, H4, D1.
    """
    return cast(
        JsonObject,
        _safe(
            lambda: client.get(
                "/api/signal", symbol=symbol, timeframe=timeframe.upper()
            )
        ),
    )


@mcp.tool()
def analyse_multiple_timeframes(symbol: str) -> JsonObject:
    """
    Get the weighted multi-timeframe view across M1, M5, M15 and H1.

    Each timeframe is scored independently, then combined using weights
    tuned for short-term analysis (M15 and M5 carry most weight; M1 is
    damped as noise). Timeframes without enough captured history are
    excluded and listed in `missing_timeframes` — they are never counted
    as agreement.

    `consensus` is the fraction of included weight pointing the same way as
    the combined result.

    Args:
        symbol: Instrument symbol, e.g. "GBP/USD".
    """
    return cast(
        JsonObject,
        _safe(lambda: client.get("/api/signal/timeframes", symbol=symbol)),
    )


@mcp.tool()
def get_recent_signals(
    symbol: str | None = None,
    timeframe: str | None = None,
    limit: int = 50,
) -> list[JsonObject]:
    """
    Get the stored history of signals, newest first.

    Signals are recorded only when the bias or score actually changes, so
    this is a log of decisions rather than of polling. Useful for asking
    how a view developed over time.

    Args:
        symbol: Optional instrument filter, e.g. "GBP/USD".
        timeframe: Optional timeframe filter.
        limit: Maximum rows to return.
    """
    body = cast(
        JsonObject,
        _safe(
            lambda: client.get(
                "/api/signals/recent",
                symbol=symbol,
                timeframe=timeframe.upper() if timeframe else None,
                limit=limit,
            )
        ),
    )

    return cast("list[JsonObject]", body.get("signals", []))


@mcp.tool()
def run_backtest(
    symbol: str,
    timeframe: str = "M5",
    min_score: int = 65,
    stop_atr: float = 1.5,
    target_atr: float = 3.0,
    spread: float = 0.0,
) -> JsonObject:
    """
    Backtest the signal engine over the stored candle history.

    Walks the history forward, taking each signal as it would have
    appeared. Entries fill at the open of the bar AFTER the signal, so no
    indicator sees the bar that fills the order. When a bar contains both
    the stop and the target, the stop is assumed hit first — bar data
    cannot say which came first, and the optimistic reading flatters the
    result.

    Check `ran` and `metrics.sufficient` before quoting any figure. With
    fewer than 20 trades the derived statistics are withheld, not
    estimated. A `spread` of 0 means a frictionless test whose real-world
    results would be worse.

    These are historical simulations over a small sample, not evidence of
    an edge. Do not present them as expected future performance.

    Args:
        symbol: Instrument symbol, e.g. "GBP/USD".
        timeframe: One of M1, M5, M15, M30, H1, H4, D1.
        min_score: Minimum signal score required to take a trade.
        stop_atr: Stop distance as a multiple of ATR at entry.
        target_atr: Target distance as a multiple of ATR at entry.
        spread: Round-trip cost in price terms.
    """
    return cast(
        JsonObject,
        _safe(
            lambda: client.get(
                "/api/backtest",
                symbol=symbol,
                timeframe=timeframe.upper(),
                min_score=min_score,
                stop_atr=stop_atr,
                target_atr=target_atr,
                spread=spread,
            )
        ),
    )


@mcp.tool()
def get_backtest_result(run_id: int) -> JsonObject:
    """
    Get a stored backtest run and its metrics by id.

    Args:
        run_id: Identifier returned when the run was saved.
    """
    return cast(
        JsonObject, _safe(lambda: client.get(f"/api/backtest/runs/{run_id}"))
    )


@mcp.tool()
def list_backtest_runs(limit: int = 20) -> list[JsonObject]:
    """
    List recent backtest runs with their headline metrics, newest first.

    Args:
        limit: Maximum rows to return.
    """
    body = cast(
        JsonObject,
        _safe(lambda: client.get("/api/backtest/runs", limit=limit)),
    )

    return cast("list[JsonObject]", body.get("runs", []))


@mcp.tool()
def get_paper_positions() -> JsonObject:
    """
    Get simulated paper-trading positions and their performance.

    Returns `open` positions with unrealised P&L, recently `closed`
    trades with their R multiples, an account `summary`, and `metrics`.

    These positions are SIMULATED. They are not real trades, are not
    placed with Fortrade, and have no effect on the live account. Never
    describe them as executed trades or as instructions to trade.

    `metrics.sufficient` is false until at least 20 trades have closed;
    until then the win rate and expectancy are withheld rather than
    estimated from too small a sample.
    """
    return cast(
        JsonObject, _safe(lambda: client.get("/api/paper/positions"))
    )


@mcp.tool()
def fortrade_candle_coverage() -> JsonObject:
    """
    Report what OHLC history Fortrader AI actually holds, per instrument
    and timeframe.

    History is captured passively from charts the user opens, so a series
    is absent until it has been viewed. Check this before requesting
    candles or drawing conclusions about a timeframe.
    """
    return cast(
        JsonObject, _safe(lambda: client.get("/api/candles/coverage"))
    )


@mcp.tool()
def fortrade_get_candles(
    symbol: str,
    timeframe: str = "M5",
    limit: int = 200,
) -> JsonObject:
    """
    Get historical OHLC candles for an instrument.

    The response includes a `sufficient` flag. When it is false, fewer bars
    are held than requested and any analysis over them should be treated as
    provisional rather than reliable.

    Args:
        symbol: Instrument symbol, e.g. "GBP/USD".
        timeframe: One of M1, M5, M15, M30, H1, H4, D1.
        limit: Maximum number of bars to return.
    """
    return cast(
        JsonObject,
        _safe(
            lambda: client.get(
                "/api/candles",
                symbol=symbol,
                timeframe=timeframe.upper(),
                limit=limit,
            )
        ),
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
