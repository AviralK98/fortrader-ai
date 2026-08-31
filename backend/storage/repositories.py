"""Persistence for observed market data.

Candle history is durable: the desktop application only captures a series
when the user opens that chart, so what has been collected must survive
restarts rather than being re-gathered every launch.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.fortrade.models import (
    Candle,
    DataSourceKind,
    MarketSnapshot,
    Quote,
    Timeframe,
)
from backend.fortrade.source import CandleProvider
from backend.logging_setup import get_logger
from backend.paper.engine import (
    CloseReason,
    PaperTrade,
    PlannedTrade,
    TradeStatus,
)
from backend.signals.engine import Bias, Signal
from backend.storage.database import Database

logger = get_logger(__name__)


@dataclass(frozen=True)
class SeriesCoverage:
    """What history exists for one instrument/timeframe."""

    symbol: str
    timeframe: Timeframe
    count: int
    first: datetime | None
    last: datetime | None

    def sufficient_for(self, required: int) -> bool:
        return self.count >= required


class CandleRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    def upsert_many(self, candles: list[Candle]) -> int:
        """Insert or update bars. Returns the number of new rows."""
        if not candles:
            return 0

        before = self._total_rows()

        rows = [
            (
                candle.symbol.upper(),
                candle.timeframe.value,
                candle.timestamp.isoformat(),
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                candle.volume,
                1 if candle.complete else 0,
                candle.source.value,
            )
            for candle in candles
        ]

        with self._db.transaction() as conn:
            conn.executemany(
                """
                INSERT INTO candles
                    (symbol, timeframe, timestamp, open, high, low,
                     close, volume, complete, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (symbol, timeframe, timestamp) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    -- A bar never reverts from closed to forming.
                    complete = MAX(candles.complete, excluded.complete),
                    source = excluded.source
                """,
                rows,
            )

        return self._total_rows() - before

    def _total_rows(self) -> int:
        row = self._db.connection.execute(
            "SELECT COUNT(*) AS n FROM candles"
        ).fetchone()

        return int(row["n"])

    def get(
        self,
        symbol: str,
        timeframe: Timeframe,
        limit: int = 500,
    ) -> list[Candle]:
        """Most recent `limit` bars, returned oldest-first."""
        rows = self._db.connection.execute(
            """
            SELECT * FROM candles
            WHERE symbol = ? AND timeframe = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (symbol.upper(), timeframe.value, max(limit, 0)),
        ).fetchall()

        candles = [
            Candle(
                symbol=row["symbol"],
                timeframe=Timeframe(row["timeframe"]),
                timestamp=datetime.fromisoformat(row["timestamp"]),
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                complete=bool(row["complete"]),
                source=DataSourceKind(row["source"]),
            )
            for row in rows
        ]

        candles.reverse()

        return candles

    def count(self, symbol: str, timeframe: Timeframe) -> int:
        row = self._db.connection.execute(
            "SELECT COUNT(*) AS n FROM candles WHERE symbol = ? AND timeframe = ?",
            (symbol.upper(), timeframe.value),
        ).fetchone()

        return int(row["n"])

    def coverage(self) -> list[SeriesCoverage]:
        """Every stored series, so the UI can show what is actually held."""
        rows = self._db.connection.execute(
            """
            SELECT symbol, timeframe, COUNT(*) AS n,
                   MIN(timestamp) AS first, MAX(timestamp) AS last
            FROM candles
            GROUP BY symbol, timeframe
            ORDER BY symbol, timeframe
            """
        ).fetchall()

        result: list[SeriesCoverage] = []

        for row in rows:
            try:
                timeframe = Timeframe(row["timeframe"])
            except ValueError:
                logger.warning(
                    "Unknown timeframe in database",
                    extra={"context": {"timeframe": row["timeframe"]}},
                )
                continue

            result.append(
                SeriesCoverage(
                    symbol=row["symbol"],
                    timeframe=timeframe,
                    count=int(row["n"]),
                    first=datetime.fromisoformat(row["first"]),
                    last=datetime.fromisoformat(row["last"]),
                )
            )

        return result


