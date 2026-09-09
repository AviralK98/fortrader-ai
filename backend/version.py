"""The application version, on its own.

Kept out of the API module so that reading it costs nothing. The
strategy runner is spawned once per signal and needs the entry point to
start fast; importing `backend.api.server` for a string would drag in
FastAPI, uvicorn and pandas -- about two seconds, every run.
"""

VERSION = "0.5.1"
