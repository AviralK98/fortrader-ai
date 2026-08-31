"""Paper trading: sizing, spread handling, exits and persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.analysis.engine import Indicators
from backend.backtest.metrics import MINIMUM_TRADES
from backend.fortrade.models import Quote, Timeframe
from backend.paper.engine import (
    CloseReason,
    PaperConfig,
    TradeStatus,
    entry_price_for,
    evaluate_exit,
    exit_price_for,
    mark_to_market,
    plan_trade,
    realise,
)
from backend.paper.service import PaperTradingService
from backend.signals.engine import Bias, Signal
from backend.storage.database import Database
from backend.storage.repositories import PaperTradeRepository

ATR = 0.0010


@pytest.fixture
def repo(tmp_path: Path) -> PaperTradeRepository:
    database = Database(tmp_path / "paper.sqlite3")
    database.initialise()

    return PaperTradeRepository(database)


@pytest.fixture
def service(repo: PaperTradeRepository) -> PaperTradingService:
    return PaperTradingService(repo, PaperConfig(min_score=70))


def quote(sell: float = 1.3500, buy: float = 1.3502) -> Quote:
    return Quote(symbol="GBP/USD", sell=sell, buy=buy)


def signal(
    bias: Bias = Bias.LONG,
    score: int = 80,
    atr: float | None = ATR,
    symbol: str = "GBP/USD",
    timeframe: Timeframe = Timeframe.M5,
) -> Signal:
    return Signal(
        symbol=symbol,
        timeframe=timeframe,
        bias=bias,
        score=score,
        indicators=Indicators(atr14=atr),
        reasons=("EMA alignment supports the upside.",),
    )


class TestSpreadHandling:
    def test_long_enters_at_the_ask_and_exits_at_the_bid(self) -> None:
        q = quote(sell=1.3500, buy=1.3502)

        assert entry_price_for(Bias.LONG, q) == pytest.approx(1.3502)
        assert exit_price_for(Bias.LONG, q) == pytest.approx(1.3500)

    def test_short_enters_at_the_bid_and_exits_at_the_ask(self) -> None:
        q = quote(sell=1.3500, buy=1.3502)

        assert entry_price_for(Bias.SHORT, q) == pytest.approx(1.3500)
        assert exit_price_for(Bias.SHORT, q) == pytest.approx(1.3502)

    def test_an_instantly_closed_trade_loses_the_spread(self) -> None:
        # Using the mid on both sides would hand every trade half the
        # spread for free.
        planned = plan_trade(signal(), quote())

        assert planned is not None

        opened = _as_trade(planned)

        _, r = realise(opened, exit_price_for(Bias.LONG, quote()))

        assert r < 0


def _as_trade(planned, trade_id: int = 1):  # type: ignore[no-untyped-def]
    from backend.paper.engine import PaperTrade

    return PaperTrade(
        id=trade_id,
        symbol=planned.symbol,
        timeframe=planned.timeframe,
        direction=planned.direction,
        entry=planned.entry,
        stop=planned.stop,
        target=planned.target,
        size=planned.size,
        opened_at=datetime.now(tz=timezone.utc),
    )


class TestPlanning:
    def test_sizes_so_a_stop_costs_the_risk_budget(self) -> None:
        config = PaperConfig(starting_equity=10_000, risk_fraction=0.01)

        planned = plan_trade(signal(), quote(), config)

        assert planned is not None

        risk_per_unit = abs(planned.entry - planned.stop)

        assert planned.size * risk_per_unit == pytest.approx(100.0, rel=1e-6)

    def test_stop_and_target_follow_atr_multiples(self) -> None:
        config = PaperConfig(stop_atr=1.5, target_atr=3.0)

        planned = plan_trade(signal(), quote(), config)

        assert planned is not None
        assert planned.entry - planned.stop == pytest.approx(ATR * 1.5)
        assert planned.target - planned.entry == pytest.approx(ATR * 3.0)

    def test_short_places_the_stop_above_entry(self) -> None:
        planned = plan_trade(signal(bias=Bias.SHORT), quote())

        assert planned is not None
        assert planned.stop > planned.entry
        assert planned.target < planned.entry

    def test_declines_a_wait_signal(self) -> None:
        assert plan_trade(signal(bias=Bias.WAIT), quote()) is None

    def test_declines_below_the_score_threshold(self) -> None:
        config = PaperConfig(min_score=75)

        assert plan_trade(signal(score=74), quote(), config) is None
        assert plan_trade(signal(score=75), quote(), config) is not None

    def test_declines_without_an_atr(self) -> None:
        # No ATR means no defensible stop distance.
        assert plan_trade(signal(atr=None), quote()) is None
        assert plan_trade(signal(atr=0.0), quote()) is None

    def test_records_the_entry_reason(self) -> None:
        planned = plan_trade(signal(), quote())

        assert planned is not None
        assert "LONG" in planned.entry_reason
        assert "80" in planned.entry_reason

    def test_refuses_when_the_stop_sits_inside_the_spread(self) -> None:
        # Observed live: GBP/USD out of hours had a 124-point spread
        # against a 1.5 x ATR stop of 24 points. The position was entered
        # at one side of the book and had to close at the other, booking
        # -5.1R instantly. Such a trade must never be opened.
        wide = Quote(symbol="GBP/USD", sell=1.35284, buy=1.35408)

        assert plan_trade(signal(atr=0.000161), wide) is None

    def test_allows_a_stop_comfortably_outside_the_spread(self) -> None:
        tight = Quote(symbol="GBP/USD", sell=1.3500, buy=1.3501)

        # Stop of 1.5 x 0.001 = 0.0015 against a 0.0001 spread.
        assert plan_trade(signal(atr=0.001), tight) is not None

    def test_the_spread_multiple_is_enforced(self) -> None:
        quote_ = Quote(symbol="GBP/USD", sell=1.3500, buy=1.3502)

        # Spread 0.0002; stop 1.5 x 0.0002 = 0.0003, which is 1.5 spreads.
        lenient = PaperConfig(min_stop_spread_multiple=1.0)
        strict = PaperConfig(min_stop_spread_multiple=3.0)

        assert plan_trade(signal(atr=0.0002), quote_, lenient) is not None
        assert plan_trade(signal(atr=0.0002), quote_, strict) is None

    def test_rejects_impossible_config(self) -> None:
        with pytest.raises(ValueError):
            PaperConfig(min_stop_spread_multiple=0.5).validated()

        for config in (
            PaperConfig(starting_equity=0),
            PaperConfig(risk_fraction=0),
            PaperConfig(risk_fraction=1.0),
            PaperConfig(stop_atr=0),
        ):
            with pytest.raises(ValueError):
                config.validated()


class TestExits:
    def _open_long(self):  # type: ignore[no-untyped-def]
        planned = plan_trade(signal(), quote())
        assert planned is not None
        return _as_trade(planned)

    def test_long_stops_out(self) -> None:
        trade = self._open_long()

        below = trade.stop - 0.0001
        outcome = evaluate_exit(trade, quote(sell=below, buy=below + 0.0002))

        assert outcome is not None
        assert outcome[1] is CloseReason.STOP

    def test_long_hits_target(self) -> None:
        trade = self._open_long()

        above = trade.target + 0.0001 if trade.target else 2.0
        outcome = evaluate_exit(trade, quote(sell=above, buy=above + 0.0002))

        assert outcome is not None
        assert outcome[1] is CloseReason.TARGET

    def test_no_exit_inside_the_range(self) -> None:
        trade = self._open_long()

        assert evaluate_exit(trade, quote()) is None

    def test_short_stops_out_on_a_rise(self) -> None:
        planned = plan_trade(signal(bias=Bias.SHORT), quote())
        assert planned is not None
        trade = _as_trade(planned)

        above = trade.stop + 0.0001
        outcome = evaluate_exit(trade, quote(sell=above - 0.0002, buy=above))

        assert outcome is not None
        assert outcome[1] is CloseReason.STOP

    def test_r_multiple_is_minus_one_at_the_stop(self) -> None:
        trade = self._open_long()

        _, r = realise(trade, trade.stop)

        assert r == pytest.approx(-1.0)

    def test_r_multiple_is_plus_two_at_a_two_r_target(self) -> None:
        trade = self._open_long()

        assert trade.target is not None

        _, r = realise(trade, trade.target)

        assert r == pytest.approx(2.0)

    def test_pnl_scales_with_size(self) -> None:
        trade = self._open_long()

        pnl, _ = realise(trade, trade.stop)

        # Risking 1% of a 10,000 notional account.
        assert pnl == pytest.approx(-100.0, rel=1e-6)


class TestMarkToMarket:
    def test_attaches_unrealised_figures(self) -> None:
        planned = plan_trade(signal(), quote())
        assert planned is not None

        marked = mark_to_market(_as_trade(planned), quote(1.3550, 1.3552))

        assert marked.current_price == pytest.approx(1.3550)
        assert marked.unrealised_r is not None
        assert marked.unrealised_r > 0


class TestService:
    def test_opens_and_persists(self, service: PaperTradingService) -> None:
        trade = service.maybe_open(signal(), quote(), force=True)

        assert trade is not None
        assert trade.status is TradeStatus.OPEN
        assert len(service.open_positions()) == 1

    def test_one_position_per_series(self, service: PaperTradingService) -> None:
        assert service.maybe_open(signal(), quote(), force=True) is not None
        # Entries must not stack on the same symbol and timeframe.
        assert service.maybe_open(signal(), quote(), force=True) is None

        assert len(service.open_positions()) == 1

    def test_different_timeframes_are_separate_series(
        self, service: PaperTradingService
    ) -> None:
        service.maybe_open(signal(timeframe=Timeframe.M5), quote(), force=True)
        service.maybe_open(signal(timeframe=Timeframe.H1), quote(), force=True)

        assert len(service.open_positions()) == 2

    def test_auto_open_respects_the_switch(
        self, repo: PaperTradeRepository
    ) -> None:
        service = PaperTradingService(repo, PaperConfig(auto_open=False))

        assert service.maybe_open(signal(), quote()) is None
        # An explicit request still works.
        assert service.maybe_open(signal(), quote(), force=True) is not None

    def test_auto_open_is_rate_limited(
        self, repo: PaperTradeRepository
    ) -> None:
        service = PaperTradingService(
            repo, PaperConfig(evaluation_interval_seconds=3600)
        )

        assert service.maybe_open(signal(), quote()) is not None

        # Close it, then confirm the interval blocks an immediate re-entry.
        opened = service.open_positions()[0]
        service.close_manually(opened.id, [quote()])

        assert service.maybe_open(signal(), quote()) is None

    def test_closes_on_stop(self, service: PaperTradingService) -> None:
        trade = service.maybe_open(signal(), quote(), force=True)
        assert trade is not None

        below = trade.stop - 0.0002
        closed = service.update_from_quotes([quote(below, below + 0.0002)])

        assert len(closed) == 1
        assert closed[0].r_multiple is not None
        assert closed[0].r_multiple < 0
        assert service.open_positions() == []

    def test_manual_close(self, service: PaperTradingService) -> None:
        trade = service.maybe_open(signal(), quote(), force=True)
        assert trade is not None

        assert service.close_manually(trade.id, [quote()]) is True
        assert service.open_positions() == []
        assert len(service.closed_positions()) == 1

    def test_closing_an_unknown_trade_fails(
        self, service: PaperTradingService
    ) -> None:
        assert service.close_manually(999, [quote()]) is False

    def test_quotes_for_other_symbols_are_ignored(
        self, service: PaperTradingService
    ) -> None:
        service.maybe_open(signal(), quote(), force=True)

        other = Quote(symbol="EUR/USD", sell=1.0, buy=1.0001)

        assert service.update_from_quotes([other]) == []
        assert len(service.open_positions()) == 1

    def test_summary_tracks_equity(self, service: PaperTradingService) -> None:
        trade = service.maybe_open(signal(), quote(), force=True)
        assert trade is not None

        below = trade.stop - 0.0002
        service.update_from_quotes([quote(below, below + 0.0002)])

        summary = service.summary()

        assert summary.closed_trades == 1
        assert summary.realised_pnl < 0
        assert summary.equity < summary.starting_equity

    def test_positions_survive_a_new_service(
        self, repo: PaperTradeRepository
    ) -> None:
        PaperTradingService(repo).maybe_open(signal(), quote(), force=True)

        # A restart must not lose the record.
        assert len(PaperTradingService(repo).open_positions()) == 1


class TestServiceMetrics:
    def test_holds_the_same_evidence_bar_as_the_backtester(
        self, service: PaperTradingService
    ) -> None:
        trade = service.maybe_open(signal(), quote(), force=True)
        assert trade is not None

        below = trade.stop - 0.0002
        service.update_from_quotes([quote(below, below + 0.0002)])

        metrics = service.metrics()

        assert metrics.trades == 1
        assert metrics.sufficient is False
        assert metrics.win_rate is None
        assert metrics.minimum_trades == MINIMUM_TRADES

    def test_no_trades_yet(self, service: PaperTradingService) -> None:
        metrics = service.metrics()

        assert metrics.trades == 0
        assert metrics.sufficient is False
