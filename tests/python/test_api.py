from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.server import create_app
from backend.config import Settings
from backend.fortrade.state import AppState

TOKEN = "test-ingest-token"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("FORTRADER_INGEST_TOKEN", TOKEN)

    app = create_app(Settings(data_dir=tmp_path))

    with TestClient(app) as test_client:
        yield test_client


def auth() -> dict[str, str]:
    return {"X-Ingest-Token": TOKEN}


SNAPSHOT = {
    "account": {
        "balance": 10000.0,
        "equity": 10000.0,
        "open_pnl": 0.0,
        "used_margin": 0.0,
        "available_margin": 10000.0,
        "currency": "GBP",
        "account_type": "DEMO",
    },
    "quotes": [
        {"symbol": "GBP/USD", "sell": 1.35284, "buy": 1.35408},
        {"symbol": "EUR/USD", "sell": 1.15811, "buy": 1.15836},
    ],
    "positions": [],
    "chart": {"symbol": "GBP/USD", "timeframe": "M5"},
}


class TestHealth:
    def test_reports_ok(self, client: TestClient) -> None:
        body = client.get("/health").json()

        assert body["ok"] is True
        assert body["schema_version"] >= 1

    def test_trading_is_reported_disabled(self, client: TestClient) -> None:
        assert client.get("/health").json()["trading_enabled"] is False


class TestStatus:
    def test_starts_stale_with_no_data(self, client: TestClient) -> None:
        status = client.get("/api/status").json()["status"]

        assert status["stale"] is True
        assert status["last_snapshot_at"] is None
        assert status["database"] == "READY"

    def test_becomes_connected_after_ingest(self, client: TestClient) -> None:
        client.post(
            "/internal/ingest/snapshot", json=SNAPSHOT, headers=auth()
        )

        status = client.get("/api/status").json()["status"]

        assert status["state"] == AppState.CONNECTED.value
        assert status["stale"] is False
        assert status["data_age_seconds"] is not None


class TestReadEndpointsBeforeData:
    @pytest.mark.parametrize(
        "path", ["/api/account", "/api/quotes", "/api/chart"]
    )
    def test_return_503_not_fabricated_data(
        self, client: TestClient, path: str
    ) -> None:
        assert client.get(path).status_code == 503

    def test_positions_are_empty_not_erroring(self, client: TestClient) -> None:
        body = client.get("/api/positions").json()

        assert body["positions"] == []
        assert body["count"] == 0


class TestReadEndpointsAfterIngest:
    @pytest.fixture(autouse=True)
    def _ingest(self, client: TestClient) -> None:
        client.post(
            "/internal/ingest/snapshot", json=SNAPSHOT, headers=auth()
        )

    def test_account(self, client: TestClient) -> None:
        body = client.get("/api/account").json()

        assert body["balance"] == pytest.approx(10000.0)
        assert body["account_type"] == "DEMO"

    def test_quotes(self, client: TestClient) -> None:
        body = client.get("/api/quotes").json()

        assert body["count"] == 2

    def test_single_quote_with_slash_in_symbol(
        self, client: TestClient
    ) -> None:
        body = client.get("/api/quotes/GBP/USD").json()

        assert body["symbol"] == "GBP/USD"

    def test_unknown_symbol_is_404(self, client: TestClient) -> None:
        assert client.get("/api/quotes/AUD/CAD").status_code == 404

    def test_symbols(self, client: TestClient) -> None:
        assert client.get("/api/symbols").json()["symbols"] == [
            "EUR/USD",
            "GBP/USD",
        ]

    def test_chart(self, client: TestClient) -> None:
        assert client.get("/api/chart").json()["timeframe"] == "M5"


class TestCandles:
    def test_empty_series_reports_insufficient(
        self, client: TestClient
    ) -> None:
        body = client.get(
            "/api/candles", params={"symbol": "GBP/USD", "limit": 100}
        ).json()

        assert body["count"] == 0
        assert body["sufficient"] is False

    def test_ingest_then_read(self, client: TestClient) -> None:
        candles = [
            {
                "symbol": "GBP/USD",
                "timeframe": "M5",
                "timestamp": f"2026-08-28T12:{minute:02d}:00Z",
                "open": 1.35,
                "high": 1.36,
                "low": 1.34,
                "close": 1.355,
            }
            for minute in range(0, 30, 5)
        ]

        result = client.post(
            "/internal/ingest/candles",
            json={"candles": candles},
            headers=auth(),
        ).json()

        assert result["stored"] == 6

        body = client.get(
            "/api/candles",
            params={"symbol": "GBP/USD", "timeframe": "M5", "limit": 6},
        ).json()

        assert body["count"] == 6
        assert body["sufficient"] is True

    def test_rejects_invalid_timeframe(self, client: TestClient) -> None:
        response = client.get(
            "/api/candles", params={"symbol": "GBP/USD", "timeframe": "M7"}
        )

        assert response.status_code == 422


