from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import ClassVar

import pytest

from backend.storage.database import Database
from backend.storage.migrations import (
    MIGRATIONS,
    apply_migrations,
    current_version,
)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.sqlite3")
    database.initialise()

    return database


class TestMigrations:
    def test_versions_are_unique_and_sequential(self) -> None:
        versions = [m.version for m in MIGRATIONS]

        assert versions == sorted(versions)
        assert len(versions) == len(set(versions))
        assert versions[0] == 1

    def test_initialise_reaches_latest_version(self, db: Database) -> None:
        assert db.schema_version == max(m.version for m in MIGRATIONS)

    def test_is_idempotent(self, db: Database) -> None:
        before = current_version(db.connection)

        assert apply_migrations(db.connection) == before
        assert apply_migrations(db.connection) == before

    def test_records_applied_migrations(self, db: Database) -> None:
        rows = db.connection.execute(
            "SELECT version, name, applied_at FROM schema_migrations"
        ).fetchall()

        assert len(rows) == len(MIGRATIONS)
        assert all(row["applied_at"] for row in rows)

    def test_creates_database_file(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "dir" / "created.sqlite3"

        Database(path).initialise()

        assert path.exists()


class TestSchema:
    EXPECTED_TABLES: ClassVar[set[str]] = {
        "quotes",
        "candles",
        "analysis_snapshots",
        "signals",
        "paper_trades",
        "backtest_runs",
        "backtest_metrics",
        "schema_migrations",
    }

    def test_all_tables_exist(self, db: Database) -> None:
        rows = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()

        assert {row["name"] for row in rows} >= self.EXPECTED_TABLES

    def test_candles_are_unique_per_bar(self, db: Database) -> None:
        insert = (
            "INSERT INTO candles"
            " (symbol, timeframe, timestamp, open, high, low, close)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
        )
        row = ("GBP/USD", "M5", "2026-08-28T21:55:00", 1.1, 1.2, 1.0, 1.15)

        with db.transaction() as conn:
            conn.execute(insert, row)

        with pytest.raises(sqlite3.IntegrityError), db.transaction() as conn:
            conn.execute(insert, row)

    def test_signal_bias_is_constrained(self, db: Database) -> None:
        with pytest.raises(sqlite3.IntegrityError), db.transaction() as conn:
            conn.execute(
                "INSERT INTO signals (symbol, timeframe, bias, score,"
                " trend_score, momentum_score, structure_score,"
                " volatility_score, timeframe_score, created_at)"
                " VALUES ('GBP/USD','M5','MAYBE',50,10,10,10,10,10,'now')"
            )

    def test_signal_score_range_is_constrained(self, db: Database) -> None:
        with pytest.raises(sqlite3.IntegrityError), db.transaction() as conn:
            conn.execute(
                "INSERT INTO signals (symbol, timeframe, bias, score,"
                " trend_score, momentum_score, structure_score,"
                " volatility_score, timeframe_score, created_at)"
                " VALUES ('GBP/USD','M5','LONG',150,10,10,10,10,10,'now')"
            )

    def test_paper_trade_direction_is_constrained(self, db: Database) -> None:
        with pytest.raises(sqlite3.IntegrityError), db.transaction() as conn:
            conn.execute(
                "INSERT INTO paper_trades"
                " (symbol, direction, entry, stop, size, opened_at)"
                " VALUES ('GBP/USD','HOLD',1.35,1.34,1000,'now')"
            )


class TestTransactions:
    def test_rolls_back_on_error(self, db: Database) -> None:
        with pytest.raises(sqlite3.Error), db.transaction() as conn:
            conn.execute(
                "INSERT INTO analysis_snapshots (captured_at, payload)"
                " VALUES ('now', '{}')"
            )
            conn.execute("INSERT INTO does_not_exist VALUES (1)")

        count = db.connection.execute(
            "SELECT COUNT(*) AS n FROM analysis_snapshots"
        ).fetchone()["n"]

        assert count == 0

    def test_commits_on_success(self, db: Database) -> None:
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO analysis_snapshots (captured_at, payload)"
                " VALUES ('now', '{\"a\":1}')"
            )

        count = db.connection.execute(
            "SELECT COUNT(*) AS n FROM analysis_snapshots"
        ).fetchone()["n"]

        assert count == 1


def test_health_reports_ok(db: Database) -> None:
    health = db.health()

    assert health["ok"] is True
    assert health["schema_version"] == db.schema_version
