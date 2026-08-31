"""Tunable parameters for the signal engine.

Every threshold that shapes a bias lives here rather than being buried in
the scoring code, so the behaviour can be adjusted and, once backtesting
exists in Phase H, justified against results.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.fortrade.models import Timeframe

#: Each of the five components contributes 0-20, summing to 0-100.
COMPONENT_MAX = 20
COMPONENT_COUNT = 5
SCORE_MAX = COMPONENT_MAX * COMPONENT_COUNT


def _default_timeframe_weights() -> dict[Timeframe, float]:
    """Weights for combining timeframes in short-term day-trading analysis.

    Deliberately not a flat average. M1 is mostly noise and is damped; M5
    and M15 carry the working horizon; H1 supplies context without being
    allowed to dominate an intraday read.
    """
    return {
        Timeframe.M1: 0.10,
        Timeframe.M5: 0.30,
        Timeframe.M15: 0.35,
        Timeframe.H1: 0.25,
    }


@dataclass(frozen=True)
class SignalConfig:
    """Thresholds and weights governing signal generation."""

    #: Net directional conviction, in [-1, 1], needed to leave WAIT.
    direction_threshold: float = 0.24

    #: Timeframes the multi-timeframe analyser evaluates, and their weight.
    timeframe_weights: dict[Timeframe, float] = field(
        default_factory=_default_timeframe_weights
    )

    #: Bars required before a timeframe contributes to the combined view.
    minimum_bars_for_timeframe: int = 100

    #: Penalty applied to momentum when RSI is stretched, since a fresh
    #: entry into an extended move carries worse reward-to-risk.
    stretched_rsi_penalty: float = 0.25

    #: Distance from a level, in ATR multiples, treated as "approaching".
    level_proximity_atr: float = 1.0

    #: How much approaching a level moves the structure component.
    level_proximity_effect: float = 0.35

    def weight_for(self, timeframe: Timeframe) -> float:
        return self.timeframe_weights.get(timeframe, 0.0)

    @property
    def timeframes(self) -> tuple[Timeframe, ...]:
        return tuple(self.timeframe_weights.keys())

    def validated(self) -> SignalConfig:
        """Raise if the configuration could not produce sensible output."""
        if not 0.0 < self.direction_threshold < 1.0:
            raise ValueError("direction_threshold must be between 0 and 1")

        if not self.timeframe_weights:
            raise ValueError("at least one timeframe weight is required")

        if any(weight < 0 for weight in self.timeframe_weights.values()):
            raise ValueError("timeframe weights must not be negative")

        if sum(self.timeframe_weights.values()) <= 0:
            raise ValueError("timeframe weights must sum to a positive value")

        return self


DEFAULT_CONFIG = SignalConfig()
