"""Turns a signal into a concrete, risk-defined trade plan.

Entirely deterministic. Every number here is arithmetic over values the
analysis engine already produced — there is no forecasting, and nothing
in this module consults a language model.

The distinction that matters: a *plan* says "if you took this, here is
what it would cost and where it would be wrong". It does not say the
trade will work. `viability` gates whether the setup is even mechanically
tradeable, and `opposing` exists so the case against is as visible as the
case for.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.fortrade.models import Account, Quote, Timeframe
from backend.signals.engine import Bias, Signal


class Viability(str, Enum):
    TRADEABLE = "TRADEABLE"
    NO_DIRECTION = "NO_DIRECTION"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    NO_VOLATILITY_READING = "NO_VOLATILITY_READING"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"


#: Stop and target as ATR multiples, matching the paper engine so a plan
#: and the position it would open agree with each other.
STOP_ATR = 1.5
TARGET_ATR = 3.0

#: A stop nearer than this many spreads is unreachable — the position
#: opens on one side of the book and can only close on the other.
MIN_STOP_SPREAD_MULTIPLE = 2.0

DEFAULT_RISK_PERCENT = 1.0


class TradePlan(BaseModel):
    """What this setup would look like as a trade. Not a recommendation."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: Timeframe
    bias: Bias
    score: int

    viability: Viability = Viability.NO_DIRECTION
    viable: bool = False

    entry: float | None = None
    stop: float | None = None
    target: float | None = None

    #: Reward divided by risk, in price terms.
    risk_reward: float | None = None

    size: float | None = None
    risk_amount: float | None = None
    risk_percent: float = DEFAULT_RISK_PERCENT
    currency: str | None = None

    #: The level that would say this read was wrong.
    invalidation: float | None = None

    spread: float | None = None
    atr: float | None = None

    supporting: tuple[str, ...] = ()
    opposing: tuple[str, ...] = ()

    #: How much evidence exists that any of this works. Usually none yet.
    evidence: str = ""

    warnings: tuple[str, ...] = ()

    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))


#: Fragments marking a reason as cautionary rather than supportive.
#:
#: The signal engine emits all of its reasons into one list, mixing the
#: directional case with warnings about conditions. Presenting that list
#: as "supporting" puts arguments against the trade under a heading that
#: says they are for it.
_CAUTION_MARKERS = (
    "widens stops",
    "little room",
    "stretched",
    "inconclusive",
    "squeezed",
    "approaching resistance",
    "changed sign",
    "not in a consistent order",
    "unavailable",
)


def _is_caution(reason: str) -> bool:
    lowered = reason.lower()

    return any(marker in lowered for marker in _CAUTION_MARKERS)


def _partition_reasons(signal: Signal) -> tuple[list[str], list[str]]:
    """Split the engine's reasons into the case for and the case against."""
    supporting = [r for r in signal.reasons if not _is_caution(r)]
    cautions = [r for r in signal.reasons if _is_caution(r)]

    return supporting, cautions


def _opposing_factors(signal: Signal, spread: float | None) -> list[str]:
    """Everything arguing against the trade.

    Assembled separately from the supporting case on purpose. A plan that
    lists only reasons to enter is an advert, not an analysis.
    """
    against: list[str] = []

    for component, label in (
        (signal.trend_score, "trend"),
        (signal.momentum_score, "momentum"),
        (signal.structure_score, "structure"),
        (signal.timeframe_score, "timeframe agreement"),
    ):
        if component < 10:
            against.append(f"The {label} component disagrees ({component}/20).")

    if signal.volatility_score < 10:
        against.append(
            f"Conditions score poorly for tradeability ({signal.volatility_score}/20)."
        )

    if not signal.reliable:
        against.append(
            f"Only {signal.bars_used} bars of history; readings are provisional."
        )

    rsi = signal.indicators.rsi14

    if rsi is not None:
        if signal.bias is Bias.LONG and rsi >= 70:
            against.append(f"RSI {rsi:.0f} is already stretched to the upside.")
        elif signal.bias is Bias.SHORT and rsi <= 30:
            against.append(f"RSI {rsi:.0f} is already stretched to the downside.")

    atr = signal.indicators.atr14

    if spread is not None and atr is not None and atr > 0 and spread / atr > 0.5:
        against.append(
            f"The spread is {spread / atr:.0%} of one ATR — "
            "costly relative to the move being targeted."
        )

    return against


