"""Signal, snapshot, quote and backtest persistence, plus retention."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.fortrade.models import (
    Account,
    DataSourceKind,
    MarketSnapshot,
    Quote,
    Timeframe,
)
from backend.signals.engine import Bias, Signal
from backend.storage.database import Database
from backend.storage.repositories import (
    BacktestRepository,
    QuoteRepository,
    Retention,
    RetentionPolicy,
    SignalRepository,
    SnapshotRepository,
)

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "persist.sqlite3")
    database.initialise()

    return database


def make_signal(
    bias: Bias = Bias.LONG,
    score: int = 76,
    symbol: str = "GBP/USD",
    timeframe: Timeframe = Timeframe.M5,
) -> Signal:
    return Signal(
        symbol=symbol,
        timeframe=timeframe,
        bias=bias,
        score=score,
        trend_score=20,
        momentum_score=16,
        structure_score=15,
        volatility_score=9,
        timeframe_score=16,
        support=1.35,
        resistance=1.36,
        reasons=("EMA alignment supports the upside.",),
        warnings=("VWAP unavailable.",),
    )


class TestSignalRepository:
    def test_round_trips_a_signal(self, db: Database) -> None:
        repo = SignalRepository(db)
        repo.save(make_signal())

        latest = repo.latest("GBP/USD", Timeframe.M5)

        assert latest is not None
        assert latest["bias"] == "LONG"
        assert latest["score"] == 76
        assert latest["reasons"] == ["EMA alignment supports the upside."]
        assert latest["warnings"] == ["VWAP unavailable."]

    def test_indicators_survive_as_structured_data(self, db: Database) -> None:
        repo = SignalRepository(db)
        repo.save(make_signal())

        latest = repo.latest("GBP/USD", Timeframe.M5)

        assert latest is not None
        assert isinstance(latest["indicators"], dict)

    def test_unchanged_signals_are_not_duplicated(self, db: Database) -> None:
        # The UI polls every ten seconds; storing each poll would bury the
        # actual decisions.
        repo = SignalRepository(db)

        assert repo.save_if_changed(make_signal()) is not None
        assert repo.save_if_changed(make_signal()) is None
        assert repo.save_if_changed(make_signal()) is None

        assert len(repo.recent()) == 1

    def test_a_score_change_is_recorded(self, db: Database) -> None:
        repo = SignalRepository(db)

        repo.save_if_changed(make_signal(score=76))
        repo.save_if_changed(make_signal(score=81))

        assert len(repo.recent()) == 2

    def test_a_bias_change_is_recorded(self, db: Database) -> None:
        repo = SignalRepository(db)

        repo.save_if_changed(make_signal(bias=Bias.LONG))
        repo.save_if_changed(make_signal(bias=Bias.SHORT))

        assert len(repo.recent()) == 2

    def test_filters_by_symbol_and_timeframe(self, db: Database) -> None:
        repo = SignalRepository(db)

        repo.save(make_signal(symbol="GBP/USD", timeframe=Timeframe.M5))
        repo.save(make_signal(symbol="EUR/USD", timeframe=Timeframe.M5))
        repo.save(make_signal(symbol="GBP/USD", timeframe=Timeframe.H1))

        assert len(repo.recent(symbol="GBP/USD")) == 2
        assert len(repo.recent(timeframe=Timeframe.H1)) == 1
        assert len(repo.recent("GBP/USD", Timeframe.M5)) == 1

    def test_returns_newest_first(self, db: Database) -> None:
        repo = SignalRepository(db)

        for score in (60, 70, 80):
            repo.save(make_signal(score=score))

        assert [row["score"] for row in repo.recent()] == [80, 70, 60]

    def test_empty_repository(self, db: Database) -> None:
        repo = SignalRepository(db)

        assert repo.recent() == []
        assert repo.latest("GBP/USD", Timeframe.M5) is None


class TestQuoteRepository:
    def _quotes(self) -> list[Quote]:
        return [
            Quote(symbol="GBP/USD", sell=1.35284, buy=1.35408, spread_points=124),
            Quote(symbol="EUR/USD", sell=1.15811, buy=1.15836, spread_points=25),
        ]

    def test_writes_the_first_sample(self, db: Database) -> None:
        repo = QuoteRepository(db)

        assert repo.save_sampled(self._quotes()) == 2
        assert repo.count() == 2

    def test_rate_limits_repeated_writes(self, db: Database) -> None:
        # Ingest runs every two seconds; without sampling this table would
        # gain tens of thousands of near-identical rows per day.
        repo = QuoteRepository(db, min_interval_seconds=3600)

        repo.save_sampled(self._quotes())

        assert repo.save_sampled(self._quotes()) == 0
        assert repo.count() == 2

    def test_sampling_is_per_symbol(self, db: Database) -> None:
        repo = QuoteRepository(db, min_interval_seconds=3600)

        repo.save_sampled([self._quotes()[0]])

        # A symbol not yet written is still due.
        assert repo.save_sampled(self._quotes()) == 1

    def test_zero_interval_writes_every_time(self, db: Database) -> None:
        repo = QuoteRepository(db, min_interval_seconds=0)

        repo.save_sampled(self._quotes())
        repo.save_sampled(self._quotes())

        assert repo.count() == 4

    def test_counts_by_symbol(self, db: Database) -> None:
        repo = QuoteRepository(db, min_interval_seconds=0)
        repo.save_sampled(self._quotes())

        assert repo.count("GBP/USD") == 1

    def test_empty_input(self, db: Database) -> None:
        assert QuoteRepository(db).save_sampled([]) == 0


class TestSnapshotRepository:
    def test_round_trips(self, db: Database) -> None:
        repo = SnapshotRepository(db)

        snapshot = MarketSnapshot(
            account=Account(
                balance=10000.0,
                equity=10000.0,
                open_pnl=0.0,
                used_margin=0.0,
                available_margin=10000.0,
                currency="GBP",
                source=DataSourceKind.DOM,
            ),
            quotes=(Quote(symbol="GBP/USD", sell=1.35, buy=1.36),),
        )

        assert repo.save(snapshot) > 0
        assert repo.count() == 1


class TestBacktestRepository:
    def _result(self):  # type: ignore[no-untyped-def]
        from backend.backtest.engine import BacktestResult
        from backend.backtest.metrics import BacktestMetrics

        return BacktestResult(
            symbol="GBP/USD",
            timeframe=Timeframe.M5,
            bars_available=500,
            bars_tested=250,
            range_start=NOW - timedelta(days=1),
            range_end=NOW,
            metrics=BacktestMetrics(
                trades=30,
                wins=17,
                losses=13,
                win_rate=56.67,
                average_win_r=1.4,
                average_loss_r=-1.0,
                expectancy_r=0.36,
                profit_factor=1.83,
                max_drawdown_pct=8.7,
                max_consecutive_losses=4,
                sufficient=True,
            ),
            params={"stop_atr": 1.5},
            ran=True,
        )

    def test_saves_run_and_metrics(self, db: Database) -> None:
        repo = BacktestRepository(db)

        run_id = repo.save(self._result())
        record = repo.get(run_id)

        assert record is not None
        assert record["symbol"] == "GBP/USD"
        assert record["trades"] == 30
        assert record["win_rate"] == pytest.approx(56.67)
        assert record["max_drawdown_pct"] == pytest.approx(8.7)
        assert record["params"] == {"stop_atr": 1.5}

    def test_lists_recent_runs(self, db: Database) -> None:
        repo = BacktestRepository(db)

        repo.save(self._result())
        repo.save(self._result())

        assert len(repo.recent()) == 2

    def test_unknown_run(self, db: Database) -> None:
        assert BacktestRepository(db).get(999) is None


class TestRetention:
    def test_prunes_only_what_is_past_its_policy(self, db: Database) -> None:
        signals = SignalRepository(db)
        quotes = QuoteRepository(db, min_interval_seconds=0)

        quotes.save_sampled([Quote(symbol="GBP/USD", sell=1.35, buy=1.36)])
        signals.save(make_signal())

        # Nothing is old yet.
        removed = Retention(db, RetentionPolicy()).run(NOW)

        assert removed == {"quotes": 0, "snapshots": 0, "signals": 0}
        assert quotes.count() == 1
        assert len(signals.recent()) == 1

    def test_prunes_beyond_the_window(self, db: Database) -> None:
        quotes = QuoteRepository(db, min_interval_seconds=0)
        quotes.save_sampled([Quote(symbol="GBP/USD", sell=1.35, buy=1.36)])

        # Far enough in the future that the row is past its retention.
        removed = Retention(db, RetentionPolicy(quote_days=1)).run(
            NOW + timedelta(days=400)
        )

        assert removed["quotes"] == 1
        assert quotes.count() == 0

    def test_candles_are_never_pruned(self, db: Database) -> None:
        # Candles are only captured when the user opens a chart, and are
        # the input to backtesting. Losing them is expensive.
        from backend.fortrade.models import Candle
        from backend.storage.repositories import CandleRepository

        candles = CandleRepository(db)
        candles.upsert_many(
            [
                Candle(
                    symbol="GBP/USD",
                    timeframe=Timeframe.M5,
                    timestamp=datetime(2020, 1, 1, tzinfo=timezone.utc),
                    open=1.3,
                    high=1.31,
                    low=1.29,
                    close=1.3,
                )
            ]
        )

        Retention(db, RetentionPolicy(quote_days=1, signal_days=1)).run(
            NOW + timedelta(days=4000)
        )

        assert candles.count("GBP/USD", Timeframe.M5) == 1
