"""The `FortradeDataSource` / `CandleProvider` abstractions.

Nothing downstream may know how data was obtained. Two implementations
exist today:

* `PushedDataSource` — fed by the Electron main process, which owns the
  authenticated `WebContentsView` and performs extraction. The backend
  never drives a browser itself.
* `FixtureDataSource` — parses a captured page dump, so the test suite and
  development mode work with no Fortrade account.

A network-observation provider is added in Phase D and slots in here
without changes elsewhere.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

from backend.fortrade import parser
from backend.fortrade.models import (
    Account,
    Candle,
    ChartSelection,
    DataSourceKind,
    MarketSnapshot,
    Position,
    Quote,
    Timeframe,
)


class FortradeDataUnavailableError(RuntimeError):
    """Raised when the requested data has not been observed yet."""


T = TypeVar("T")


def _optional(fn: Callable[[], T]) -> T | None:
    """Return `fn()`, or None when that section of the page is absent."""
    try:
        return fn()
    except (FortradeDataUnavailableError, parser.FortradeParseError):
        return None


class FortradeDataSource(ABC):
    """Read-only view of the authenticated Fortrade session.

    There is deliberately no write method on this interface. Order entry
    is not merely disabled — it has no representation in the type system.
    """

    @abstractmethod
    def get_account(self) -> Account: ...

    @abstractmethod
    def get_quotes(self) -> list[Quote]: ...

    @abstractmethod
    def get_positions(self) -> list[Position]: ...

    @abstractmethod
    def get_chart(self) -> ChartSelection: ...

    def get_quote(self, symbol: str) -> Quote:
        return parser.find_quote(self.get_quotes(), symbol)

    def list_symbols(self) -> list[str]:
        return sorted(quote.symbol for quote in self.get_quotes())

    def snapshot(self) -> MarketSnapshot:
        """Best-effort composite; absent sections are left as None."""
        quotes = _optional(self.get_quotes) or []
        positions = _optional(self.get_positions) or []

        return MarketSnapshot(
            account=_optional(self.get_account),
            quotes=tuple(quotes),
            positions=tuple(positions),
            chart=_optional(self.get_chart),
        )


class PushedDataSource(FortradeDataSource):
    """Holds the most recent snapshot pushed in by the desktop shell."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._account: Account | None = None
        self._quotes: list[Quote] = []
        self._positions: list[Position] = []
        self._chart: ChartSelection | None = None
        self._updated_at: datetime | None = None

    def ingest(self, snapshot: MarketSnapshot) -> None:
        with self._lock:
            if snapshot.account is not None:
                self._account = snapshot.account

            if snapshot.quotes:
                self._quotes = list(snapshot.quotes)

            # Positions legitimately go to zero, so an empty list is a
            # real value rather than "nothing observed".
            self._positions = list(snapshot.positions)

            if snapshot.chart is not None:
                self._chart = snapshot.chart

            self._updated_at = datetime.now(tz=timezone.utc)

    @property
    def updated_at(self) -> datetime | None:
        with self._lock:
            return self._updated_at

    def get_account(self) -> Account:
        with self._lock:
            if self._account is None:
                raise FortradeDataUnavailableError(
                    "No account data has been observed yet"
                )

            return self._account

    def get_quotes(self) -> list[Quote]:
        with self._lock:
            if not self._quotes:
                raise FortradeDataUnavailableError(
                    "No quotes have been observed yet"
                )

            return list(self._quotes)

    def get_positions(self) -> list[Position]:
        with self._lock:
            return list(self._positions)

    def get_chart(self) -> ChartSelection:
        with self._lock:
            if self._chart is None:
                raise FortradeDataUnavailableError(
                    "No chart selection has been observed yet"
                )

            return self._chart


class FixtureDataSource(FortradeDataSource):
    """Parses a captured Fortrade page dump. Used by tests and dev mode."""

    def __init__(self, text: str) -> None:
        self._text = text

    @classmethod
    def from_file(cls, path: Path) -> FixtureDataSource:
        return cls(path.read_text(encoding="utf-8"))

    def get_account(self) -> Account:
        return parser.parse_account(self._text, DataSourceKind.FIXTURE)

    def get_quotes(self) -> list[Quote]:
        return parser.parse_quotes(self._text, DataSourceKind.FIXTURE)

    def get_positions(self) -> list[Position]:
        # The captured dumps contain no open positions; position parsing
        # arrives in Phase C once a fixture with positions exists.
        return []

    def get_chart(self) -> ChartSelection:
        return parser.parse_chart_selection(self._text, DataSourceKind.FIXTURE)


class CandleProvider(ABC):
    """Supplies OHLC history, independent of how it was obtained."""

    @abstractmethod
    def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        limit: int = 500,
    ) -> list[Candle]: ...

    @abstractmethod
    def available(self, symbol: str, timeframe: Timeframe) -> int:
        """How many bars are held. Callers must not assume `limit` bars."""


class InMemoryCandleProvider(CandleProvider):
    """Accumulates observed candles, de-duplicated and time-ordered."""

    def __init__(self, max_per_series: int = 5000) -> None:
        self._lock = threading.RLock()
        self._series: dict[tuple[str, Timeframe], dict[datetime, Candle]] = {}
        self._max_per_series = max_per_series

    def ingest(self, candles: list[Candle]) -> int:
        """Merge candles in; later observations replace earlier ones."""
        added = 0

        with self._lock:
            for candle in candles:
                key = (candle.symbol.upper(), candle.timeframe)
                bucket = self._series.setdefault(key, {})

                if candle.timestamp not in bucket:
                    added += 1

                bucket[candle.timestamp] = candle

                if len(bucket) > self._max_per_series:
                    for stamp in sorted(bucket)[
                        : len(bucket) - self._max_per_series
                    ]:
                        del bucket[stamp]

        return added

    def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        limit: int = 500,
    ) -> list[Candle]:
        with self._lock:
            bucket = self._series.get((symbol.upper(), timeframe), {})

            ordered = [bucket[stamp] for stamp in sorted(bucket)]

            return ordered[-limit:] if limit > 0 else ordered

    def available(self, symbol: str, timeframe: Timeframe) -> int:
        with self._lock:
            return len(self._series.get((symbol.upper(), timeframe), {}))
