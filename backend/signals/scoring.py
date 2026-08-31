"""Component scoring for the signal engine.

Four components are **directional**: they yield a value in [-1, +1] where
positive is bullish. One — volatility — is **not** directional; it grades
how tradeable conditions are, and contributes conviction without pushing
the bias either way.

Nothing here consults a language model. The whole point of the split is
that these numbers are reproducible and auditable.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.analysis.momentum import MomentumResult
from backend.analysis.structure import StructureResult
from backend.analysis.trend import TrendResult
from backend.analysis.volatility import VolatilityRegime, VolatilityResult
from backend.signals.config import COMPONENT_MAX, SignalConfig

# Trend blend: the EMA stack carries most of the weight, with slope and
# the EMA200 side as confirmations.
STACK_WEIGHT = 0.5
SLOPE_WEIGHT = 0.3
EMA200_WEIGHT = 0.2

#: Slope magnitudes below this are treated as flat.
SLOPE_DEADBAND = 1e-5

#: Grades for each volatility regime, as a fraction of the component max.
REGIME_QUALITY: dict[VolatilityRegime, float] = {
    # Normal ranges are the most tradeable: enough movement to matter,
    # not so much that stops must be absurdly wide.
    VolatilityRegime.NORMAL: 0.95,
    VolatilityRegime.LOW: 0.45,
    VolatilityRegime.HIGH: 0.40,
    VolatilityRegime.UNKNOWN: 0.50,
}


def clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class Component:
    """One scored component."""

    #: Directional reading in [-1, 1]; 0.0 for non-directional components.
    direction: float

    #: Explanations contributed to the signal.
    reasons: tuple[str, ...] = ()

    #: True when this component measures quality rather than direction.
    non_directional: bool = False

    #: Quality in [0, 1], used only by non-directional components.
    quality: float = 0.0


def score_trend(trend: TrendResult) -> Component:
    """EMA alignment, slope and position relative to the EMA200."""
    reasons: list[str] = []

    stack = trend.signed_alignment

    slope_sign = 0.0

    if trend.slope is not None and abs(trend.slope) > SLOPE_DEADBAND:
        slope_sign = 1.0 if trend.slope > 0 else -1.0

    ema200_side = 0.0

    if trend.above_ema200 is not None:
        ema200_side = 1.0 if trend.above_ema200 else -1.0

    direction = clamp(
        STACK_WEIGHT * stack + SLOPE_WEIGHT * slope_sign + EMA200_WEIGHT * ema200_side
    )

    if abs(stack) >= 0.99:
        reasons.append(
            "EMA alignment is complete and supports the "
            f"{'upside' if stack > 0 else 'downside'}."
        )
    elif abs(stack) < 0.34:
        reasons.append("EMA alignment is inconclusive.")

    return Component(direction=direction, reasons=tuple(reasons))


def score_momentum(
    momentum: MomentumResult,
    config: SignalConfig,
) -> Component:
    """RSI, MACD and rate of change, damped when RSI is stretched."""
    reasons: list[str] = []

    direction = clamp(momentum.score)

    # Entering in the direction of an already-stretched move is worse
    # reward-to-risk, so conviction is reduced rather than the direction
    # being reversed.
    stretched = (momentum.overbought and direction > 0) or (
        momentum.oversold and direction < 0
    )

    if stretched:
        direction *= 1.0 - config.stretched_rsi_penalty
        reasons.append(
            "RSI is stretched in the direction of the move; conviction reduced."
        )

    if momentum.histogram_flipped:
        reasons.append("MACD histogram has just changed sign.")

    return Component(direction=direction, reasons=tuple(reasons))


def score_structure(
    structure: StructureResult,
    price: float | None,
    atr: float | None,
    config: SignalConfig,
) -> Component:
    """Where price sits in its recent range, and its room to the next level."""
    reasons: list[str] = []

    if price is None or structure.recent_high is None or structure.recent_low is None:
        return Component(
            direction=0.0,
            reasons=("Market structure could not be established.",),
        )

    span = structure.recent_high - structure.recent_low

    if span <= 0:
        return Component(direction=0.0, reasons=("Recent range has no width.",))

    # Upper half of the range reads as strength, lower half as weakness.
    position = (price - structure.recent_low) / span
    direction = clamp(2.0 * position - 1.0)

    if atr is not None and atr > 0:
        reach = atr * config.level_proximity_atr

        near_resistance = (
            structure.resistance is not None
            and 0 <= structure.resistance - price <= reach
        )
        near_support = (
            structure.support is not None
            and 0 <= price - structure.support <= reach
        )

        if near_resistance and near_support:
            # Both levels sit within reach. The pulls cancel, and saying
            # "approaching resistance" alongside "holding above support"
            # reads as a contradiction when it is really a squeeze.
            reasons.append(
                "Price is squeezed between nearby support and resistance."
            )
        elif near_resistance:
            direction -= config.level_proximity_effect
            reasons.append("Price is approaching resistance.")
        elif near_support:
            direction += config.level_proximity_effect
            reasons.append("Price is holding just above support.")

    return Component(direction=clamp(direction), reasons=tuple(reasons))


def score_volatility(volatility: VolatilityResult) -> Component:
    """Grade tradeability. Deliberately carries no directional opinion."""
    quality = REGIME_QUALITY.get(volatility.regime, 0.5)

    reasons: list[str] = []

    if volatility.regime is VolatilityRegime.HIGH:
        reasons.append("Elevated volatility widens stops and reduces edge.")
    elif volatility.regime is VolatilityRegime.LOW:
        reasons.append("Compressed ranges leave little room to a target.")

    return Component(
        direction=0.0,
        reasons=tuple(reasons),
        non_directional=True,
        quality=quality,
    )


def to_component_score(component: Component, bias_sign: int) -> int:
    """Map a component onto the 0-20 scale.

    Directional components are scored by **agreement with the chosen
    bias**: full agreement is 20, neutral is 10, full opposition is 0.
    Non-directional components are scored on quality alone.
    """
    if component.non_directional:
        return round(COMPONENT_MAX * clamp(component.quality, 0.0, 1.0))

    if bias_sign == 0:
        return COMPONENT_MAX // 2

    agreement = clamp(component.direction * bias_sign)

    return round(COMPONENT_MAX * (agreement + 1.0) / 2.0)
