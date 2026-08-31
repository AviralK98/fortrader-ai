"""Momentum from RSI, MACD and rate of change."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from backend.analysis.indicators import last_value, macd, rsi


class MomentumDirection(str, Enum):
    RISING = "RISING"
    FALLING = "FALLING"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class MomentumResult:
    direction: MomentumDirection

    rsi14: float | None
    macd: float | None
    macd_signal: float | None
    macd_histogram: float | None

    #: Percentage change over the lookback window.
    roc: float | None

    overbought: bool
    oversold: bool

    #: True when the histogram has changed sign on the latest bar.
    histogram_flipped: bool

    #: Composite momentum in [-1, 1]. Negative is downward.
    score: float = 0.0

    reasons: tuple[str, ...] = ()


RSI_OVERBOUGHT = 70.0
RSI_OVERSOLD = 30.0

# Deadbands separating a real reading from arithmetic noise.
#
# On a smoothly trending series the MACD histogram converges toward zero
# and its residual is floating-point dust (~1e-16 of price). Without a
# deadband that dust casts a full directional vote. Real histograms on
# trending data sit around 1e-4 of price, so this threshold has orders of
# magnitude of margin.
HISTOGRAM_EPSILON_RATIO = 1e-6
ROC_EPSILON_PERCENT = 1e-4
RSI_NEUTRAL_BAND = 1.0

# RSI carries magnitude — it is a bounded oscillator, so its distance from
# the midpoint is meaningful. MACD and rate of change only contribute
# direction, so they are confirmations rather than the primary reading.
# Equal-weight voting would let a marginally negative histogram cancel an
# RSI of 90, which reads as neutral when it plainly is not.
RSI_WEIGHT = 0.5
HISTOGRAM_WEIGHT = 0.25
ROC_WEIGHT = 0.25

#: Composite score beyond which a direction is declared.
DIRECTION_THRESHOLD = 0.2


def _vote(value: float | None, threshold: float) -> int:
    """+1 / -1 / 0, treating anything inside the deadband as neutral."""
    if value is None or abs(value) <= threshold:
        return 0

    return 1 if value > 0 else -1


def rate_of_change(close: pd.Series, lookback: int = 10) -> float | None:
    if len(close) < lookback + 1:
        return None

    latest = float(close.iloc[-1])
    earlier = float(close.iloc[-1 - lookback])

    if earlier == 0:
        return None

    return (latest - earlier) / abs(earlier) * 100.0


def analyse_momentum(frame: pd.DataFrame, roc_lookback: int = 10) -> MomentumResult:
    if frame.empty:
        # Keyword arguments throughout: positional construction silently
        # misaligns whenever a field is inserted.
        return MomentumResult(
            direction=MomentumDirection.UNKNOWN,
            rsi14=None,
            macd=None,
            macd_signal=None,
            macd_histogram=None,
            roc=None,
            overbought=False,
            oversold=False,
            histogram_flipped=False,
            score=0.0,
            reasons=("No data.",),
        )

    close = frame["close"]

    rsi_value = last_value(rsi(close, 14))
    macd_result = macd(close)

    line = last_value(macd_result.line)
    signal = last_value(macd_result.signal)
    histogram = last_value(macd_result.histogram)

    roc = rate_of_change(close, roc_lookback)

    reasons: list[str] = []

    overbought = rsi_value is not None and rsi_value >= RSI_OVERBOUGHT
    oversold = rsi_value is not None and rsi_value <= RSI_OVERSOLD

    # A sign change on the histogram is the conventional MACD trigger.
    histogram_series = macd_result.histogram.dropna()
    flipped = False

    if len(histogram_series) >= 2:
        previous = float(histogram_series.iloc[-2])
        current = float(histogram_series.iloc[-1])
        flipped = (previous < 0 < current) or (previous > 0 > current)

    price = abs(float(close.iloc[-1])) or 1.0

    rsi_vote = _vote(None if rsi_value is None else rsi_value - 50.0, RSI_NEUTRAL_BAND)
    histogram_vote = _vote(histogram, price * HISTOGRAM_EPSILON_RATIO)
    roc_vote = _vote(roc, ROC_EPSILON_PERCENT)

    # RSI contributes its magnitude, normalised to [-1, 1].
    rsi_strength = 0.0 if rsi_value is None else (rsi_value - 50.0) / 50.0

    score = (
        RSI_WEIGHT * rsi_strength
        + HISTOGRAM_WEIGHT * histogram_vote
        + ROC_WEIGHT * roc_vote
    )

    if rsi_vote > 0:
        reasons.append(f"RSI at {rsi_value:.1f} is above the midpoint.")
    elif rsi_vote < 0:
        reasons.append(f"RSI at {rsi_value:.1f} is below the midpoint.")

    if histogram_vote > 0:
        reasons.append("MACD histogram is positive.")
    elif histogram_vote < 0:
        reasons.append("MACD histogram is negative.")
    elif histogram is not None:
        reasons.append("MACD histogram is flat.")

    if roc is not None:
        if roc_vote > 0:
            reasons.append(f"Price is up {roc:.2f}% over {roc_lookback} bars.")
        elif roc_vote < 0:
            reasons.append(f"Price is down {abs(roc):.2f}% over {roc_lookback} bars.")

    if rsi_value is None and histogram is None and roc is None:
        direction = MomentumDirection.UNKNOWN
        score = 0.0
    elif score > DIRECTION_THRESHOLD:
        direction = MomentumDirection.RISING
    elif score < -DIRECTION_THRESHOLD:
        direction = MomentumDirection.FALLING
    else:
        direction = MomentumDirection.NEUTRAL

    if overbought:
        reasons.append("RSI is in overbought territory.")
    if oversold:
        reasons.append("RSI is in oversold territory.")
    if flipped:
        reasons.append("MACD histogram changed sign on the latest bar.")

    return MomentumResult(
        direction=direction,
        rsi14=rsi_value,
        macd=line,
        macd_signal=signal,
        macd_histogram=histogram,
        roc=roc,
        overbought=overbought,
        oversold=oversold,
        histogram_flipped=flipped,
        score=round(score, 4),
        reasons=tuple(reasons),
    )
