"""Versioned schema migrations.

Deliberately plain SQL over a version table rather than Alembic: this is a
single-writer local database with a fixed schema shipped inside an
installer, so the migration story is "apply forward, in order, once".

Rules:
* Never edit a migration that has shipped. Add a new one.
* Each migration runs inside a transaction and is recorded on success.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from backend.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


MIGRATION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TEXT NOT NULL
);
"""


_INITIAL_SCHEMA = """
-- Point-in-time quotes observed from the session.
CREATE TABLE quotes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT    NOT NULL,
    sell            REAL    NOT NULL,
    buy             REAL    NOT NULL,
    spread_points   INTEGER,
    change_percent  REAL,
    quoted_at       TEXT,
    captured_at     TEXT    NOT NULL,
    source          TEXT    NOT NULL DEFAULT 'unknown'
);

CREATE INDEX idx_quotes_symbol_time ON quotes (symbol, captured_at DESC);

-- OHLC history. Unique per instrument/timeframe/bar so repeated
-- observation of the forming bar updates rather than duplicates.
CREATE TABLE candles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT    NOT NULL,
    timeframe   TEXT    NOT NULL,
    timestamp   TEXT    NOT NULL,
    open        REAL    NOT NULL,
    high        REAL    NOT NULL,
    low         REAL    NOT NULL,
    close       REAL    NOT NULL,
    volume      REAL,
    complete    INTEGER NOT NULL DEFAULT 1,
    source      TEXT    NOT NULL DEFAULT 'unknown',
    UNIQUE (symbol, timeframe, timestamp)
);

CREATE INDEX idx_candles_series ON candles (symbol, timeframe, timestamp);

-- Full account/market state at a moment, stored as JSON for replay.
CREATE TABLE analysis_snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at  TEXT NOT NULL,
    payload      TEXT NOT NULL
);

CREATE INDEX idx_snapshots_time ON analysis_snapshots (captured_at DESC);

-- Deterministic signal engine output.
CREATE TABLE signals (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol           TEXT    NOT NULL,
    timeframe        TEXT    NOT NULL,
    bias             TEXT    NOT NULL CHECK (bias IN ('LONG','SHORT','WAIT')),
    score            INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
    trend_score      INTEGER NOT NULL,
    momentum_score   INTEGER NOT NULL,
    structure_score  INTEGER NOT NULL,
    volatility_score INTEGER NOT NULL,
    timeframe_score  INTEGER NOT NULL,
    support          REAL,
    resistance       REAL,
    indicators       TEXT    NOT NULL DEFAULT '{}',
    reasons          TEXT    NOT NULL DEFAULT '[]',
    warnings         TEXT    NOT NULL DEFAULT '[]',
    created_at       TEXT    NOT NULL
);

CREATE INDEX idx_signals_symbol_time ON signals (symbol, created_at DESC);

-- Simulated positions only. There is no linkage to broker order entry.
CREATE TABLE paper_trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol        TEXT NOT NULL,
    direction     TEXT NOT NULL CHECK (direction IN ('BUY','SELL')),
    entry         REAL NOT NULL,
    stop          REAL NOT NULL,
    target        REAL,
    size          REAL NOT NULL,
    opened_at     TEXT NOT NULL,
    closed_at     TEXT,
    exit_price    REAL,
    pnl           REAL,
    r_multiple    REAL,
    entry_reason  TEXT,
    signal_id     INTEGER REFERENCES signals (id) ON DELETE SET NULL,
    status        TEXT NOT NULL DEFAULT 'OPEN'
                    CHECK (status IN ('OPEN','CLOSED','CANCELLED'))
);

CREATE INDEX idx_paper_status ON paper_trades (status, opened_at DESC);

CREATE TABLE backtest_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy     TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    timeframe    TEXT NOT NULL,
    params       TEXT NOT NULL DEFAULT '{}',
    bars_used    INTEGER NOT NULL,
    range_start  TEXT,
    range_end    TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE backtest_metrics (
    run_id                  INTEGER PRIMARY KEY
                              REFERENCES backtest_runs (id) ON DELETE CASCADE,
    trades                  INTEGER NOT NULL,
    wins                    INTEGER NOT NULL,
    losses                  INTEGER NOT NULL,
    win_rate                REAL,
    average_win_r           REAL,
    average_loss_r          REAL,
    expectancy_r            REAL,
    profit_factor           REAL,
    max_drawdown_pct        REAL,
    max_consecutive_losses  INTEGER
);
"""


_PAPER_TIMEFRAME = """
-- Paper trades originate from a signal on a specific timeframe. Without
-- it, positions cannot be deduplicated per series and closed trades
-- cannot be segmented by horizon.
ALTER TABLE paper_trades ADD COLUMN timeframe TEXT NOT NULL DEFAULT 'M5';

CREATE INDEX idx_paper_series ON paper_trades (symbol, timeframe, status);
"""


MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, name="initial_schema", sql=_INITIAL_SCHEMA),
    Migration(version=2, name="paper_trade_timeframe", sql=_PAPER_TIMEFRAME),
)


def current_version(connection: sqlite3.Connection) -> int:
    connection.execute(MIGRATION_TABLE)

    row = connection.execute(
        "SELECT MAX(version) FROM schema_migrations"
    ).fetchone()

    return int(row[0]) if row and row[0] is not None else 0


def apply_migrations(connection: sqlite3.Connection) -> int:
    """Apply every pending migration. Returns the resulting version."""
    version = current_version(connection)

    pending = [m for m in MIGRATIONS if m.version > version]

    if not pending:
        logger.debug(
            "Schema already current", extra={"context": {"version": version}}
        )
        return version

    for migration in sorted(pending, key=lambda m: m.version):
        logger.info(
            "Applying migration",
            extra={
                "context": {
                    "version": migration.version,
                    "name": migration.name,
                }
            },
        )

        try:
            with connection:
                connection.executescript(migration.sql)

                connection.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at)"
                    " VALUES (?, ?, ?)",
                    (
                        migration.version,
                        migration.name,
                        datetime.now(tz=timezone.utc).isoformat(),
                    ),
                )
        except sqlite3.Error:
            logger.exception(
                "Migration failed",
                extra={"context": {"version": migration.version}},
            )
            raise

        version = migration.version

    return version
