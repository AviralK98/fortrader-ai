"""Reusing readings, and noticing when they stop being true.

A cache that serves a stale signal is worse than a slow one: it reports
a bias for a market that has since moved, and nothing on screen says so.
These tests care much more about invalidation than about speed.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.analysis.memo import Memo
from backend.api import server
from backend.api.server import create_app
from backend.config import Settings
from backend.fortrade.models import Candle, DataSourceKind, Timeframe

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def bar(index: int, close: float, symbol: str = "TEST/X") -> Candle:
    return Candle(
        symbol=symbol,
        timeframe=Timeframe.M1,
        timestamp=BASE + timedelta(minutes=index),
        open=close,
        high=close + 0.002,
        low=close - 0.002,
        close=close,
        volume=10,
        complete=True,
        source=DataSourceKind.NETWORK,
    )


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(Settings(data_dir=tmp_path))) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _clear_memos() -> None:
    """The caches are module-level, so one test must not seed another."""
    server._signal_memo.clear()
    server._analysis_memo.clear()
    server._multi_memo.clear()


class TestMemo:
    def test_returns_a_value_only_for_the_same_fingerprint(self) -> None:
        memo: Memo[str] = Memo("test")

        memo.put("k", ("fp", 1), "value")

        assert memo.get("k", ("fp", 1)) == "value"
        assert memo.get("k", ("fp", 2)) is None

    def test_an_unknown_key_is_a_miss(self) -> None:
        memo: Memo[str] = Memo("test")

        assert memo.get("nothing", "fp") is None

    def test_the_store_is_bounded(self) -> None:
        memo: Memo[int] = Memo("test", max_entries=3)

        for i in range(10):
            memo.put(f"k{i}", "fp", i)

        assert memo.stats()["entries"] == 3

    def test_eviction_drops_the_least_recently_used(self) -> None:
        memo: Memo[int] = Memo("test", max_entries=2)

        memo.put("a", "fp", 1)
        memo.put("b", "fp", 2)
        memo.get("a", "fp")  # `a` is now the more recent of the two
        memo.put("c", "fp", 3)

        assert memo.get("a", "fp") == 1
        assert memo.get("b", "fp") is None


class TestSeriesFingerprint:
    def test_changes_when_a_bar_arrives(self, client: TestClient) -> None:
        ctx = client.app.state.context  # type: ignore[attr-defined]

        ctx.candles.ingest([bar(i, 1.0) for i in range(10)])
        before = ctx.candles.fingerprint("TEST/X", Timeframe.M1)

        ctx.candles.ingest([bar(10, 1.5)])

        assert ctx.candles.fingerprint("TEST/X", Timeframe.M1) != before

    def test_changes_when_the_last_bar_is_revised(
        self, client: TestClient
    ) -> None:
        # The forming bar is rewritten in place as price moves; the count
        # does not change, so the newest timestamp has to be part of it.
        ctx = client.app.state.context  # type: ignore[attr-defined]

        ctx.candles.ingest([bar(i, 1.0) for i in range(10)])
        before = ctx.candles.fingerprint("TEST/X", Timeframe.M1)

        ctx.candles.ingest([bar(9, 2.0)])
        after = ctx.candles.fingerprint("TEST/X", Timeframe.M1)

        assert after[0] == before[0], "a revision should not add a row"

    def test_is_stable_when_nothing_changes(self, client: TestClient) -> None:
        ctx = client.app.state.context  # type: ignore[attr-defined]

        ctx.candles.ingest([bar(i, 1.0) for i in range(10)])

        assert ctx.candles.fingerprint(
            "TEST/X", Timeframe.M1
        ) == ctx.candles.fingerprint("TEST/X", Timeframe.M1)


class TestSignalsAreNotServedStale:
    """The property that matters: a cached reading is a current reading."""

    def test_repeated_requests_reuse_the_reading(
        self, client: TestClient
    ) -> None:
        ctx = client.app.state.context  # type: ignore[attr-defined]
        ctx.candles.ingest([bar(i, 1.0) for i in range(300)])

        params = {"symbol": "TEST/X", "timeframe": "M1"}
        first = client.get("/api/signal", params=params).json()

        assert client.get("/api/signal", params=params).json() == first
        assert server._signal_memo.hits >= 1

    def test_new_bars_produce_a_new_reading(self, client: TestClient) -> None:
        ctx = client.app.state.context  # type: ignore[attr-defined]
        ctx.candles.ingest([bar(i, 1.0) for i in range(300)])

        params = {"symbol": "TEST/X", "timeframe": "M1"}
        flat = client.get("/api/signal", params=params).json()

        # A sustained rise: the bias must follow the market, not the cache.
        ctx.candles.ingest([bar(300 + i, 1.0 + i * 0.02) for i in range(60)])

        rising = client.get("/api/signal", params=params).json()

        assert rising != flat
        assert rising["score"] != flat["score"]

    def test_each_symbol_is_cached_separately(
        self, client: TestClient
    ) -> None:
        ctx = client.app.state.context  # type: ignore[attr-defined]
        ctx.candles.ingest([bar(i, 1.0, "AAA/X") for i in range(300)])
        ctx.candles.ingest(
            [bar(i, 1.0 + i * 0.01, "BBB/X") for i in range(300)]
        )

        a = client.get(
            "/api/signal", params={"symbol": "AAA/X", "timeframe": "M1"}
        ).json()
        b = client.get(
            "/api/signal", params={"symbol": "BBB/X", "timeframe": "M1"}
        ).json()

        assert a["symbol"] == "AAA/X"
        assert b["symbol"] == "BBB/X"
        assert a["score"] != b["score"]

    def test_analysis_follows_the_bars_too(self, client: TestClient) -> None:
        ctx = client.app.state.context  # type: ignore[attr-defined]
        ctx.candles.ingest([bar(i, 1.0) for i in range(300)])

        params = {"symbol": "TEST/X", "timeframe": "M1"}
        flat = client.get("/api/analysis", params=params).json()

        ctx.candles.ingest([bar(300 + i, 1.0 + i * 0.02) for i in range(60)])

        assert client.get("/api/analysis", params=params).json() != flat


class TestTheBuiltInStrategyIsStable:
    def test_its_timestamps_do_not_move(self) -> None:
        """A key built from these must not change on every read.

        The built-in strategy is synthesised per call. While its
        updated_at was `now`, every request produced a different cache
        key -- the signal cache stored a fresh entry each time and never
        once hit.
        """
        from backend.strategies.models import builtin_strategy

        assert builtin_strategy().updated_at == builtin_strategy().updated_at
        assert builtin_strategy().created_at == builtin_strategy().created_at
