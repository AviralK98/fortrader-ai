"""Multi-timeframe agreement.

Combines per-timeframe readings using configurable weights rather than a
flat average: M1 is largely noise for a day-trading horizon, while M5 and
M15 carry the working view and H1 supplies context.

Timeframes with too little history are excluded and reported, so a missing
series never silently counts as agreement.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from backend.analysis.frames import candles_to_frame
from backend.fortrade.models import Timeframe
from backend.fortrade.source import CandleProvider
from backend.signals.config import DEFAULT_CONFIG, SignalConfig
from backend.signals.engine import Bias, Signal, generate_signal


class TimeframeReading(BaseModel):
    model_config = ConfigDict(frozen=True)

    timeframe: Timeframe
    bias: Bias
    score: int
    net_direction: float
    bars_used: int
    weight: float
    included: bool
    note: str | None = None


class MultiTimeframeResult(BaseModel):
    """The combined view across timeframes."""

    model_config = ConfigDict(frozen=True)

    symbol: str

    readings: tuple[TimeframeReading, ...] = ()

    #: Weighted net direction across included timeframes, in [-1, 1].
    agreement: float = 0.0

    combined_score: int = 50
    overall_bias: Bias = Bias.WAIT

    #: Fraction of included weight pointing the same way as the result.
    consensus: float = 0.0

    included_timeframes: tuple[Timeframe, ...] = ()
    missing_timeframes: tuple[Timeframe, ...] = ()

    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    computed_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))


def analyse_timeframes(
    symbol: str,
    provider: CandleProvider,
    config: SignalConfig = DEFAULT_CONFIG,
    limit: int = 500,
) -> MultiTimeframeResult:
    """Evaluate each configured timeframe and combine them."""
    config.validated()

    readings: list[TimeframeReading] = []
    missing: list[Timeframe] = []
    warnings: list[str] = []

    weighted_sum = 0.0
    total_weight = 0.0

    for timeframe in config.timeframes:
        weight = config.weight_for(timeframe)
        candles = provider.get_candles(symbol, timeframe, limit)

        bars = len(candles_to_frame(candles, drop_incomplete=True))

        if bars < config.minimum_bars_for_timeframe:
            missing.append(timeframe)

            readings.append(
                TimeframeReading(
                    timeframe=timeframe,
                    bias=Bias.WAIT,
                    score=50,
                    net_direction=0.0,
                    bars_used=bars,
                    weight=weight,
                    included=False,
                    note=(
                        f"{bars} bars; {config.minimum_bars_for_timeframe} required."
                    ),
                )
            )
            continue

        # No agreement is passed down: the per-timeframe reading must be
        # independent, or the combination would double-count itself.
        signal = generate_signal(symbol, timeframe, candles, None, config)

        readings.append(
            TimeframeReading(
                timeframe=timeframe,
                bias=signal.bias,
                score=signal.score,
                net_direction=signal.net_direction,
                bars_used=signal.bars_used,
                weight=weight,
                included=True,
            )
        )

        weighted_sum += signal.net_direction * weight
        total_weight += weight

    if total_weight <= 0:
        return MultiTimeframeResult(
            symbol=symbol,
            readings=tuple(readings),
            missing_timeframes=tuple(missing),
            warnings=(
                "No timeframe has enough history for a combined view. "
                "Open the missing charts in Fortrade to collect them.",
            ),
        )

    agreement = weighted_sum / total_weight

    if agreement >= config.direction_threshold:
        overall, sign = Bias.LONG, 1
    elif agreement <= -config.direction_threshold:
        overall, sign = Bias.SHORT, -1
    else:
        overall, sign = Bias.WAIT, 0

    combined_score = round(100 * (abs(agreement) + 1.0) / 2.0)

    included = [r for r in readings if r.included]

    consensus = 0.0

    if sign != 0:
        aligned = sum(r.weight for r in included if r.net_direction * sign > 0)
        consensus = aligned / total_weight

    reasons: list[str] = []

    for reading in included:
        reasons.append(
            f"{reading.timeframe.value}: {reading.bias.value} ({reading.score}/100)"
        )

    if missing:
        names = ", ".join(tf.value for tf in missing)
        warnings.append(
            f"Excluded for insufficient history: {names}. "
            "Open those charts in Fortrade to collect them."
        )

    if sign != 0 and consensus < 0.6:
        warnings.append(
            "Timeframes disagree; the combined bias rests on a narrow margin."
        )

    return MultiTimeframeResult(
        symbol=symbol,
        readings=tuple(readings),
        agreement=round(agreement, 4),
        combined_score=combined_score,
        overall_bias=overall,
        consensus=round(consensus, 4),
        included_timeframes=tuple(r.timeframe for r in included),
        missing_timeframes=tuple(missing),
        reasons=tuple(reasons),
        warnings=tuple(warnings),
    )


def signal_with_timeframes(
    symbol: str,
    timeframe: Timeframe,
    provider: CandleProvider,
    config: SignalConfig = DEFAULT_CONFIG,
    limit: int = 500,
) -> tuple[Signal, MultiTimeframeResult]:
    """Produce a signal whose timeframe component reflects the wider view."""
    multi = analyse_timeframes(symbol, provider, config, limit)

    candles = provider.get_candles(symbol, timeframe, limit)

    agreement = multi.agreement if multi.included_timeframes else None

    signal = generate_signal(symbol, timeframe, candles, agreement, config)

    return signal, multi
