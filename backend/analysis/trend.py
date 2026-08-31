"""Trend classification from moving-average alignment and slope.

Deliberately mechanical: the output states what the averages are doing,
not what price will do next.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from itertools import pairwise

import pandas as pd

from backend.analysis.indicators import ema, last_value


class TrendDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TrendResult:
    direction: TrendDirection

    ema9: float | None
    ema21: float | None
    ema50: float | None
    ema200: float | None

    price: float | None

    #: Fraction of adjacent EMA pairs ordered consistently, 0.0-1.0.
    alignment: float

    #: Alignment carrying direction, -1.0 (fully bearish) to +1.0.
    #: Scoring needs the sign; `alignment` alone cannot supply it.
    signed_alignment: float

    #: EMA50 slope over the lookback, as a fraction of price.
    slope: float | None

    above_ema200: bool | None

    reasons: tuple[str, ...] = ()


def _slope(series: pd.Series, lookback: int = 20) -> float | None:
    """Change in the series over `lookback`, normalised by price level."""
    cleaned = series.dropna()

    if len(cleaned) < lookback + 1:
        return None

    latest = float(cleaned.iloc[-1])
    earlier = float(cleaned.iloc[-1 - lookback])

    if earlier == 0:
        return None

    return (latest - earlier) / abs(earlier)


def analyse_trend(frame: pd.DataFrame, slope_lookback: int = 20) -> TrendResult:
    """Classify trend from EMA stack ordering and EMA50 slope."""
    if frame.empty:
        return TrendResult(
            direction=TrendDirection.UNKNOWN,
            ema9=None,
            ema21=None,
            ema50=None,
            ema200=None,
            price=None,
            alignment=0.0,
            signed_alignment=0.0,
            slope=None,
            above_ema200=None,
        )

    close = frame["close"]

    ema9_s = ema(close, 9)
    ema21_s = ema(close, 21)
    ema50_s = ema(close, 50)
    ema200_s = ema(close, 200)

    values = {
        "ema9": last_value(ema9_s),
        "ema21": last_value(ema21_s),
        "ema50": last_value(ema50_s),
        "ema200": last_value(ema200_s),
    }

    price = float(close.iloc[-1])

    # Only compare the averages that actually resolved; a missing EMA200
    # must not be read as bearish.
    stack = [
        v
        for v in (values["ema9"], values["ema21"], values["ema50"], values["ema200"])
        if v is not None
    ]

    reasons: list[str] = []

    if len(stack) < 2:
        return TrendResult(
            direction=TrendDirection.UNKNOWN,
            ema9=values["ema9"],
            ema21=values["ema21"],
            ema50=values["ema50"],
            ema200=values["ema200"],
            price=price,
            alignment=0.0,
            signed_alignment=0.0,
            slope=None,
            above_ema200=None,
            reasons=("Not enough history to establish a trend.",),
        )

    pairs = list(pairwise(stack))

    descending = sum(1 for a, b in pairs if a > b)
    ascending = sum(1 for a, b in pairs if a < b)

    total = len(pairs)

    # Descending stack (fast above slow) is the bullish ordering.
    signed_alignment = (descending - ascending) / total

    if descending == total and price > stack[0]:
        direction = TrendDirection.BULLISH
        alignment = 1.0
        reasons.append("EMAs stacked bullishly with price above the fast average.")
    elif ascending == total and price < stack[0]:
        direction = TrendDirection.BEARISH
        alignment = 1.0
        reasons.append("EMAs stacked bearishly with price below the fast average.")
    else:
        direction = TrendDirection.MIXED
        alignment = max(descending, ascending) / total
        reasons.append("Moving averages are not in a consistent order.")

    slope = _slope(ema50_s, slope_lookback)

    if slope is not None:
        if slope > 0:
            reasons.append("EMA50 is rising.")
        elif slope < 0:
            reasons.append("EMA50 is falling.")

    above_200 = None

    if values["ema200"] is not None:
        above_200 = price > values["ema200"]
        reasons.append(
            "Price is above the EMA200." if above_200 else "Price is below the EMA200."
        )

    return TrendResult(
        direction=direction,
        ema9=values["ema9"],
        ema21=values["ema21"],
        ema50=values["ema50"],
        ema200=values["ema200"],
        price=price,
        alignment=alignment,
        signed_alignment=signed_alignment,
        slope=slope,
        above_ema200=above_200,
        reasons=tuple(reasons),
    )
