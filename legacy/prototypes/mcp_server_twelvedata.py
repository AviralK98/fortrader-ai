import os

import httpx
import pandas as pd

from dotenv import load_dotenv
from mcp.server import MCPServer

from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from ta.volatility import AverageTrueRange


load_dotenv()

API_KEY = os.getenv("TWELVE_DATA_API_KEY")

if not API_KEY:
    raise RuntimeError("TWELVE_DATA_API_KEY is not configured")


BASE_URL = "https://api.twelvedata.com"

mcp = MCPServer(
    "fortrader-market-analysis",
    instructions=(
        "Provides read-only forex market data and technical analysis. "
        "This server cannot place, modify, or close trades."
    ),
)


async def td_request(endpoint: str, params: dict) -> dict:
    params["apikey"] = API_KEY

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{BASE_URL}/{endpoint}",
            params=params,
        )

        response.raise_for_status()

        data = response.json()

        if data.get("status") == "error":
            raise RuntimeError(data.get("message", "Twelve Data error"))

        return data


async def fetch_candles(
    symbol: str,
    interval: str,
    outputsize: int,
) -> pd.DataFrame:

    data = await td_request(
        "time_series",
        {
            "symbol": symbol,
            "interval": interval,
            "outputsize": outputsize,
            "format": "JSON",
        },
    )

    values = data["values"]

    df = pd.DataFrame(values)

    for column in ["open", "high", "low", "close"]:
        df[column] = pd.to_numeric(df[column])

    df["datetime"] = pd.to_datetime(df["datetime"])

    # API normally returns newest first.
    df = df.sort_values("datetime").reset_index(drop=True)

    return df


@mcp.tool()
async def get_quote(symbol: str = "EUR/USD") -> dict:
    """
    Get the latest available quote for a forex pair.
    Example symbol: EUR/USD or GBP/USD.
    """

    data = await td_request(
        "quote",
        {
            "symbol": symbol,
        },
    )

    return data


@mcp.tool()
async def get_candles(
    symbol: str = "EUR/USD",
    interval: str = "5min",
    count: int = 100,
) -> list[dict]:
    """
    Get historical OHLC forex candles.
    """

    df = await fetch_candles(symbol, interval, count)

    return df[
        ["datetime", "open", "high", "low", "close"]
    ].astype(
        {"datetime": str}
    ).to_dict(orient="records")


@mcp.tool()
async def analyse_market(
    symbol: str = "EUR/USD",
    interval: str = "5min",
    count: int = 250,
) -> dict:
    """
    Calculate technical indicators and basic market structure.

    This is analysis only. It does not execute trades.
    """

    df = await fetch_candles(symbol, interval, count)

    close = df["close"]
    high = df["high"]
    low = df["low"]

    df["ema9"] = EMAIndicator(close, window=9).ema_indicator()
    df["ema21"] = EMAIndicator(close, window=21).ema_indicator()
    df["ema50"] = EMAIndicator(close, window=50).ema_indicator()

    df["rsi14"] = RSIIndicator(
        close,
        window=14,
    ).rsi()

    macd = MACD(close)

    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_histogram"] = macd.macd_diff()

    atr = AverageTrueRange(
        high,
        low,
        close,
        window=14,
    )

    df["atr14"] = atr.average_true_range()

    latest = df.iloc[-1]

    price = float(latest["close"])
    ema9 = float(latest["ema9"])
    ema21 = float(latest["ema21"])
    ema50 = float(latest["ema50"])

    if price > ema9 > ema21 > ema50:
        trend = "bullish"

    elif price < ema9 < ema21 < ema50:
        trend = "bearish"

    else:
        trend = "mixed"

    recent = df.tail(20)

    support = float(recent["low"].min())
    resistance = float(recent["high"].max())

    return {
        "symbol": symbol,
        "interval": interval,

        "price": price,

        "trend": trend,

        "indicators": {
            "ema9": ema9,
            "ema21": ema21,
            "ema50": ema50,

            "rsi14": float(latest["rsi14"]),

            "macd": float(latest["macd"]),
            "macd_signal": float(latest["macd_signal"]),
            "macd_histogram": float(
                latest["macd_histogram"]
            ),

            "atr14": float(latest["atr14"]),
        },

        "structure": {
            "support_20_bar": support,
            "resistance_20_bar": resistance,
        },

        "timestamp": str(latest["datetime"]),
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")