class SignalRepository:
    """History of generated signals.

    Signals are only written when something meaningful changes, so the
    table is a record of decisions rather than of polling.
    """

    def __init__(self, database: Database) -> None:
        self._db = database

    def save(self, signal: Signal) -> int:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO signals
                    (symbol, timeframe, bias, score, trend_score,
                     momentum_score, structure_score, volatility_score,
                     timeframe_score, support, resistance, indicators,
                     reasons, warnings, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal.symbol.upper(),
                    signal.timeframe.value,
                    signal.bias.value,
                    signal.score,
                    signal.trend_score,
                    signal.momentum_score,
                    signal.structure_score,
                    signal.volatility_score,
                    signal.timeframe_score,
                    signal.support,
                    signal.resistance,
                    signal.indicators.model_dump_json(),
                    json.dumps(list(signal.reasons)),
                    json.dumps(list(signal.warnings)),
                    signal.created_at.isoformat(),
                ),
            )

            return int(cursor.lastrowid or 0)

    def latest(self, symbol: str, timeframe: Timeframe) -> dict[str, Any] | None:
        row = self._db.connection.execute(
            """
            SELECT * FROM signals
            WHERE symbol = ? AND timeframe = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (symbol.upper(), timeframe.value),
        ).fetchone()

        return _signal_row(row) if row else None

    def recent(
        self,
        symbol: str | None = None,
        timeframe: Timeframe | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())

        if timeframe:
            clauses.append("timeframe = ?")
            params.append(timeframe.value)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(limit, 0))

        rows = self._db.connection.execute(
            f"SELECT * FROM signals {where} ORDER BY created_at DESC, id DESC LIMIT ?",
            params,
        ).fetchall()

        return [_signal_row(row) for row in rows]

    def save_if_changed(self, signal: Signal) -> int | None:
        """Persist only when the bias or score has moved.

        The UI polls every ten seconds; storing every poll would fill the
        table with duplicates and make the history useless.
        """
        previous = self.latest(signal.symbol, signal.timeframe)

        if (
            previous is not None
            and previous["bias"] == signal.bias.value
            and previous["score"] == signal.score
        ):
            return None

        return self.save(signal)

    def prune(self, older_than: datetime) -> int:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM signals WHERE created_at < ?",
                (older_than.isoformat(),),
            )

            return cursor.rowcount


def _signal_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "symbol": row["symbol"],
        "timeframe": row["timeframe"],
        "bias": row["bias"],
        "score": row["score"],
        "trend_score": row["trend_score"],
        "momentum_score": row["momentum_score"],
        "structure_score": row["structure_score"],
        "volatility_score": row["volatility_score"],
        "timeframe_score": row["timeframe_score"],
        "support": row["support"],
        "resistance": row["resistance"],
        "indicators": json.loads(row["indicators"]),
        "reasons": json.loads(row["reasons"]),
        "warnings": json.loads(row["warnings"]),
        "created_at": row["created_at"],
    }


class SnapshotRepository:
    """Point-in-time market state, stored as JSON for later replay."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def save(self, snapshot: MarketSnapshot) -> int:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO analysis_snapshots (captured_at, payload) VALUES (?, ?)",
                (
                    snapshot.captured_at.isoformat(),
                    snapshot.model_dump_json(),
                ),
            )

            return int(cursor.lastrowid or 0)

    def count(self) -> int:
        row = self._db.connection.execute(
            "SELECT COUNT(*) AS n FROM analysis_snapshots"
        ).fetchone()

        return int(row["n"])

    def prune(self, older_than: datetime) -> int:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM analysis_snapshots WHERE captured_at < ?",
                (older_than.isoformat(),),
            )

            return cursor.rowcount


