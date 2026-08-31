from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.fortrade.models import (
    Account,
    Candle,
    ChartSelection,
    MarketSnapshot,
    Quote,
    Timeframe,
)
from backend.fortrade.source import (
    FixtureDataSource,
    FortradeDataSource,
    FortradeDataUnavailableError,
    InMemoryCandleProvider,
    PushedDataSource,
)


def make_candle(minutes: int, close: float = 1.35) -> Candle:
    return Candle(
        symbol="GBP/USD",
        timeframe=Timeframe.M5,
        timestamp=datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
        + timedelta(minutes=minutes),
        open=1.35,
        high=1.36,
        low=1.34,
        close=close,
    )


class TestFixtureDataSource:
    def test_reads_account(self, page_text: str) -> None:
        account = FixtureDataSource(page_text).get_account()

        assert account.balance == pytest.approx(10000.0)
        assert account.currency == "GBP"

    def test_lists_symbols_sorted(self, page_text: str) -> None:
        symbols = FixtureDataSource(page_text).list_symbols()

        assert symbols == sorted(symbols)
        assert "GBP/USD" in symbols

    def test_snapshot_is_composite(self, page_text: str) -> None:
        snapshot = FixtureDataSource(page_text).snapshot()

        assert snapshot.account is not None
        assert snapshot.chart is not None
        assert len(snapshot.quotes) == 5

    def test_snapshot_tolerates_partial_pages(self) -> None:
        # Account panel only — chart and quotes absent.
        snapshot = FixtureDataSource(
            "Balance\n£10,000.00\nOpen P&L\n£0.00\nEquity\n£10,000.00\n"
            "Used Margin\n£0.00\nAvailable Margin\n£10,000.00"
        ).snapshot()

        assert snapshot.account is not None
        assert snapshot.chart is None
        assert snapshot.quotes == ()


class TestPushedDataSource:
    def test_raises_before_any_ingest(self) -> None:
        source = PushedDataSource()

        with pytest.raises(FortradeDataUnavailableError):
            source.get_account()

        with pytest.raises(FortradeDataUnavailableError):
            source.get_quotes()

        with pytest.raises(FortradeDataUnavailableError):
            source.get_chart()

    def test_positions_default_to_empty_not_error(self) -> None:
        assert PushedDataSource().get_positions() == []

    def test_ingest_then_read(self) -> None:
        source = PushedDataSource()

        source.ingest(
            MarketSnapshot(
                account=Account(
                    balance=10000.0,
                    equity=10000.0,
                    open_pnl=0.0,
                    used_margin=0.0,
                    available_margin=10000.0,
                    currency="GBP",
                ),
                quotes=(Quote(symbol="GBP/USD", sell=1.35284, buy=1.35408),),
                chart=ChartSelection(
                    symbol="GBP/USD", timeframe=Timeframe.M5
                ),
            )
        )

        assert source.get_account().balance == pytest.approx(10000.0)
        assert source.get_quote("GBP/USD").spread == pytest.approx(0.00124)
        assert source.get_chart().timeframe is Timeframe.M5
        assert source.updated_at is not None

    def test_empty_positions_list_clears_previous(self) -> None:
        source = PushedDataSource()

        source.ingest(
            MarketSnapshot(
                quotes=(Quote(symbol="GBP/USD", sell=1.0, buy=1.1),),
            )
        )

        # A flat account is a real observation, not missing data.
        source.ingest(MarketSnapshot(positions=()))

        assert source.get_positions() == []

    def test_absent_sections_do_not_erase_known_state(self) -> None:
        source = PushedDataSource()

        source.ingest(
            MarketSnapshot(
                quotes=(Quote(symbol="GBP/USD", sell=1.0, buy=1.1),),
            )
        )
        source.ingest(MarketSnapshot())

        assert source.get_quotes()[0].symbol == "GBP/USD"


class TestInMemoryCandleProvider:
    def test_returns_time_ordered(self) -> None:
        provider = InMemoryCandleProvider()

        provider.ingest([make_candle(10), make_candle(0), make_candle(5)])

        candles = provider.get_candles("GBP/USD", Timeframe.M5)

        assert [c.timestamp for c in candles] == sorted(
            c.timestamp for c in candles
        )

    def test_deduplicates_by_timestamp(self) -> None:
        provider = InMemoryCandleProvider()

        assert provider.ingest([make_candle(0, close=1.30)]) == 1
        # Re-observing the forming bar updates rather than duplicates.
        assert provider.ingest([make_candle(0, close=1.31)]) == 0

        candles = provider.get_candles("GBP/USD", Timeframe.M5)

        assert len(candles) == 1
        assert candles[0].close == pytest.approx(1.31)

    def test_limit_returns_most_recent(self) -> None:
        provider = InMemoryCandleProvider()

        provider.ingest([make_candle(i * 5) for i in range(10)])

        candles = provider.get_candles("GBP/USD", Timeframe.M5, limit=3)

        assert len(candles) == 3
        assert candles[-1].timestamp == make_candle(45).timestamp

    def test_series_are_isolated_by_symbol_and_timeframe(self) -> None:
        provider = InMemoryCandleProvider()

        provider.ingest([make_candle(0)])

        assert provider.available("GBP/USD", Timeframe.M5) == 1
        assert provider.available("GBP/USD", Timeframe.M1) == 0
        assert provider.available("EUR/USD", Timeframe.M5) == 0

    def test_symbol_lookup_is_case_insensitive(self) -> None:
        provider = InMemoryCandleProvider()

        provider.ingest([make_candle(0)])

        assert provider.available("gbp/usd", Timeframe.M5) == 1

    def test_unknown_series_is_empty_not_error(self) -> None:
        provider = InMemoryCandleProvider()

        assert provider.get_candles("XAU/USD", Timeframe.H1) == []

    def test_evicts_beyond_cap(self) -> None:
        provider = InMemoryCandleProvider(max_per_series=5)

        provider.ingest([make_candle(i * 5) for i in range(12)])

        assert provider.available("GBP/USD", Timeframe.M5) == 5


def test_interface_exposes_no_write_methods() -> None:
    """Order entry must be absent from the type system, not just disabled."""
    forbidden = {
        "open_trade",
        "close_trade",
        "modify_trade",
        "place_order",
        "buy",
        "sell",
        "submit",
    }

    assert not forbidden & set(dir(FortradeDataSource))
