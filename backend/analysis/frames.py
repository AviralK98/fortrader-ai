"""Conversion from domain candles into the frames indicators operate on.

Keeping this in one place means indicator code never touches a `Candle`,
and Fortrade's models never leak into the maths.
"""

from __future__ import annotations

import pandas as pd

from backend.fortrade.models import Candle


class InsufficientDataError(ValueError):
    """Raised when a calculation cannot be performed honestly."""


def candles_to_frame(
    candles: list[Candle],
    drop_incomplete: bool = True,
) -> pd.DataFrame:
    """Build an OHLCV frame indexed by bar open time, oldest first.

    The forming bar is excluded by default: an indicator computed over a
    half-finished candle moves as the bar develops and reads as signal
    when it is not.
    """
    usable = [c for c in candles if c.complete] if drop_incomplete else list(candles)

    if not usable:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"]).astype(
            float
        )

    usable.sort(key=lambda c: c.timestamp)

    frame = pd.DataFrame(
        {
            "open": [c.open for c in usable],
            "high": [c.high for c in usable],
            "low": [c.low for c in usable],
            "close": [c.close for c in usable],
            "volume": [c.volume for c in usable],
        },
        index=pd.DatetimeIndex([c.timestamp for c in usable], name="timestamp"),
    )

    for column in ("open", "high", "low", "close"):
        frame[column] = frame[column].astype(float)

    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")

    # Repeated observation of the same bar should never double-count.
    return frame[~frame.index.duplicated(keep="last")]


def has_volume(frame: pd.DataFrame) -> bool:
    """True when volume is present for every bar.

    Fortrade's chart feed omits volume, so volume-weighted measures are
    reported as unavailable rather than computed from partial data.
    """
    if "volume" not in frame.columns or frame.empty:
        return False

    return bool(frame["volume"].notna().all() and (frame["volume"] > 0).any())
