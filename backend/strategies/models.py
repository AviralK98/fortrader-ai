"""What a user-defined strategy is, and what it deliberately is not.

A strategy is a **named set of parameters** for the signal engine. It is
not code. Nothing here is imported, evaluated or executed: every field is
a number or a weight that the existing deterministic engine already
accepts, and every one of them is bounds-checked before it is stored.

That restraint is the whole design. Letting people drop a Python file in
a folder would be more powerful and would also mean a strategy shared
between friends is an executable with full access to the machine, the
Fortrade session and every credential on it. Parameters can be shared
safely; code cannot.

The built-in strategy is defined in code rather than seeded into the
database. It is always present, cannot be edited, and cannot be deleted,
so no amount of editing or a damaged table can leave the application
without a working engine.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from backend.fortrade.models import Timeframe
from backend.signals.config import DEFAULT_CONFIG, SignalConfig

#: Reserved id of the strategy shipped with the application.
BUILTIN_ID = "builtin"

BUILTIN_NAME = "Built-in"

BUILTIN_NOTES = (
    "The engine the application ships with. Read-only: duplicate it to "
    "make your own. Its numbers have not been tuned to any measured "
    "result -- they are a starting point, not a recommendation."
)

#: Bounds every stored strategy is held to. These are not opinions about
#: what trades well; they are the range in which the engine produces
#: meaningful output at all.
LIMITS: dict[str, tuple[float, float]] = {
    "direction_threshold": (0.01, 0.99),
    "minimum_bars_for_timeframe": (20, 5000),
    "stretched_rsi_penalty": (0.0, 1.0),
    "level_proximity_atr": (0.1, 10.0),
    "level_proximity_effect": (0.0, 1.0),
}

MAX_NAME_CHARS = 60
MAX_NOTES_CHARS = 500


class StrategyParameters(BaseModel):
    """The tunable surface of the signal engine, as data.

    Mirrors `SignalConfig`. Kept separate so the stored shape is
    explicitly validated at the boundary rather than trusting whatever
    JSON happens to be in the table.
    """

    model_config = ConfigDict(extra="forbid")

    direction_threshold: float = DEFAULT_CONFIG.direction_threshold
    minimum_bars_for_timeframe: int = DEFAULT_CONFIG.minimum_bars_for_timeframe
    stretched_rsi_penalty: float = DEFAULT_CONFIG.stretched_rsi_penalty
    level_proximity_atr: float = DEFAULT_CONFIG.level_proximity_atr
    level_proximity_effect: float = DEFAULT_CONFIG.level_proximity_effect

    timeframe_weights: dict[Timeframe, float] = Field(
        default_factory=lambda: dict(DEFAULT_CONFIG.timeframe_weights)
    )

    @classmethod
    def from_config(cls, config: SignalConfig) -> StrategyParameters:
        return cls(
            direction_threshold=config.direction_threshold,
            minimum_bars_for_timeframe=config.minimum_bars_for_timeframe,
            stretched_rsi_penalty=config.stretched_rsi_penalty,
            level_proximity_atr=config.level_proximity_atr,
            level_proximity_effect=config.level_proximity_effect,
            timeframe_weights=dict(config.timeframe_weights),
        )

    def to_config(self) -> SignalConfig:
        """Build the engine's own config, validated as the engine would."""
        return SignalConfig(
            direction_threshold=self.direction_threshold,
            minimum_bars_for_timeframe=self.minimum_bars_for_timeframe,
            stretched_rsi_penalty=self.stretched_rsi_penalty,
            level_proximity_atr=self.level_proximity_atr,
            level_proximity_effect=self.level_proximity_effect,
            timeframe_weights=dict(self.timeframe_weights),
        ).validated()

    def checked(self) -> StrategyParameters:
        """Reject values the engine cannot do anything sensible with.

        `SignalConfig.validated()` catches what is structurally broken.
        This additionally holds each number inside a usable range, so a
        strategy cannot be saved that silently never produces a signal.
        """
        for field_name, (low, high) in LIMITS.items():
            value = float(getattr(self, field_name))

            if not low <= value <= high:
                raise ValueError(
                    f"{field_name} must be between {low} and {high}, got {value}"
                )

        if not self.timeframe_weights:
            raise ValueError("at least one timeframe weight is required")

        if any(weight < 0 for weight in self.timeframe_weights.values()):
            raise ValueError("timeframe weights must not be negative")

        if sum(self.timeframe_weights.values()) <= 0:
            raise ValueError("timeframe weights must sum to more than zero")

        # Proves the engine will accept it, so a strategy cannot be
        # stored that only fails later when a signal is requested.
        self.to_config()

        return self


#: Prefix marking a strategy that is a file on disk rather than a row.
SCRIPT_PREFIX = "script:"


def script_id(filename: str) -> str:
    return f"{SCRIPT_PREFIX}{filename}"


class Strategy(BaseModel):
    """A named strategy: either a parameter set or a user script."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)
    parameters: StrategyParameters
    notes: str = Field(default="", max_length=MAX_NOTES_CHARS)

    #: Shipped with the application: cannot be edited or deleted.
    builtin: bool = False

    #: "parameters" tunes the built-in engine; "script" replaces the
    #: decision with a Python file the user wrote. Scripts are discovered
    #: from a folder rather than stored, so editing one means editing the
    #: file -- the application never rewrites a user's code.
    kind: str = Field(default="parameters", pattern="^(parameters|script)$")

    #: Filename within the scripts folder. Set only when kind is "script".
    script: str | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))


#: Fixed rather than "now". The built-in strategy is defined in code and
#: never changes, so a timestamp that moves on every read is not only
#: untrue -- it also defeats anything keyed on it, which is exactly how
#: the signal cache came to miss every single request.
BUILTIN_TIMESTAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)


def builtin_strategy() -> Strategy:
    """The engine as shipped. Synthesised, never read from the database."""
    return Strategy(
        id=BUILTIN_ID,
        name=BUILTIN_NAME,
        parameters=StrategyParameters.from_config(DEFAULT_CONFIG),
        notes=BUILTIN_NOTES,
        builtin=True,
        created_at=BUILTIN_TIMESTAMP,
        updated_at=BUILTIN_TIMESTAMP,
    )
