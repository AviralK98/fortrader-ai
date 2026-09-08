"""User-defined strategies.

Two properties matter more than the CRUD around them:

1. The built-in strategy survives anything the user does. It is defined
   in code, so no edit, deletion or damaged row can leave the engine
   without a configuration.
2. A strategy is data. Nothing here imports, evaluates or executes what
   is stored, because a strategy shared between friends must not be able
   to run on their machine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.fortrade.models import Timeframe
from backend.signals.config import DEFAULT_CONFIG
from backend.storage.database import Database
from backend.strategies.models import (
    BUILTIN_ID,
    StrategyParameters,
    builtin_strategy,
)
from backend.strategies.repository import (
    ACTIVE_KEY,
    MAX_STRATEGIES,
    StrategyExistsError,
    StrategyNotFoundError,
    StrategyReadOnlyError,
    StrategyRepository,
    TooManyStrategiesError,
)


@pytest.fixture
def repo(tmp_path: Path) -> StrategyRepository:
    database = Database(tmp_path / "test.sqlite3")
    database.initialise()

    return StrategyRepository(database)


def params(**overrides: float) -> StrategyParameters:
    return StrategyParameters(**overrides)  # type: ignore[arg-type]


class TestBuiltIn:
    def test_matches_the_shipped_engine(self) -> None:
        # If these drift, the strategy shown as "Built-in" is not the one
        # the application actually ships with.
        built = builtin_strategy().parameters

        assert built.direction_threshold == DEFAULT_CONFIG.direction_threshold
        assert built.timeframe_weights == DEFAULT_CONFIG.timeframe_weights
        assert (
            built.minimum_bars_for_timeframe
            == DEFAULT_CONFIG.minimum_bars_for_timeframe
        )

    def test_is_present_without_being_stored(
        self, repo: StrategyRepository
    ) -> None:
        listed = repo.list()

        assert len(listed) == 1
        assert listed[0].id == BUILTIN_ID
        assert listed[0].builtin is True

    def test_is_always_listed_first(self, repo: StrategyRepository) -> None:
        repo.create("AAA sorts before builtin", params())

        assert repo.list()[0].id == BUILTIN_ID

    def test_cannot_be_edited(self, repo: StrategyRepository) -> None:
        with pytest.raises(StrategyReadOnlyError):
            repo.update(BUILTIN_ID, "Renamed", params())

    def test_cannot_be_deleted(self, repo: StrategyRepository) -> None:
        with pytest.raises(StrategyReadOnlyError):
            repo.delete(BUILTIN_ID)

    def test_is_the_default_when_nothing_is_selected(
        self, repo: StrategyRepository
    ) -> None:
        assert repo.active().id == BUILTIN_ID

    def test_is_the_fallback_when_the_selection_is_gone(
        self, repo: StrategyRepository
    ) -> None:
        # Deleting the active strategy must not leave the engine pointing
        # at a row that no longer exists.
        created = repo.create("Mine", params())
        repo.activate(created.id)
        repo.delete(created.id)

        assert repo.active().id == BUILTIN_ID

    def test_survives_a_selection_pointing_at_nothing(
        self, repo: StrategyRepository
    ) -> None:
        with repo._db.transaction() as conn:
            conn.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                (ACTIVE_KEY, "does-not-exist", "2026-01-01T00:00:00+00:00"),
            )

        assert repo.active().id == BUILTIN_ID

    def test_a_damaged_row_does_not_break_the_list(
        self, repo: StrategyRepository
    ) -> None:
        repo.create("Good", params())

        with repo._db.transaction() as conn:
            conn.execute(
                "INSERT INTO strategies "
                "(id, name, parameters, notes, created_at, updated_at) "
                "VALUES ('broken', 'Broken', 'not json', '', ?, ?)",
                ("2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
            )

        listed = repo.list()

        assert [s.name for s in listed] == ["Built-in", "Good"]


class TestLifecycle:
    def test_create_and_read_back(self, repo: StrategyRepository) -> None:
        created = repo.create("Slower", params(direction_threshold=0.4), "notes")

        found = repo.get(created.id)

        assert found is not None
        assert found.name == "Slower"
        assert found.notes == "notes"
        assert found.parameters.direction_threshold == pytest.approx(0.4)
        assert found.builtin is False

    def test_names_are_unique(self, repo: StrategyRepository) -> None:
        repo.create("Mine", params())

        with pytest.raises(StrategyExistsError):
            repo.create("Mine", params())

    def test_update_changes_the_parameters(
        self, repo: StrategyRepository
    ) -> None:
        created = repo.create("Mine", params())

        updated = repo.update(
            created.id, "Mine", params(direction_threshold=0.5)
        )

        assert updated.parameters.direction_threshold == pytest.approx(0.5)

    def test_update_of_a_missing_strategy_raises(
        self, repo: StrategyRepository
    ) -> None:
        with pytest.raises(StrategyNotFoundError):
            repo.update("nope", "X", params())

    def test_delete_of_a_missing_strategy_raises(
        self, repo: StrategyRepository
    ) -> None:
        with pytest.raises(StrategyNotFoundError):
            repo.delete("nope")

    def test_activation_selects_it(self, repo: StrategyRepository) -> None:
        created = repo.create("Mine", params())

        repo.activate(created.id)

        assert repo.active().id == created.id

    def test_activating_something_missing_raises(
        self, repo: StrategyRepository
    ) -> None:
        with pytest.raises(StrategyNotFoundError):
            repo.activate("nope")

    def test_storage_is_bounded(self, repo: StrategyRepository) -> None:
        # A UI with a duplicate button and no ceiling is a way to fill a
        # disk, so the limit is enforced rather than assumed.
        for i in range(MAX_STRATEGIES):
            repo.create(f"Strategy {i}", params())

        with pytest.raises(TooManyStrategiesError):
            repo.create("One too many", params())


class TestValidation:
    """A strategy that cannot produce a signal must not be storable."""

    @pytest.mark.parametrize(
        "field,value",
        [
            ("direction_threshold", 0.0),
            ("direction_threshold", 1.0),
            ("direction_threshold", -0.5),
            ("stretched_rsi_penalty", 1.5),
            ("level_proximity_atr", 0.0),
            ("level_proximity_effect", 2.0),
            ("minimum_bars_for_timeframe", 1),
        ],
    )
    def test_out_of_range_values_are_refused(
        self, repo: StrategyRepository, field: str, value: float
    ) -> None:
        with pytest.raises(ValueError):
            repo.create("Bad", params(**{field: value}))

    def test_empty_timeframe_weights_are_refused(
        self, repo: StrategyRepository
    ) -> None:
        with pytest.raises(ValueError):
            repo.create(
                "Bad", StrategyParameters(timeframe_weights={})
            )

    def test_negative_weights_are_refused(
        self, repo: StrategyRepository
    ) -> None:
        with pytest.raises(ValueError):
            repo.create(
                "Bad",
                StrategyParameters(timeframe_weights={Timeframe.M5: -1.0}),
            )

    def test_weights_summing_to_zero_are_refused(
        self, repo: StrategyRepository
    ) -> None:
        with pytest.raises(ValueError):
            repo.create(
                "Bad",
                StrategyParameters(timeframe_weights={Timeframe.M5: 0.0}),
            )

    def test_unknown_fields_are_refused(self) -> None:
        # extra="forbid": a stored strategy cannot smuggle in a key the
        # engine does not know about.
        with pytest.raises(ValueError):
            StrategyParameters.model_validate(
                {"direction_threshold": 0.3, "run_this": "rm -rf /"}
            )

    def test_a_stored_strategy_produces_a_usable_engine_config(
        self, repo: StrategyRepository
    ) -> None:
        created = repo.create("Mine", params(direction_threshold=0.31))

        config = created.parameters.to_config()

        assert config.direction_threshold == pytest.approx(0.31)
        assert config.validated() is config


class TestNoCodeExecution:
    """Strategies are parameters. They are never code."""

    def test_the_stored_shape_holds_only_numbers(self) -> None:
        stored = builtin_strategy().parameters.model_dump()

        stored.pop("timeframe_weights")

        for key, value in stored.items():
            assert isinstance(value, (int, float)), f"{key} is not a number"

    def test_the_strategy_modules_never_evaluate_anything(self) -> None:
        import ast

        root = Path(__file__).resolve().parents[2] / "backend" / "strategies"

        forbidden = {"eval", "exec", "compile", "__import__"}

        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))

            called = {
                node.func.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }

            assert not forbidden & called, f"{path.name} evaluates input"

    def test_the_strategy_modules_import_nothing_dynamic(self) -> None:
        import ast

        root = Path(__file__).resolve().parents[2] / "backend" / "strategies"

        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))

            imported = {
                node.module
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module
            } | {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            }

            for module in imported:
                assert module not in {
                    "importlib",
                    "runpy",
                    "subprocess",
                    "pickle",
                }, f"{path.name} imports {module}"
