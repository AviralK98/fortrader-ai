"""FastAPI application for the local backend.

Bound to loopback. The `/internal/*` ingest routes additionally require a
shared token that the Electron main process generates at launch and passes
through the environment, so that another local process cannot inject market
data into the analysis pipeline.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from typing import Annotated

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.middleware.cors import CORSMiddleware

from backend.analysis.engine import MINIMUM_BARS, AnalysisResult, analyse
from backend.api import schemas
from backend.backtest.engine import BacktestParams, BacktestResult, run_backtest
from backend.chat import providers as chat_providers
from backend.chat import service as chat_service
from backend.config import Settings, load_settings
from backend.fortrade.models import MarketSnapshot, Quote, Timeframe
from backend.fortrade.parser import FortradeParseError
from backend.fortrade.source import (
    FortradeDataUnavailableError,
    PushedDataSource,
)
from backend.fortrade.state import AppState, StateStore
from backend.logging_setup import configure_logging, get_logger
from backend.paper.engine import PaperTrade
from backend.paper.service import PaperTradingService
from backend.planning import narrative
from backend.planning.plan import TradePlan, build_plan
from backend.signals.engine import Signal
from backend.signals.multi_timeframe import (
    MultiTimeframeResult,
    analyse_timeframes,
    signal_with_timeframes,
)
from backend.storage.database import Database
from backend.storage.repositories import (
    BacktestRepository,
    CandleRepository,
    PaperTradeRepository,
    QuoteRepository,
    Retention,
    SignalRepository,
    SnapshotRepository,
    SqliteCandleProvider,
)

#: How often a full market snapshot is written to the database.
SNAPSHOT_INTERVAL_SECONDS = 300

VERSION = "0.2.5"

# Bars needed before analysis over a series is considered reliable. EMA 200
# alone consumes 200 closes before producing its first meaningful value.
REQUIRED_BARS = 500

logger = get_logger(__name__)


class AppContext:
    """Wiring for the process. Held on `app.state`."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.database = Database(settings.database_path)
        self.source = PushedDataSource()

        # Durable: a series is only captured when the user opens that
        # chart, so it must survive restarts.
        self.candles = SqliteCandleProvider(CandleRepository(self.database))

        self.signals = SignalRepository(self.database)
        self.snapshots = SnapshotRepository(self.database)
        self.quotes = QuoteRepository(self.database)
        self.backtests = BacktestRepository(self.database)
        self.paper = PaperTradingService(PaperTradeRepository(self.database))
        self.retention = Retention(self.database)

        #: Snapshots are stored on an interval, not on every ingest.
        self.last_snapshot_stored: datetime | None = None

        self.state = StateStore()
        self.started_at = datetime.now(tz=timezone.utc)

        # Electron passes this in; a random fallback keeps standalone dev
        # runs functional while still rejecting unauthenticated ingest.
        self.ingest_token = os.environ.get(
            "FORTRADER_INGEST_TOKEN"
        ) or secrets.token_urlsafe(32)


def get_context(app: FastAPI) -> AppContext:
    return app.state.context  # type: ignore[no-any-return]


def app_context(request: Request) -> AppContext:
    """FastAPI dependency resolving the per-process wiring."""
    return request.app.state.context  # type: ignore[no-any-return]


# Must live at module scope: `from __future__ import annotations` turns every
# annotation into a string, and FastAPI resolves those against module globals.
# A closure-local alias would not be visible there.
Ctx = Annotated[AppContext, Depends(app_context)]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    context: AppContext = app.state.context

    configure_logging(
        level=context.settings.log_level,
        log_dir=context.settings.log_dir,
    )

    logger.info(
        "Backend starting",
        extra={
            "context": {
                "version": VERSION,
                "host": context.settings.host,
                "port": context.settings.port,
            }
        },
    )

    try:
        context.database.initialise()
        context.state.set_database_ready(True)
    except Exception:
        logger.exception("Database initialisation failed")
        context.state.set_state(
            AppState.BACKEND_ERROR, "Database initialisation failed"
        )
        raise

    context.state.set_state(AppState.FORTRADE_LOADING)

    yield

    logger.info("Backend shutting down")
    context.database.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or load_settings()

    app = FastAPI(
        title="Fortrader AI Backend",
        version=VERSION,
        lifespan=lifespan,
        docs_url="/docs",
    )

    app.state.context = AppContext(resolved)

    # The renderer is served from a vite origin in development.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    _register_routes(app)

    return app


