"""Trend, momentum, structure, volatility and the composed engine.

Series are constructed so the correct answer is knowable in advance.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from backend.analysis.engine import MINIMUM_BARS, RELIABLE_BARS, analyse
from backend.analysis.frames import candles_to_frame, has_volume
from backend.analysis.momentum import MomentumDirection, analyse_momentum
from backend.analysis.structure import (
    analyse_structure,
    cluster_levels,
    find_swings,
)
from backend.analysis.trend import TrendDirection, analyse_trend
from backend.analysis.volatility import VolatilityRegime, analyse_volatility
from backend.fortrade.models import Candle, Timeframe

BASE = datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc)


def make_candles(
    closes: list[float],
    spread: float = 0.001,
    volume: float | None = None,
    complete: bool = True,
) -> list[Candle]:
    return [
        Candle(
            symbol="GBP/USD",
            timeframe=Timeframe.M5,
            timestamp=BASE + timedelta(minutes=5 * i),
            open=close,
            high=close + spread,
            low=close - spread,
            close=close,
            volume=volume,
            complete=complete,
        )
        for i, close in enumerate(closes)
    ]


def frame_from(closes: list[float], spread: float = 0.001) -> pd.DataFrame:
    return candles_to_frame(make_candles(closes, spread))


def rising(n: int = 300, step: float = 0.001) -> list[float]:
    return [1.30 + i * step for i in range(n)]


def falling(n: int = 300, step: float = 0.001) -> list[float]:
    return [1.30 + (n - i) * step for i in range(n)]


def choppy(n: int = 300, seed: int = 17) -> list[float]:
    """Driftless random walk — the honest shape of a directionless market."""
    rng = np.random.default_rng(seed)

    return list(1.30 + np.cumsum(rng.normal(0.0, 0.0004, n)))


def noisy_rise(n: int = 300, seed: int = 3) -> list[float]:
    """Trend plus noise, which is what real data looks like."""
    rng = np.random.default_rng(seed)

    return list(1.30 + np.cumsum(rng.normal(0.0006, 0.0006, n)))


def noisy_fall(n: int = 300, seed: int = 4) -> list[float]:
    rng = np.random.default_rng(seed)

    return list(1.60 + np.cumsum(rng.normal(-0.0006, 0.0006, n)))


class TestFrames:
    def test_drops_the_forming_bar(self) -> None:
        candles = make_candles([1.0, 2.0, 3.0])
        candles[-1] = candles[-1].model_copy(update={"complete": False})

        assert len(candles_to_frame(candles)) == 2

    def test_can_retain_the_forming_bar_when_asked(self) -> None:
        candles = make_candles([1.0, 2.0, 3.0])
        candles[-1] = candles[-1].model_copy(update={"complete": False})

        assert len(candles_to_frame(candles, drop_incomplete=False)) == 3

    def test_sorts_oldest_first(self) -> None:
        candles = list(reversed(make_candles([1.0, 2.0, 3.0])))

        frame = candles_to_frame(candles)

        assert list(frame["close"]) == [1.0, 2.0, 3.0]

    def test_deduplicates_repeated_bars(self) -> None:
        candles = make_candles([1.0, 2.0])

        assert len(candles_to_frame(candles + candles)) == 2

    def test_empty_input_yields_empty_frame(self) -> None:
        frame = candles_to_frame([])

        assert frame.empty
        assert list(frame.columns) == ["open", "high", "low", "close", "volume"]

    def test_volume_absence_is_detected(self) -> None:
        assert has_volume(frame_from([1.0] * 10)) is False

    def test_volume_presence_is_detected(self) -> None:
        assert (
            has_volume(candles_to_frame(make_candles([1.0] * 10, volume=100))) is True
        )


class TestTrend:
    def test_sustained_advance_is_bullish(self) -> None:
        assert analyse_trend(frame_from(rising())).direction is TrendDirection.BULLISH

    def test_sustained_decline_is_bearish(self) -> None:
        assert analyse_trend(frame_from(falling())).direction is TrendDirection.BEARISH

    def test_tangled_averages_are_mixed(self) -> None:
        # Rise, then a sharp reversal: the fast EMAs have rolled over while
        # the slow ones still reflect the advance, so the stack is not
        # ordered in either direction.
        #
        # A driftless random walk is deliberately not used here — one can
        # trend strongly by chance, and classifying that as MIXED would be
        # wrong rather than desirable.
        reversal = rising(200) + [1.30 + 200 * 0.001 - i * 0.002 for i in range(40)]

        assert analyse_trend(frame_from(reversal)).direction is TrendDirection.MIXED

    def test_alignment_is_partial_when_tangled(self) -> None:
        reversal = rising(200) + [1.30 + 200 * 0.001 - i * 0.002 for i in range(40)]

        alignment = analyse_trend(frame_from(reversal)).alignment

        assert 0.0 <= alignment < 1.0

    def test_unknown_without_enough_history(self) -> None:
        result = analyse_trend(frame_from([1.30] * 5))

        assert result.direction is TrendDirection.UNKNOWN

    def test_missing_ema200_is_not_treated_as_bearish(self) -> None:
        # 100 bars: EMA200 cannot resolve, but the trend is clearly up.
        result = analyse_trend(frame_from(rising(100)))

        assert result.ema200 is None
        assert result.direction is TrendDirection.BULLISH

    def test_reports_alignment_and_slope(self) -> None:
        result = analyse_trend(frame_from(rising()))

        assert result.alignment == pytest.approx(1.0)
        assert result.slope is not None and result.slope > 0

    def test_flags_price_above_the_long_average(self) -> None:
        assert analyse_trend(frame_from(rising())).above_ema200 is True

    def test_empty_frame_is_unknown(self) -> None:
        assert analyse_trend(candles_to_frame([])).direction is TrendDirection.UNKNOWN


class TestMomentum:
    def test_advance_reads_as_rising(self) -> None:
        assert (
            analyse_momentum(frame_from(rising())).direction is MomentumDirection.RISING
        )

    def test_noisy_advance_reads_as_rising(self) -> None:
        assert (
            analyse_momentum(frame_from(noisy_rise())).direction
            is MomentumDirection.RISING
        )

    def test_decline_reads_as_falling(self) -> None:
        assert (
            analyse_momentum(frame_from(falling())).direction
            is MomentumDirection.FALLING
        )

    def test_noisy_decline_reads_as_falling(self) -> None:
        assert (
            analyse_momentum(frame_from(noisy_fall())).direction
            is MomentumDirection.FALLING
        )

    def test_float_dust_does_not_cast_a_vote(self) -> None:
        # On a perfectly smooth ramp the MACD histogram converges to zero;
        # its residual is ~1e-16 of price. Counting that as bearish would
        # make a textbook uptrend read NEUTRAL.
        result = analyse_momentum(frame_from(rising()))

        assert result.macd_histogram is not None
        assert abs(result.macd_histogram) < 1e-9
        assert result.direction is MomentumDirection.RISING
        assert "MACD histogram is negative." not in result.reasons

    def test_flat_market_is_neutral(self) -> None:
        assert (
            analyse_momentum(frame_from([1.30] * 200)).direction
            is MomentumDirection.NEUTRAL
        )

    def test_flags_overbought(self) -> None:
        result = analyse_momentum(frame_from(rising()))

        assert result.overbought is True
        assert result.oversold is False

    def test_flags_oversold(self) -> None:
        result = analyse_momentum(frame_from(falling()))

        assert result.oversold is True
        assert result.overbought is False

    def test_rate_of_change_sign_follows_direction(self) -> None:
        assert (analyse_momentum(frame_from(rising())).roc or 0) > 0
        assert (analyse_momentum(frame_from(falling())).roc or 0) < 0

    def test_gives_reasons(self) -> None:
        assert len(analyse_momentum(frame_from(rising())).reasons) > 0


class TestStructure:
    def test_finds_an_obvious_swing_high(self) -> None:
        high = pd.Series([1, 2, 3, 9, 3, 2, 1], dtype=float)
        low = pd.Series([1, 1, 1, 1, 1, 1, 1], dtype=float)

        highs, _ = find_swings(high, low, strength=2)

        assert [s.index for s in highs] == [3]
        assert highs[0].price == pytest.approx(9.0)

    def test_finds_an_obvious_swing_low(self) -> None:
        high = pd.Series([9] * 7, dtype=float)
        low = pd.Series([5, 4, 3, 1, 3, 4, 5], dtype=float)

        _, lows = find_swings(high, low, strength=2)

        assert [s.index for s in lows] == [3]

    def test_flat_series_produces_no_swings(self) -> None:
        flat = pd.Series([1.0] * 20)

        highs, lows = find_swings(flat, flat, strength=2)

        assert highs == [] and lows == []

    def test_too_short_produces_no_swings(self) -> None:
        short = pd.Series([1.0, 2.0, 3.0])

        assert find_swings(short, short, strength=2) == ([], [])

    def test_rejects_zero_strength(self) -> None:
        with pytest.raises(ValueError):
            find_swings(pd.Series([1.0]), pd.Series([1.0]), strength=0)

    def test_clusters_nearby_levels(self) -> None:
        _, lows = find_swings(
            pd.Series([9.0] * 20),
            pd.Series(
                [5, 4, 3, 1, 3, 4, 5, 4, 3, 1.01, 3, 4, 5, 4, 3, 5, 5, 5, 5, 5],
                dtype=float,
            ),
            strength=2,
        )

        levels = cluster_levels(lows, tolerance=0.5, kind="support")

        # 1.00 and 1.01 are the same level in practice.
        assert any(level.touches >= 2 for level in levels)

    def test_support_sits_below_price_and_resistance_above(self) -> None:
        result = analyse_structure(frame_from(choppy()))

        price = frame_from(choppy())["close"].iloc[-1]

        if result.support is not None:
            assert result.support < price
        if result.resistance is not None:
            assert result.resistance > price

    def test_reports_the_window_extremes(self) -> None:
        result = analyse_structure(frame_from(rising(120)))

        assert result.recent_high is not None
        assert result.recent_low is not None
        assert result.recent_high > result.recent_low

    def test_empty_frame_is_all_none(self) -> None:
        result = analyse_structure(candles_to_frame([]))

        assert result.support is None and result.resistance is None


class TestVolatility:
    def test_steady_ranges_are_normal(self) -> None:
        assert (
            analyse_volatility(frame_from([1.30] * 200)).regime
            is VolatilityRegime.NORMAL
        )

    def test_expansion_is_detected(self) -> None:
        calm = make_candles([1.30] * 150, spread=0.0002)
        wild = make_candles([1.30] * 30, spread=0.01)

        for i, candle in enumerate(wild):
            wild[i] = candle.model_copy(
                update={"timestamp": BASE + timedelta(minutes=5 * (150 + i))}
            )

        result = analyse_volatility(candles_to_frame(calm + wild))

        assert result.regime is VolatilityRegime.HIGH

    def test_atr_percent_is_relative_to_price(self) -> None:
        result = analyse_volatility(frame_from([1.30] * 200, spread=0.0065))

        assert result.atr_percent is not None
        assert result.atr_percent == pytest.approx(1.0, abs=0.05)

    def test_vwap_reported_unavailable_without_volume(self) -> None:
        result = analyse_volatility(frame_from([1.30] * 200))

        assert result.vwap_available is False
        assert result.vwap is None
        assert any("VWAP" in r for r in result.reasons)

    def test_vwap_computed_when_volume_exists(self) -> None:
        frame = candles_to_frame(make_candles([1.30] * 200, volume=1000))

        result = analyse_volatility(frame)

        assert result.vwap_available is True
        assert result.vwap == pytest.approx(1.30, abs=1e-6)

    def test_unknown_without_enough_history(self) -> None:
        assert (
            analyse_volatility(frame_from([1.30] * 15)).regime
            is VolatilityRegime.UNKNOWN
        )


class TestEngine:
    def test_refuses_to_compute_on_too_few_bars(self) -> None:
        result = analyse("GBP/USD", Timeframe.M5, make_candles([1.30] * 5))

        assert result.reliable is False
        assert result.indicators.rsi14 is None
        assert any("at least" in w for w in result.warnings)

    def test_marks_short_history_provisional(self) -> None:
        result = analyse("GBP/USD", Timeframe.M5, make_candles(rising(100)))

        assert result.reliable is False
        assert result.indicators.rsi14 is not None
        assert any("provisional" in w for w in result.warnings)

    def test_full_history_is_reliable(self) -> None:
        result = analyse(
            "GBP/USD", Timeframe.M5, make_candles(rising(RELIABLE_BARS + 50))
        )

        assert result.reliable is True
        assert result.bars_used >= RELIABLE_BARS
        assert not any("provisional" in w for w in result.warnings)

    def test_populates_indicators(self) -> None:
        result = analyse("GBP/USD", Timeframe.M5, make_candles(rising()))

        ind = result.indicators

        assert ind.ema9 is not None
        assert ind.ema200 is not None
        assert ind.rsi14 is not None
        assert ind.macd is not None
        assert ind.atr14 is not None

    def test_classifies_a_rising_market(self) -> None:
        result = analyse("GBP/USD", Timeframe.M5, make_candles(rising()))

        assert result.trend is TrendDirection.BULLISH
        assert result.momentum is MomentumDirection.RISING

    def test_excludes_the_forming_bar_from_the_count(self) -> None:
        candles = make_candles(rising(250))
        candles[-1] = candles[-1].model_copy(update={"complete": False})

        result = analyse("GBP/USD", Timeframe.M5, candles)

        assert result.bars_available == 250
        assert result.bars_used == 249

    def test_warns_when_ema200_cannot_resolve(self) -> None:
        result = analyse("GBP/USD", Timeframe.M5, make_candles(rising(100)))

        assert result.indicators.ema200 is None
        assert any("EMA200" in w for w in result.warnings)

    def test_records_the_last_bar_time(self) -> None:
        result = analyse("GBP/USD", Timeframe.M5, make_candles(rising(100)))

        assert result.last_bar_at is not None

    def test_is_deterministic(self) -> None:
        candles = make_candles(rising())

        first = analyse("GBP/USD", Timeframe.M5, candles)
        second = analyse("GBP/USD", Timeframe.M5, candles)

        assert first.indicators == second.indicators
        assert first.trend == second.trend

    def test_no_bars_at_all(self) -> None:
        result = analyse("GBP/USD", Timeframe.M5, [])

        assert result.bars_used == 0
        assert result.reliable is False
        assert result.price is None


def test_minimum_is_below_reliable_threshold() -> None:
    assert MINIMUM_BARS < RELIABLE_BARS
