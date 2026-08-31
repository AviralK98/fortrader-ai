"""Market structure: swing points, support and resistance.

Swings are detected with a symmetric fractal rule — a bar is a swing high
when it is the highest of the `strength` bars either side. Levels are then
formed by clustering nearby swings, because price respects a zone rather
than an exact tick.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class SwingPoint:
    index: int
    price: float
    kind: str  # "high" | "low"


@dataclass(frozen=True)
class Level:
    """A clustered price level and how often it has been touched."""

    price: float
    touches: int
    kind: str  # "support" | "resistance"


@dataclass(frozen=True)
class StructureResult:
    swing_highs: tuple[SwingPoint, ...]
    swing_lows: tuple[SwingPoint, ...]

    support: float | None
    resistance: float | None

    recent_high: float | None
    recent_low: float | None

    support_levels: tuple[Level, ...] = ()
    resistance_levels: tuple[Level, ...] = ()


def find_swings(
    high: pd.Series,
    low: pd.Series,
    strength: int = 2,
) -> tuple[list[SwingPoint], list[SwingPoint]]:
    """Locate fractal swing highs and lows.

    `strength` is the number of bars required on each side. The last
    `strength` bars can never qualify — a swing is only confirmed once
    enough bars have formed after it.
    """
    if strength < 1:
        raise ValueError("strength must be at least 1")

    highs: list[SwingPoint] = []
    lows: list[SwingPoint] = []

    n = len(high)

    if n < strength * 2 + 1:
        return highs, lows

    high_values = high.to_numpy(dtype=float)
    low_values = low.to_numpy(dtype=float)

    for i in range(strength, n - strength):
        window = slice(i - strength, i + strength + 1)

        centre_high = high_values[i]
        centre_low = low_values[i]

        # Strict on one side keeps a flat run from producing a swing at
        # every bar in the plateau.
        if centre_high == high_values[window].max() and all(
            centre_high > high_values[j] for j in range(i - strength, i)
        ):
            highs.append(SwingPoint(index=i, price=float(centre_high), kind="high"))

        if centre_low == low_values[window].min() and all(
            centre_low < low_values[j] for j in range(i - strength, i)
        ):
            lows.append(SwingPoint(index=i, price=float(centre_low), kind="low"))

    return highs, lows


def cluster_levels(
    swings: list[SwingPoint],
    tolerance: float,
    kind: str,
) -> list[Level]:
    """Group swings that sit within `tolerance` of each other."""
    if not swings or tolerance <= 0:
        return []

    ordered = sorted(swings, key=lambda s: s.price)

    clusters: list[list[float]] = [[ordered[0].price]]

    for swing in ordered[1:]:
        current = clusters[-1]
        centre = sum(current) / len(current)

        if abs(swing.price - centre) <= tolerance:
            current.append(swing.price)
        else:
            clusters.append([swing.price])

    return [
        Level(
            price=round(sum(group) / len(group), 8),
            touches=len(group),
            kind=kind,
        )
        for group in clusters
    ]


def analyse_structure(
    frame: pd.DataFrame,
    strength: int = 2,
    lookback: int = 100,
    tolerance: float | None = None,
) -> StructureResult:
    """Derive structure from the most recent `lookback` bars.

    `support` and `resistance` are the nearest clustered levels below and
    above the current price. Both are None when no qualifying swing
    exists, rather than falling back to an arbitrary window extreme.
    """
    if frame.empty:
        return StructureResult((), (), None, None, None, None)

    window = frame.tail(lookback)

    high = window["high"]
    low = window["low"]
    price = float(window["close"].iloc[-1])

    highs, lows = find_swings(high, low, strength)

    if tolerance is None:
        # Scale with the instrument: a fixed pip tolerance cannot serve
        # both EUR/USD and GOLD.
        span = float(high.max() - low.min())
        tolerance = span * 0.02 if span > 0 else 0.0

    resistance_levels = cluster_levels(highs, tolerance, "resistance")
    support_levels = cluster_levels(lows, tolerance, "support")

    below = [level for level in support_levels if level.price < price]
    above = [level for level in resistance_levels if level.price > price]

    return StructureResult(
        swing_highs=tuple(highs),
        swing_lows=tuple(lows),
        support=max(below, key=lambda level: level.price).price if below else None,
        resistance=min(above, key=lambda level: level.price).price if above else None,
        recent_high=float(high.max()),
        recent_low=float(low.min()),
        support_levels=tuple(support_levels),
        resistance_levels=tuple(resistance_levels),
    )