class QuoteRepository:
    """Sampled quote history.

    Ingest runs every two seconds; storing all of it would add tens of
    thousands of near-identical rows per instrument per day for no
    analytical benefit. Writes are therefore rate-limited per symbol.
    """

    def __init__(self, database: Database, min_interval_seconds: float = 60.0) -> None:
        self._db = database
        self._min_interval = min_interval_seconds
        self._last_written: dict[str, datetime] = {}

    def save_sampled(self, quotes: list[Quote]) -> int:
        now = datetime.now(tz=timezone.utc)
        due: list[Quote] = []

        for quote in quotes:
            key = quote.symbol.upper()
            last = self._last_written.get(key)

            if last is None or (now - last).total_seconds() >= self._min_interval:
                due.append(quote)
                self._last_written[key] = now

        if not due:
            return 0

        with self._db.transaction() as conn:
            conn.executemany(
                """
                INSERT INTO quotes
                    (symbol, sell, buy, spread_points, change_percent,
                     quoted_at, captured_at, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        q.symbol.upper(),
                        q.sell,
                        q.buy,
                        q.spread_points,
                        q.change_percent,
                        q.quoted_at.isoformat() if q.quoted_at else None,
                        q.captured_at.isoformat(),
                        q.source.value,
                    )
                    for q in due
                ],
            )

        return len(due)

    def count(self, symbol: str | None = None) -> int:
        if symbol:
            row = self._db.connection.execute(
                "SELECT COUNT(*) AS n FROM quotes WHERE symbol = ?",
                (symbol.upper(),),
            ).fetchone()
        else:
            row = self._db.connection.execute(
                "SELECT COUNT(*) AS n FROM quotes"
            ).fetchone()

        return int(row["n"])

    def prune(self, older_than: datetime) -> int:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM quotes WHERE captured_at < ?",
                (older_than.isoformat(),),
            )

            return cursor.rowcount


class PaperTradeRepository:
    """Simulated positions. Must outlive the process to be worth anything."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def open_position(
        self,
        planned: PlannedTrade,
        signal_id: int | None = None,
        opened_at: datetime | None = None,
    ) -> int:
        moment = opened_at or datetime.now(tz=timezone.utc)

        with self._db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO paper_trades
                    (symbol, timeframe, direction, entry, stop, target,
                     size, opened_at, entry_reason, signal_id, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
                """,
                (
                    planned.symbol.upper(),
                    planned.timeframe.value,
                    # The schema constrains direction to BUY/SELL.
                    "BUY" if planned.direction is Bias.LONG else "SELL",
                    planned.entry,
                    planned.stop,
                    planned.target,
                    planned.size,
                    moment.isoformat(),
                    planned.entry_reason,
                    signal_id,
                ),
            )

            return int(cursor.lastrowid or 0)

    def close_position(
        self,
        trade_id: int,
        exit_price: float,
        pnl: float,
        r_multiple: float,
        reason: CloseReason,
        closed_at: datetime | None = None,
    ) -> bool:
        moment = closed_at or datetime.now(tz=timezone.utc)

        with self._db.transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE paper_trades
                SET status = 'CLOSED', closed_at = ?, exit_price = ?,
                    pnl = ?, r_multiple = ?,
                    entry_reason = COALESCE(entry_reason, '') || ' | exit: ' || ?
                WHERE id = ? AND status = 'OPEN'
                """,
                (
                    moment.isoformat(),
                    exit_price,
                    pnl,
                    r_multiple,
                    reason.value,
                    trade_id,
                ),
            )

            return cursor.rowcount > 0

    def open_positions(self, symbol: str | None = None) -> list[PaperTrade]:
        if symbol:
            rows = self._db.connection.execute(
                "SELECT * FROM paper_trades WHERE status = 'OPEN' AND symbol = ?"
                " ORDER BY opened_at DESC",
                (symbol.upper(),),
            ).fetchall()
        else:
            rows = self._db.connection.execute(
                "SELECT * FROM paper_trades WHERE status = 'OPEN'"
                " ORDER BY opened_at DESC"
            ).fetchall()

        return [_paper_row(row) for row in rows]

    def closed_positions(self, limit: int = 200) -> list[PaperTrade]:
        rows = self._db.connection.execute(
            "SELECT * FROM paper_trades WHERE status = 'CLOSED'"
            " ORDER BY closed_at DESC LIMIT ?",
            (max(limit, 0),),
        ).fetchall()

        return [_paper_row(row) for row in rows]

    def has_open(self, symbol: str, timeframe: Timeframe) -> bool:
        """One position per series at a time, so entries cannot stack."""
        row = self._db.connection.execute(
            "SELECT 1 FROM paper_trades"
            " WHERE symbol = ? AND timeframe = ? AND status = 'OPEN' LIMIT 1",
            (symbol.upper(), timeframe.value),
        ).fetchone()

        return row is not None

    def realised_r(self) -> list[float]:
        rows = self._db.connection.execute(
            "SELECT r_multiple FROM paper_trades"
            " WHERE status = 'CLOSED' AND r_multiple IS NOT NULL"
            " ORDER BY closed_at"
        ).fetchall()

        return [float(row["r_multiple"]) for row in rows]

    def realised_pnl(self) -> float:
        row = self._db.connection.execute(
            "SELECT COALESCE(SUM(pnl), 0) AS total FROM paper_trades"
            " WHERE status = 'CLOSED'"
        ).fetchone()

        return float(row["total"])


def _paper_row(row: sqlite3.Row) -> PaperTrade:
    return PaperTrade(
        id=row["id"],
        symbol=row["symbol"],
        timeframe=Timeframe(row["timeframe"]),
        direction=Bias.LONG if row["direction"] == "BUY" else Bias.SHORT,
        entry=row["entry"],
        stop=row["stop"],
        target=row["target"],
        size=row["size"],
        opened_at=datetime.fromisoformat(row["opened_at"]),
        closed_at=(
            datetime.fromisoformat(row["closed_at"]) if row["closed_at"] else None
        ),
        exit_price=row["exit_price"],
        pnl=row["pnl"],
        r_multiple=row["r_multiple"],
        entry_reason=row["entry_reason"],
        signal_id=row["signal_id"],
        status=TradeStatus(row["status"]),
    )


