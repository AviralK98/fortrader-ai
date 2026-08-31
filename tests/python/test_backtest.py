"""Backtest metrics and the walk-forward engine.

The properties that matter here are the ones that make a backtest
trustworthy rather than flattering: no lookahead, pessimistic intrabar
resolution, and withheld statistics when the sample is too small.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import pairwise

import pytest

from backend.backtest.engine import (
    BacktestParams,
    ExitReason,
    OpenPosition,
    _resolve_exit,
    run_backtest,
)
from backend.backtest.metrics import (
    MINIMUM_TRADES,
    ClosedTrade,
    compute_metrics,
    max_consecutive_losses,
    max_drawdown_percent,
)
from backend.fortrade.models import Candle, Timeframe
from backend.signals.engine import Bias

BASE = datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc)


def candle(
    index: int,
    close: float,
    high: float | None = None,
    low: float | None = None,
    open_: float | None = None,
) -> Candle:
    return Candle(
        symbol="GBP/USD",
        timeframe=Timeframe.M5,
        timestamp=BASE + timedelta(minutes=5 * index),
        open=close if open_ is None else open_,
        high=close + 0.001 if high is None else high,
        low=close - 0.001 if low is None else low,
        close=close,
        complete=True,
    )


def uptrend(n: int = 400) -> list[Candle]:
    return [candle(i, 1.30 + i * 0.0008) for i in range(n)]


def trades_from(r_values: list[float]) -> list[ClosedTrade]:
    return [ClosedTrade(r_multiple=r) for r in r_values]


class TestDrawdown:
    def test_no_losses_means_no_drawdown(self) -> None:
        assert max_drawdown_percent([1.0, 2.0, 1.0]) == 0.0

    def test_single_loss(self) -> None:
        # One trade losing 1R at 1% risk: equity 1.0 -> 0.99.
        assert max_drawdown_percent([-1.0], 0.01) == pytest.approx(1.0, abs=0.01)

    def test_measures_peak_to_trough_not_start_to_end(self) -> None:
        # At 1% risk: 1.0 -> 1.05 (peak) -> 1.0185 -> higher again.
        # The decline from the peak is 0.0315 / 1.05 = 3.0%, which is
        # larger than the start-to-end change of +1.9%.
        drawdown = max_drawdown_percent([5.0, -3.0, 1.0], 0.01)

        assert drawdown == pytest.approx(3.0, abs=0.01)

    def test_empty_history(self) -> None:
        assert max_drawdown_percent([]) == 0.0

    def test_never_negative(self) -> None:
        assert max_drawdown_percent([-1.0] * 50, 0.01) >= 0.0


class TestConsecutiveLosses:
    def test_counts_the_longest_run(self) -> None:
        assert max_consecutive_losses([-1, -1, 2, -1, -1, -1, 3]) == 3

    def test_zero_when_no_losses(self) -> None:
        assert max_consecutive_losses([1.0, 2.0]) == 0

    def test_a_breakeven_trade_breaks_the_run(self) -> None:
        assert max_consecutive_losses([-1, 0.0, -1]) == 1

    def test_all_losses(self) -> None:
        assert max_consecutive_losses([-1.0] * 7) == 7


class TestMetrics:
    def test_no_trades_is_reported_not_faked(self) -> None:
        metrics = compute_metrics([])

        assert metrics.trades == 0
        assert metrics.sufficient is False
        assert metrics.win_rate is None
        assert any("No trades" in w for w in metrics.warnings)

    def test_withholds_statistics_on_a_small_sample(self) -> None:
        metrics = compute_metrics(trades_from([1.0, -1.0, 2.0]))

        # Counts are facts and are reported; derived figures are not.
        assert metrics.trades == 3
        assert metrics.wins == 2
        assert metrics.sufficient is False
        assert metrics.win_rate is None
        assert metrics.profit_factor is None
        assert metrics.expectancy_r is None
        assert any("carry meaning" in w for w in metrics.warnings)

    def test_reports_statistics_once_the_sample_is_large_enough(self) -> None:
        metrics = compute_metrics(trades_from([2.0, -1.0] * (MINIMUM_TRADES // 2)))

        assert metrics.sufficient is True
        assert metrics.win_rate == pytest.approx(50.0)
        assert metrics.average_win_r == pytest.approx(2.0)
        assert metrics.average_loss_r == pytest.approx(-1.0)
        assert metrics.expectancy_r == pytest.approx(0.5)
        assert metrics.profit_factor == pytest.approx(2.0)

    def test_profit_factor_undefined_without_losses(self) -> None:
        metrics = compute_metrics(trades_from([1.0] * MINIMUM_TRADES))

        # Infinity would imply an infinitely good strategy; it is a
        # sample-size artefact.
        assert metrics.profit_factor is None
        assert any("undefined" in w for w in metrics.warnings)

    def test_counts_breakeven_separately(self) -> None:
        metrics = compute_metrics(trades_from([0.0] * MINIMUM_TRADES))

        assert metrics.breakeven == MINIMUM_TRADES
        assert metrics.wins == 0
        assert metrics.losses == 0

    def test_expectancy_is_the_mean_r(self) -> None:
        values = [3.0, -1.0, -1.0, -1.0] * (MINIMUM_TRADES // 4)

        metrics = compute_metrics(trades_from(values))

        assert metrics.expectancy_r == pytest.approx(sum(values) / len(values))

    def test_a_losing_strategy_reports_negative_expectancy(self) -> None:
        metrics = compute_metrics(trades_from([-1.0, 0.5] * (MINIMUM_TRADES // 2)))

        assert metrics.expectancy_r is not None
        assert metrics.expectancy_r < 0
        assert metrics.profit_factor is not None
        assert metrics.profit_factor < 1.0


class TestIntrabarResolution:
    """A bar's range cannot say which level was touched first."""

    def test_long_stop_is_assumed_when_both_are_inside_the_bar(self) -> None:
        bar = candle(0, 1.30, high=1.40, low=1.20)

        outcome = _resolve_exit(bar, Bias.LONG, stop=1.25, target=1.35)

        # The optimistic reading is how backtests flatter themselves.
        assert outcome == (1.25, ExitReason.STOP)

    def test_short_stop_is_assumed_when_both_are_inside_the_bar(self) -> None:
        bar = candle(0, 1.30, high=1.40, low=1.20)

        outcome = _resolve_exit(bar, Bias.SHORT, stop=1.35, target=1.25)

        assert outcome == (1.35, ExitReason.STOP)

    def test_target_alone(self) -> None:
        bar = candle(0, 1.36, high=1.37, low=1.34)

        assert _resolve_exit(bar, Bias.LONG, 1.30, 1.35) == (
            1.35,
            ExitReason.TARGET,
        )

    def test_neither_level_touched(self) -> None:
        bar = candle(0, 1.32, high=1.33, low=1.31)

        assert _resolve_exit(bar, Bias.LONG, 1.30, 1.35) is None


