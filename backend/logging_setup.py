"""Structured logging with mandatory redaction of session material.

Anything flowing out of the Fortrade browser session may contain cookies,
bearer tokens or account identifiers. Redaction is applied as a logging
filter so it cannot be bypassed by a caller forgetting to sanitise.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REDACTED = "[REDACTED]"

# Substring match against a key name; any hit redacts the whole value.
SENSITIVE_KEY_PARTS = (
    "cookie",
    "authorization",
    "auth",
    "token",
    "password",
    "passwd",
    "secret",
    "session",
    "credential",
    "api_key",
    "apikey",
    "bearer",
    "jwt",
    "signature",
)

# Bare secrets: the whole match is the secret, so it is replaced outright.
_JWT = re.compile(
    r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/]+=*")

# Key/value pairs: the key is informative and is kept, the value is not.
# The value stops at whitespace or a separator so trailing context survives.
_KEY_VALUE = re.compile(
    r"(?i)\b("
    r"authorization|set-cookie|cookie"
    r"|password|passwd|secret"
    r"|token|api[_-]?key|apikey"
    r"|session[_-]?id|jwt|signature"
    r")\s*[:=]\s*[^\s;,&]+"
)


def redact_text(text: str) -> str:
    """Strip credential-shaped substrings from free text.

    Order matters: bare tokens are removed before the key/value pass, so a
    secret is never left behind by a rule that only rewrites its label.
    """
    text = _JWT.sub(REDACTED, text)
    text = _BEARER.sub(f"Bearer {REDACTED}", text)
    text = _KEY_VALUE.sub(lambda m: f"{m.group(1)}={REDACTED}", text)

    return text


def redact_value(key: str, value: Any) -> Any:
    """Redact a single key/value pair, recursing into containers."""
    lowered = key.lower()

    if any(part in lowered for part in SENSITIVE_KEY_PARTS):
        return REDACTED

    return redact(value)


def redact(value: Any) -> Any:
    """Recursively redact a structure before it reaches a log sink."""
    if isinstance(value, dict):
        return {k: redact_value(str(k), v) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]

    if isinstance(value, str):
        return redact_text(value)

    return value


class RedactionFilter(logging.Filter):
    """Applies redaction to every record passing through a handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = redact(record.args)
            else:
                record.args = tuple(redact(arg) for arg in record.args)

        extra = getattr(record, "context", None)

        if extra is not None:
            record.context = redact(extra)

        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, so the Electron side can parse the stream."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        context = getattr(record, "context", None)

        if context is not None:
            payload["context"] = context

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    """Install the redacting JSON logging configuration."""
    root = logging.getLogger()
    root.setLevel(level)

    for existing in list(root.handlers):
        root.removeHandler(existing)

    redaction = RedactionFilter()
    formatter = JsonFormatter()

    # stderr, so stdout stays clean for any future stdio protocol use.
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(redaction)
    root.addHandler(stream_handler)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(
            log_dir / "backend.log", encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redaction)
        root.addHandler(file_handler)

    # uvicorn's own handlers would bypass our filter.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
