"""Request/response shapes for the local HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.backtest.metrics import BacktestMetrics
from backend.chat.service import ChatMessage
from backend.fortrade.models import (
    Account,
    Candle,
    ChartSelection,
    Position,
    Quote,
    Timeframe,
)
from backend.fortrade.state import AppState, SystemStatus
from backend.paper.engine import PaperSummary, PaperTrade


class HealthResponse(BaseModel):
    ok: bool
    service: str = "fortrader-backend"
    version: str
    schema_version: int
    trading_enabled: bool = Field(
        default=False,
        description="Always false. This build has no execution capability.",
    )
    started_at: datetime


class StatusResponse(BaseModel):
    status: SystemStatus


class QuotesResponse(BaseModel):
    quotes: list[Quote]
    count: int


class PositionsResponse(BaseModel):
    positions: list[Position]
    count: int


class SymbolsResponse(BaseModel):
    symbols: list[str]


class CandlesResponse(BaseModel):
    symbol: str
    timeframe: Timeframe
    candles: list[Candle]
    count: int
    requested: int
    sufficient: bool = Field(
        description=(
            "False when fewer bars are held than requested. Callers must "
            "not present analysis on insufficient history as reliable."
        )
    )


class SeriesCoverageOut(BaseModel):
    symbol: str
    timeframe: Timeframe
    count: int
    first: datetime | None
    last: datetime | None
    sufficient: bool


class CoverageResponse(BaseModel):
    """What OHLC history is actually held, per instrument and timeframe."""

    series: list[SeriesCoverageOut]
    required: int = Field(
        description="Bars considered sufficient for reliable analysis."
    )
    total_bars: int


class ChatRequest(BaseModel):
    """A scoped question about the user's own analysis."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=40)

    symbol: str = "GBP/USD"
    timeframe: Timeframe = Timeframe.M5


class ChatStatusResponse(BaseModel):
    """Which transport the chat would use, and why not if none."""

    available: bool
    provider: str | None = None
    detail: str | None = None


class NarrativeResponse(BaseModel):
    """Optional written explanation. Absence is normal, not an error."""

    available: bool
    narrative: str | None = None
    detail: str | None = None


class PaperPositionsResponse(BaseModel):
    """Simulated positions. Never mapped to Fortrade order entry."""

    open: list[PaperTrade]
    closed: list[PaperTrade]
    summary: PaperSummary
    metrics: BacktestMetrics


class RecentSignalsResponse(BaseModel):
    signals: list[dict[str, Any]]
    count: int


class BacktestRunsResponse(BaseModel):
    runs: list[dict[str, Any]]
    count: int


class SnapshotIngest(BaseModel):
    """Pushed by the Electron main process after each extraction pass."""

    model_config = ConfigDict(extra="forbid")

    account: Account | None = None
    quotes: list[Quote] = Field(default_factory=list)
    positions: list[Position] = Field(default_factory=list)
    chart: ChartSelection | None = None


class CandlesIngest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candles: list[Candle]


class StateIngest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: AppState
    detail: str | None = None


class IngestResult(BaseModel):
    accepted: bool
    received: int = 0
    stored: int = 0


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
