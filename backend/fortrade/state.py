"""Application state machine shared by the backend and the desktop shell.

The UI must never imply data is live when the feed is stale, so state is an
explicit value rather than something inferred from whether a fetch happened
to succeed.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from backend.fortrade.models import MarketSnapshot, utcnow


class AppState(str, Enum):
    STARTING = "STARTING"
    FORTRADE_LOADING = "FORTRADE_LOADING"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    CONNECTED = "CONNECTED"
    MARKET_CLOSED = "MARKET_CLOSED"
    BACKEND_ERROR = "BACKEND_ERROR"
    FORTRADE_ERROR = "FORTRADE_ERROR"
    DISCONNECTED = "DISCONNECTED"


class ComponentStatus(str, Enum):
    READY = "READY"
    PENDING = "PENDING"
    ERROR = "ERROR"
    UNAVAILABLE = "UNAVAILABLE"


# Beyond this age a snapshot is reported as stale rather than current.
STALE_AFTER = timedelta(seconds=15)


class SystemStatus(BaseModel):
    """The shape rendered by the status strip in the UI."""

    model_config = ConfigDict(frozen=True)

    state: AppState = AppState.STARTING

    fortrade: ComponentStatus = ComponentStatus.PENDING
    analysis_engine: ComponentStatus = ComponentStatus.PENDING
    database: ComponentStatus = ComponentStatus.PENDING
    mcp: ComponentStatus = ComponentStatus.PENDING

    trading_enabled: bool = False

    last_snapshot_at: datetime | None = None
    data_age_seconds: float | None = None
    stale: bool = True

    detail: str | None = None

    updated_at: datetime = Field(default_factory=utcnow)


class StateStore:
    """Thread-safe holder for current state and the latest snapshot.

    uvicorn may serve requests from more than one thread, and the ingest
    path is driven from the Electron side, so mutation is locked.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = AppState.STARTING
        self._detail: str | None = None
        self._snapshot: MarketSnapshot | None = None
        self._snapshot_at: datetime | None = None
        self._database_ready = False

    def set_state(self, state: AppState, detail: str | None = None) -> None:
        with self._lock:
            self._state = state
            self._detail = detail

    def set_database_ready(self, ready: bool) -> None:
        with self._lock:
            self._database_ready = ready

    def update_snapshot(self, snapshot: MarketSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot
            self._snapshot_at = datetime.now(tz=timezone.utc)

            if self._state in (
                AppState.STARTING,
                AppState.FORTRADE_LOADING,
                AppState.AUTH_REQUIRED,
                AppState.DISCONNECTED,
            ):
                self._state = AppState.CONNECTED
                self._detail = None

    @property
    def snapshot(self) -> MarketSnapshot | None:
        with self._lock:
            return self._snapshot

    def status(self) -> SystemStatus:
        with self._lock:
            age: float | None = None
            stale = True

            if self._snapshot_at is not None:
                delta = datetime.now(tz=timezone.utc) - self._snapshot_at
                age = delta.total_seconds()
                stale = delta > STALE_AFTER

            if self._state is AppState.CONNECTED and stale:
                fortrade = ComponentStatus.PENDING
            elif self._state is AppState.CONNECTED:
                fortrade = ComponentStatus.READY
            elif self._state in (
                AppState.FORTRADE_ERROR,
                AppState.BACKEND_ERROR,
            ):
                fortrade = ComponentStatus.ERROR
            else:
                fortrade = ComponentStatus.PENDING

            return SystemStatus(
                state=self._state,
                fortrade=fortrade,
                analysis_engine=ComponentStatus.READY,
                database=(
                    ComponentStatus.READY
                    if self._database_ready
                    else ComponentStatus.PENDING
                ),
                mcp=ComponentStatus.READY,
                trading_enabled=False,
                last_snapshot_at=self._snapshot_at,
                data_age_seconds=age,
                stale=stale,
                detail=self._detail,
            )