class BacktestRepository:
    """Stored backtest runs and their metrics."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def save(self, result: Any) -> int:
        """Persist a `BacktestResult`. Returns the run id."""
        with self._db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO backtest_runs
                    (strategy, symbol, timeframe, params, bars_used,
                     range_start, range_end, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.strategy,
                    result.symbol.upper(),
                    result.timeframe.value,
                    json.dumps(result.params),
                    result.bars_tested,
                    result.range_start.isoformat() if result.range_start else None,
                    result.range_end.isoformat() if result.range_end else None,
                    result.computed_at.isoformat(),
                ),
            )

            run_id = int(cursor.lastrowid or 0)

            m = result.metrics

            conn.execute(
                """
                INSERT INTO backtest_metrics
                    (run_id, trades, wins, losses, win_rate, average_win_r,
                     average_loss_r, expectancy_r, profit_factor,
                     max_drawdown_pct, max_consecutive_losses)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    m.trades,
                    m.wins,
                    m.losses,
                    m.win_rate,
                    m.average_win_r,
                    m.average_loss_r,
                    m.expectancy_r,
                    m.profit_factor,
                    m.max_drawdown_pct,
                    m.max_consecutive_losses,
                ),
            )

            return run_id

    def get(self, run_id: int) -> dict[str, Any] | None:
        row = self._db.connection.execute(
            """
            SELECT r.*, m.trades, m.wins, m.losses, m.win_rate,
                   m.average_win_r, m.average_loss_r, m.expectancy_r,
                   m.profit_factor, m.max_drawdown_pct,
                   m.max_consecutive_losses
            FROM backtest_runs r
            LEFT JOIN backtest_metrics m ON m.run_id = r.id
            WHERE r.id = ?
            """,
            (run_id,),
        ).fetchone()

        if row is None:
            return None

        record = dict(row)
        record["params"] = json.loads(record["params"])

        return record

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._db.connection.execute(
            """
            SELECT r.id, r.strategy, r.symbol, r.timeframe, r.bars_used,
                   r.created_at, m.trades, m.win_rate, m.expectancy_r,
                   m.profit_factor, m.max_drawdown_pct
            FROM backtest_runs r
            LEFT JOIN backtest_metrics m ON m.run_id = r.id
            ORDER BY r.created_at DESC, r.id DESC
            LIMIT ?
            """,
            (max(limit, 0),),
        ).fetchall()

        return [dict(row) for row in rows]


@dataclass(frozen=True)
class RetentionPolicy:
    """How long each kind of record is kept.

    Candles are never pruned: they are expensive to collect (only captured
    when the user opens a chart) and are the input to backtesting.
    """

    quote_days: int = 14
    snapshot_days: int = 7
    signal_days: int = 90


class Retention:
    def __init__(
        self,
        database: Database,
        policy: RetentionPolicy = RetentionPolicy(),
    ) -> None:
        self._db = database
        self._policy = policy

    def run(self, now: datetime | None = None) -> dict[str, int]:
        moment = now or datetime.now(tz=timezone.utc)

        removed = {
            "quotes": QuoteRepository(self._db).prune(
                moment - timedelta(days=self._policy.quote_days)
            ),
            "snapshots": SnapshotRepository(self._db).prune(
                moment - timedelta(days=self._policy.snapshot_days)
            ),
            "signals": SignalRepository(self._db).prune(
                moment - timedelta(days=self._policy.signal_days)
            ),
        }

        if any(removed.values()):
            logger.info("Retention pruned rows", extra={"context": removed})

        return removed


class SqliteCandleProvider(CandleProvider):
    """Durable `CandleProvider` backed by the local database."""

    def __init__(self, repository: CandleRepository) -> None:
        self._repo = repository

    def ingest(self, candles: list[Candle]) -> int:
        return self._repo.upsert_many(candles)

    def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        limit: int = 500,
    ) -> list[Candle]:
        return self._repo.get(symbol, timeframe, limit)

    def available(self, symbol: str, timeframe: Timeframe) -> int:
        return self._repo.count(symbol, timeframe)

    def coverage(self) -> list[SeriesCoverage]:
        return self._repo.coverage()
