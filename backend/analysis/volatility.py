"""Volatility characterisation.

Absolute ATR means nothing without context — 0.0012 is calm on GOLD and
wild on EUR/USD. Everything here is expressed relative to price or to the
instrument's own recent behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from backend.analysis.frames import has_volume
from backend.analysis.indicators import atr, last_value, rolling_volatility, vwap


class VolatilityRegime(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class VolatilityResult:
    regime: VolatilityRegime

    atr14: float | None
    #: ATR as a percentage of price, so instruments are comparable.
    atr_percent: float | None

    realised: float | None

    #: Current ATR divided by its own median over the lookback.
    atr_ratio: float | None

    vwap: float | None
    vwap_available: bool

    reasons: tuple[str, ...] = ()


# Ratio of current ATR to its median that separates the regimes.
LOW_RATIO = 0.7
HIGH_RATIO = 1.4


def analyse_volatility(
    frame: pd.DataFrame,
    lookback: int = 100,
) -> VolatilityResult:
    if frame.empty:
        return VolatilityResult(
            regime=VolatilityRegime.UNKNOWN,
            atr14=None,
            atr_percent=None,
            realised=None,
            atr_ratio=None,
            vwap=None,
            vwap_available=False,
            reasons=("No data.",),
        )

    high, low, close = frame["high"], frame["low"], frame["close"]

    atr_series = atr(high, low, close, 14)
    atr_value = last_value(atr_series)

    price = float(close.iloc[-1])

    atr_percent = (
        (atr_value / price * 100.0) if atr_value is not None and price else None
    )

    realised = last_value(rolling_volatility(close, 20))

    reasons: list[str] = []

    # Compare against the instrument's own history rather than a constant.
    recent = atr_series.dropna().tail(lookback)
    ratio: float | None = None

    if len(recent) >= 20 and atr_value is not None:
        median = float(recent.median())
        ratio = atr_value / median if median > 0 else None

    if ratio is None:
        regime = VolatilityRegime.UNKNOWN
        reasons.append("Not enough history to characterise volatility.")
    elif ratio <= LOW_RATIO:
        regime = VolatilityRegime.LOW
        reasons.append("Ranges are compressed against recent norms.")
    elif ratio >= HIGH_RATIO:
        regime = VolatilityRegime.HIGH
        reasons.append("Ranges are expanded against recent norms.")
    else:
        regime = VolatilityRegime.NORMAL
        reasons.append("Volatility is near its recent median.")

    # Fortrade's chart feed carries no volume, so VWAP is genuinely
    # unavailable rather than approximated from price alone.
    vwap_available = has_volume(frame)
    vwap_value = (
        last_value(vwap(high, low, close, frame["volume"])) if vwap_available else None
    )

    if not vwap_available:
        reasons.append("VWAP unavailable: the feed provides no volume.")

    return VolatilityResult(
        regime=regime,
        atr14=atr_value,
        atr_percent=atr_percent,
        realised=realised,
        atr_ratio=ratio,
        vwap=vwap_value,
        vwap_available=vwap_available,
        reasons=tuple(reasons),
    )