class TestIngestAuthentication:
    @pytest.mark.parametrize(
        "path",
        [
            "/internal/ingest/snapshot",
            "/internal/ingest/candles",
            "/internal/state",
        ],
    )
    def test_requires_token(self, client: TestClient, path: str) -> None:
        assert client.post(path, json={}).status_code == 401

    def test_rejects_wrong_token(self, client: TestClient) -> None:
        response = client.post(
            "/internal/ingest/snapshot",
            json=SNAPSHOT,
            headers={"X-Ingest-Token": "wrong"},
        )

        assert response.status_code == 401

    def test_rejects_unknown_fields(self, client: TestClient) -> None:
        response = client.post(
            "/internal/ingest/snapshot",
            json={**SNAPSHOT, "injected": "value"},
            headers=auth(),
        )

        assert response.status_code == 422


class TestStateTransitions:
    def test_can_be_set_by_shell(self, client: TestClient) -> None:
        body = client.post(
            "/internal/state",
            json={"state": "AUTH_REQUIRED", "detail": "Login required"},
            headers=auth(),
        ).json()

        assert body["status"]["state"] == "AUTH_REQUIRED"
        assert body["status"]["detail"] == "Login required"


class TestNoExecutionSurface:
    """The invariant: no route can place a real order.

    Phase I adds simulated positions, which legitimately need POST routes
    with words like "open" and "close" in them. Rather than relaxing the
    guard, it is narrowed: order-shaped routes are permitted *only* under
    the explicitly simulated `/api/paper/` namespace, and the structural
    tests below assert the backend has no way to reach Fortrade at all.
    """

    SIMULATED_PREFIX = "/api/paper/"

    #: POST routes outside the simulated namespace. These carry a request
    #: body but persist nothing and reach nothing — POST is used because
    #: the payload is too large for a query string, not because state
    #: changes. Listed individually so a genuinely mutating route cannot
    #: arrive unnoticed under the same method.
    STATELESS_POST = frozenset({"/api/chat"})

    def test_no_order_routes_outside_the_paper_namespace(
        self, client: TestClient
    ) -> None:
        paths = client.get("/openapi.json").json()["paths"]

        forbidden = ("order", "trade", "buy", "sell", "open", "close")

        offenders = [
            path
            for path in paths
            if not path.startswith(self.SIMULATED_PREFIX)
            and any(word in path.lower() for word in forbidden)
        ]

        assert offenders == []

    def test_public_api_is_read_only_except_simulated_positions(
        self, client: TestClient
    ) -> None:
        paths = client.get("/openapi.json").json()["paths"]

        for path, methods in paths.items():
            if not path.startswith("/api/"):
                continue

            if path.startswith(self.SIMULATED_PREFIX):
                assert set(methods) <= {"get", "post"}, path
            elif path in self.STATELESS_POST:
                assert set(methods) == {"post"}, path
            else:
                assert set(methods) == {"get"}, path

    def test_backend_cannot_reach_fortrade(self) -> None:
        """Structural guarantee, not a policy.

        The desktop shell pushes data *into* the backend; the backend has
        no outbound channel to Fortrade. If a hostname ever appears in
        backend code, that assumption has been broken.
        """
        backend_dir = Path(__file__).resolve().parents[2] / "backend"

        offenders = [
            path.name
            for path in backend_dir.rglob("*.py")
            if "fortrade.com" in path.read_text(encoding="utf-8")
        ]

        assert offenders == []

    def test_chat_cannot_write_anything(self) -> None:
        """The one route where free text reaches a model reads only.

        A question is not an instruction. The chat service composes a
        prompt from state other code already computed; it must not be
        able to persist, open, or close anything on the way.
        """
        import ast

        tree = ast.parse(
            (
                Path(__file__).resolve().parents[2] / "backend" / "chat" / "service.py"
            ).read_text(encoding="utf-8")
        )

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

        # Live state arrives as plain arguments. Importing a module that
        # owns a database handle or a position would give this path a
        # write it has no reason to hold.
        for module in imported:
            for forbidden in ("storage", "paper", "fortrade"):
                assert forbidden not in module, f"{module} imports {forbidden}"

    def test_paper_module_has_no_execution_helpers(self) -> None:
        import backend.paper.engine as engine
        import backend.paper.service as service

        forbidden = {
            "place_order",
            "submit_order",
            "send_order",
            "execute",
            "buy",
            "sell",
        }

        for module in (engine, service):
            exported = {
                name for name in dir(module) if not name.startswith("_")
            }

            assert not forbidden & exported, module.__name__

    def test_trading_stays_disabled_with_paper_enabled(
        self, client: TestClient
    ) -> None:
        assert client.get("/health").json()["trading_enabled"] is False
