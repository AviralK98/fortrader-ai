"""Normalised Fortrade domain models.

These are the contract between the Fortrade integration layer and the rest
of the application. Nothing downstream of here may know whether a value was
scraped from the DOM, observed on a WebSocket, or replayed from a fixture.

Every model carries `captured_at` so the UI can prove data freshness rather
than implying that stale values are live.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class DataSourceKind(str, Enum):
    """How a piece of data reached us. Diagnostics only."""

    DOM = "dom"
    NETWORK = "network"
    WEBSOCKET = "websocket"
    FIXTURE = "fixture"
    UNKNOWN = "unknown"


class AccountType(str, Enum):
    DEMO = "DEMO"
    LIVE = "LIVE"
    UNKNOWN = "UNKNOWN"


class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class Timeframe(str, Enum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"

    @property
    def minutes(self) -> int:
        return _TIMEFRAME_MINUTES[self]


_TIMEFRAME_MINUTES: dict[Timeframe, int] = {
    Timeframe.M1: 1,
    Timeframe.M5: 5,
    Timeframe.M15: 15,
    Timeframe.M30: 30,
    Timeframe.H1: 60,
    Timeframe.H4: 240,
    Timeframe.D1: 1440,
}


class FortradeModel(BaseModel):
    """Base with strict validation — remote data is untrusted."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class Account(FortradeModel):
    balance: float
    equity: float
    open_pnl: float
    used_margin: float
    available_margin: float

    currency: str = Field(min_length=3, max_length=3)

    account_type: AccountType = AccountType.UNKNOWN

    captured_at: datetime = Field(default_factory=utcnow)
    source: DataSourceKind = DataSourceKind.UNKNOWN

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, value: str) -> str:
        return value.upper()


class Quote(FortradeModel):
    symbol: str
    sell: float
    buy: float

    change_percent: float | None = None

    # Broker-reported spread in points, when the UI exposes it.
    spread_points: int | None = None

    quoted_at: datetime | None = None
    captured_at: datetime = Field(default_factory=utcnow)
    source: DataSourceKind = DataSourceKind.UNKNOWN

    @property
    def spread(self) -> float:
        """Ask minus bid, in price terms."""
        return round(self.buy - self.sell, 10)

    @property
    def mid(self) -> float:
        return (self.buy + self.sell) / 2.0


class Position(FortradeModel):
    symbol: str
    direction: Direction
    amount: float

    open_rate: float
    current_rate: float | None = None

    stop_loss: float | None = None
    take_profit: float | None = None

    pnl: float | None = None

    position_id: str | None = None
    opened_at: datetime | None = None

    captured_at: datetime = Field(default_factory=utcnow)
    source: DataSourceKind = DataSourceKind.UNKNOWN


class ChartSelection(FortradeModel):
    """Whatever instrument/timeframe the user currently has on screen."""

    symbol: str
    timeframe: Timeframe

    captured_at: datetime = Field(default_factory=utcnow)
    source: DataSourceKind = DataSourceKind.UNKNOWN


class Candle(FortradeModel):
    """A single OHLC bar. `complete` is False for the forming bar."""

    symbol: str
    timeframe: Timeframe

    timestamp: datetime

    open: float
    high: float
    low: float
    close: float

    volume: float | None = None
    complete: bool = True

    source: DataSourceKind = DataSourceKind.UNKNOWN

    @field_validator("high")
    @classmethod
    def _high_is_highest(cls, value: float, info: Any) -> float:
        low = info.data.get("low")

        if low is not None and value < low:
            raise ValueError("high must be >= low")

        return value


class MarketSnapshot(FortradeModel):
    """Everything readable from the session at one moment."""

    account: Account | None = None
    quotes: tuple[Quote, ...] = ()
    positions: tuple[Position, ...] = ()
    chart: ChartSelection | None = None

    captured_at: datetime = Field(default_factory=utcnow)
