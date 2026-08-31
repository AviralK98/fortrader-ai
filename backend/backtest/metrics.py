"""Backtest metrics.

Everything is derived from a list of closed trades expressed in R — the
multiple of the risk taken on entry. R keeps results comparable across
instruments and position sizes.

Metrics are only reported when there are enough trades to mean anything.
A win rate computed from three trades is noise wearing a percentage sign.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

#: Below this many closed trades the statistics are not reported.
MINIMUM_TRADES = 20

#: Fraction of equity risked per trade when building the equity curve.
DEFAULT_RISK_FRACTION = 0.01


@dataclass(frozen=True)
class ClosedTrade:
    """A finished simulated trade, in R terms."""

    r_multiple: float

    @property
    def is_win(self) -> bool:
        return self.r_multiple > 0

    @property
    def is_loss(self) -> bool:
        return self.r_multiple < 0


class BacktestMetrics(BaseModel):
    """Summary statistics. `sufficient` gates whether they mean anything."""

    model_config = ConfigDict(frozen=True)

    trades: int = 0
    wins: int = 0
    losses: int = 0
    breakeven: int = 0

    win_rate: float | None = None

    average_win_r: float | None = None
    average_loss_r: float | None = None
    expectancy_r: float | None = None
    profit_factor: float | None = None

    max_drawdown_pct: float | None = None
    max_consecutive_losses: int = 0

    total_r: float = 0.0

    #: False when too few trades exist for the figures to be meaningful.
    sufficient: bool = False

    minimum_trades: int = MINIMUM_TRADES

    warnings: tuple[str, ...] = ()


def max_drawdown_percent(
    r_multiples: list[float],
    risk_fraction: float = DEFAULT_RISK_FRACTION,
) -> float:
    """Peak-to-trough decline of an equity curve, as a percentage.

    Equity compounds with a fixed fractional risk per trade, which is the
    usual convention and makes the percentage well defined. Reporting
    drawdown in raw R would not be comparable between accounts.
    """
    equity = 1.0
    peak = 1.0
    worst = 0.0

    for r in r_multiples:
        equity *= 1.0 + r * risk_fraction

        # A blown account cannot recover; clamp rather than go negative.
        equity = max(equity, 0.0)

        peak = max(peak, equity)

        if peak > 0:
            worst = max(worst, (peak - equity) / peak)

    return round(worst * 100.0, 4)


def max_consecutive_losses(r_multiples: list[float]) -> int:
    longest = 0
    current = 0

    for r in r_multiples:
        if r < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0

    return longest


def compute_metrics(
    trades: list[ClosedTrade],
    risk_fraction: float = DEFAULT_RISK_FRACTION,
    minimum_trades: int = MINIMUM_TRADES,
) -> BacktestMetrics:
    """Summarise closed trades.

    With too few trades the counts are still reported — they are facts —
    but the derived statistics are left as None and `sufficient` is False.
    """
    r_multiples = [t.r_multiple for t in trades]

    wins = [r for r in r_multiples if r > 0]
    losses = [r for r in r_multiples if r < 0]
    flat = [r for r in r_multiples if r == 0]

    warnings: list[str] = []

    if not trades:
        return BacktestMetrics(
            minimum_trades=minimum_trades,
            warnings=("No trades were generated over this history.",),
        )

    if len(trades) < minimum_trades:
        warnings.append(
            f"Only {len(trades)} trades; at least {minimum_trades} are "
            "needed before these statistics carry meaning. Derived metrics "
            "are withheld."
        )

        return BacktestMetrics(
            trades=len(trades),
            wins=len(wins),
            losses=len(losses),
            breakeven=len(flat),
            total_r=round(sum(r_multiples), 4),
            sufficient=False,
            minimum_trades=minimum_trades,
            warnings=tuple(warnings),
        )

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    profit_factor: float | None = None

    if gross_loss > 0:
        profit_factor = round(gross_profit / gross_loss, 4)
    elif gross_profit > 0:
        # Undefined rather than infinite; a run with no losing trade is a
        # sample-size problem, not an infinitely good strategy.
        warnings.append(
            "No losing trades in this sample; profit factor is undefined."
        )

    average_win = round(sum(wins) / len(wins), 4) if wins else None
    average_loss = round(sum(losses) / len(losses), 4) if losses else None

    return BacktestMetrics(
        trades=len(trades),
        wins=len(wins),
        losses=len(losses),
        breakeven=len(flat),
        win_rate=round(len(wins) / len(trades) * 100.0, 2),
        average_win_r=average_win,
        average_loss_r=average_loss,
        expectancy_r=round(sum(r_multiples) / len(trades), 4),
        profit_factor=profit_factor,
        max_drawdown_pct=max_drawdown_percent(r_multiples, risk_fraction),
        max_consecutive_losses=max_consecutive_losses(r_multiples),
        total_r=round(sum(r_multiples), 4),
        sufficient=True,
        minimum_trades=minimum_trades,
        warnings=tuple(warnings),
    )
