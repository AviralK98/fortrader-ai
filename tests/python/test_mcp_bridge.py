from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_bridge.client import (
    NOT_RUNNING_MESSAGE,
    BackendClient,
    BackendError,
    BackendUnavailableError,
    _discover_base_url,
)


class TestDiscovery:
    def test_explicit_url_wins(self) -> None:
        client = BackendClient("http://127.0.0.1:9999/")

        assert client.base_url == "http://127.0.0.1:9999"

    def test_env_var_is_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FORTRADER_BACKEND_URL", "http://127.0.0.1:1234")

        assert BackendClient().base_url == "http://127.0.0.1:1234"

    def test_reads_runtime_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runtime = tmp_path / "FortraderAI" / "data"
        runtime.mkdir(parents=True)

        (runtime / "runtime.json").write_text(
            json.dumps({"url": "http://127.0.0.1:7777", "pid": 42}),
            encoding="utf-8",
        )

        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

        assert _discover_base_url() == "http://127.0.0.1:7777"

    def test_missing_runtime_file_is_not_an_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

        assert _discover_base_url() is None

    def test_corrupt_runtime_file_is_not_an_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runtime = tmp_path / "FortraderAI" / "data"
        runtime.mkdir(parents=True)
        (runtime / "runtime.json").write_text("not json", encoding="utf-8")

        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

        assert _discover_base_url() is None


class TestFailureBehaviour:
    """A missing desktop app must fail fast and readably, never hang."""

    def test_reports_not_running(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FORTRADER_BACKEND_URL", raising=False)

        # Port 1 is reserved and refuses immediately.
        client = BackendClient("http://127.0.0.1:1")

        with pytest.raises(BackendUnavailableError) as exc:
            client.get("/health")

        assert str(exc.value) == NOT_RUNNING_MESSAGE

    def test_is_running_is_false_when_absent(self) -> None:
        assert BackendClient("http://127.0.0.1:1").is_running() is False

    def test_connect_timeout_is_short(self) -> None:
        # Guards against a regression that would hang Claude Code.
        client = BackendClient("http://127.0.0.1:1")

        assert client._timeout.connect is not None
        assert client._timeout.connect <= 3.0


class TestNoExecutionTools:
    def test_bridge_exposes_no_order_entry(self) -> None:
        import mcp_bridge.server as server

        forbidden = {
            "open_trade",
            "close_trade",
            "modify_trade",
            "place_order",
            "buy",
            "sell",
            "submit_order",
        }

        exported = {name for name in dir(server) if not name.startswith("_")}

        assert not forbidden & exported

    def test_client_has_no_mutating_helper(self) -> None:
        assert not hasattr(BackendClient, "post")


def test_backend_error_is_distinct_from_unavailable() -> None:
    assert not issubclass(BackendError, BackendUnavailableError)
    assert not issubclass(BackendUnavailableError, BackendError)
