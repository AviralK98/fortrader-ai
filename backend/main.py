"""Entrypoint for the backend sidecar.

Two modes, one executable:

* default — run the HTTP backend. Started automatically by the Electron
  main process, which waits for the port rather than polling blindly.
* ``--mcp`` — run the read-only MCP stdio bridge instead.

Sharing one binary matters for distribution: an installed copy has no
Python and no source tree, so Claude Code must be able to point at
something that already exists on the user's machine. That is this exe.
"""

from __future__ import annotations

import argparse
import json
import sys

from backend.version import VERSION


def run_mcp_bridge() -> int:
    """Run the stdio MCP bridge.

    Imported lazily so the HTTP path never pays for it, and so a broken
    MCP dependency cannot stop the backend from serving.
    """
    from mcp_bridge.server import main as bridge_main

    bridge_main()

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="fortrader-backend",
        description="Fortrader AI backend. Read-only; cannot place trades.",
    )
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Run the read-only MCP stdio bridge instead of the HTTP server.",
    )
    parser.add_argument(
        "--run-strategy",
        metavar="PATH",
        help="Run one strategy script against JSON on stdin. Internal.",
    )
    parser.add_argument(
        "--version", action="version", version=f"fortrader-backend {VERSION}"
    )

    args = parser.parse_args()

    if args.mcp:
        # stdout belongs to the MCP protocol in this mode, so nothing else
        # may be printed to it.
        return run_mcp_bridge()

    if args.run_strategy:
        # Deliberately before logging is configured: this process exists
        # to run one user script and print one line of JSON, and a log
        # file opened here would be opened once per signal.
        from backend.strategies.scripts import run_child

        return run_child(args.run_strategy)

    # Imported here rather than at module scope: --run-strategy above
    # returns before this, and the runner is spawned once per signal.
    import uvicorn

    from backend.api.server import create_app
    from backend.config import load_settings
    from backend.logging_setup import configure_logging, get_logger

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
