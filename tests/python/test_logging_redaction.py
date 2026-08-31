"""Redaction is a security control, so it is tested as one."""

from __future__ import annotations

import logging

import pytest

from backend.logging_setup import (
    REDACTED,
    JsonFormatter,
    RedactionFilter,
    redact,
    redact_text,
)


class TestRedactText:
    @pytest.mark.parametrize(
        "text",
        [
            "Cookie: session=abc123secret",
            "authorization: Bearer eyJhbGciOi.JzdWIiOiIx.SflKxwRJSM",
            "Set-Cookie: FTSESSION=deadbeefcafe; Path=/",
            "password=hunter2",
            "api_key: sk-live-0123456789abcdef",
            "token=9f8e7d6c5b4a3210",
        ],
    )
    def test_credential_shapes_are_removed(self, text: str) -> None:
        result = redact_text(text)

        assert REDACTED in result

        for secret in (
            "abc123secret",
            "SflKxwRJSM",
            "deadbeefcafe",
            "hunter2",
            "sk-live-0123456789abcdef",
            "9f8e7d6c5b4a3210",
        ):
            assert secret not in result

    def test_bare_jwt_is_removed(self) -> None:
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.dBjftJeZ4CVPmB92K"

        assert jwt not in redact_text(f"observed {jwt} in frame")

    def test_ordinary_text_survives(self) -> None:
        text = "GBP/USD quote 1.35284/1.35408 spread 124 points"

        assert redact_text(text) == text


class TestRedactStructure:
    def test_sensitive_keys_are_redacted(self) -> None:
        result = redact(
            {
                "symbol": "GBP/USD",
                "cookie": "FTSESSION=abc",
                "Authorization": "Bearer xyz",
                "sessionToken": "tok_123",
                "balance": 10000.0,
            }
        )

        assert result["symbol"] == "GBP/USD"
        assert result["balance"] == 10000.0
        assert result["cookie"] == REDACTED
        assert result["Authorization"] == REDACTED
        assert result["sessionToken"] == REDACTED

    def test_recurses_into_nested_containers(self) -> None:
        result = redact(
            {"request": {"headers": [{"cookie": "a=b"}, {"accept": "json"}]}}
        )

        headers = result["request"]["headers"]

        assert headers[0]["cookie"] == REDACTED
        assert headers[1]["accept"] == "json"

    def test_non_string_scalars_pass_through(self) -> None:
        assert redact({"count": 5, "ok": True, "ratio": 1.5}) == {
            "count": 5,
            "ok": True,
            "ratio": 1.5,
        }


class TestFilterAndFormatter:
    def _record(self, msg: str, **extra: object) -> logging.LogRecord:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=msg,
            args=(),
            exc_info=None,
        )

        for key, value in extra.items():
            setattr(record, key, value)

        return record

    def test_filter_scrubs_message(self) -> None:
        record = self._record("Cookie: session=leaky")

        RedactionFilter().filter(record)

        assert "leaky" not in record.getMessage()

    def test_filter_scrubs_context(self) -> None:
        record = self._record("ok", context={"token": "leaky"})

        RedactionFilter().filter(record)

        assert record.context["token"] == REDACTED  # type: ignore[attr-defined]

    def test_formatter_emits_single_line_json(self) -> None:
        import json

        record = self._record("hello", context={"symbol": "GBP/USD"})

        line = JsonFormatter().format(record)

        assert "\n" not in line

        payload = json.loads(line)

        assert payload["message"] == "hello"
        assert payload["level"] == "INFO"
        assert payload["context"]["symbol"] == "GBP/USD"