class TestEngineGuards:
    def test_refuses_on_insufficient_history(self) -> None:
        result = run_backtest("GBP/USD", Timeframe.M5, uptrend(50))

        assert result.ran is False
        assert result.trades == ()
        assert any("at least" in w for w in result.warnings)

    def test_no_candles_at_all(self) -> None:
        result = run_backtest("GBP/USD", Timeframe.M5, [])

        assert result.ran is False
        assert result.metrics.sufficient is False

    def test_rejects_invalid_parameters(self) -> None:
        for params in (
            BacktestParams(stop_atr=0),
            BacktestParams(target_atr=-1),
            BacktestParams(max_bars_held=0),
            BacktestParams(warmup_bars=0),
        ):
            with pytest.raises(ValueError):
                params.validated()

    def test_warns_that_a_frictionless_test_flatters(self) -> None:
        result = run_backtest(
            "GBP/USD",
            Timeframe.M5,
            uptrend(400),
            BacktestParams(warmup_bars=250, spread=0.0),
        )

        assert any("Frictionless" in w for w in result.warnings)


class TestNoLookahead:
    def test_entry_uses_the_bar_after_the_signal(self) -> None:
        candles = uptrend(400)

        result = run_backtest(
            "GBP/USD",
            Timeframe.M5,
            candles,
            BacktestParams(warmup_bars=250, min_score=55),
        )

        assert result.ran is True

        for trade in result.trades:
            # The fill price must be the open of the entry bar, which the
            # signal window never included.
            assert trade.entry_price == pytest.approx(
                candles[trade.entry_index].open
            )
            assert trade.exit_index > trade.entry_index

    def test_trades_never_start_before_the_warmup(self) -> None:
        result = run_backtest(
            "GBP/USD",
            Timeframe.M5,
            uptrend(400),
            BacktestParams(warmup_bars=250, min_score=55),
        )

        for trade in result.trades:
            assert trade.entry_index > 250