def require_ingest_token(
    request: Request,
    x_ingest_token: Annotated[str | None, Header()] = None,
) -> None:
    """Authenticate an ingest call.

    Declared as a dependency rather than checked inside the handler so that
    FastAPI resolves it *before* validating the request body — an
    unauthenticated caller gets 401 and learns nothing about the schema.
    """
    expected: str = request.app.state.context.ingest_token

    if x_ingest_token is None or not secrets.compare_digest(
        x_ingest_token, expected
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing ingest token",
        )


IngestAuth = Annotated[None, Depends(require_ingest_token)]


def _safe_quotes(ctx: AppContext) -> list[Quote]:
    """Current quotes, or an empty list before any have been observed."""
    try:
        return ctx.source.get_quotes()
    except (FortradeDataUnavailableError, FortradeParseError):
        return []


def _register_routes(app: FastAPI) -> None:
    # ---------------------------------------------------------------
    # Health and status
    # ---------------------------------------------------------------

    @app.get("/health", response_model=schemas.HealthResponse)
    def health(ctx: Ctx) -> schemas.HealthResponse:
        return schemas.HealthResponse(
            ok=True,
            version=VERSION,
            schema_version=ctx.database.schema_version,
            trading_enabled=False,
            started_at=ctx.started_at,
        )

    @app.get("/api/status", response_model=schemas.StatusResponse)
    def get_status(ctx: Ctx) -> schemas.StatusResponse:
        return schemas.StatusResponse(status=ctx.state.status())

    # ---------------------------------------------------------------
    # Read-only market data
    # ---------------------------------------------------------------

    @app.get("/api/account")
    def get_account(ctx: Ctx):  # type: ignore[no-untyped-def]
        try:
            return ctx.source.get_account()
        except FortradeDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/quotes", response_model=schemas.QuotesResponse)
    def get_quotes(ctx: Ctx) -> schemas.QuotesResponse:
        try:
            quotes = ctx.source.get_quotes()
        except FortradeDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        return schemas.QuotesResponse(quotes=quotes, count=len(quotes))

    @app.get("/api/quotes/{symbol:path}")
    def get_quote(symbol: str, ctx: Ctx):  # type: ignore[no-untyped-def]
        try:
            return ctx.source.get_quote(symbol)
        except FortradeDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except FortradeParseError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/positions", response_model=schemas.PositionsResponse)
    def get_positions(ctx: Ctx) -> schemas.PositionsResponse:
        positions = ctx.source.get_positions()

        return schemas.PositionsResponse(
            positions=positions, count=len(positions)
        )

    @app.get("/api/symbols", response_model=schemas.SymbolsResponse)
    def get_symbols(ctx: Ctx) -> schemas.SymbolsResponse:
        try:
            return schemas.SymbolsResponse(symbols=ctx.source.list_symbols())
        except FortradeDataUnavailableError:
            return schemas.SymbolsResponse(symbols=[])

    @app.get("/api/chart")
    def get_chart(ctx: Ctx):  # type: ignore[no-untyped-def]
        try:
            return ctx.source.get_chart()
        except FortradeDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/analysis", response_model=AnalysisResult)
    def get_analysis(
        ctx: Ctx,
        symbol: Annotated[str, Query(min_length=1)],
        timeframe: Timeframe = Timeframe.M5,
        limit: Annotated[int, Query(ge=MINIMUM_BARS, le=5000)] = 500,
    ) -> AnalysisResult:
        """Deterministic indicators over stored history.

        Returns a result even when history is short; the `reliable` flag
        and `warnings` say so rather than the endpoint failing or the
        numbers being quietly wrong.
        """
        candles = ctx.candles.get_candles(symbol, timeframe, limit)

        return analyse(symbol.upper(), timeframe, candles)

    @app.get("/api/signal", response_model=Signal)
    def get_signal(
        ctx: Ctx,
        symbol: Annotated[str, Query(min_length=1)],
        timeframe: Timeframe = Timeframe.M5,
        limit: Annotated[int, Query(ge=MINIMUM_BARS, le=5000)] = 500,
    ) -> Signal:
        """Deterministic LONG/SHORT/WAIT signal with a 0-100 conviction score.

        The score is a conviction summary, not a probability.
        """
        signal, _ = signal_with_timeframes(
            symbol.upper(), timeframe, ctx.candles, limit=limit
        )

        # Recorded only when the bias or score moves, so the history is a
        # log of decisions rather than of polling.
        signal_id: int | None = None

        try:
            signal_id = ctx.signals.save_if_changed(signal)
        except Exception:
            logger.exception("Persisting signal failed")

        # Automatic paper entry is rate-limited inside the service, so
        # polling this endpoint cannot open a stream of positions.
        try:
            quote = next(
                (
                    q
                    for q in _safe_quotes(ctx)
                    if q.symbol.upper() == signal.symbol.upper()
                ),
                None,
            )

            if quote is not None:
                ctx.paper.maybe_open(signal, quote, signal_id)
        except Exception:
            logger.exception("Paper entry evaluation failed")

        return signal

    @app.get("/api/plan", response_model=TradePlan)
    def get_trade_plan(
        ctx: Ctx,
        symbol: Annotated[str, Query(min_length=1)],
        timeframe: Timeframe = Timeframe.M5,
        risk_percent: Annotated[float, Query(gt=0, le=100)] = 1.0,
    ) -> TradePlan:
        """Translate the current signal into a risk-defined trade plan.

        Deterministic. Reports why a setup is not tradeable rather than
        manufacturing one, and never recommends taking it.
        """
        signal, _ = signal_with_timeframes(
            symbol.upper(), timeframe, ctx.candles
        )

        quote = next(
            (q for q in _safe_quotes(ctx) if q.symbol.upper() == symbol.upper()),
            None,
        )

        account = None

        with suppress(FortradeDataUnavailableError):
            account = ctx.source.get_account()

        metrics = ctx.paper.metrics()

        return build_plan(
            signal,
            quote=quote,
            account=account,
            risk_percent=risk_percent,
            paper_trades_closed=metrics.trades,
            paper_trades_required=metrics.minimum_trades,
        )

    @app.post("/api/chat", response_model=chat_service.ChatReply)
    def chat(
        payload: schemas.ChatRequest, ctx: Ctx
    ) -> chat_service.ChatReply:
        """Answer a question about this application's own market analysis.

        Scoped: off-topic questions are declined. Grounded: the live
        deterministic state is injected each turn so answers describe the
        user's actual data rather than trading in general.
        """
        plan = None

        with suppress(Exception):
            plan = get_trade_plan(ctx, payload.symbol, payload.timeframe)

        account = None

        with suppress(FortradeDataUnavailableError):
            account = ctx.source.get_account()

        coverage = None

        with suppress(Exception):
            coverage = ctx.candles.coverage()

        context, grounded = chat_service.build_context(
            plan=plan,
            account=account,
            coverage=coverage,
            paper_metrics=ctx.paper.metrics(),
        )

        return chat_service.ask(
            payload.message, list(payload.history), context, grounded
        )

    @app.get("/api/chat/status", response_model=schemas.ChatStatusResponse)
    def chat_status() -> schemas.ChatStatusResponse:
        """Report the transport without spending anything to find out."""
        provider = chat_providers.select_provider()
        usable, detail = provider.available()

        return schemas.ChatStatusResponse(
            available=usable,
            provider=provider.name,
            detail=(
                None
                if usable
                else chat_service.unavailable_detail(provider, detail)
            ),
        )

    @app.get("/api/plan/explain", response_model=schemas.NarrativeResponse)
    def explain_trade_plan(
        ctx: Ctx,
        symbol: Annotated[str, Query(min_length=1)],
        timeframe: Timeframe = Timeframe.M5,
    ) -> schemas.NarrativeResponse:
        """Plain-language narrative over the plan, when a key is configured.

        The model explains numbers it is given; it never produces them.
        """
        plan = get_trade_plan(ctx, symbol, timeframe)

        if not narrative.is_configured():
            return schemas.NarrativeResponse(
                available=False,
                detail=(
                    "No ANTHROPIC_API_KEY configured. The plan itself is "
                    "unaffected — this only adds a written explanation."
                ),
            )

        text = narrative.explain(plan)

        return schemas.NarrativeResponse(
            available=text is not None,
            narrative=text,
            detail=None if text else "The narrative could not be generated.",
        )

    # ---------------------------------------------------------------
    # Paper trading — simulated positions only
    # ---------------------------------------------------------------

    @app.get("/api/paper/positions", response_model=schemas.PaperPositionsResponse)
    def get_paper_positions(ctx: Ctx) -> schemas.PaperPositionsResponse:
        quotes = _safe_quotes(ctx)

        return schemas.PaperPositionsResponse(
            open=ctx.paper.open_positions(quotes),
            closed=ctx.paper.closed_positions(50),
            summary=ctx.paper.summary(quotes),
            metrics=ctx.paper.metrics(),
        )

    @app.post("/api/paper/open", response_model=PaperTrade)
    def open_paper_position(
        ctx: Ctx,
        symbol: Annotated[str, Query(min_length=1)],
        timeframe: Timeframe = Timeframe.M5,
    ) -> PaperTrade:
        """Open a simulated position from the current signal.

        Simulated only. This never reaches Fortrade's order entry — the
        backend has no channel to the trading interface at all.
        """
        signal, _ = signal_with_timeframes(
            symbol.upper(), timeframe, ctx.candles
        )

        quotes = _safe_quotes(ctx)

        quote = next(
            (q for q in quotes if q.symbol.upper() == symbol.upper()), None
        )

        if quote is None:
            raise HTTPException(
                status_code=503, detail="No live quote for this symbol"
            )

        trade = ctx.paper.maybe_open(signal, quote, force=True)

        if trade is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "No position opened: the signal does not qualify "
                    f"(bias {signal.bias.value}, score {signal.score}, "
                    f"threshold {ctx.paper.config.min_score}) or one is "
                    "already open on this series."
                ),
            )

        return trade

    @app.post("/api/paper/close/{trade_id}")
    def close_paper_position(trade_id: int, ctx: Ctx) -> dict[str, int]:
        quotes = _safe_quotes(ctx)

        if not ctx.paper.close_manually(trade_id, quotes):
            raise HTTPException(
                status_code=404,
                detail="No open paper position with that id, or no live quote",
            )

        return {"closed": trade_id}

    @app.get("/api/signals/recent", response_model=schemas.RecentSignalsResponse)
    def get_recent_signals(
        ctx: Ctx,
        symbol: str | None = None,
        timeframe: Timeframe | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
    ) -> schemas.RecentSignalsResponse:
        rows = ctx.signals.recent(symbol, timeframe, limit)

        return schemas.RecentSignalsResponse(signals=rows, count=len(rows))

    # ---------------------------------------------------------------
    # Backtesting
    # ---------------------------------------------------------------

    @app.get("/api/backtest", response_model=BacktestResult)
    def get_backtest(
        ctx: Ctx,
        symbol: Annotated[str, Query(min_length=1)],
        timeframe: Timeframe = Timeframe.M5,
        limit: Annotated[int, Query(ge=1, le=5000)] = 5000,
        min_score: Annotated[int, Query(ge=0, le=100)] = 65,
        stop_atr: Annotated[float, Query(gt=0, le=20)] = 1.5,
        target_atr: Annotated[float, Query(gt=0, le=50)] = 3.0,
        spread: Annotated[float, Query(ge=0)] = 0.0,
        save: bool = True,
    ) -> BacktestResult:
        """Walk the stored history forward, taking signals as they appeared.

        Returns a result even when history is too short; `ran` and
        `metrics.sufficient` report that rather than inventing figures.
        """
        candles = ctx.candles.get_candles(symbol, timeframe, limit)

        result = run_backtest(
            symbol.upper(),
            timeframe,
            candles,
            BacktestParams(
                stop_atr=stop_atr,
                target_atr=target_atr,
                min_score=min_score,
                spread=spread,
            ),
        )

        if save and result.ran:
            try:
                ctx.backtests.save(result)
            except Exception:
                logger.exception("Persisting backtest failed")

        return result

    @app.get("/api/backtest/runs", response_model=schemas.BacktestRunsResponse)
    def list_backtests(
        ctx: Ctx,
        limit: Annotated[int, Query(ge=1, le=200)] = 20,
    ) -> schemas.BacktestRunsResponse:
        runs = ctx.backtests.recent(limit)

        return schemas.BacktestRunsResponse(runs=runs, count=len(runs))

    @app.get("/api/backtest/runs/{run_id}")
    def get_backtest_run(run_id: int, ctx: Ctx):  # type: ignore[no-untyped-def]
        record = ctx.backtests.get(run_id)

        if record is None:
            raise HTTPException(status_code=404, detail="Backtest run not found")

        return record

    @app.get("/api/signal/timeframes", response_model=MultiTimeframeResult)
    def get_multi_timeframe(
        ctx: Ctx,
        symbol: Annotated[str, Query(min_length=1)],
        limit: Annotated[int, Query(ge=MINIMUM_BARS, le=5000)] = 500,
    ) -> MultiTimeframeResult:
        """Weighted M1/M5/M15/H1 view. Timeframes lacking history are excluded."""
        return analyse_timeframes(symbol.upper(), ctx.candles, limit=limit)

    @app.get("/api/candles/coverage", response_model=schemas.CoverageResponse)
    def get_coverage(ctx: Ctx) -> schemas.CoverageResponse:
        series = ctx.candles.coverage()

        return schemas.CoverageResponse(
            series=[
                schemas.SeriesCoverageOut(
                    symbol=item.symbol,
                    timeframe=item.timeframe,
                    count=item.count,
                    first=item.first,
                    last=item.last,
                    sufficient=item.sufficient_for(REQUIRED_BARS),
                )
                for item in series
            ],
            required=REQUIRED_BARS,
            total_bars=sum(item.count for item in series),
        )

    @app.get("/api/candles", response_model=schemas.CandlesResponse)
    def get_candles(
        ctx: Ctx,
        symbol: Annotated[str, Query(min_length=1)],
        timeframe: Timeframe = Timeframe.M5,
        limit: Annotated[int, Query(ge=1, le=5000)] = 500,
    ) -> schemas.CandlesResponse:
        candles = ctx.candles.get_candles(symbol, timeframe, limit)

        return schemas.CandlesResponse(
            symbol=symbol.upper(),
            timeframe=timeframe,
            candles=candles,
            count=len(candles),
            requested=limit,
            sufficient=len(candles) >= limit,
        )

    # ---------------------------------------------------------------
    # Ingest — desktop shell only
    # ---------------------------------------------------------------

    @app.post("/internal/ingest/snapshot", response_model=schemas.IngestResult)
    def ingest_snapshot(
        payload: schemas.SnapshotIngest,
        ctx: Ctx,
        _auth: IngestAuth = None,
    ) -> schemas.IngestResult:
        snapshot = MarketSnapshot(
            account=payload.account,
            quotes=tuple(payload.quotes),
            positions=tuple(payload.positions),
            chart=payload.chart,
        )

        ctx.source.ingest(snapshot)
        ctx.state.update_snapshot(snapshot)

        stored = 0

        # Exits are checked on every ingest: it is a price comparison, and
        # a stop that is noticed a minute late is a stop that lied.
        try:
            if payload.quotes:
                ctx.paper.update_from_quotes(list(payload.quotes))
        except Exception:
            logger.exception("Paper position update failed")

        # Persistence must never break live ingest: a full disk should
        # degrade history, not the dashboard.
        try:
            stored = ctx.quotes.save_sampled(list(payload.quotes))

            now = datetime.now(tz=timezone.utc)
            due = (
                ctx.last_snapshot_stored is None
                or (now - ctx.last_snapshot_stored).total_seconds()
                >= SNAPSHOT_INTERVAL_SECONDS
            )

            if due:
                ctx.snapshots.save(snapshot)
                ctx.last_snapshot_stored = now
                ctx.retention.run(now)
        except Exception:
            logger.exception("Persisting ingest failed; live data unaffected")

        return schemas.IngestResult(
            accepted=True,
            received=len(payload.quotes) + len(payload.positions),
            stored=stored,
        )

    @app.post("/internal/ingest/candles", response_model=schemas.IngestResult)
    def ingest_candles(
        payload: schemas.CandlesIngest,
        ctx: Ctx,
        _auth: IngestAuth = None,
    ) -> schemas.IngestResult:
        stored = ctx.candles.ingest(payload.candles)

        return schemas.IngestResult(
            accepted=True,
            received=len(payload.candles),
            stored=stored,
        )

    @app.post("/internal/state", response_model=schemas.StatusResponse)
    def set_app_state(
        payload: schemas.StateIngest,
        ctx: Ctx,
        _auth: IngestAuth = None,
    ) -> schemas.StatusResponse:
        ctx.state.set_state(payload.state, payload.detail)

        return schemas.StatusResponse(status=ctx.state.status())
