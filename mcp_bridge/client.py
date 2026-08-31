"""HTTP client from the MCP bridge to the running backend.

The bridge is a thin stdio process. It holds no market state and performs
no analysis — it forwards to the backend owned by the desktop application.

Failure behaviour matters here: if Fortrader AI is not running, Claude Code
must get a clear answer quickly rather than a hung tool call.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8756"


def _discover_base_url() -> str | None:
    """Read the URL published by a running desktop application.

    The app writes `runtime.json` on startup and deletes it on shutdown, so
    the bridge finds the live instance without the user configuring a port.
    """
    local_app_data = os.environ.get("LOCALAPPDATA")

    if not local_app_data:
        return None

    runtime = Path(local_app_data) / "FortraderAI" / "data" / "runtime.json"

    try:
        payload = json.loads(runtime.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    url = payload.get("url")

    return url if isinstance(url, str) else None

# Deliberately short. A missing backend should surface in about a second.
CONNECT_TIMEOUT = 1.5
READ_TIMEOUT = 10.0

NOT_RUNNING_MESSAGE = (
    "Fortrader AI is not currently running. "
    "Start the Fortrader AI desktop application and try again."
)


class BackendUnavailableError(RuntimeError):
    """The desktop application is not running or not reachable."""


class BackendError(RuntimeError):
    """The backend responded, but with an error."""


class BackendClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (
            base_url
            or os.environ.get("FORTRADER_BACKEND_URL")
            or _discover_base_url()
            or DEFAULT_BASE_URL
        ).rstrip("/")

        self._timeout = httpx.Timeout(
            READ_TIMEOUT,
            connect=CONNECT_TIMEOUT,
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"

        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.request(method, url, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise BackendUnavailableError(NOT_RUNNING_MESSAGE) from exc
        except httpx.TimeoutException as exc:
            raise BackendUnavailableError(
                "Fortrader AI did not respond in time."
            ) from exc

        if response.status_code == 503:
            detail = _detail(response)
            raise BackendError(
                f"Data not available yet: {detail}. "
                "Fortrade may still be loading or awaiting login."
            )

        if response.status_code == 404:
            raise BackendError(_detail(response))

        if response.status_code >= 400:
            raise BackendError(
                f"Backend returned {response.status_code}: {_detail(response)}"
            )

        return response.json()

    def get(self, path: str, **params: Any) -> Any:
        clean = {k: v for k, v in params.items() if v is not None}

        return self._request("GET", path, params=clean)

    def is_running(self) -> bool:
        try:
            self._request("GET", "/health")
            return True
        except (BackendUnavailableError, BackendError):
            return False


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]

    if isinstance(body, dict):
        detail = body.get("detail") or body.get("error")

        if isinstance(detail, str):
            return detail

    return str(body)[:200]
