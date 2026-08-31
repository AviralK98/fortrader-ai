"""Coordinates simulated positions against live quotes.

Exits are evaluated on every ingest, which is cheap — it is a price
comparison. Entries are evaluated on a slower interval because they
require a full signal computation.

The realised R multiples feed the *same* metrics module the backtester
uses, so a paper record and a backtest are directly comparable and hold to
the same evidence bar: below 20 closed trades the statistics are withheld.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from backend.backtest.metrics import BacktestMetrics, ClosedTrade, compute_metrics
from backend.fortrade.models import Quote, Timeframe
from backend.logging_setup import get_logger
from backend.paper.engine import (
    PaperConfig,
    PaperSummary,
    PaperTrade,
    evaluate_exit,
    exit_price_for,
    mark_to_market,
    plan_trade,
    realise,
)
from backend.signals.engine import Bias, Signal
from backend.storage.repositories import PaperTradeRepository

logger = get_logger(__name__)


class PaperTradingService:
    def __init__(
        self,
        repository: PaperTradeRepository,
        config: PaperConfig = PaperConfig(),
    ) -> None:
        self._repo = repository
        self._config = config.validated()
        self._lock = threading.RLock()
        self._last_evaluation: dict[tuple[str, Timeframe], datetime] = {}

    @property
    def config(self) -> PaperConfig:
        return self._config

    # ---------------------------------------------------------------
    # Exits
    # ---------------------------------------------------------------

    def update_from_quotes(self, quotes: list[Quote]) -> list[PaperTrade]:
        """Close any open position whose stop or target has been reached."""
        by_symbol = {q.symbol.upper(): q for q in quotes}

        closed: list[PaperTrade] = []

        with self._lock:
            for trade in self._repo.open_positions():
                quote = by_symbol.get(trade.symbol.upper())

                if quote is None:
                    continue

                outcome = evaluate_exit(trade, quote)

                if outcome is None:
                    continue

                exit_price, reason = outcome
                pnl, r_multiple = realise(trade, exit_price)

                if self._repo.close_position(
                    trade.id, exit_price, pnl, r_multiple, reason
                ):
                    logger.info(
                        "Paper position closed",
                        extra={
                            "context": {
                                "id": trade.id,
                                "symbol": trade.symbol,
                                "reason": reason.value,
                                "r": r_multiple,
                            }
                        },
                    )

                    closed.append(
                        trade.model_copy(
                            update={
                                "exit_price": exit_price,
                                "pnl": pnl,
                                "r_multiple": r_multiple,
                            }
                        )
                    )

        return closed

    def close_manually(self, trade_id: int, quotes: list[Quote]) -> bool:
        from backend.paper.engine import CloseReason

        by_symbol = {q.symbol.upper(): q for q in quotes}

        with self._lock:
            for trade in self._repo.open_positions():
                if trade.id != trade_id:
                    continue

                quote = by_symbol.get(trade.symbol.upper())

                if quote is None:
                    return False

                exit_price = exit_price_for(trade.direction, quote)
                pnl, r_multiple = realise(trade, exit_price)

                return self._repo.close_position(
                    trade.id, exit_price, pnl, r_multiple, CloseReason.MANUAL
                )

        return False

    # ---------------------------------------------------------------
    # Entries
    # ---------------------------------------------------------------

    def maybe_open(
        self,
        signal: Signal,
        quote: Quote,
        signal_id: int | None = None,
        force: bool = False,
    ) -> PaperTrade | None:
        """Open a position if the signal qualifies and none is running.

        `force` bypasses the auto-open switch and the interval, for an
        explicit request from the UI. It does not bypass the score
        threshold or the one-position-per-series rule.
        """
        with self._lock:
            if not force and not self._config.auto_open:
                return None

            key = (signal.symbol.upper(), signal.timeframe)

            now = datetime.now(tz=timezone.utc)

            if not force:
                last = self._last_evaluation.get(key)

                if (
                    last is not None
                    and (now - last).total_seconds()
                    < self._config.evaluation_interval_seconds
                ):
                    return None

            self._last_evaluation[key] = now

            # One position per series: entries must not stack.
            if self._repo.has_open(signal.symbol, signal.timeframe):
                return None

            planned = plan_trade(signal, quote, self._config)

            if planned is None:
                return None

            trade_id = self._repo.open_position(planned, signal_id)

            logger.info(
                "Paper position opened",
                extra={
                    "context": {
                        "id": trade_id,
                        "symbol": planned.symbol,
                        "timeframe": planned.timeframe.value,
                        "direction": planned.direction.value,
                        "score": signal.score,
                    }
                },
            )

            for trade in self._repo.open_positions(planned.symbol):
                if trade.id == trade_id:
                    return trade

            return None

    # ---------------------------------------------------------------
    # Reporting
    # ---------------------------------------------------------------

    def open_positions(self, quotes: list[Quote] | None = None) -> list[PaperTrade]:
        by_symbol = {q.symbol.upper(): q for q in (quotes or [])}

        positions = self._repo.open_positions()

        return [
            mark_to_market(trade, by_symbol[trade.symbol.upper()])
            if trade.symbol.upper() in by_symbol
            else trade
            for trade in positions
        ]

    def closed_positions(self, limit: int = 200) -> list[PaperTrade]:
        return self._repo.closed_positions(limit)

    def metrics(self) -> BacktestMetrics:
        """Same evidence bar as the backtester, deliberately."""
        return compute_metrics(
            [ClosedTrade(r_multiple=r) for r in self._repo.realised_r()],
            risk_fraction=self._config.risk_fraction,
        )

    def summary(self, quotes: list[Quote] | None = None) -> PaperSummary:
        open_positions = self.open_positions(quotes)

        realised = self._repo.realised_pnl()
        unrealised = sum(t.unrealised_pnl or 0.0 for t in open_positions)

        return PaperSummary(
            open_positions=len(open_positions),
            closed_trades=len(self._repo.realised_r()),
            starting_equity=self._config.starting_equity,
            realised_pnl=round(realised, 4),
            unrealised_pnl=round(unrealised, 4),
            equity=round(self._config.starting_equity + realised + unrealised, 4),
            total_r=round(sum(self._repo.realised_r()), 4),
            auto_open=self._config.auto_open,
        )


__all__ = ["Bias", "PaperTradingService"]
