"""Runtime configuration for the Fortrader AI backend.

Configuration is resolved from environment variables so that the Electron
main process can control the sidecar without a config file on disk. Every
value has a development-friendly default.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "FortraderAI"

# Bound to loopback only. This process must never be reachable off-machine.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8756


def _default_data_dir() -> Path:
    """Per-user writable directory for the database and logs.

    Only a fallback: the desktop shell passes `FORTRADER_DATA_DIR`
    explicitly so that both processes agree on one location. This matters
    when the backend is run standalone.
    """
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")

        if local_app_data:
            return Path(local_app_data) / APP_NAME

    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME

    return Path.home() / f".{APP_NAME.lower()}"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)

    if raw is None:
        return default

    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Immutable backend settings."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT

    data_dir: Path = field(default_factory=_default_data_dir)

    log_level: str = "INFO"

    # Phase gate. While False the application refuses to expose any
    # order-placing surface. Nothing in this codebase sets it True.
    trading_enabled: bool = False

    @property
    def database_path(self) -> Path:
        return self.data_dir / "fortrader.sqlite3"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def load_settings() -> Settings:
    """Build settings from the environment."""
    data_dir_raw = os.environ.get("FORTRADER_DATA_DIR")

    settings = Settings(
        host=os.environ.get("FORTRADER_HOST", DEFAULT_HOST),
        port=int(os.environ.get("FORTRADER_PORT", DEFAULT_PORT)),
        data_dir=Path(data_dir_raw) if data_dir_raw else _default_data_dir(),
        log_level=os.environ.get("FORTRADER_LOG_LEVEL", "INFO").upper(),
        trading_enabled=False,
    )

    if _env_bool("FORTRADER_TRADING_ENABLED", False):
        # Deliberately ignored rather than honoured. Execution is out of
        # scope for this phase and must not be reachable by configuration.
        raise RuntimeError(
            "FORTRADER_TRADING_ENABLED is set, but live execution is not "
            "implemented in this build and cannot be enabled."
        )

    return settings
