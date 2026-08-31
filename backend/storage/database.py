"""SQLite connection management.

One `Database` instance owns the file. Connections are thread-local because
uvicorn may dispatch across threads and sqlite3 connections are not safe to
share.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from backend.logging_setup import get_logger
from backend.storage.migrations import apply_migrations, current_version

logger = get_logger(__name__)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._local = threading.local()
        self._schema_version = 0

    def initialise(self) -> int:
        """Create the file if needed and bring the schema up to date."""
        self.path.parent.mkdir(parents=True, exist_ok=True)

        connection = self.connection

        # WAL keeps reads from blocking the ingest writer.
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")

        self._schema_version = apply_migrations(connection)

        logger.info(
            "Database ready",
            extra={
                "context": {
                    "path": str(self.path),
                    "schema_version": self._schema_version,
                }
            },
        )

        return self._schema_version

    @property
    def schema_version(self) -> int:
        return self._schema_version

    @property
    def connection(self) -> sqlite3.Connection:
        existing: sqlite3.Connection | None = getattr(
            self._local, "connection", None
        )

        if existing is not None:
            return existing

        connection = sqlite3.connect(
            self.path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")

        self._local.connection = connection

        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Commit on success, roll back on any exception."""
        connection = self.connection

        try:
            with connection:
                yield connection
        except sqlite3.Error:
            logger.exception("Database transaction failed")
            raise

    def close(self) -> None:
        connection: sqlite3.Connection | None = getattr(
            self._local, "connection", None
        )

        if connection is not None:
            connection.close()
            self._local.connection = None

    def health(self) -> dict[str, object]:
        try:
            version = current_version(self.connection)

            return {
                "ok": True,
                "path": str(self.path),
                "schema_version": version,
            }
        except sqlite3.Error as exc:
            logger.exception("Database health check failed")

            return {"ok": False, "error": str(exc)}
