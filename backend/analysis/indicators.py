"""Deterministic technical indicators.

Implemented directly over pandas rather than delegating to a third-party
TA package, so the test suite exercises *our* code and the conventions are
explicit. The functions are pure: same input, same output, no I/O.

Conventions follow the usual trading-platform definitions:

* EMA is seeded with the simple average of the first `period` values,
  matching MetaTrader/TradingView rather than pandas' default of seeding
  from the first observation.
* RSI and ATR use Wilder's smoothing (alpha = 1/period), not a plain EMA.
* A value is `NaN` until enough history exists to compute it honestly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "atr",
    "ema",
    "macd",
    "rolling_volatility",
    "rsi",
    "sma",
    "true_range",
    "vwap",
    "wilder_rma",
]


def _empty(index: pd.Index) -> pd.Series:
    return pd.Series(np.nan, index=index, dtype=float)


def _smooth(values: pd.Series, period: int, alpha: float) -> pd.Series:
    """Recursive smoothing seeded with the mean of the first `period`.

    Shared by EMA (alpha = 2/(n+1)) and Wilder's RMA (alpha = 1/n).
    """
    out = _empty(values.index)

    if period <= 0 or len(values) < period:
        return out

    seeded = values.iloc[period - 1 :].astype(float).copy()
    seeded.iloc[0] = float(values.iloc[:period].mean())

    out.loc[seeded.index] = seeded.ewm(alpha=alpha, adjust=False).mean()

    return out


def sma(values: pd.Series, period: int) -> pd.Series:
    """Simple moving average."""
    if period <= 0:
        raise ValueError("period must be positive")

    return values.astype(float).rolling(window=period, min_periods=period).mean()


def ema(values: pd.Series, period: int) -> pd.Series:
    """Exponential moving average, SMA-seeded."""
    if period <= 0:
        raise ValueError("period must be positive")

    return _smooth(values, period, alpha=2.0 / (period + 1))


def wilder_rma(values: pd.Series, period: int) -> pd.Series:
    """Wilder's running moving average, used by RSI and ATR."""
    if period <= 0:
        raise ValueError("period must be positive")

    return _smooth(values, period, alpha=1.0 / period)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index using Wilder's smoothing.

    Returns 100 for an unbroken advance and 0 for an unbroken decline;
    both are correct rather than degenerate.
    """
    if period <= 0:
        raise ValueError("period must be positive")

    close = close.astype(float)
    delta = close.diff()

    gains = delta.clip(lower=0.0)
    losses = (-delta).clip(lower=0.0)

    avg_gain = wilder_rma(gains.iloc[1:], period)
    avg_loss = wilder_rma(losses.iloc[1:], period)

    out = _empty(close.index)

    if avg_gain.isna().all():
        return out

    # RS is undefined when average loss is zero, but RSI is not. Handle
    # the three boundary cases explicitly rather than letting infinities
    # propagate into the ratio.
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    values = 100.0 - (100.0 / (1.0 + rs))

    flat = (avg_gain == 0.0) & (avg_loss == 0.0)
    only_gains = (avg_loss == 0.0) & (avg_gain > 0.0)
    only_losses = (avg_gain == 0.0) & (avg_loss > 0.0)

    values = values.mask(only_gains, 100.0)
    values = values.mask(only_losses, 0.0)
    # An unchanged market has no strength in either direction.
    values = values.mask(flat, 50.0)

    out.loc[values.index] = values

    return out


class MacdResult:
    """MACD line, its signal, and the histogram between them."""

    __slots__ = ("histogram", "line", "signal")

    def __init__(
        self, line: pd.Series, signal: pd.Series, histogram: pd.Series
    ) -> None:
        self.line = line
        self.signal = signal
        self.histogram = histogram


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> MacdResult:
    """Moving Average Convergence Divergence."""
    if not 0 < fast < slow:
        raise ValueError("fast period must be positive and below slow")

    close = close.astype(float)

    line = ema(close, fast) - ema(close, slow)

    # The signal line is an EMA of the MACD line, which only exists from
    # the slow period onward; seeding from NaNs would shift it.
    valid = line.dropna()
    signal_series = _empty(close.index)

    if len(valid) >= signal:
        signal_series.loc[valid.index] = ema(valid, signal)

    return MacdResult(
        line=line,
        signal=signal_series,
        histogram=line - signal_series,
    )


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """True Range: the greatest of the three standard spans."""
    high = high.astype(float)
    low = low.astype(float)
    prev_close = close.astype(float).shift(1)

    spans = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    )

    tr = spans.max(axis=1)

    # Without a previous close the only defined span is the bar's range.
    tr.iloc[0] = float(high.iloc[0] - low.iloc[0]) if len(high) else np.nan

    return tr


def atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Average True Range, Wilder-smoothed."""
    return wilder_rma(true_range(high, low, close), period)


def rolling_volatility(
    close: pd.Series,
    period: int = 20,
    annualise_periods: int | None = None,
) -> pd.Series:
    """Standard deviation of log returns over a rolling window.

    Returned as a fraction (0.004 = 0.4%). `annualise_periods` scales by
    its square root when a caller wants an annualised figure.
    """
    if period <= 1:
        raise ValueError("period must be greater than 1")

    close = close.astype(float)

    returns = np.log(close / close.shift(1))

    vol = returns.rolling(window=period, min_periods=period).std(ddof=1)

    if annualise_periods:
        vol = vol * np.sqrt(annualise_periods)

    return vol


def vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
) -> pd.Series:
    """Volume-weighted average price, cumulative over the supplied range.

    Callers must confirm volume exists first — see `frames.has_volume`.
    Fortrade's chart feed omits it, so this is currently unavailable in
    practice and reported as such rather than approximated.
    """
    typical = (high.astype(float) + low.astype(float) + close.astype(float)) / 3.0
    vol = volume.astype(float)

    cumulative_volume = vol.cumsum()

    return (typical * vol).cumsum() / cumulative_volume.replace(0.0, np.nan)


def last_value(series: pd.Series) -> float | None:
    """Final non-NaN value, or None when the series never resolved."""
    if series is None or len(series) == 0:
        return None

    cleaned = series.dropna()

    if cleaned.empty:
        return None

    value = float(cleaned.iloc[-1])

    return None if not np.isfinite(value) else value
