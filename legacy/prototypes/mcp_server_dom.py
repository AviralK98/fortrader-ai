from mcp.server import MCPServer

from fortrade_browser import (
    get_account,
    get_quotes,
    get_quote,
    get_visible_chart,
)


mcp = MCPServer(
    "fortrader-market",
    instructions=(
        "Read-only access to a Fortrade demo account. "
        "This server cannot place, modify, or close trades."
    ),
)


@mcp.tool()
def fortrade_account() -> dict:
    """
    Get the current Fortrade account balance,
    equity, P&L, and margin state.
    """
    return get_account()


@mcp.tool()
def fortrade_quotes() -> list[dict]:
    """
    Get current visible quotes from the
    Fortrade Favourites watchlist.
    """
    return get_quotes()


@mcp.tool()
def fortrade_quote(
    symbol: str,
) -> dict:
    """
    Get the current Fortrade quote for
    a symbol such as GBP/USD or EUR/USD.
    """
    return get_quote(symbol)


@mcp.tool()
def fortrade_visible_chart() -> dict:
    """
    Get the currently selected chart,
    timeframe, quote and visible candle OHLC.
    """
    return get_visible_chart()


if __name__ == "__main__":
    mcp.run()