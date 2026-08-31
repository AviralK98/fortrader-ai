"""Composes the indicator layers into one analysis result.

Phase E stops at measurement. Turning these readings into a LONG/SHORT/WAIT
bias with a 0-100 score is Phase F, deliberately kept separate so the
numbers can be trusted independently of how they are weighted.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from backend.analysis.frames import candles_to_frame
from backend.analysis.momentum import (
    MomentumDirection,
    MomentumResult,
    analyse_momentum,
)
from backend.analysis.structure import analyse_structure
from backend.analysis.trend import TrendDirection, TrendResult, analyse_trend
from backend.analysis.volatility import (
    VolatilityRegime,
    VolatilityResult,
    analyse_volatility,
)
from backend.fortrade.models import Candle, Timeframe

#: Bars below which analysis is reported as provisional.
RELIABLE_BARS = 200

#: Absolute floor. Below this nothing meaningful can be computed.
MINIMUM_BARS = 30


class Indicators(BaseModel):
    model_config = ConfigDict(frozen=True)

    ema9: float | None = None
    ema21: float | None = None
    ema50: float | None = None
    ema200: float | None = None

    rsi14: float | None = None

    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None

    atr14: float | None = None
    atr_percent: float | None = None

    realised_volatility: float | None = None

    vwap: float | None = None
    vwap_available: bool = False


class Structure(BaseModel):
    model_config = ConfigDict(frozen=True)

    support: float | None = None
    resistance: float | None = None
    recent_high: float | None = None
    recent_low: float | None = None
    swing_high_count: int = 0
    swing_low_count: int = 0


class AnalysisResult(BaseModel):
    """Everything Phase E can state about one instrument and timeframe."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: Timeframe

    price: float | None = None

    trend: TrendDirection = TrendDirection.UNKNOWN
    momentum: MomentumDirection = MomentumDirection.UNKNOWN
    volatility_regime: VolatilityRegime = VolatilityRegime.UNKNOWN

    indicators: Indicators = Field(default_factory=Indicators)
    structure: Structure = Field(default_factory=Structure)

    bars_used: int = 0
    bars_available: int = 0

    #: False when history is too short for the readings to be relied on.
    reliable: bool = False

    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    computed_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    last_bar_at: datetime | None = None


def build_indicators(
    trend: TrendResult,
    momentum: MomentumResult,
    volatility: VolatilityResult,
) -> Indicators:
    """Collect already-computed readings into the wire model.

    Extracted so callers that have run the analysers themselves do not
    have to recompute everything just to obtain this shape.
    """
    return Indicators(
        ema9=trend.ema9,
        ema21=trend.ema21,
        ema50=trend.ema50,
        ema200=trend.ema200,
        rsi14=momentum.rsi14,
        macd=momentum.macd,
        macd_signal=momentum.macd_signal,
        macd_histogram=momentum.macd_histogram,
        atr14=volatility.atr14,
        atr_percent=volatility.atr_percent,
        realised_volatility=volatility.realised,
        vwap=volatility.vwap,
        vwap_available=volatility.vwap_available,
    )


def analyse(
    symbol: str,
    timeframe: Timeframe,
    candles: list[Candle],
) -> AnalysisResult:
    """Compute indicators over the supplied history.

    Never fabricates: when history is insufficient the result says so and
    leaves the corresponding values as None.
    """
    frame = candles_to_frame(candles, drop_incomplete=True)

    bars = len(frame)
    warnings: list[str] = []

    if bars < MINIMUM_BARS:
        return AnalysisResult(
            symbol=symbol,
            timeframe=timeframe,
            bars_used=bars,
            bars_available=len(candles),
            reliable=False,
            warnings=(
                f"Only {bars} complete bars available; at least "
                f"{MINIMUM_BARS} are required before anything is computed.",
            ),
        )

    trend = analyse_trend(frame)
    momentum = analyse_momentum(frame)
    volatility = analyse_volatility(frame)
    structure = analyse_structure(frame)

    if bars < RELIABLE_BARS:
        warnings.append(
            f"{bars} bars is below the {RELIABLE_BARS} considered reliable; "
            "treat these readings as provisional."
        )

    if trend.ema200 is None:
        warnings.append("EMA200 unavailable: fewer than 200 bars.")

    if not volatility.vwap_available:
        warnings.append("VWAP unavailable: the feed provides no volume.")

    if structure.support is None and structure.resistance is None:
        warnings.append("No swing-based levels identified in the lookback.")

    return AnalysisResult(
        symbol=symbol,
        timeframe=timeframe,
        price=trend.price,
        trend=trend.direction,
        momentum=momentum.direction,
        volatility_regime=volatility.regime,
        indicators=build_indicators(trend, momentum, volatility),
        structure=Structure(
            support=structure.support,
            resistance=structure.resistance,
            recent_high=structure.recent_high,
            recent_low=structure.recent_low,
            swing_high_count=len(structure.swing_highs),
            swing_low_count=len(structure.swing_lows),
        ),
        bars_used=bars,
        bars_available=len(candles),
        reliable=bars >= RELIABLE_BARS,
        reasons=(*trend.reasons, *momentum.reasons, *volatility.reasons),
        warnings=tuple(warnings),
        last_bar_at=frame.index[-1].to_pydatetime(),
    )
