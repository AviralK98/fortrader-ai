"""Entrypoint for the backend sidecar.

Started automatically by the Electron main process. Prints a single
machine-readable ready line on stdout so the parent can wait for the port
to be live instead of polling blindly.
"""

from __future__ import annotations

import json
import sys

import uvicorn

from backend.api.server import VERSION, create_app
from backend.config import load_settings
from backend.logging_setup import configure_logging, get_logger


def main() -> int:
    settings = load_settings()

    configure_logging(level=settings.log_level, log_dir=settings.log_dir)

    logger = get_logger(__name__)

    app = create_app(settings)

    # Consumed by desktop/main/backend-process.ts.
    print(
        json.dumps(
            {
                "event": "backend_ready_pending",
                "version": VERSION,
                "url": settings.base_url,
            }
        ),
        flush=True,
    )

    try:
        uvicorn.run(
            app,
            host=settings.host,
            port=settings.port,
            log_config=None,
            access_log=False,
        )
    except KeyboardInterrupt:
        logger.info("Backend interrupted")
        return 0
    except Exception:
        logger.exception("Backend terminated unexpectedly")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
