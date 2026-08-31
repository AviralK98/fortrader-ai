from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.fortrade.models import Candle, DataSourceKind, Timeframe
from backend.storage.database import Database
from backend.storage.repositories import CandleRepository, SqliteCandleProvider

BASE = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def repo(tmp_path: Path) -> CandleRepository:
    database = Database(tmp_path / "candles.sqlite3")
    database.initialise()

    return CandleRepository(database)


def candle(
    minutes: int,
    close: float = 1.35,
    symbol: str = "GBP/USD",
    timeframe: Timeframe = Timeframe.M1,
    complete: bool = True,
) -> Candle:
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=BASE + timedelta(minutes=minutes),
        open=1.35,
        high=1.36,
        low=1.34,
        close=close,
        complete=complete,
        source=DataSourceKind.NETWORK,
    )


class TestUpsert:
    def test_inserts_new_bars(self, repo: CandleRepository) -> None:
        assert repo.upsert_many([candle(i) for i in range(10)]) == 10
        assert repo.count("GBP/USD", Timeframe.M1) == 10

    def test_empty_batch_is_a_no_op(self, repo: CandleRepository) -> None:
        assert repo.upsert_many([]) == 0

    def test_reingesting_the_same_bars_adds_none(
        self, repo: CandleRepository
    ) -> None:
        bars = [candle(i) for i in range(10)]

        assert repo.upsert_many(bars) == 10
        # The chart endpoint returns overlapping windows on every load.
        assert repo.upsert_many(bars) == 0
        assert repo.count("GBP/USD", Timeframe.M1) == 10

    def test_overlapping_batches_only_count_new_bars(
        self, repo: CandleRepository
    ) -> None:
        repo.upsert_many([candle(i) for i in range(10)])

        assert repo.upsert_many([candle(i) for i in range(5, 15)]) == 5
        assert repo.count("GBP/USD", Timeframe.M1) == 15

    def test_updates_a_reobserved_bar(self, repo: CandleRepository) -> None:
        repo.upsert_many([candle(0, close=1.30)])
        repo.upsert_many([candle(0, close=1.31)])

        stored = repo.get("GBP/USD", Timeframe.M1)

        assert len(stored) == 1
        assert stored[0].close == pytest.approx(1.31)

    def test_a_closed_bar_never_reverts_to_forming(
        self, repo: CandleRepository
    ) -> None:
        repo.upsert_many([candle(0, complete=True)])
        repo.upsert_many([candle(0, complete=False)])

        assert repo.get("GBP/USD", Timeframe.M1)[0].complete is True

    def test_series_are_isolated(self, repo: CandleRepository) -> None:
        repo.upsert_many(
            [
                candle(0),
                candle(0, timeframe=Timeframe.M5),
                candle(0, symbol="EUR/USD"),
            ]
        )

        assert repo.count("GBP/USD", Timeframe.M1) == 1
        assert repo.count("GBP/USD", Timeframe.M5) == 1
        assert repo.count("EUR/USD", Timeframe.M1) == 1

    def test_symbol_lookup_is_case_insensitive(
        self, repo: CandleRepository
    ) -> None:
        repo.upsert_many([candle(0)])

        assert repo.count("gbp/usd", Timeframe.M1) == 1


class TestRead:
    def test_returns_oldest_first(self, repo: CandleRepository) -> None:
        repo.upsert_many([candle(i) for i in reversed(range(20))])

        stored = repo.get("GBP/USD", Timeframe.M1)
        stamps = [c.timestamp for c in stored]

        assert stamps == sorted(stamps)

    def test_limit_returns_the_most_recent_window(
        self, repo: CandleRepository
    ) -> None:
        repo.upsert_many([candle(i) for i in range(100)])

        stored = repo.get("GBP/USD", Timeframe.M1, limit=10)

        assert len(stored) == 10
        assert stored[-1].timestamp == BASE + timedelta(minutes=99)
        assert stored[0].timestamp == BASE + timedelta(minutes=90)

    def test_round_trips_all_fields(self, repo: CandleRepository) -> None:
        repo.upsert_many([candle(0)])

        stored = repo.get("GBP/USD", Timeframe.M1)[0]

        assert stored.symbol == "GBP/USD"
        assert stored.timeframe is Timeframe.M1
        assert stored.timestamp == BASE
        assert stored.source is DataSourceKind.NETWORK
        assert stored.timestamp.tzinfo is not None

    def test_unknown_series_is_empty(self, repo: CandleRepository) -> None:
        assert repo.get("XAU/USD", Timeframe.H1) == []
        assert repo.count("XAU/USD", Timeframe.H1) == 0


class TestCoverage:
    def test_reports_each_series(self, repo: CandleRepository) -> None:
        repo.upsert_many([candle(i) for i in range(30)])
        repo.upsert_many([candle(i, timeframe=Timeframe.M5) for i in range(4)])

        coverage = {(c.symbol, c.timeframe): c for c in repo.coverage()}

        assert coverage[("GBP/USD", Timeframe.M1)].count == 30
        assert coverage[("GBP/USD", Timeframe.M5)].count == 4

    def test_reports_the_time_range(self, repo: CandleRepository) -> None:
        repo.upsert_many([candle(i) for i in range(10)])

        series = repo.coverage()[0]

        assert series.first == BASE
        assert series.last == BASE + timedelta(minutes=9)

    def test_sufficiency_is_a_threshold_not_a_claim(
        self, repo: CandleRepository
    ) -> None:
        repo.upsert_many([candle(i) for i in range(100)])

        series = repo.coverage()[0]

        assert series.sufficient_for(100) is True
        assert series.sufficient_for(500) is False

    def test_empty_database_reports_nothing(
        self, repo: CandleRepository
    ) -> None:
        assert repo.coverage() == []


class TestProvider:
    def test_satisfies_the_candle_provider_interface(
        self, repo: CandleRepository
    ) -> None:
        provider = SqliteCandleProvider(repo)

        provider.ingest([candle(i) for i in range(5)])

        assert provider.available("GBP/USD", Timeframe.M1) == 5
        assert len(provider.get_candles("GBP/USD", Timeframe.M1, 3)) == 3

    def test_history_survives_a_new_connection(self, tmp_path: Path) -> None:
        # Series are only captured when the user opens that chart, so the
        # data must outlive the process.
        path = tmp_path / "persist.sqlite3"

        first = Database(path)
        first.initialise()
        SqliteCandleProvider(CandleRepository(first)).ingest(
            [candle(i) for i in range(25)]
        )
        first.close()

        second = Database(path)
        second.initialise()

        assert (
            SqliteCandleProvider(CandleRepository(second)).available(
                "GBP/USD", Timeframe.M1
            )
            == 25
        )
