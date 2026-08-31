"""Paper trading — simulated positions only.

A paper trade records what the signal engine *would* have done, tracked
forward against live quotes. Unlike a backtest it cannot be fitted after
the fact: the position is committed before the outcome exists, which is
what makes the resulting record genuine out-of-sample evidence.

Nothing here touches Fortrade. There is no order entry, no mapping to the
platform's buttons, and no code path from a paper trade to a real one. The
application still cannot place a trade.

Realism note: entries and exits use the correct side of the spread — a
long buys at the ask and sells at the bid — so a paper trade pays the real
spread automatically rather than a synthetic estimate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from backend.fortrade.models import Quote, Timeframe
from backend.logging_setup import get_logger
from backend.signals.engine import Bias, Signal

logger = get_logger(__name__)


class TradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CloseReason(str, Enum):
    STOP = "STOP"
    TARGET = "TARGET"
    MANUAL = "MANUAL"


@dataclass(frozen=True)
class PaperConfig:
    """Sizing and entry rules for simulated positions."""

    #: Notional account used for sizing. Independent of the real Fortrade
    #: balance so paper results are never confused with the live account.
    starting_equity: float = 10_000.0

    #: Fraction of the notional account risked per trade.
    risk_fraction: float = 0.01

    #: Stop and target distance as multiples of ATR at entry.
    stop_atr: float = 1.5
    target_atr: float = 3.0

    #: Minimum signal score before a position is opened.
    min_score: int = 70

    #: The stop must sit at least this many spreads away from entry.
    #:
    #: A position whose stop is inside the spread is dead on arrival: it
    #: is entered at one side of the book and must be closed at the other,
    #: which is already past the stop. Wide spreads out of hours make this
    #: routine, so it is refused rather than opened and instantly lost.
    min_stop_spread_multiple: float = 2.0

    #: Open positions automatically as qualifying signals appear.
    auto_open: bool = True

    #: Seconds between automatic entry evaluations.
    evaluation_interval_seconds: float = 60.0

    def validated(self) -> PaperConfig:
        if self.starting_equity <= 0:
            raise ValueError("starting_equity must be positive")

        if not 0 < self.risk_fraction < 1:
            raise ValueError("risk_fraction must be between 0 and 1")

        if self.stop_atr <= 0 or self.target_atr <= 0:
            raise ValueError("stop and target multiples must be positive")

        if self.min_stop_spread_multiple < 1:
            raise ValueError(
                "min_stop_spread_multiple below 1 permits stops inside the "
                "spread, which cannot be traded"
            )

        return self


class PaperTrade(BaseModel):
    """A simulated position. Never mapped to a broker order."""

    model_config = ConfigDict(frozen=True)

    id: int
    symbol: str
    timeframe: Timeframe
    direction: Bias

    entry: float
    stop: float
    target: float | None = None
    size: float

    opened_at: datetime
    closed_at: datetime | None = None

    exit_price: float | None = None
    pnl: float | None = None
    r_multiple: float | None = None

    entry_reason: str | None = None

    #: Links to the stored signal that triggered this trade.
    signal_id: int | None = None

    status: TradeStatus = TradeStatus.OPEN

    #: Mark-to-market values, populated for open positions only.
    current_price: float | None = None
    unrealised_pnl: float | None = None
    unrealised_r: float | None = None

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry - self.stop)


@dataclass(frozen=True)
class PlannedTrade:
    """A position sized and priced, ready to be recorded."""

    symbol: str
    timeframe: Timeframe
    direction: Bias
    entry: float
    stop: float
    target: float
    size: float
    entry_reason: str


def exit_price_for(direction: Bias, quote: Quote) -> float:
    """The price a position would actually close at.

    A long is closed by selling, so it exits at the bid; a short is closed
    by buying, so it exits at the ask. Using the mid would quietly hand
    every trade half the spread.
    """
    return quote.sell if direction is Bias.LONG else quote.buy


def entry_price_for(direction: Bias, quote: Quote) -> float:
    """A long enters at the ask, a short at the bid."""
    return quote.buy if direction is Bias.LONG else quote.sell


def plan_trade(
    signal: Signal,
    quote: Quote,
    config: PaperConfig = PaperConfig(),
) -> PlannedTrade | None:
    """Size a position from a signal, or decline with a reason logged.

    Returns None when the signal does not qualify — a WAIT bias, too low a
    score, or no ATR to derive a stop from.
    """
    config.validated()

    if signal.bias is Bias.WAIT:
        return None

    if signal.score < config.min_score:
        return None

    atr = signal.indicators.atr14

    if atr is None or atr <= 0:
        logger.debug(
            "No ATR available; cannot size a stop",
            extra={"context": {"symbol": signal.symbol}},
        )
        return None

    entry = entry_price_for(signal.bias, quote)

    risk_per_unit = atr * config.stop_atr
    reward_per_unit = atr * config.target_atr

    if risk_per_unit <= 0:
        return None

    # A stop inside the spread is unreachable: the position opens on one
    # side of the book and can only close on the other, which is already
    # beyond the stop. Refusing is the only correct outcome — opening it
    # would book a guaranteed multi-R loss and poison the record.
    required = quote.spread * config.min_stop_spread_multiple

    if quote.spread > 0 and risk_per_unit < required:
        logger.info(
            "Declined paper entry: stop is inside the spread",
            extra={
                "context": {
                    "symbol": signal.symbol,
                    "timeframe": signal.timeframe.value,
                    "stop_distance": round(risk_per_unit, 8),
                    "spread": round(quote.spread, 8),
                    "required": round(required, 8),
                }
            },
        )
        return None

    if signal.bias is Bias.LONG:
        stop = entry - risk_per_unit
        target = entry + reward_per_unit
    else:
        stop = entry + risk_per_unit
        target = entry - reward_per_unit

    # Units such that a move to the stop costs exactly the risk budget.
    risk_amount = config.starting_equity * config.risk_fraction
    size = risk_amount / risk_per_unit

    reason = (
        f"{signal.bias.value} {signal.score}/100 — "
        + (signal.reasons[0] if signal.reasons else "signal engine")
    )

    return PlannedTrade(
        symbol=signal.symbol,
        timeframe=signal.timeframe,
        direction=signal.bias,
        entry=round(entry, 8),
        stop=round(stop, 8),
        target=round(target, 8),
        size=round(size, 4),
        entry_reason=reason[:200],
    )


def evaluate_exit(
    trade: PaperTrade,
    quote: Quote,
) -> tuple[float, CloseReason] | None:
    """Decide whether a live quote closes an open position.

    Unlike the backtester this sees the actual traded price rather than a
    bar summary, so there is no stop-versus-target ambiguity to resolve.
    """
    price = exit_price_for(trade.direction, quote)

    if trade.direction is Bias.LONG:
        if price <= trade.stop:
            return price, CloseReason.STOP

        if trade.target is not None and price >= trade.target:
            return price, CloseReason.TARGET
    else:
        if price >= trade.stop:
            return price, CloseReason.STOP

        if trade.target is not None and price <= trade.target:
            return price, CloseReason.TARGET

    return None


def realise(
    trade: PaperTrade,
    exit_price: float,
) -> tuple[float, float]:
    """Return (pnl, r_multiple) for a closing price."""
    move = (
        exit_price - trade.entry
        if trade.direction is Bias.LONG
        else trade.entry - exit_price
    )

    pnl = move * trade.size

    risk = trade.risk_per_unit

    r_multiple = move / risk if risk > 0 else 0.0

    return round(pnl, 4), round(r_multiple, 4)


def mark_to_market(trade: PaperTrade, quote: Quote) -> PaperTrade:
    """Attach unrealised figures to an open position."""
    price = exit_price_for(trade.direction, quote)

    pnl, r = realise(trade, price)

    return trade.model_copy(
        update={
            "current_price": price,
            "unrealised_pnl": pnl,
            "unrealised_r": r,
        }
    )


class PaperSummary(BaseModel):
    """Headline state of the simulated account."""

    model_config = ConfigDict(frozen=True)

    open_positions: int = 0
    closed_trades: int = 0

    starting_equity: float = 0.0
    realised_pnl: float = 0.0
    unrealised_pnl: float = 0.0
    equity: float = 0.0

    total_r: float = 0.0

    auto_open: bool = True

    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
