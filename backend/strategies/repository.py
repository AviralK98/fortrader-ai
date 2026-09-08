"""Storage for user-defined strategies and the active selection.

The built-in strategy never appears in the table. It is prepended on
read, refused on write, and used whenever the active selection names
something that no longer exists — so the engine always has a valid
configuration regardless of what the user has done to their own.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.logging_setup import get_logger
from backend.storage.database import Database
from backend.strategies.models import (
    BUILTIN_ID,
    SCRIPT_PREFIX,
    Strategy,
    StrategyParameters,
    builtin_strategy,
    script_id,
)
from backend.strategies.scripts import discover

logger = get_logger(__name__)

ACTIVE_KEY = "active_strategy"

#: A cap on stored strategies. Not a licensing limit -- an unbounded
#: table behind a UI with a "duplicate" button is a way to fill a disk.
MAX_STRATEGIES = 50


class StrategyExistsError(Exception):
    """A strategy with that name already exists."""


class StrategyNotFoundError(Exception):
    """No strategy with that id, or it is the built-in one."""


class StrategyReadOnlyError(Exception):
    """The built-in strategy cannot be modified or deleted."""


class TooManyStrategiesError(Exception):
    """The stored-strategy limit has been reached."""


class StrategyRepository:
    def __init__(self, database: Database, data_dir: Path | None = None) -> None:
        self._db = database
        #: Where user scripts live. Absent in tests that only exercise
        #: stored parameters, in which case no script is discovered.
        self._data_dir = data_dir

    def scripts(self) -> list[Strategy]:
        """Strategies that are files the user wrote.

        Discovered rather than stored: the file on disk is the strategy,
        so adding one is dropping it in the folder and removing one is
        deleting it. The application never edits a user's code.
        """
        if self._data_dir is None:
            return []

        try:
            found = discover(self._data_dir)
        except OSError:
            logger.exception("Strategy scripts folder could not be read")
            return []

        return [
            Strategy(
                id=script_id(path.name),
                name=path.stem.replace("_", " "),
                parameters=StrategyParameters(),
                notes=f"Python script: {path.name}",
                kind="script",
                script=path.name,
            )
            for path in found
        ]

    # -- reads ------------------------------------------------------

    def list(self) -> list[Strategy]:
        """Every strategy, built-in first."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM strategies ORDER BY name COLLATE NOCASE"
            ).fetchall()

        stored: list[Strategy] = []

        for row in rows:
            parsed = self._row_to_strategy(row)

            # A row that will not parse is skipped rather than allowed to
            # break the list. Losing one custom strategy is recoverable;
            # a strategy page that cannot load is not.
            if parsed is not None:
                stored.append(parsed)

        return [builtin_strategy(), *stored, *self.scripts()]

    def get(self, strategy_id: str) -> Strategy | None:
        if strategy_id == BUILTIN_ID:
            return builtin_strategy()

        if strategy_id.startswith(SCRIPT_PREFIX):
            # Resolved against the folder each time: a script deleted
            # outside the application must stop being selectable.
            return next(
                (s for s in self.scripts() if s.id == strategy_id), None
            )

        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM strategies WHERE id = ?", (strategy_id,)
            ).fetchone()

        return self._row_to_strategy(row) if row else None

    def active(self) -> Strategy:
        """The selected strategy, or the built-in one.

        Never raises and never returns None: this is called on the path
        that produces a signal, and a missing or unparseable selection
        must degrade to the shipped engine rather than to no engine.
        """
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (ACTIVE_KEY,)
            ).fetchone()

        if row is None:
            return builtin_strategy()

        found = self.get(str(row["value"]))

        if found is None:
            logger.warning(
                "Active strategy no longer exists; using the built-in one",
                extra={"context": {"requested": str(row["value"])}},
            )
            return builtin_strategy()

        return found

    # -- writes -----------------------------------------------------

    def create(
        self, name: str, parameters: StrategyParameters, notes: str = ""
    ) -> Strategy:
        parameters.checked()

        now = datetime.now(tz=timezone.utc)
        strategy = Strategy(
            id=uuid.uuid4().hex,
            name=name.strip(),
            parameters=parameters,
            notes=notes.strip(),
            created_at=now,
            updated_at=now,
        )

        with self._db.transaction() as conn:
            count = conn.execute("SELECT COUNT(*) AS n FROM strategies").fetchone()

            if int(count["n"]) >= MAX_STRATEGIES:
                raise TooManyStrategiesError(
                    f"At most {MAX_STRATEGIES} strategies can be stored."
                )

            try:
                conn.execute(
                    "INSERT INTO strategies "
                    "(id, name, parameters, notes, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        strategy.id,
                        strategy.name,
                        strategy.parameters.model_dump_json(),
                        strategy.notes,
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise StrategyExistsError(
                    f"A strategy named {strategy.name!r} already exists."
                ) from error

        logger.info("Strategy created", extra={"context": {"name": strategy.name}})

        return strategy

    def update(
        self,
        strategy_id: str,
        name: str,
        parameters: StrategyParameters,
        notes: str = "",
    ) -> Strategy:
        if strategy_id == BUILTIN_ID:
            raise StrategyReadOnlyError(
                "The built-in strategy cannot be edited."
            )

        if strategy_id.startswith(SCRIPT_PREFIX):
            raise StrategyReadOnlyError(
                "A strategy script is edited by editing its file."
            )

        parameters.checked()

        now = datetime.now(tz=timezone.utc)

        with self._db.transaction() as conn:
            try:
                cursor = conn.execute(
                    "UPDATE strategies SET name = ?, parameters = ?, notes = ?, "
                    "updated_at = ? WHERE id = ?",
                    (
                        name.strip(),
                        parameters.model_dump_json(),
                        notes.strip(),
                        now.isoformat(),
                        strategy_id,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise StrategyExistsError(
                    f"A strategy named {name.strip()!r} already exists."
                ) from error

            if cursor.rowcount == 0:
                raise StrategyNotFoundError(strategy_id)

        found = self.get(strategy_id)

        if found is None:
            raise StrategyNotFoundError(strategy_id)

        return found

    def delete(self, strategy_id: str) -> None:
        if strategy_id == BUILTIN_ID:
            raise StrategyReadOnlyError(
                "The built-in strategy cannot be deleted."
            )

        if strategy_id.startswith(SCRIPT_PREFIX):
            raise StrategyReadOnlyError(
                "A strategy script is removed by deleting its file."
            )

        with self._db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM strategies WHERE id = ?", (strategy_id,)
            )

            if cursor.rowcount == 0:
                raise StrategyNotFoundError(strategy_id)

            # Deleting the active strategy is allowed; the selection is
            # cleared so resolution returns the built-in rather than
            # pointing at a row that is gone.
            conn.execute(
                "DELETE FROM settings WHERE key = ? AND value = ?",
                (ACTIVE_KEY, strategy_id),
            )

        logger.info("Strategy deleted", extra={"context": {"id": strategy_id}})

    def activate(self, strategy_id: str) -> Strategy:
        strategy = self.get(strategy_id)

        if strategy is None:
            raise StrategyNotFoundError(strategy_id)

        now = datetime.now(tz=timezone.utc).isoformat()

        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (ACTIVE_KEY, strategy_id, now),
            )

        logger.info("Active strategy changed", extra={"context": {"to": strategy.name}})

        return strategy

    # -- internals --------------------------------------------------

    @staticmethod
    def _row_to_strategy(row: sqlite3.Row) -> Strategy | None:
        try:
            return Strategy(
                id=str(row["id"]),
                name=str(row["name"]),
                parameters=StrategyParameters.model_validate(
                    json.loads(str(row["parameters"]))
                ),
                notes=str(row["notes"]),
                builtin=False,
                created_at=datetime.fromisoformat(str(row["created_at"])),
                updated_at=datetime.fromisoformat(str(row["updated_at"])),
            )
        except (ValueError, KeyError, TypeError):
            logger.exception(
                "Stored strategy could not be read",
                extra={"context": {"id": str(row["id"])}},
            )
            return None