class TestEngineBehaviour:
    def test_produces_long_trades_in_an_uptrend(self) -> None:
        result = run_backtest(
            "GBP/USD",
            Timeframe.M5,
            uptrend(400),
            BacktestParams(warmup_bars=250, min_score=55),
        )

        assert result.ran is True
        assert len(result.trades) > 0
        assert all(t.direction is Bias.LONG for t in result.trades)

    def test_only_one_position_at_a_time(self) -> None:
        result = run_backtest(
            "GBP/USD",
            Timeframe.M5,
            uptrend(400),
            BacktestParams(warmup_bars=250, min_score=55),
        )

        ordered = sorted(result.trades, key=lambda t: t.entry_index)

        for earlier, later in pairwise(ordered):
            assert later.entry_index > earlier.exit_index

    def test_a_higher_score_bar_takes_fewer_trades(self) -> None:
        lenient = run_backtest(
            "GBP/USD", Timeframe.M5, uptrend(400),
            BacktestParams(warmup_bars=250, min_score=55),
        )
        strict = run_backtest(
            "GBP/USD", Timeframe.M5, uptrend(400),
            BacktestParams(warmup_bars=250, min_score=99),
        )

        assert len(strict.trades) <= len(lenient.trades)

    def test_spread_reduces_every_result(self) -> None:
        free = run_backtest(
            "GBP/USD", Timeframe.M5, uptrend(400),
            BacktestParams(warmup_bars=250, min_score=55, spread=0.0),
        )
        costed = run_backtest(
            "GBP/USD", Timeframe.M5, uptrend(400),
            BacktestParams(warmup_bars=250, min_score=55, spread=0.0005),
        )

        assert costed.metrics.total_r < free.metrics.total_r

    def test_is_deterministic(self) -> None:
        candles = uptrend(400)
        params = BacktestParams(warmup_bars=250, min_score=55)

        first = run_backtest("GBP/USD", Timeframe.M5, candles, params)
        second = run_backtest("GBP/USD", Timeframe.M5, candles, params)

        assert [t.r_multiple for t in first.trades] == [
            t.r_multiple for t in second.trades
        ]

    def test_reports_the_tested_range(self) -> None:
        result = run_backtest(
            "GBP/USD", Timeframe.M5, uptrend(400),
            BacktestParams(warmup_bars=250),
        )

        assert result.range_start is not None
        assert result.range_end is not None
        assert result.range_end > result.range_start


def test_open_position_is_typed() -> None:
    position = OpenPosition(
        direction=Bias.LONG,
        entry_index=1,
        entry_price=1.30,
        stop=1.29,
        target=1.32,
        risk=0.01,
        score=70,
    )

    assert position.direction is Bias.LONG
    assert position.risk == pytest.approx(0.01)
