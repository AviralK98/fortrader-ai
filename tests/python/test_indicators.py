"""Indicator correctness.

Where possible the expected value is derived analytically (a constant
series, an unbroken advance) rather than pinned to whatever the code
currently emits, so these tests can actually fail.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.analysis.indicators import (
    atr,
    ema,
    last_value,
    macd,
    rolling_volatility,
    rsi,
    sma,
    true_range,
    vwap,
    wilder_rma,
)


def series(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype=float)


class TestSma:
    def test_matches_hand_calculation(self) -> None:
        result = sma(series([1, 2, 3, 4, 5]), 3)

        assert np.isnan(result.iloc[1])
        assert result.iloc[2] == pytest.approx(2.0)
        assert result.iloc[4] == pytest.approx(4.0)

    def test_undefined_before_the_window_fills(self) -> None:
        result = sma(series([1, 2, 3]), 3)

        assert result.iloc[:2].isna().all()
        assert result.iloc[2] == pytest.approx(2.0)

    def test_rejects_a_non_positive_period(self) -> None:
        with pytest.raises(ValueError):
            sma(series([1, 2, 3]), 0)


class TestEma:
    def test_constant_series_returns_the_constant(self) -> None:
        result = ema(series([5.0] * 30), 10)

        assert result.dropna().eq(5.0).all()

    def test_is_seeded_with_the_simple_average(self) -> None:
        # Platform convention: the first EMA value is the SMA, not the
        # first observation.
        values = series([1, 2, 3, 4, 5, 6, 7, 8])

        assert ema(values, 4).iloc[3] == pytest.approx(2.5)

    def test_recursion_matches_hand_calculation(self) -> None:
        values = series([1, 2, 3, 4, 5])
        alpha = 2 / (4 + 1)

        expected = alpha * 5 + (1 - alpha) * 2.5

        assert ema(values, 4).iloc[4] == pytest.approx(expected)

    def test_undefined_when_history_is_short(self) -> None:
        assert ema(series([1, 2, 3]), 10).isna().all()

    def test_reacts_faster_than_a_longer_ema(self) -> None:
        values = series([10.0] * 40 + [20.0] * 10)

        fast = last_value(ema(values, 5))
        slow = last_value(ema(values, 30))

        assert fast is not None and slow is not None
        assert fast > slow


class TestWilderRma:
    def test_uses_one_over_period_smoothing(self) -> None:
        values = series([1, 2, 3, 4, 5])
        alpha = 1 / 4

        expected = alpha * 5 + (1 - alpha) * 2.5

        assert wilder_rma(values, 4).iloc[4] == pytest.approx(expected)

    def test_differs_from_ema_of_the_same_period(self) -> None:
        values = series(list(range(1, 21)))

        assert last_value(wilder_rma(values, 5)) != pytest.approx(
            last_value(ema(values, 5))
        )


class TestRsi:
    def test_unbroken_advance_is_one_hundred(self) -> None:
        assert last_value(rsi(series(list(range(1, 40))), 14)) == pytest.approx(100.0)

    def test_unbroken_decline_is_zero(self) -> None:
        assert last_value(rsi(series(list(range(40, 1, -1))), 14)) == pytest.approx(0.0)

    def test_unchanged_market_is_fifty(self) -> None:
        # No strength in either direction.
        assert last_value(rsi(series([10.0] * 40), 14)) == pytest.approx(50.0)

    def test_stays_within_bounds(self) -> None:
        rng = np.random.default_rng(42)
        values = series(list(100 + rng.normal(0, 1, 300).cumsum()))

        result = rsi(values, 14).dropna()

        assert result.between(0.0, 100.0).all()

    def test_symmetric_zigzag_sits_near_the_midpoint(self) -> None:
        values = series([10.0 + (i % 2) for i in range(60)])

        result = last_value(rsi(values, 14))

        assert result is not None
        assert 40.0 < result < 60.0

    def test_undefined_when_history_is_short(self) -> None:
        assert rsi(series([1, 2, 3]), 14).isna().all()

    def test_known_wilder_example(self) -> None:
        # First 15 closes of Wilder's own worked example.
        closes = series(
            [
                44.34,
                44.09,
                44.15,
                43.61,
                44.33,
                44.83,
                45.10,
                45.42,
                45.84,
                46.08,
                45.89,
                46.03,
                45.61,
                46.28,
                46.28,
            ]
        )

        result = last_value(rsi(closes, 14))

        assert result is not None
        assert result == pytest.approx(70.46, abs=0.15)


class TestMacd:
    def test_constant_series_has_no_divergence(self) -> None:
        result = macd(series([5.0] * 100))

        assert last_value(result.line) == pytest.approx(0.0, abs=1e-9)
        assert last_value(result.histogram) == pytest.approx(0.0, abs=1e-9)

    def test_histogram_is_line_minus_signal(self) -> None:
        rng = np.random.default_rng(7)
        values = series(list(100 + rng.normal(0, 1, 200).cumsum()))

        result = macd(values)

        line = last_value(result.line)
        signal = last_value(result.signal)
        histogram = last_value(result.histogram)

        assert line is not None and signal is not None and histogram is not None
        assert histogram == pytest.approx(line - signal)

    def test_rising_market_gives_a_positive_line(self) -> None:
        assert (last_value(macd(series(list(range(1, 200)))).line) or 0) > 0

    def test_falling_market_gives_a_negative_line(self) -> None:
        assert (last_value(macd(series(list(range(200, 1, -1)))).line) or 0) < 0

    def test_signal_is_undefined_before_the_line_exists(self) -> None:
        result = macd(series(list(range(1, 30))))

        assert result.signal.iloc[:25].isna().all()

    def test_rejects_inverted_periods(self) -> None:
        with pytest.raises(ValueError):
            macd(series([1.0] * 50), fast=26, slow=12)


class TestTrueRangeAndAtr:
    def test_true_range_uses_the_widest_span(self) -> None:
        high = series([10, 12])
        low = series([9, 11])
        close = series([9.5, 11.5])

        # Gap up: high(12) - prev close(9.5) = 2.5 beats the 1.0 bar range.
        assert true_range(high, low, close).iloc[1] == pytest.approx(2.5)

    def test_first_bar_falls_back_to_its_own_range(self) -> None:
        result = true_range(series([10]), series([8]), series([9]))

        assert result.iloc[0] == pytest.approx(2.0)

    def test_atr_of_constant_range_equals_that_range(self) -> None:
        n = 40
        high = series([11.0] * n)
        low = series([10.0] * n)
        close = series([10.5] * n)

        assert last_value(atr(high, low, close, 14)) == pytest.approx(1.0)

    def test_atr_is_never_negative(self) -> None:
        rng = np.random.default_rng(3)
        close = pd.Series(100 + rng.normal(0, 1, 200).cumsum())
        high = close + rng.uniform(0, 1, 200)
        low = close - rng.uniform(0, 1, 200)

        assert (atr(high, low, close, 14).dropna() >= 0).all()

    def test_atr_grows_when_ranges_widen(self) -> None:
        calm_h, calm_l = series([10.1] * 60), series([10.0] * 60)
        wild_h = series([10.1] * 30 + [12.0] * 30)
        wild_l = series([10.0] * 30 + [8.0] * 30)
        close = series([10.05] * 60)

        calm = last_value(atr(calm_h, calm_l, close, 14))
        wild = last_value(atr(wild_h, wild_l, close, 14))

        assert calm is not None and wild is not None
        assert wild > calm


class TestVolatility:
    def test_constant_series_has_zero_volatility(self) -> None:
        assert last_value(rolling_volatility(series([10.0] * 60), 20)) == pytest.approx(
            0.0
        )

    def test_noisier_series_is_more_volatile(self) -> None:
        rng = np.random.default_rng(11)
        calm = series(list(100 + rng.normal(0, 0.05, 200).cumsum()))
        wild = series(list(100 + rng.normal(0, 2.0, 200).cumsum()))

        calm_v = last_value(rolling_volatility(calm, 20))
        wild_v = last_value(rolling_volatility(wild, 20))

        assert calm_v is not None and wild_v is not None
        assert wild_v > calm_v

    def test_annualisation_scales_by_root_periods(self) -> None:
        rng = np.random.default_rng(5)
        values = series(list(100 + rng.normal(0, 1, 200).cumsum()))

        plain = last_value(rolling_volatility(values, 20))
        scaled = last_value(rolling_volatility(values, 20, annualise_periods=252))

        assert plain is not None and scaled is not None
        assert scaled == pytest.approx(plain * np.sqrt(252))

    def test_rejects_a_degenerate_window(self) -> None:
        with pytest.raises(ValueError):
            rolling_volatility(series([1.0, 2.0]), 1)


class TestVwap:
    def test_equals_typical_price_when_volume_is_uniform(self) -> None:
        high = series([11.0, 11.0])
        low = series([9.0, 9.0])
        close = series([10.0, 10.0])
        volume = series([100.0, 100.0])

        assert last_value(vwap(high, low, close, volume)) == pytest.approx(10.0)

    def test_weights_towards_the_heavier_bar(self) -> None:
        high = series([10.0, 20.0])
        low = series([10.0, 20.0])
        close = series([10.0, 20.0])
        volume = series([1.0, 99.0])

        result = last_value(vwap(high, low, close, volume))

        assert result is not None
        assert result > 19.0


class TestLastValue:
    def test_returns_the_final_defined_value(self) -> None:
        assert last_value(series([1.0, 2.0, np.nan])) == pytest.approx(2.0)

    def test_none_when_never_defined(self) -> None:
        assert last_value(pd.Series([np.nan, np.nan])) is None

    def test_none_for_an_empty_series(self) -> None:
        assert last_value(pd.Series([], dtype=float)) is None

    def test_none_for_an_infinite_value(self) -> None:
        assert last_value(series([1.0, np.inf])) is None
