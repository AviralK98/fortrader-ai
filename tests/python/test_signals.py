"""Signal engine and multi-timeframe combination."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from backend.fortrade.models import Candle, Timeframe
from backend.fortrade.source import InMemoryCandleProvider
from backend.signals.config import SCORE_MAX, SignalConfig
from backend.signals.engine import Bias, generate_signal
from backend.signals.multi_timeframe import (
    analyse_timeframes,
    signal_with_timeframes,
)
from backend.signals.scoring import Component, to_component_score

BASE = datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc)


def candles(
    closes: list[float],
    timeframe: Timeframe = Timeframe.M5,
    symbol: str = "GBP/USD",
    spread: float = 0.001,
) -> list[Candle]:
    return [
        Candle(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=BASE + timedelta(minutes=timeframe.minutes * i),
            open=c,
            high=c + spread,
            low=c - spread,
            close=c,
            complete=True,
        )
        for i, c in enumerate(closes)
    ]


def rising(n: int = 300) -> list[float]:
    return [1.30 + i * 0.001 for i in range(n)]


def falling(n: int = 300) -> list[float]:
    return [1.30 + (n - i) * 0.001 for i in range(n)]


def flat(n: int = 300) -> list[float]:
    return [1.30] * n


def drifting(n: int = 300, seed: int = 9) -> list[float]:
    rng = np.random.default_rng(seed)

    return list(1.30 + np.cumsum(rng.normal(0.0, 0.0003, n)))


class TestBias:
    def test_strong_uptrend_is_long(self) -> None:
        signal = generate_signal("GBP/USD", Timeframe.M5, candles(rising()))

        assert signal.bias is Bias.LONG

    def test_strong_downtrend_is_short(self) -> None:
        signal = generate_signal("GBP/USD", Timeframe.M5, candles(falling()))

        assert signal.bias is Bias.SHORT

    def test_flat_market_waits(self) -> None:
        signal = generate_signal("GBP/USD", Timeframe.M5, candles(flat()))

        assert signal.bias is Bias.WAIT

    def test_only_three_biases_exist(self) -> None:
        assert {b.value for b in Bias} == {"LONG", "SHORT", "WAIT"}

    def test_wait_explains_itself(self) -> None:
        signal = generate_signal("GBP/USD", Timeframe.M5, candles(flat()))

        assert any("enough agreement" in r for r in signal.reasons)


class TestScoring:
    def test_score_is_the_sum_of_components(self) -> None:
        signal = generate_signal("GBP/USD", Timeframe.M5, candles(rising()))

        assert signal.score == (
            signal.trend_score
            + signal.momentum_score
            + signal.structure_score
            + signal.volatility_score
            + signal.timeframe_score
        )

    def test_score_stays_in_range(self) -> None:
        for closes in (rising(), falling(), flat(), drifting()):
            signal = generate_signal("GBP/USD", Timeframe.M5, candles(closes))

            assert 0 <= signal.score <= SCORE_MAX

    @pytest.mark.parametrize(
        "field",
        [
            "trend_score",
            "momentum_score",
            "structure_score",
            "volatility_score",
            "timeframe_score",
        ],
    )
    def test_each_component_stays_in_range(self, field: str) -> None:
        signal = generate_signal("GBP/USD", Timeframe.M5, candles(rising()))

        assert 0 <= getattr(signal, field) <= 20

    def test_conviction_is_higher_in_a_clean_trend(self) -> None:
        trending = generate_signal("GBP/USD", Timeframe.M5, candles(rising()))
        drifty = generate_signal("GBP/USD", Timeframe.M5, candles(drifting()))

        assert trending.score > drifty.score

    def test_trend_component_is_maximal_in_a_clean_trend(self) -> None:
        signal = generate_signal("GBP/USD", Timeframe.M5, candles(rising()))

        assert signal.trend_score >= 18

    def test_net_direction_sign_matches_bias(self) -> None:
        assert (
            generate_signal("GBP/USD", Timeframe.M5, candles(rising())).net_direction
            > 0
        )
        assert (
            generate_signal("GBP/USD", Timeframe.M5, candles(falling())).net_direction
            < 0
        )


class TestComponentMapping:
    def test_full_agreement_scores_twenty(self) -> None:
        assert to_component_score(Component(direction=1.0), 1) == 20

    def test_full_opposition_scores_zero(self) -> None:
        assert to_component_score(Component(direction=1.0), -1) == 0

    def test_neutral_scores_ten(self) -> None:
        assert to_component_score(Component(direction=0.0), 1) == 10

    def test_non_directional_uses_quality(self) -> None:
        component = Component(direction=0.0, non_directional=True, quality=0.75)

        # Quality is independent of which way the bias points.
        assert to_component_score(component, 1) == 15
        assert to_component_score(component, -1) == 15

    def test_no_bias_scores_midpoint(self) -> None:
        assert to_component_score(Component(direction=0.9), 0) == 10


class TestStructureReasons:
    def test_squeeze_is_reported_as_one_coherent_reason(self) -> None:
        from backend.analysis.structure import Level, StructureResult
        from backend.signals.config import DEFAULT_CONFIG
        from backend.signals.scoring import score_structure

        # Support and resistance both within an ATR of price.
        structure = StructureResult(
            swing_highs=(),
            swing_lows=(),
            support=1.3499,
            resistance=1.3501,
            recent_high=1.3510,
            recent_low=1.3490,
            support_levels=(Level(1.3499, 2, "support"),),
            resistance_levels=(Level(1.3501, 2, "resistance"),),
        )

        component = score_structure(structure, 1.3500, 0.0005, DEFAULT_CONFIG)

        joined = " ".join(component.reasons)

        assert "squeezed" in joined
        # The contradictory pair must not both appear.
        assert "approaching resistance" not in joined
        assert "holding just above support" not in joined


class TestVolatilityIsNotDirectional:
    def test_volatility_does_not_drive_the_bias(self) -> None:
        # A flat market has calm volatility; if that voted, it would
        # manufacture a direction out of nothing.
        signal = generate_signal("GBP/USD", Timeframe.M5, candles(flat()))

        assert signal.bias is Bias.WAIT
        assert signal.net_direction == pytest.approx(0.0, abs=0.24)


class TestInsufficientHistory:
    def test_waits_when_too_short(self) -> None:
        signal = generate_signal("GBP/USD", Timeframe.M5, candles(rising(10)))

        assert signal.bias is Bias.WAIT
        assert signal.reliable is False
        assert any("required" in w for w in signal.warnings)

    def test_marks_provisional_below_the_reliable_threshold(self) -> None:
        signal = generate_signal("GBP/USD", Timeframe.M5, candles(rising(100)))

        assert signal.reliable is False
        assert any("provisional" in w for w in signal.warnings)

    def test_warns_when_timeframe_agreement_is_absent(self) -> None:
        signal = generate_signal("GBP/USD", Timeframe.M5, candles(rising()))

        assert any("Multi-timeframe" in w for w in signal.warnings)
        # Absent agreement must be neutral, never counted as support.
        assert signal.timeframe_score == 10

    def test_empty_history(self) -> None:
        signal = generate_signal("GBP/USD", Timeframe.M5, [])

        assert signal.bias is Bias.WAIT
        assert signal.bars_used == 0


class TestDeterminism:
    def test_same_input_gives_same_output(self) -> None:
        data = candles(rising())

        first = generate_signal("GBP/USD", Timeframe.M5, data)
        second = generate_signal("GBP/USD", Timeframe.M5, data)

        assert first.score == second.score
        assert first.bias == second.bias
        assert first.net_direction == second.net_direction


class TestConfig:
    def test_rejects_an_impossible_threshold(self) -> None:
        with pytest.raises(ValueError):
            SignalConfig(direction_threshold=0.0).validated()

    def test_rejects_empty_weights(self) -> None:
        with pytest.raises(ValueError):
            SignalConfig(timeframe_weights={}).validated()

    def test_rejects_negative_weights(self) -> None:
        with pytest.raises(ValueError):
            SignalConfig(timeframe_weights={Timeframe.M5: -1.0}).validated()

    def test_weights_are_not_a_flat_average(self) -> None:
        weights = SignalConfig().timeframe_weights

        assert len(set(weights.values())) > 1
        # M1 is the noisiest horizon and must not dominate.
        assert weights[Timeframe.M1] < weights[Timeframe.M15]

    def test_a_higher_threshold_produces_more_waiting(self) -> None:
        data = candles(drifting())

        lenient = generate_signal(
            "GBP/USD", Timeframe.M5, data, 0.3, SignalConfig(direction_threshold=0.05)
        )
        strict = generate_signal(
            "GBP/USD", Timeframe.M5, data, 0.3, SignalConfig(direction_threshold=0.95)
        )

        assert strict.bias is Bias.WAIT
        assert lenient.bias is not Bias.WAIT


class TestMultiTimeframe:
    def _provider(self, series: dict[Timeframe, list[float]]) -> InMemoryCandleProvider:
        provider = InMemoryCandleProvider()

        for timeframe, closes in series.items():
            provider.ingest(candles(closes, timeframe))

        return provider

    def test_aligned_timeframes_agree(self) -> None:
        provider = self._provider(
            {
                tf: rising()
                for tf in (Timeframe.M1, Timeframe.M5, Timeframe.M15, Timeframe.H1)
            }
        )

        result = analyse_timeframes("GBP/USD", provider)

        assert result.overall_bias is Bias.LONG
        assert result.consensus == pytest.approx(1.0)
        assert len(result.included_timeframes) == 4

    def test_aligned_downtrend(self) -> None:
        provider = self._provider(
            {
                tf: falling()
                for tf in (Timeframe.M1, Timeframe.M5, Timeframe.M15, Timeframe.H1)
            }
        )

        assert analyse_timeframes("GBP/USD", provider).overall_bias is Bias.SHORT

    def test_missing_timeframes_are_excluded_not_assumed(self) -> None:
        provider = self._provider({Timeframe.M5: rising()})

        result = analyse_timeframes("GBP/USD", provider)

        assert result.included_timeframes == (Timeframe.M5,)
        assert set(result.missing_timeframes) == {
            Timeframe.M1,
            Timeframe.M15,
            Timeframe.H1,
        }
        assert any("insufficient history" in w for w in result.warnings)

    def test_no_history_at_all_waits(self) -> None:
        result = analyse_timeframes("GBP/USD", InMemoryCandleProvider())

        assert result.overall_bias is Bias.WAIT
        assert result.included_timeframes == ()
        assert result.warnings

    def test_weighting_is_not_a_flat_average(self) -> None:
        # M1 disagrees with the rest; its low weight must not flip the view.
        provider = self._provider(
            {
                Timeframe.M1: falling(),
                Timeframe.M5: rising(),
                Timeframe.M15: rising(),
                Timeframe.H1: rising(),
            }
        )

        result = analyse_timeframes("GBP/USD", provider)

        assert result.overall_bias is Bias.LONG
        assert result.consensus < 1.0

    def test_disagreement_is_flagged(self) -> None:
        provider = self._provider(
            {
                Timeframe.M1: rising(),
                Timeframe.M5: falling(),
                Timeframe.M15: rising(),
                Timeframe.H1: falling(),
            }
        )

        result = analyse_timeframes("GBP/USD", provider)

        if result.overall_bias is not Bias.WAIT:
            assert any("disagree" in w for w in result.warnings)

    def test_every_reading_is_reported(self) -> None:
        provider = self._provider({Timeframe.M5: rising(), Timeframe.M15: rising()})

        result = analyse_timeframes("GBP/USD", provider)

        assert len(result.readings) == 4
        assert {r.timeframe for r in result.readings} == {
            Timeframe.M1,
            Timeframe.M5,
            Timeframe.M15,
            Timeframe.H1,
        }

    def test_combined_score_in_range(self) -> None:
        provider = self._provider(
            {tf: rising() for tf in (Timeframe.M5, Timeframe.M15)}
        )

        result = analyse_timeframes("GBP/USD", provider)

        assert 0 <= result.combined_score <= 100

    def test_signal_uses_the_combined_agreement(self) -> None:
        provider = self._provider(
            {
                tf: rising()
                for tf in (Timeframe.M1, Timeframe.M5, Timeframe.M15, Timeframe.H1)
            }
        )

        signal, multi = signal_with_timeframes("GBP/USD", Timeframe.M5, provider)

        assert multi.overall_bias is Bias.LONG
        assert signal.timeframe_score > 10
        assert not any("Multi-timeframe" in w for w in signal.warnings)


def test_score_is_documented_as_not_a_probability() -> None:
    import backend.signals.engine as engine

    assert "not a probability" in (engine.__doc__ or "").lower()
