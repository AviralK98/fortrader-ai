"""Walk-forward backtester over captured candle history.

The strategy under test is the *actual* signal engine, evaluated bar by
bar over a growing window. Testing a simplified stand-in would measure
something the application never does.

Three rules protect the result from being flattering nonsense:

1. **No lookahead.** A signal computed on bars ``[0..i]`` can only be
   acted on at the open of bar ``i+1``. Indicators never see the bar that
   fills the order.
2. **Pessimistic intrabar resolution.** When a bar's range contains both
   the stop and the target, the stop is assumed to have been hit first.
   Bar data cannot say which came first, and the optimistic reading is
   how backtests flatter themselves.
3. **Insufficient data is reported, not smoothed over.** Too little
   history, or too few trades, yields withheld statistics rather than a
   confident-looking number.

Costs: entries and exits are modelled at the spread supplied by the
caller. With no spread specified the result is frictionless and says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from backend.analysis.frames import candles_to_frame
from backend.backtest.metrics import (
    DEFAULT_RISK_FRACTION,
    MINIMUM_TRADES,
    BacktestMetrics,
    ClosedTrade,
    compute_metrics,
)
from backend.fortrade.models import Candle, Timeframe
from backend.logging_setup import get_logger
from backend.signals.config import DEFAULT_CONFIG, SignalConfig
from backend.signals.engine import Bias, generate_signal

logger = get_logger(__name__)

#: Bars consumed before the first signal, so indicators are warmed up.
DEFAULT_WARMUP = 250


class ExitReason(str, Enum):
    STOP = "STOP"
    TARGET = "TARGET"
    TIME = "TIME"
    END_OF_DATA = "END_OF_DATA"


@dataclass(frozen=True)
class BacktestParams:
    """Strategy and execution assumptions."""

    #: Stop distance as a multiple of ATR at entry.
    stop_atr: float = 1.5

    #: Target distance as a multiple of ATR at entry.
    target_atr: float = 3.0

    #: Bars after which an open trade is abandoned.
    max_bars_held: int = 48

    #: Minimum signal score required to take a trade.
    min_score: int = 65

    warmup_bars: int = DEFAULT_WARMUP

    #: Round-trip cost in price terms. Zero means a frictionless test.
    spread: float = 0.0

    risk_fraction: float = DEFAULT_RISK_FRACTION

    minimum_trades: int = MINIMUM_TRADES

    def validated(self) -> BacktestParams:
        if self.stop_atr <= 0:
            raise ValueError("stop_atr must be positive")

        if self.target_atr <= 0:
            raise ValueError("target_atr must be positive")

        if self.max_bars_held < 1:
            raise ValueError("max_bars_held must be at least 1")

        if self.warmup_bars < 1:
            raise ValueError("warmup_bars must be at least 1")

        return self


@dataclass(frozen=True)
class OpenPosition:
    """A position under simulation.

    A typed record rather than a dict: the fields are read on every bar,
    and an untyped mapping turns each read into a cast.
    """

    direction: Bias
    entry_index: int
    entry_price: float
    stop: float
    target: float
    risk: float
    score: int


class Trade(BaseModel):
    model_config = ConfigDict(frozen=True)

    direction: Bias

    entry_index: int
    entry_at: datetime
    entry_price: float

    stop: float
    target: float

    exit_index: int
    exit_at: datetime
    exit_price: float
    exit_reason: ExitReason

    r_multiple: float
    signal_score: int
    bars_held: int


class BacktestResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: Timeframe
    strategy: str = "signal_engine"

    bars_available: int = 0
    bars_tested: int = 0

    range_start: datetime | None = None
    range_end: datetime | None = None

    metrics: BacktestMetrics = Field(default_factory=BacktestMetrics)
    trades: tuple[Trade, ...] = ()

    params: dict[str, float | int] = Field(default_factory=dict)

    #: False when there was not enough history to run a meaningful test.
    ran: bool = False

    warnings: tuple[str, ...] = ()

    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


def _resolve_exit(
    candle: Candle,
    direction: Bias,
    stop: float,
    target: float,
) -> tuple[float, ExitReason] | None:
    """Decide whether a bar closes the trade, pessimistically.

    A bar reports only its range, so when both levels sit inside it the
    order of touches is unknowable. Assuming the stop first is the
    conservative reading and avoids inflating the result.
    """
    if direction is Bias.LONG:
        hit_stop = candle.low <= stop
        hit_target = candle.high >= target
    else:
        hit_stop = candle.high >= stop
        hit_target = candle.low <= target

    if hit_stop:
        return stop, ExitReason.STOP

    if hit_target:
        return target, ExitReason.TARGET

    return None


def run_backtest(
    symbol: str,
    timeframe: Timeframe,
    candles: list[Candle],
    params: BacktestParams = BacktestParams(),
    config: SignalConfig = DEFAULT_CONFIG,
) -> BacktestResult:
    """Walk the history forward, taking signals as they would have appeared."""
    params.validated()

    frame = candles_to_frame(candles, drop_incomplete=True)

    usable = [c for c in candles if c.complete]
    usable.sort(key=lambda c: c.timestamp)

    # De-duplicate, keeping the last observation of each bar.
    seen: dict[datetime, Candle] = {c.timestamp: c for c in usable}
    ordered = [seen[stamp] for stamp in sorted(seen)]

    bars = len(ordered)

    param_summary: dict[str, float | int] = {
        "stop_atr": params.stop_atr,
        "target_atr": params.target_atr,
        "max_bars_held": params.max_bars_held,
        "min_score": params.min_score,
        "warmup_bars": params.warmup_bars,
        "spread": params.spread,
    }

    # One warmup window plus room for at least a few trades.
    required = params.warmup_bars + params.max_bars_held + 2

    if bars < required:
        return BacktestResult(
            symbol=symbol,
            timeframe=timeframe,
            bars_available=bars,
            params=param_summary,
            ran=False,
            warnings=(
                f"Only {bars} complete bars; at least {required} are needed "
                f"for a {params.warmup_bars}-bar warmup plus a holding "
                "window. Collect more history by opening this chart in "
                "Fortrade.",
            ),
        )

    trades: list[Trade] = []

    open_trade: OpenPosition | None = None

    for i in range(params.warmup_bars, bars):
        candle = ordered[i]

        # ---- manage an open position first -------------------------
        if open_trade is not None:
            outcome = _resolve_exit(
                candle, open_trade.direction, open_trade.stop, open_trade.target
            )

            held = i - open_trade.entry_index

            if outcome is None and held >= params.max_bars_held:
                outcome = (candle.close, ExitReason.TIME)

            if outcome is not None:
                exit_price, reason = outcome

                move = (
                    exit_price - open_trade.entry_price
                    if open_trade.direction is Bias.LONG
                    else open_trade.entry_price - exit_price
                )

                # Cost is charged once, on the round trip.
                move -= params.spread

                trades.append(
                    Trade(
                        direction=open_trade.direction,
                        entry_index=open_trade.entry_index,
                        entry_at=ordered[open_trade.entry_index].timestamp,
                        entry_price=open_trade.entry_price,
                        stop=open_trade.stop,
                        target=open_trade.target,
                        exit_index=i,
                        exit_at=candle.timestamp,
                        exit_price=exit_price,
                        exit_reason=reason,
                        r_multiple=round(move / open_trade.risk, 4),
                        signal_score=open_trade.score,
                        bars_held=held,
                    )
                )

                open_trade = None

            continue

        # ---- look for a new entry ----------------------------------
        # The window ends at bar i, and entry happens at i+1's open, so
        # no indicator can see the bar that fills the order.
        if i + 1 >= bars:
            break

        window = ordered[: i + 1]

        signal = generate_signal(symbol, timeframe, window, None, config)

        if signal.bias is Bias.WAIT or signal.score < params.min_score:
            continue

        atr = signal.indicators.atr14

        if atr is None or atr <= 0:
            continue

        entry_candle = ordered[i + 1]
        entry_price = entry_candle.open

        risk = atr * params.stop_atr
        reward = atr * params.target_atr

        if signal.bias is Bias.LONG:
            stop = entry_price - risk
            target = entry_price + reward
        else:
            stop = entry_price + risk
            target = entry_price - reward

        open_trade = OpenPosition(
            direction=signal.bias,
            entry_index=i + 1,
            entry_price=entry_price,
            stop=stop,
            target=target,
            risk=risk,
            score=signal.score,
        )

    warnings: list[str] = []

    if open_trade is not None:
        warnings.append(
            "A position was still open at the end of the data and is "
            "excluded from the statistics."
        )

    if params.spread <= 0:
        warnings.append(
            "Frictionless test: no spread or commission was applied, so "
            "real results would be worse."
        )

    metrics = compute_metrics(
        [ClosedTrade(r_multiple=t.r_multiple) for t in trades],
        risk_fraction=params.risk_fraction,
        minimum_trades=params.minimum_trades,
    )

    logger.info(
        "Backtest complete",
        extra={
            "context": {
                "symbol": symbol,
                "timeframe": timeframe.value,
                "bars": bars,
                "trades": len(trades),
                "sufficient": metrics.sufficient,
            }
        },
    )

    return BacktestResult(
        symbol=symbol,
        timeframe=timeframe,
        bars_available=len(candles),
        bars_tested=bars - params.warmup_bars,
        range_start=frame.index[0].to_pydatetime() if len(frame) else None,
        range_end=frame.index[-1].to_pydatetime() if len(frame) else None,
        metrics=metrics,
        trades=tuple(trades),
        params=param_summary,
        ran=True,
        warnings=(*warnings, *metrics.warnings),
    )