def build_plan(
    signal: Signal,
    quote: Quote | None = None,
    account: Account | None = None,
    risk_percent: float = DEFAULT_RISK_PERCENT,
    paper_trades_closed: int = 0,
    paper_trades_required: int = 20,
) -> TradePlan:
    """Compose the plan, refusing rather than inventing a tradeable setup."""
    spread = quote.spread if quote else None
    atr = signal.indicators.atr14

    supporting, cautions = _partition_reasons(signal)

    evidence = (
        f"{paper_trades_closed} of {paper_trades_required} paper trades "
        "closed. Until that threshold is reached this system has no measured "
        f"record, and {signal.score}/100 describes component agreement rather "
        "than odds."
    )

    base: dict[str, Any] = {
        "symbol": signal.symbol,
        "timeframe": signal.timeframe,
        "bias": signal.bias,
        "score": signal.score,
        "spread": spread,
        "atr": atr,
        "risk_percent": risk_percent,
        "evidence": evidence,
        "supporting": tuple(supporting[:5]),
        # Cautions the engine emitted alongside the directional case
        # belong here, not under a heading that reads as endorsement.
        "opposing": tuple(
            dict.fromkeys([*_opposing_factors(signal, spread), *cautions])
        ),
    }

    if signal.bias is Bias.WAIT:
        return TradePlan(
            **base,
            viability=Viability.NO_DIRECTION,
            warnings=("No side has enough agreement to justify a position.",),
        )

    if signal.bars_used == 0:
        return TradePlan(
            **base,
            viability=Viability.INSUFFICIENT_HISTORY,
            warnings=("No candle history for this series.",),
        )

    if atr is None or atr <= 0:
        return TradePlan(
            **base,
            viability=Viability.NO_VOLATILITY_READING,
            warnings=("No ATR, so no defensible stop distance.",),
        )

    # Enter on the side of the book the trade would actually fill at.
    if quote is not None:
        entry = quote.buy if signal.bias is Bias.LONG else quote.sell
    elif signal.price is not None:
        entry = signal.price
    else:
        return TradePlan(
            **base,
            viability=Viability.NO_VOLATILITY_READING,
            warnings=("No price available.",),
        )

    stop_distance = atr * STOP_ATR
    target_distance = atr * TARGET_ATR

    if (
        spread is not None
        and spread > 0
        and stop_distance < spread * MIN_STOP_SPREAD_MULTIPLE
    ):
        return TradePlan(
            **base,
            entry=round(entry, 8),
            viability=Viability.SPREAD_TOO_WIDE,
            warnings=(
                f"The stop ({stop_distance:.5f}) sits inside the spread "
                f"({spread:.5f}), so the position would open already beyond "
                "it. Not tradeable at this spread — usually means the market "
                "is closed or illiquid.",
            ),
        )

    if signal.bias is Bias.LONG:
        stop = entry - stop_distance
        target = entry + target_distance
    else:
        stop = entry + stop_distance
        target = entry - target_distance

    equity = account.equity if account else None

    risk_amount = equity * (risk_percent / 100.0) if equity else None
    size = risk_amount / stop_distance if risk_amount else None

    return TradePlan(
        **base,
        viability=Viability.TRADEABLE,
        viable=True,
        entry=round(entry, 8),
        stop=round(stop, 8),
        target=round(target, 8),
        risk_reward=round(target_distance / stop_distance, 2),
        size=round(size, 2) if size else None,
        risk_amount=round(risk_amount, 2) if risk_amount else None,
        currency=account.currency if account else None,
        invalidation=round(stop, 8),
        warnings=(
            "Sizing is arithmetic from your equity and the ATR stop. It is "
            "not a recommendation to risk that amount.",
        ),
    )
