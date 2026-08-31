"""The deterministic signal engine.

Turns the Phase E measurements into a LONG / SHORT / WAIT bias with a
0-100 conviction score.

Two things this is not:

* It is not an "ask the model whether to buy" system. Every number here
  comes from arithmetic over candles, and the same input always produces
  the same output.
* The score is **not a probability**. It is a conviction summary on an
  arbitrary scale where 50 means "no directional conviction" and 100 means
  "every component agrees". Calling it a win rate would require calibration
  against outcomes, which needs the Phase H backtester and has not been
  done. Nothing here should be read as a claimed edge.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from backend.analysis.engine import (
    MINIMUM_BARS,
    RELIABLE_BARS,
    Indicators,
    build_indicators,
)
from backend.analysis.frames import candles_to_frame
from backend.analysis.momentum import analyse_momentum
from backend.analysis.structure import analyse_structure
from backend.analysis.trend import analyse_trend
from backend.analysis.volatility import analyse_volatility
from backend.fortrade.models import Candle, Timeframe
from backend.signals.config import DEFAULT_CONFIG, SCORE_MAX, SignalConfig
from backend.signals.scoring import (
    Component,
    score_momentum,
    score_structure,
    score_trend,
    score_volatility,
    to_component_score,
)


class Bias(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    WAIT = "WAIT"


class Signal(BaseModel):
    """A structured research signal. Not advice, and not an instruction."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: Timeframe

    bias: Bias = Bias.WAIT

    #: Conviction in the stated bias, 0-100. 50 means no conviction.
    #: Not a probability — see the module docstring.
    score: int = 50

    trend_score: int = 10
    momentum_score: int = 10
    structure_score: int = 10
    volatility_score: int = 10
    timeframe_score: int = 10

    #: Net directional reading in [-1, 1] before scaling. Positive is long.
    net_direction: float = 0.0

    price: float | None = None
    support: float | None = None
    resistance: float | None = None

    indicators: Indicators = Field(default_factory=Indicators)

    bars_used: int = 0
    reliable: bool = False

    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))


def _insufficient(
    symbol: str,
    timeframe: Timeframe,
    bars: int,
    detail: str,
) -> Signal:
    return Signal(
        symbol=symbol,
        timeframe=timeframe,
        bias=Bias.WAIT,
        score=50,
        bars_used=bars,
        reliable=False,
        warnings=(detail,),
        reasons=("Insufficient history to form a view.",),
    )


def generate_signal(
    symbol: str,
    timeframe: Timeframe,
    candles: list[Candle],
    timeframe_agreement: float | None = None,
    config: SignalConfig = DEFAULT_CONFIG,
) -> Signal:
    """Score one instrument on one timeframe.

    `timeframe_agreement` is the multi-timeframe reading in [-1, 1] when
    the caller has it. When absent that component scores neutral and a
    warning says so, rather than being silently treated as agreement.
    """
    config.validated()

    frame = candles_to_frame(candles, drop_incomplete=True)
    bars = len(frame)

    if bars < MINIMUM_BARS:
        return _insufficient(
            symbol,
            timeframe,
            bars,
            f"Only {bars} complete bars; at least {MINIMUM_BARS} required.",
        )

    trend = analyse_trend(frame)
    momentum = analyse_momentum(frame)
    volatility = analyse_volatility(frame)
    structure = analyse_structure(frame)

    warnings: list[str] = []

    trend_component = score_trend(trend)
    momentum_component = score_momentum(momentum, config)
    structure_component = score_structure(
        structure, trend.price, volatility.atr14, config
    )
    volatility_component = score_volatility(volatility)

    if timeframe_agreement is None:
        timeframe_component = Component(direction=0.0)
        warnings.append(
            "Multi-timeframe agreement unavailable; that component is neutral."
        )
    else:
        timeframe_component = Component(
            direction=max(-1.0, min(1.0, timeframe_agreement))
        )

    # Only the directional components determine the bias. Volatility
    # grades conditions; letting it vote would push a direction for a
    # reason unrelated to direction.
    directional = (
        trend_component,
        momentum_component,
        structure_component,
        timeframe_component,
    )

    net = sum(c.direction for c in directional) / len(directional)

    if net >= config.direction_threshold:
        bias, sign = Bias.LONG, 1
    elif net <= -config.direction_threshold:
        bias, sign = Bias.SHORT, -1
    else:
        bias = Bias.WAIT
        # Score the weak lean so the components still read coherently.
        sign = 1 if net > 0 else -1 if net < 0 else 0

    trend_score = to_component_score(trend_component, sign)
    momentum_score = to_component_score(momentum_component, sign)
    structure_score = to_component_score(structure_component, sign)
    volatility_score = to_component_score(volatility_component, sign)
    timeframe_score = to_component_score(timeframe_component, sign)

    score = (
        trend_score
        + momentum_score
        + structure_score
        + volatility_score
        + timeframe_score
    )

    reasons = [
        *trend_component.reasons,
        *momentum_component.reasons,
        *structure_component.reasons,
        *volatility_component.reasons,
        *trend.reasons,
        *momentum.reasons,
    ]

    if bias is Bias.WAIT:
        reasons.insert(
            0,
            "No side has enough agreement across components to justify a bias.",
        )

    if bars < RELIABLE_BARS:
        warnings.append(
            f"{bars} bars is below the {RELIABLE_BARS} considered reliable; "
            "treat this signal as provisional."
        )

    if trend.ema200 is None:
        warnings.append("EMA200 unavailable: fewer than 200 bars.")

    if not volatility.vwap_available:
        warnings.append("VWAP unavailable: the feed provides no volume.")

    return Signal(
        symbol=symbol,
        timeframe=timeframe,
        bias=bias,
        score=max(0, min(SCORE_MAX, score)),
        trend_score=trend_score,
        momentum_score=momentum_score,
        structure_score=structure_score,
        volatility_score=volatility_score,
        timeframe_score=timeframe_score,
        net_direction=round(net, 4),
        price=trend.price,
        support=structure.support,
        resistance=structure.resistance,
        # Reuses the analysers already run above; recomputing via
        # `analyse()` would double the work on every call, which the
        # backtester makes hundreds of times per run.
        indicators=build_indicators(trend, momentum, volatility),
        bars_used=bars,
        reliable=bars >= RELIABLE_BARS,
        reasons=tuple(dict.fromkeys(reasons)),
        warnings=tuple(dict.fromkeys(warnings)),
    )
