import json
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from stocks_trading.config.settings import get_settings
from stocks_trading.config.time import localize_datetime
from stocks_trading.analysis.config import (
    AnalysisConfiguration,
    load_analysis_configuration,
)
from stocks_trading.alerts.config import AlertConfiguration, load_alert_configuration
from stocks_trading.risk.config import RiskConfiguration, load_risk_configuration
from stocks_trading.positions.config import PositionConfiguration, load_position_configuration
from stocks_trading.persistence.database import create_database_engine, create_session_factory
from stocks_trading.persistence.repositories import (
    SqlAlchemyAnalysisRepository,
    SqlAlchemyAlertRepository,
    SqlAlchemyBacktestRepository,
    SqlAlchemyHistoricalBackfillRepository,
    SqlAlchemyFundamentalRepository,
    SqlAlchemyMarketDataRepository,
    SqlAlchemyRunRepository,
    SqlAlchemyOptimizationRepository,
    SqlAlchemyResearchRepository,
    SqlAlchemyRiskRepository,
    SqlAlchemyPositionRepository,
    SqlAlchemyPortfolioRepository,
    SqlAlchemyRuleRepository,
    SqlAlchemyRankingRepository,
    SqlAlchemyScoreRepository,
    SqlAlchemyStrategyRepository,
)
from stocks_trading.rules.config import RuleConfiguration, load_rule_configuration
from stocks_trading.ranking.config import (
    RankingConfiguration,
    load_ranking_configuration,
)
from stocks_trading.scoring.config import (
    ScoringConfiguration,
    load_scoring_configuration,
)
from stocks_trading.strategies.config import (
    StrategyConfiguration,
    load_strategy_configuration,
)
from stocks_trading.market_data.yahoo import latest_completed_market_date
from stocks_trading.market_data.yahoo import YahooFinanceProvider
from stocks_trading.market_data.service import MarketDataCollector
from stocks_trading.market_data.calendar import load_market_calendar
from stocks_trading.stocks.service import (
    StockDataError,
    StockNotFoundError,
    StockService,
    StockValidationError,
)
from stocks_trading.sync.service import SyncManager
from stocks_trading.scheduler.service import next_run
from stocks_trading.research.service import ResearchManager, ResearchValidationError
from stocks_trading.portfolio.service import PortfolioService, PortfolioValidationError
from stocks_trading.backfill.service import HistoricalBackfillManager, BackfillValidationError
from stocks_trading.debug.live_stream import LiveStreamManager
from stocks_trading.liquidity.config import TIERS, load_liquidity_configuration
from stocks_trading.fundamentals.config import load_fundamental_configuration
from stocks_trading.fundamentals.service import FundamentalService, FundamentalSyncManager
from stocks_trading.sync.service import PipelineCoordinator


def research_dependencies() -> SqlAlchemyResearchRepository:
    settings = get_settings()
    return SqlAlchemyResearchRepository(
        create_session_factory(create_database_engine(settings.database_url))
    )


def backfill_dependencies() -> SqlAlchemyHistoricalBackfillRepository:
    settings = get_settings()
    return SqlAlchemyHistoricalBackfillRepository(
        create_session_factory(create_database_engine(settings.database_url))
    )


research_manager = ResearchManager(
    research_dependencies(),
    lambda: __import__("stocks_trading.cli.app", fromlist=["dependencies"]).dependencies(),
    get_settings(),
)

backfill_manager = HistoricalBackfillManager(
    backfill_dependencies(),
    lambda: __import__("stocks_trading.cli.app", fromlist=["dependencies"]).dependencies(),
    get_settings(),
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    research_manager.recover_interrupted()
    backfill_manager.recover_interrupted()
    try:
        yield
    finally:
        await live_stream_manager.close()


app = FastAPI(
    title="Indonesia Stock Trading Analysis Platform",
    version="0.10.0",
    description="IDX technical analysis, backtesting, and strategy optimization service.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

sync_manager = SyncManager(lambda: __import__("stocks_trading.cli.app", fromlist=["dependencies"]).dependencies(), get_settings())
live_stream_manager = LiveStreamManager(get_settings().market_timezone)


def fundamental_dependencies():
    settings = get_settings()
    repository = SqlAlchemyFundamentalRepository(create_session_factory(create_database_engine(settings.database_url)))
    configuration = load_fundamental_configuration(settings.fundamental_config_path)
    return repository, configuration


def fundamental_service() -> FundamentalService:
    repository, configuration = fundamental_dependencies()
    return FundamentalService(repository, configuration, get_settings().max_workers)


fundamental_sync_manager = FundamentalSyncManager(fundamental_service, PipelineCoordinator(get_settings()))


class ResearchRequest(BaseModel):
    start_date: date
    end_date: date


class BackfillRequest(BaseModel):
    target_years: int = 5


class PortfolioTransactionRequest(BaseModel):
    transaction_type: str
    symbol: str
    transaction_date: date
    quantity: Decimal
    price: Decimal
    fee: Decimal = Decimal("0")
    notes: str | None = None


def research_response(job):
    return jsonable_encoder(research_manager.response(job))


def backfill_response(job):
    return jsonable_encoder(backfill_manager.response(job))


@app.get("/backfills/availability", tags=["backfills"])
def backfill_availability(target_years: int = Query(default=5, ge=1, le=5)):
    return jsonable_encoder(backfill_manager.availability(target_years))


@app.post("/backfills", status_code=202, tags=["backfills"])
async def start_backfill(request: BackfillRequest):
    try:
        job, created = await backfill_manager.start(request.target_years)
    except BackfillValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not created:
        raise HTTPException(status_code=409, detail={"message": "A backfill job is already running", "job": backfill_response(job)})
    return backfill_response(job)


@app.post("/backfills/{job_id}/resume", status_code=202, tags=["backfills"])
async def resume_backfill(job_id: UUID):
    try:
        job, created = await backfill_manager.resume(job_id)
    except BackfillValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not created:
        raise HTTPException(status_code=409, detail={"message": "A backfill job is already running", "job": backfill_response(job)})
    return backfill_response(job)


@app.get("/backfills/current", tags=["backfills"])
def current_backfill():
    job = backfill_manager.current()
    return backfill_response(job) if job else {"status": "idle"}


@app.get("/backfills", tags=["backfills"])
def list_backfills(limit: int = Query(default=10, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    items = [backfill_response(item) for item in backfill_manager.list(limit, offset)]
    return {"items": items, "total": backfill_manager.count(), "limit": limit, "offset": offset}


@app.get("/backfills/{job_id}", tags=["backfills"])
def get_backfill(job_id: UUID):
    job = backfill_manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Backfill job not found")
    return backfill_response(job)


@app.get("/backfills/{job_id}/symbols", tags=["backfills"])
def backfill_symbols(job_id: UUID, status: str | None = None,
                     limit: int = Query(default=10, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    if not backfill_manager.get(job_id):
        raise HTTPException(status_code=404, detail="Backfill job not found")
    items, total = backfill_manager.symbols(job_id, status, limit, offset)
    return jsonable_encoder({"items": items, "total": total, "limit": limit, "offset": offset})


@app.get("/research/availability", tags=["research"])
def research_availability():
    return jsonable_encoder(research_manager.availability())


async def start_research(job_type: str, request: ResearchRequest):
    try:
        job, created = await research_manager.start(job_type, request.start_date, request.end_date)
    except ResearchValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not created:
        raise HTTPException(
            status_code=409,
            detail={"message": "A research job is already running", "job": research_response(job)},
        )
    return research_response(job)


@app.post("/research/backtests", status_code=202, tags=["research"])
async def start_research_backtest(request: ResearchRequest):
    return await start_research("backtest", request)


@app.post("/sync/backtest", status_code=202, tags=["sync", "research"])
async def start_scoped_backtest(request: ResearchRequest):
    return await start_research("backtest", request)


@app.post("/research/optimizations", status_code=202, tags=["research"])
async def start_research_optimization(request: ResearchRequest):
    return await start_research("optimization", request)


@app.get("/research/jobs", tags=["research"])
def research_jobs(limit: int = Query(default=50, ge=1, le=200)):
    return [research_response(job) for job in research_manager.list(limit)]


def page_response(items, total: int, limit: int, offset: int, **metadata):
    return {**metadata, "items": items, "total": total, "limit": limit, "offset": offset}


def risk_dependencies() -> tuple[SqlAlchemyRiskRepository, RiskConfiguration]:
    settings = get_settings()
    return (
        SqlAlchemyRiskRepository(create_session_factory(create_database_engine(settings.database_url))),
        load_risk_configuration(settings.risk_config_path),
    )


def position_dependencies() -> tuple[SqlAlchemyPositionRepository, PositionConfiguration]:
    settings = get_settings()
    return (
        SqlAlchemyPositionRepository(create_session_factory(create_database_engine(settings.database_url))),
        load_position_configuration(settings.positions_config_path),
    )


def portfolio_dependencies() -> PortfolioService:
    settings = get_settings()
    repository = SqlAlchemyPortfolioRepository(
        create_session_factory(create_database_engine(settings.database_url)),
        settings.portfolio_initial_cash_idr,
    )
    return PortfolioService(repository, settings.market_timezone)


@app.get("/research/jobs/paged", tags=["research"])
def research_jobs_paged(
    limit: int = Query(default=10, ge=1, le=10),
    offset: int = Query(default=0, ge=0),
):
    return page_response(
        [research_response(job) for job in research_manager.list(limit, offset)],
        research_manager.repository.count_jobs(), limit, offset,
    )


@app.get("/research/jobs/current", tags=["research"])
def current_research_job():
    job = research_manager.current()
    return research_response(job) if job else {"status": "idle"}


@app.get("/research/jobs/{job_id}", tags=["research"])
def research_job(job_id: UUID):
    job = research_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Research job not found")
    return research_response(job)


def sync_response(job) -> dict[str, object]:
    payload = job.to_dict()
    timezone = get_settings().market_timezone
    payload["started_at"] = localize_datetime(job.started_at, timezone)
    payload["finished_at"] = localize_datetime(job.finished_at, timezone)
    return jsonable_encoder(payload)


@app.post("/sync", status_code=202, tags=["sync"])
async def start_sync(years: int | None = Query(default=None, ge=1, le=5)):
    job, created = await sync_manager.start(years)
    if not created:
        raise HTTPException(
            status_code=409,
            detail={"message": "A sync is already running", "job": sync_response(job)},
        )
    return sync_response(job)


@app.get("/sync", tags=["sync"])
def current_sync():
    job = sync_manager.current()
    return sync_response(job) if job else {"status": "idle"}


def fundamental_job_response(job):
    payload = job.to_dict()
    timezone = get_settings().market_timezone
    payload["started_at"] = localize_datetime(job.started_at, timezone)
    payload["finished_at"] = localize_datetime(job.finished_at, timezone)
    return jsonable_encoder(payload)


@app.post("/sync/fundamental", status_code=202, tags=["sync", "fundamentals"])
async def start_fundamental_sync():
    job, created = await fundamental_sync_manager.start()
    if not created:
        raise HTTPException(status_code=409, detail={"message": "A fundamental sync is already running", "job": fundamental_job_response(job)})
    return fundamental_job_response(job)


@app.get("/sync/fundamental/current", tags=["sync", "fundamentals"])
def current_fundamental_sync():
    job = fundamental_sync_manager.current()
    return fundamental_job_response(job) if job else {"status": "idle"}


@app.get("/sync/fundamental/{job_id}", tags=["sync", "fundamentals"])
def fundamental_sync_status(job_id: UUID):
    job = fundamental_sync_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Fundamental sync job not found")
    return fundamental_job_response(job)


@app.post("/sync/combined", tags=["sync", "fundamentals"])
def recompute_combined(dependencies=Depends(fundamental_dependencies)):
    repository, configuration = dependencies
    technical = load_scoring_configuration(get_settings().scoring_config_path)
    snapshot = repository.ranking_page(
        view="combined", version=configuration.version, checksum=configuration.checksum,
        technical_version=technical.version, technical_checksum=technical.checksum,
        technical_weight=configuration.technical_weight, fundamental_weight=configuration.fundamental_weight,
        limit=1, offset=0,
    )
    if snapshot is None:
        raise HTTPException(status_code=422, detail="Combined ranking requires both technical and fundamental snapshots")
    fundamental_date, technical_date, _, total = snapshot
    run = repository.record_combined_run(
        status="succeeded", technical_data_as_of=technical_date,
        fundamental_data_as_of=fundamental_date, eligible_stocks=total,
    )
    return jsonable_encoder({
        "id": run["id"],
        "status": "succeeded", "message": "Combined ranking recomputed from persisted scores",
        "technical_data_as_of": technical_date, "fundamental_data_as_of": fundamental_date,
        "eligible_stocks": total, "started_at": localize_datetime(run["started_at"], get_settings().market_timezone),
        "finished_at": localize_datetime(run["finished_at"], get_settings().market_timezone),
    })


@app.get("/sync/{job_id}", tags=["sync"])
def sync_status(job_id: UUID):
    job = sync_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Sync job not found")
    return sync_response(job)


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    return {
        "name": "Indonesia Stock Trading Analysis Platform",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "healthy"}


def market_data_dependencies() -> SqlAlchemyMarketDataRepository:
    settings = get_settings()
    return SqlAlchemyMarketDataRepository(
        create_session_factory(create_database_engine(settings.database_url))
    )


def stocks_dependencies() -> StockService:
    settings = get_settings()
    session_factory = create_session_factory(create_database_engine(settings.database_url))
    repository = SqlAlchemyMarketDataRepository(session_factory)
    provider = YahooFinanceProvider(settings.market_timezone)
    collector = MarketDataCollector(
        provider=provider,
        market_repository=repository,
        run_repository=SqlAlchemyRunRepository(session_factory),
        settings=settings,
    )
    return StockService(
        repository, collector, provider, settings,
        load_liquidity_configuration(settings.liquidity_config_path),
    )


def parse_liquidity_tiers(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    tiers = tuple(dict.fromkeys(item.strip().lower() for item in value.split(",") if item.strip()))
    invalid = set(tiers) - set(TIERS)
    if invalid:
        raise HTTPException(status_code=422, detail=f"unsupported liquidity tier: {', '.join(sorted(invalid))}")
    return tiers


@app.get("/stocks", tags=["stocks"])
def stocks(
    search: str | None = Query(default=None, max_length=100),
    min_turnover: Decimal | None = Query(default=None, ge=0),
    liquidity_tier: str | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    service: StockService = Depends(stocks_dependencies),
):
    try:
        return jsonable_encoder(service.list(
            search=search, limit=limit, offset=offset, min_turnover=min_turnover,
            liquidity_tiers=parse_liquidity_tiers(liquidity_tier),
        ))
    except StockValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/stocks/liquidity-breakdown", tags=["stocks"])
def stock_liquidity_breakdown(service: StockService = Depends(stocks_dependencies)):
    scoring = load_scoring_configuration(get_settings().scoring_config_path)
    return jsonable_encoder(service.liquidity_breakdown(
        scoring_version=scoring.version, scoring_config_checksum=scoring.checksum,
    ))


def live_stream_dependencies():
    return live_stream_manager, market_data_dependencies()


def sse_message(event: dict[str, object]) -> str:
    return f"event: {event['event']}\ndata: {json.dumps(event['data'], separators=(',', ':'))}\n\n"


@app.get("/stocks/{symbol}/live", tags=["debug-live"])
async def stock_live_stream(symbol: str, dependencies=Depends(live_stream_dependencies)):
    manager, repository = dependencies
    normalized = normalize_symbol(symbol)
    if repository.stock_metadata(normalized) is None:
        raise HTTPException(status_code=404, detail=f"symbol {normalized} is not active in the IDX universe")

    async def events():
        async for event in manager.stream(normalized):
            yield sse_message(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/debug/live/ticks/{symbol}", tags=["debug-live"])
def live_tick_snapshot(symbol: str, dependencies=Depends(live_stream_dependencies)):
    manager, repository = dependencies
    normalized = normalize_symbol(symbol)
    if repository.stock_metadata(normalized) is None:
        raise HTTPException(status_code=404, detail=f"symbol {normalized} is not active in the IDX universe")
    return jsonable_encoder(manager.snapshot(normalized))


@app.get("/stocks/{symbol}", tags=["stocks"])
async def stock_detail(
    symbol: str,
    period: str = Query(default="6mo"),
    interval: str = Query(default="1d"),
    service: StockService = Depends(stocks_dependencies),
):
    try:
        return jsonable_encoder(
            await service.detail(
                normalize_symbol(symbol), period=period.lower(), interval=interval.lower()
            )
        )
    except StockNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except StockValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except StockDataError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.get("/market-data/status", tags=["market-data"])
def market_data_status(
    as_of: date | None = None,
    repository=Depends(market_data_dependencies),
) -> dict[str, object]:
    settings = get_settings()
    market_calendar = load_market_calendar(settings.market_calendar_config_path)
    target = as_of or latest_completed_market_date(
        datetime.now(UTC), settings.market_timezone, market_calendar
    )
    payload = repository.cache_status(target)
    timezone = settings.market_timezone
    payload["last_collection_started_at"] = localize_datetime(
        payload.get("last_collection_started_at"), timezone
    )
    payload["last_collection_finished_at"] = localize_datetime(
        payload.get("last_collection_finished_at"), timezone
    )
    return jsonable_encoder(payload)


@app.get("/market-calendar", tags=["market-data"])
def market_calendar_status(as_of: date | None = None) -> dict[str, object]:
    settings = get_settings()
    calendar = load_market_calendar(settings.market_calendar_config_path)
    local_today = datetime.now(calendar.timezone).date()
    selected_date = as_of or local_today
    coverage = {
        str(year): {
            "status": value.status,
            "closure_count": len(value.closures),
        }
        for year, value in sorted(calendar.coverage.items())
    }
    nearby_holidays = [
        {
            "date": closure.trading_date,
            "name": closure.name,
            "type": closure.closure_type,
        }
        for closure in calendar.nearby_closures(selected_date)
    ]
    return jsonable_encoder(
        {
            "calendar_version": calendar.calendar_version,
            "checksum": calendar.checksum,
            "exchange": calendar.exchange,
            "timezone": str(calendar.timezone),
            "source_reference": calendar.source_reference,
            "source_published_date": calendar.source_published_date,
            "coverage": coverage,
            "official_years": calendar.official_years,
            "pending_years": calendar.pending_years,
            "today": local_today,
            "selected_date": selected_date,
            "coverage_status": calendar.coverage_status(selected_date.year),
            "is_trading_day": calendar.is_trading_day(selected_date),
            "previous_trading_day": calendar.previous_trading_day(selected_date),
            "next_trading_day": calendar.next_trading_day(selected_date),
            "nearby_holidays": nearby_holidays,
        }
    )


@app.get("/operations/status", tags=["operations"])
def operations_status(
    repository=Depends(market_data_dependencies),
) -> dict[str, object]:
    settings = get_settings()
    calendar = load_market_calendar(settings.market_calendar_config_path)
    now = datetime.now(settings.market_timezone)
    target = latest_completed_market_date(now, settings.market_timezone, calendar)
    cache = repository.cache_status(target)
    cache["last_collection_started_at"] = localize_datetime(
        cache.get("last_collection_started_at"), settings.market_timezone
    )
    cache["last_collection_finished_at"] = localize_datetime(
        cache.get("last_collection_finished_at"), settings.market_timezone
    )
    selected_date = now.date()
    scheduler_next_run = None
    if settings.scheduler_enabled:
        scheduler_next_run = next_run(
            now,
            settings.scheduler_hour,
            settings.scheduler_minute,
            calendar,
        )
    coverage = {
        str(year): {
            "status": value.status,
            "closure_count": len(value.closures),
        }
        for year, value in sorted(calendar.coverage.items())
    }
    nearby_holidays = [
        {
            "date": closure.trading_date,
            "name": closure.name,
            "type": closure.closure_type,
        }
        for closure in calendar.nearby_closures(selected_date)
    ]
    history = backfill_manager.availability(5)
    backfill = backfill_manager.current()
    ranking_repository, ranking_configuration = ranking_dependencies()
    fundamental_repository, fundamental_configuration = fundamental_dependencies()
    return jsonable_encoder(
        {
            "observed_at": now,
            "api_status": "healthy",
            "market_data": cache,
            "calendar": {
                "calendar_version": calendar.calendar_version,
                "checksum": calendar.checksum,
                "exchange": calendar.exchange,
                "timezone": str(calendar.timezone),
                "source_reference": calendar.source_reference,
                "source_published_date": calendar.source_published_date,
                "coverage": coverage,
                "official_years": calendar.official_years,
                "pending_years": calendar.pending_years,
                "today": selected_date,
                "target_date": target,
                "coverage_status": calendar.coverage_status(selected_date.year),
                "is_trading_day": calendar.is_trading_day(selected_date),
                "previous_trading_day": calendar.previous_trading_day(selected_date),
                "next_trading_day": calendar.next_trading_day(selected_date),
                "nearby_holidays": nearby_holidays,
            },
            "scheduler": {
                "enabled": settings.scheduler_enabled,
                "timezone": settings.scheduler_timezone,
                "hour": settings.scheduler_hour,
                "minute": settings.scheduler_minute,
                "next_run_at": scheduler_next_run,
            },
            "sync": sync_response(sync_manager.current()) if sync_manager.current() else {"status": "idle"},
            "scoped_sync": {
                "technical": sync_response(sync_manager.current()) if sync_manager.current() else {
                    "status": "idle", "last_run": ranking_repository.latest_completed_run(
                        ranking_configuration.version, ranking_configuration.checksum
                    ),
                },
                "fundamental": fundamental_job_response(fundamental_sync_manager.current()) if fundamental_sync_manager.current() else {
                    "status": "idle", "last_run": fundamental_repository.latest_run(
                        fundamental_configuration.version, fundamental_configuration.checksum
                    ),
                },
                "combined": {"status": "idle", "last_run": fundamental_repository.latest_combined_run()},
            },
            "historical_coverage": history,
            "backfill": backfill_response(backfill) if backfill else {"status": "idle"},
        }
    )


def rule_dependencies() -> tuple[SqlAlchemyRuleRepository, RuleConfiguration]:
    settings = get_settings()
    repository = SqlAlchemyRuleRepository(
        create_session_factory(create_database_engine(settings.database_url))
    )
    return repository, load_rule_configuration(settings.rules_config_path)


@app.get("/rules/{symbol}", tags=["rules"])
def latest_rules(
    symbol: str,
    dependencies=Depends(rule_dependencies),
) -> dict[str, object]:
    repository, configuration = dependencies
    normalized = normalize_symbol(symbol)
    result = repository.latest_rules(
        normalized, configuration.formula_version, configuration.checksum
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Rule result not found")
    return rule_response(result)


@app.get("/rules/{symbol}/history", tags=["rules"])
def rule_history(
    symbol: str,
    limit: int = Query(default=100, ge=1, le=500),
    before: date | None = None,
    dependencies=Depends(rule_dependencies),
) -> list[dict[str, object]]:
    repository, configuration = dependencies
    normalized = normalize_symbol(symbol)
    results = repository.rule_history(
        normalized,
        configuration.formula_version,
        configuration.checksum,
        limit=limit,
        before=before,
    )
    if not results:
        raise HTTPException(status_code=404, detail="Rule result not found")
    return [rule_response(item) for item in results]


def normalize_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if "." not in normalized:
        normalized = f"{normalized}.JK"
    return normalized


def rule_response(item) -> dict[str, object]:
    return {
        "symbol": item.symbol,
        "trading_date": item.trading_date,
        "formula_version": item.formula_version,
        "config_checksum": item.config_checksum,
        "indicator_version": item.indicator_version,
        "rules": {
            "price_above_ma5": item.price_above_ma5,
            "price_above_ma10": item.price_above_ma10,
            "price_above_ma20": item.price_above_ma20,
            "ma5_above_ma10": item.ma5_above_ma10,
            "ma10_above_ma20": item.ma10_above_ma20,
            "volume_spike": item.volume_spike,
            "breakout_20": item.breakout_20,
            "high_liquidity": item.high_liquidity,
            "positive_momentum": item.positive_momentum,
        },
    }


def strategy_dependencies() -> tuple[SqlAlchemyStrategyRepository, StrategyConfiguration]:
    settings = get_settings()
    repository = SqlAlchemyStrategyRepository(
        create_session_factory(create_database_engine(settings.database_url))
    )
    configuration = load_strategy_configuration(
        settings.strategies_config_dir / "swing-trend-following-v1.yaml"
    )
    return repository, configuration


@app.get("/strategies", tags=["strategies"])
def strategies(dependencies=Depends(strategy_dependencies)) -> list[dict[str, object]]:
    _, configuration = dependencies
    return [{
        "name": configuration.name,
        "version": configuration.version,
        "description": configuration.description,
        "enabled": configuration.enabled,
        "default": configuration.default,
        "suggested_holding_period": configuration.holding_period,
    }]


@app.get("/strategies/{strategy}/{symbol}", tags=["strategies"])
def latest_strategy(
    strategy: str,
    symbol: str,
    dependencies=Depends(strategy_dependencies),
) -> dict[str, object]:
    repository, configuration = dependencies
    require_strategy(strategy, configuration)
    result = repository.latest_strategy_result(
        normalize_symbol(symbol), configuration.name, configuration.version, configuration.checksum
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Strategy result not found")
    return strategy_response(result, configuration)


@app.get("/strategies/{strategy}/{symbol}/history", tags=["strategies"])
def strategy_history(
    strategy: str,
    symbol: str,
    limit: int = Query(default=100, ge=1, le=500),
    before: date | None = None,
    dependencies=Depends(strategy_dependencies),
) -> list[dict[str, object]]:
    repository, configuration = dependencies
    require_strategy(strategy, configuration)
    results = repository.strategy_history(
        normalize_symbol(symbol), configuration.name, configuration.version,
        configuration.checksum, limit=limit, before=before,
    )
    if not results:
        raise HTTPException(status_code=404, detail="Strategy result not found")
    return [strategy_response(item, configuration) for item in results]


def require_strategy(value: str, configuration: StrategyConfiguration) -> None:
    if value.casefold() != configuration.name.casefold():
        raise HTTPException(status_code=404, detail="Strategy not found")


def strategy_response(item, configuration: StrategyConfiguration | None = None) -> dict[str, object]:
    payload = {
        "symbol": item.symbol,
        "trading_date": item.trading_date,
        "strategy": item.strategy_name,
        "strategy_version": item.strategy_version,
        "strategy_config_checksum": item.strategy_config_checksum,
        "passed": item.passed,
        "evaluation_details": item.evaluation_details,
        "source_rule_formula_version": item.source_rule_formula_version,
        "source_rule_config_checksum": item.source_rule_config_checksum,
    }
    if configuration is not None:
        payload.update({
            "suggested_holding_period": configuration.holding_period,
            "entry_conditions": list(configuration.required_rules),
            "exit_conditions": list(configuration.exit_rules),
        })
    return payload


def score_dependencies() -> tuple[SqlAlchemyScoreRepository, ScoringConfiguration]:
    settings = get_settings()
    repository = SqlAlchemyScoreRepository(
        create_session_factory(create_database_engine(settings.database_url))
    )
    return repository, load_scoring_configuration(settings.scoring_config_path)


@app.get("/scores/{symbol}", tags=["scores"])
def latest_score(
    symbol: str,
    dependencies=Depends(score_dependencies),
) -> dict[str, object]:
    repository, configuration = dependencies
    result = repository.latest_score(
        normalize_symbol(symbol), configuration.version, configuration.checksum
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Score result not found")
    return score_response(result)


@app.get("/scores/{symbol}/history", tags=["scores"])
def score_history(
    symbol: str,
    limit: int = Query(default=100, ge=1, le=500),
    before: date | None = None,
    dependencies=Depends(score_dependencies),
) -> list[dict[str, object]]:
    repository, configuration = dependencies
    results = repository.score_history(
        normalize_symbol(symbol), configuration.version, configuration.checksum,
        limit=limit, before=before,
    )
    if not results:
        raise HTTPException(status_code=404, detail="Score result not found")
    return [score_response(item) for item in results]


def score_response(item) -> dict[str, object]:
    return {
        "symbol": item.symbol,
        "trading_date": item.trading_date,
        "scoring_version": item.scoring_version,
        "scoring_config_checksum": item.scoring_config_checksum,
        "score": item.score,
        "rating": item.rating,
        "contributions": item.contributions,
        "source_rule_formula_version": item.source_rule_formula_version,
        "source_rule_config_checksum": item.source_rule_config_checksum,
    }


def ranking_dependencies() -> tuple[SqlAlchemyRankingRepository, RankingConfiguration]:
    settings = get_settings()
    repository = SqlAlchemyRankingRepository(
        create_session_factory(create_database_engine(settings.database_url))
    )
    return repository, load_ranking_configuration(settings.ranking_config_path)


@app.get("/ranking", tags=["ranking"])
def ranking(
    view: str = Query(default="technical", pattern="^(technical|fundamental|combined)$"),
    trading_date: date | None = None,
    rating: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    dependencies=Depends(ranking_dependencies),
) -> dict[str, object]:
    if view != "technical":
        repository, fundamental = fundamental_dependencies()
        technical = load_scoring_configuration(get_settings().scoring_config_path)
        snapshot = repository.ranking_page(
            view=view, version=fundamental.version, checksum=fundamental.checksum,
            technical_version=technical.version, technical_checksum=technical.checksum,
            technical_weight=fundamental.technical_weight, fundamental_weight=fundamental.fundamental_weight,
            limit=limit, offset=0, rating=rating,
        )
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"{view.title()} ranking snapshot not found")
        fundamental_date, technical_date, rows, total = snapshot
        return ranking_view_response(view, fundamental_date, technical_date, rows, total, limit, 0, fundamental)
    repository, configuration = dependencies
    snapshot = repository.ranking_snapshot(
        configuration.version,
        configuration.checksum,
        trading_date=trading_date,
        rating=rating,
        limit=limit,
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Ranking snapshot not found")
    selected_date, items = snapshot
    return {
        "trading_date": selected_date,
        "ranking_version": configuration.version,
        "ranking_config_checksum": configuration.checksum,
        "items": [ranking_response(item) for item in items],
        "suggested_holding_period": "3-20 trading days",
    }


@app.get("/ranking/paged", tags=["ranking"])
def ranking_paged(
    view: str = Query(default="technical", pattern="^(technical|fundamental|combined)$"),
    trading_date: date | None = None,
    rating: str | None = None,
    min_turnover: Decimal | None = Query(default=None, ge=0),
    liquidity_tier: str | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=10),
    offset: int = Query(default=0, ge=0),
    dependencies=Depends(ranking_dependencies),
):
    if view != "technical":
        repository, fundamental = fundamental_dependencies()
        technical = load_scoring_configuration(get_settings().scoring_config_path)
        snapshot = repository.ranking_page(
            view=view, version=fundamental.version, checksum=fundamental.checksum,
            technical_version=technical.version, technical_checksum=technical.checksum,
            technical_weight=fundamental.technical_weight, fundamental_weight=fundamental.fundamental_weight,
            limit=limit, offset=offset, rating=rating,
        )
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"{view.title()} ranking snapshot not found")
        fundamental_date, technical_date, rows, total = snapshot
        return ranking_view_response(view, fundamental_date, technical_date, rows, total, limit, offset, fundamental)
    repository, configuration = dependencies
    settings = get_settings()
    liquidity = load_liquidity_configuration(settings.liquidity_config_path)
    liquidity_tiers = parse_liquidity_tiers(liquidity_tier)
    liquidity_as_of_date = repository.liquidity_snapshot_date(liquidity.indicator_version)
    snapshot = repository.ranking_snapshot_page(
        configuration.version, configuration.checksum,
        trading_date=trading_date, rating=rating, limit=limit, offset=offset,
        liquidity_as_of_date=liquidity_as_of_date,
        indicator_version=liquidity.indicator_version,
        min_turnover=min_turnover, liquidity_tiers=liquidity_tiers,
        liquidity_thresholds=liquidity.thresholds,
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Ranking snapshot not found")
    selected_date, items, total, unfiltered_total, total_stocks = snapshot
    filters_applied = {}
    if min_turnover is not None:
        filters_applied["min_turnover"] = min_turnover
    if liquidity_tiers:
        filters_applied["liquidity_tier"] = list(liquidity_tiers)
    return page_response(
        [ranking_response(item) for item in items], total, limit, offset,
        trading_date=selected_date, ranking_version=configuration.version,
        ranking_config_checksum=configuration.checksum,
        suggested_holding_period="3-20 trading days",
        unfiltered_total=unfiltered_total, filtered_count=total,
        total_stocks=total_stocks, filters_applied=filters_applied,
        liquidity_as_of_date=liquidity_as_of_date,
    )


def ranking_response(item) -> dict[str, object]:
    return {
        "rank": item.rank,
        "symbol": item.symbol,
        "score": item.score,
        "rating": item.rating,
        "suggested_holding_period": "3-20 trading days",
    }


def fundamental_item(snapshot, symbol: str, rank: int, technical_score=None, combined_score=None):
    return {
        "rank": rank, "symbol": symbol,
        "score": snapshot.fundamental_score if combined_score is None else combined_score,
        "rating": fundamental_rating(snapshot.fundamental_score if combined_score is None else combined_score),
        "technical_score": technical_score,
        "fundamental_score": snapshot.fundamental_score,
        "combined_score": combined_score,
        "data_status": snapshot.data_status,
        "is_red_flagged": snapshot.is_red_flagged,
        "red_flag_reasons": snapshot.red_flag_reasons,
        "fundamental_data_as_of": snapshot.fundamental_data_as_of,
        "rule_values": snapshot.rule_values,
        "roe_percent": snapshot.roe_percent,
        "der_percent": snapshot.der_percent,
    }


def fundamental_rating(score) -> str | None:
    if score is None: return None
    value = Decimal(score)
    return "Strong" if value >= 80 else "Good" if value >= 65 else "Fair" if value >= 50 else "Weak"


def ranking_view_response(view, fundamental_date, technical_date, rows, total, limit, offset, configuration):
    items = []
    for index, row in enumerate(rows, start=offset + 1):
        if view == "fundamental":
            snapshot, symbol = row
            items.append(fundamental_item(snapshot, symbol, index))
        else:
            snapshot, technical, symbol = row
            combined = (Decimal(technical.score) * configuration.technical_weight + Decimal(snapshot.fundamental_score) * configuration.fundamental_weight) / 100
            items.append(fundamental_item(snapshot, symbol, index, technical.score, combined))
    return jsonable_encoder({
        "view": view, "trading_date": technical_date, "fundamental_data_as_of": fundamental_date,
        "ranking_version": configuration.version, "ranking_config_checksum": configuration.checksum,
        "items": items, "total": total, "limit": limit, "offset": offset,
    })


@app.get("/fundamentals/status", tags=["fundamentals"])
def fundamental_status(dependencies=Depends(fundamental_dependencies)):
    repository, configuration = dependencies
    return jsonable_encoder({
        "version": configuration.version,
        "fundamental_data_as_of": repository.latest_snapshot_date(configuration.version, configuration.checksum),
        "last_run": repository.latest_run(configuration.version, configuration.checksum),
    })


@app.get("/fundamentals/{symbol}", tags=["fundamentals"])
def latest_fundamental(symbol: str, dependencies=Depends(fundamental_dependencies)):
    repository, configuration = dependencies
    row = repository.latest_for_symbol(normalize_symbol(symbol), configuration.version, configuration.checksum)
    if row is None:
        raise HTTPException(status_code=404, detail="Fundamental snapshot not found")
    snapshot, normalized = row
    return jsonable_encoder(fundamental_item(snapshot, normalized, 0))


def analysis_dependencies() -> tuple[SqlAlchemyAnalysisRepository, AnalysisConfiguration]:
    settings = get_settings()
    repository = SqlAlchemyAnalysisRepository(
        create_session_factory(create_database_engine(settings.database_url))
    )
    return repository, load_analysis_configuration(settings.analysis_config_path)


@app.get("/analysis", tags=["analysis"])
def analysis_listing(
    trading_date: date | None = None,
    rating: str | None = None,
    strategy_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    dependencies=Depends(analysis_dependencies),
) -> dict[str, object]:
    if strategy_status is not None and strategy_status.lower() not in {
        "passed", "failed", "unavailable"
    }:
        raise HTTPException(status_code=422, detail="Invalid strategy status")
    repository, configuration = dependencies
    snapshot = repository.analysis_snapshot(
        configuration.version, configuration.checksum,
        trading_date=trading_date, rating=rating,
        strategy_status=strategy_status, limit=limit,
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Analysis snapshot not found")
    selected_date, items = snapshot
    return {
        "trading_date": selected_date,
        "analysis_version": configuration.version,
        "analysis_config_checksum": configuration.checksum,
        "items": [analysis_response(item) for item in items],
    }


@app.get("/analysis/{symbol}", tags=["analysis"])
def latest_analysis(
    symbol: str,
    view: str = Query(default="technical", pattern="^(technical|fundamental|combined)$"),
    dependencies=Depends(analysis_dependencies),
) -> dict[str, object]:
    if view != "technical":
        fundamental_repository, fundamental_configuration = fundamental_dependencies()
        row = fundamental_repository.latest_for_symbol(
            normalize_symbol(symbol), fundamental_configuration.version, fundamental_configuration.checksum
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Fundamental snapshot not found")
        snapshot, normalized = row
        technical_payload = None
        if view == "combined":
            repository, configuration = dependencies
            result = repository.latest_analysis(normalized, configuration.version, configuration.checksum)
            technical_payload = analysis_response(result) if result else None
        reasons = []
        cautions = []
        if snapshot.roe_percent is not None:
            reasons.append(f"ROE is {snapshot.roe_percent:.2f}%.")
        if snapshot.der_percent is not None:
            reasons.append(f"DER is {snapshot.der_percent:.2f}%.")
        elif snapshot.is_bank:
            reasons.append("DER is not applicable to this banking company.")
        for rule, value in snapshot.rule_values.items():
            label = rule.replace("_", " ")
            if value is True:
                reasons.append(f"{label} passed.")
            elif value is False:
                cautions.append(f"{label} failed.")
        cautions.extend(snapshot.red_flag_reasons)
        narrative = " ".join(reasons + (["Cautions: " + " ".join(cautions)] if cautions else []))
        if technical_payload:
            narrative = f"{technical_payload['narrative']} Fundamental context: {narrative}"
        return jsonable_encoder({
            "symbol": normalized, "view": view,
            "trading_date": technical_payload.get("trading_date") if technical_payload else None,
            "fundamental_data_as_of": snapshot.fundamental_data_as_of,
            "narrative": narrative, "bullish_reasons": reasons, "caution_reasons": cautions,
            "source_availability": {"technical": technical_payload is not None, "fundamental": True},
            "score": technical_payload.get("score") if technical_payload else snapshot.fundamental_score,
            "fundamental_score": snapshot.fundamental_score,
            "rating": technical_payload.get("rating") if technical_payload else fundamental_rating(snapshot.fundamental_score),
            "rank": technical_payload.get("rank") if technical_payload else None,
            "strategy_status": technical_payload.get("strategy_status") if technical_payload else "not_applicable",
            "disclaimer": "Analysis is generated only from persisted technical and fundamental data and is not financial advice.",
        })
    repository, configuration = dependencies
    result = repository.latest_analysis(
        normalize_symbol(symbol), configuration.version, configuration.checksum
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return analysis_response(result)


@app.get("/analysis/{symbol}/history", tags=["analysis"])
def analysis_history(
    symbol: str,
    limit: int = Query(default=100, ge=1, le=500),
    before: date | None = None,
    dependencies=Depends(analysis_dependencies),
) -> list[dict[str, object]]:
    repository, configuration = dependencies
    results = repository.analysis_history(
        normalize_symbol(symbol), configuration.version, configuration.checksum,
        limit=limit, before=before,
    )
    if not results:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return [analysis_response(item) for item in results]


def analysis_response(item) -> dict[str, object]:
    return {
        "symbol": item.symbol, "trading_date": item.trading_date,
        "analysis_version": item.analysis_version,
        "analysis_config_checksum": item.analysis_config_checksum,
        "narrative": item.narrative,
        "bullish_reasons": item.bullish_reasons,
        "caution_reasons": item.caution_reasons,
        "source_availability": item.source_availability,
        "strategy_status": item.strategy_status,
        "score": item.score, "rating": item.rating, "rank": item.rank,
        "disclaimer": item.disclaimer, "source_versions": item.source_versions,
    }


def alert_dependencies() -> tuple[SqlAlchemyAlertRepository, AlertConfiguration]:
    settings = get_settings()
    return (
        SqlAlchemyAlertRepository(create_session_factory(create_database_engine(settings.database_url))),
        load_alert_configuration(settings.alerts_config_path),
    )


@app.get("/alerts", tags=["alerts"])
def alerts(
    trading_date: date | None = None, symbol: str | None = None,
    trigger: str | None = None, delivery_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    dependencies=Depends(alert_dependencies),
) -> list[dict[str, object]]:
    repository, _ = dependencies
    normalized = normalize_symbol(symbol) if symbol else None
    return [alert_response(item) for item in repository.list_alerts(
        trading_date=trading_date, symbol=normalized, trigger=trigger,
        delivery_status=delivery_status, limit=limit,
    )]


@app.get("/alerts/{alert_id}", tags=["alerts"])
def alert_detail(alert_id: UUID, dependencies=Depends(alert_dependencies)) -> dict[str, object]:
    repository, _ = dependencies
    item = repository.get_alert(alert_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert_response(item)


def alert_response(item) -> dict[str, object]:
    return {
        "id": item.id, "symbol": item.symbol, "trading_date": item.trading_date,
        "triggers": item.triggers, "message": item.message,
        "current_score": item.current_score, "previous_score": item.previous_score,
        "current_rating": item.current_rating, "previous_rating": item.previous_rating,
        "rank": item.rank, "strategy_status": item.strategy_status,
        "bullish_reasons": item.bullish_reasons, "caution_reasons": item.caution_reasons,
        "delivery_status": item.delivery_status, "delivery_attempts": item.delivery_attempts,
        "last_error": item.last_error, "sent_at": item.sent_at,
    }


@app.get("/risk/recommendations", tags=["risk"])
def risk_recommendations(
    trading_date: date | None = None, rating: str | None = None,
    minimum_score: int | None = Query(default=None, ge=0, le=100),
    limit: int = Query(default=10, ge=1, le=10),
    offset: int = Query(default=0, ge=0),
    dependencies=Depends(risk_dependencies),
):
    repository, configuration = dependencies
    selected_date, items = repository.list(
        configuration, trading_date=trading_date, rating=rating,
        minimum_score=minimum_score, limit=limit, offset=offset,
    )
    total = repository.count(
        configuration, trading_date=selected_date, rating=rating,
        minimum_score=minimum_score,
    )
    return page_response(items, total, limit, offset, trading_date=selected_date)


@app.get("/risk/recommendations/{symbol}/history", tags=["risk"])
def risk_recommendation_history(
    symbol: str, limit: int = Query(default=10, ge=1, le=10),
    offset: int = Query(default=0, ge=0), dependencies=Depends(risk_dependencies),
):
    repository, configuration = dependencies
    normalized = normalize_symbol(symbol)
    return page_response(
        repository.history(normalized, configuration, limit, offset),
        repository.count_history(normalized, configuration), limit, offset,
    )


@app.get("/risk/recommendations/{symbol}", tags=["risk"])
def risk_recommendation(symbol: str, dependencies=Depends(risk_dependencies)):
    repository, configuration = dependencies
    item = repository.latest_for_symbol(normalize_symbol(symbol), configuration)
    if item is None:
        raise HTTPException(status_code=404, detail="Risk recommendation not found")
    return item


@app.get("/risk/{symbol}", tags=["risk"])
def risk_recommendation_alias(symbol: str, dependencies=Depends(risk_dependencies)):
    return risk_recommendation(symbol, dependencies)


@app.get("/positions", tags=["positions"])
def positions(
    status: str | None = None,
    limit: int = Query(default=10, ge=1, le=10),
    offset: int = Query(default=0, ge=0),
    dependencies=Depends(position_dependencies),
):
    repository, configuration = dependencies
    try:
        items = repository.list(configuration, status=status, limit=limit, offset=offset)
        total = repository.count(configuration, status=status)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return page_response(items, total, limit, offset)


@app.get("/positions/{symbol}/history", tags=["positions"])
def position_history(
    symbol: str, limit: int = Query(default=10, ge=1, le=10),
    offset: int = Query(default=0, ge=0), dependencies=Depends(position_dependencies),
):
    repository, configuration = dependencies
    normalized = normalize_symbol(symbol)
    return page_response(repository.history(normalized, configuration, limit, offset),
                         repository.count_history(normalized, configuration), limit, offset)


@app.get("/positions/{symbol}/events", tags=["positions"])
def position_events(
    symbol: str, position_id: UUID | None = None,
    limit: int = Query(default=10, ge=1, le=10), offset: int = Query(default=0, ge=0),
    dependencies=Depends(position_dependencies),
):
    repository, configuration = dependencies
    normalized = normalize_symbol(symbol)
    return page_response(repository.events(normalized, configuration, position_id, limit, offset),
                         repository.count_events(normalized, configuration, position_id), limit, offset)


@app.get("/positions/{symbol}", tags=["positions"])
def latest_position(symbol: str, dependencies=Depends(position_dependencies)):
    repository, configuration = dependencies
    item = repository.latest_for_symbol(normalize_symbol(symbol), configuration)
    if item is None:
        raise HTTPException(status_code=404, detail="Position not found")
    return item


@app.get("/portfolio", tags=["portfolio"])
def portfolio_summary(service=Depends(portfolio_dependencies)):
    return jsonable_encoder(service.summary())


@app.get("/portfolio/holdings", tags=["portfolio"])
def portfolio_holdings(limit: int = Query(default=10, ge=1, le=10), offset: int = Query(default=0, ge=0), service=Depends(portfolio_dependencies)):
    items, total = service.repository.holdings(limit=limit, offset=offset)
    return jsonable_encoder(page_response(items, total, limit, offset))


@app.get("/portfolio/transactions", tags=["portfolio"])
def portfolio_transactions(limit: int = Query(default=10, ge=1, le=10), offset: int = Query(default=0, ge=0), service=Depends(portfolio_dependencies)):
    items, total = service.transactions(limit, offset)
    return jsonable_encoder(page_response(items, total, limit, offset))


@app.post("/portfolio/transactions", status_code=201, tags=["portfolio"])
def create_portfolio_transaction(request: PortfolioTransactionRequest, service=Depends(portfolio_dependencies)):
    try:
        return jsonable_encoder(service.create(**request.model_dump()))
    except PortfolioValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/portfolio/transactions/{transaction_id}/reverse", status_code=201, tags=["portfolio"])
def reverse_portfolio_transaction(transaction_id: UUID, notes: str | None = None, service=Depends(portfolio_dependencies)):
    try:
        return jsonable_encoder(service.reverse(transaction_id, notes))
    except PortfolioValidationError as error:
        status = 404 if str(error) == "Transaction not found" else 422
        raise HTTPException(status_code=status, detail=str(error)) from error


@app.get("/portfolio/performance", tags=["portfolio"])
def portfolio_performance(service=Depends(portfolio_dependencies)):
    return jsonable_encoder(service.repository.performance())


def backtest_dependencies() -> SqlAlchemyBacktestRepository:
    settings = get_settings()
    return SqlAlchemyBacktestRepository(
        create_session_factory(create_database_engine(settings.database_url))
    )


def localized_run(item: dict[str, object]) -> dict[str, object]:
    payload = dict(item)
    timezone = get_settings().market_timezone
    payload["started_at"] = localize_datetime(payload.get("started_at"), timezone)
    payload["finished_at"] = localize_datetime(payload.get("finished_at"), timezone)
    return jsonable_encoder(payload)


@app.get("/backtests", tags=["backtests"])
def backtests(limit: int = Query(default=100, ge=1, le=500), repository=Depends(backtest_dependencies)):
    return [localized_run(item) for item in repository.list_runs(limit)]


@app.get("/backtests/{run_id}", tags=["backtests"])
def backtest_detail(run_id: UUID, repository=Depends(backtest_dependencies)):
    item = repository.get_run(run_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Backtest not found")
    return localized_run(item)


@app.get("/backtests/{run_id}/metrics", tags=["backtests"])
def backtest_metrics(run_id: UUID, repository=Depends(backtest_dependencies)):
    item = repository.get_run(run_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Backtest not found")
    return item["metrics"]


@app.get("/backtests/{run_id}/symbols", tags=["backtests"])
def backtest_symbols(run_id: UUID, repository=Depends(backtest_dependencies)):
    return repository.symbol_metrics(run_id)


@app.get("/backtests/{run_id}/symbols/paged", tags=["backtests"])
def backtest_symbols_paged(
    run_id: UUID, limit: int = Query(default=10, ge=1, le=10),
    offset: int = Query(default=0, ge=0), repository=Depends(backtest_dependencies),
):
    if repository.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Backtest not found")
    return page_response(repository.symbol_metrics(run_id, limit, offset), repository.count_symbol_metrics(run_id), limit, offset)


@app.get("/backtests/{run_id}/trades", tags=["backtests"])
def backtest_trades(
    run_id: UUID, symbol: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0), repository=Depends(backtest_dependencies),
):
    return repository.trades(
        run_id, symbol=normalize_symbol(symbol) if symbol else None,
        limit=limit, offset=offset,
    )


@app.get("/backtests/{run_id}/trades/paged", tags=["backtests"])
def backtest_trades_paged(
    run_id: UUID, symbol: str | None = None,
    limit: int = Query(default=10, ge=1, le=10), offset: int = Query(default=0, ge=0),
    repository=Depends(backtest_dependencies),
):
    if repository.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Backtest not found")
    normalized = normalize_symbol(symbol) if symbol else None
    return page_response(
        repository.trades(run_id, symbol=normalized, limit=limit, offset=offset),
        repository.count_trades(run_id, symbol=normalized), limit, offset,
    )


def optimization_dependencies() -> SqlAlchemyOptimizationRepository:
    settings = get_settings()
    return SqlAlchemyOptimizationRepository(
        create_session_factory(create_database_engine(settings.database_url))
    )


@app.get("/optimizations", tags=["optimizations"])
def optimizations(
    limit: int = Query(default=100, ge=1, le=500),
    repository=Depends(optimization_dependencies),
):
    return [localized_run(item) for item in repository.list_runs(limit)]


@app.get("/optimizations/{run_id}", tags=["optimizations"])
def optimization_detail(
    run_id: UUID, repository=Depends(optimization_dependencies)
):
    item = repository.get_run(run_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Optimization run not found")
    return localized_run(item)


@app.get("/optimizations/{run_id}/winner", tags=["optimizations"])
def optimization_winner(
    run_id: UUID, repository=Depends(optimization_dependencies)
):
    if repository.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Optimization run not found")
    item = repository.winner(run_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Optimization winner not found")
    return item


@app.get("/optimizations/{run_id}/candidates", tags=["optimizations"])
def optimization_candidates(
    run_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    repository=Depends(optimization_dependencies),
):
    if repository.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Optimization run not found")
    return repository.candidates(run_id, limit=limit, offset=offset)


@app.get("/optimizations/{run_id}/candidates/paged", tags=["optimizations"])
def optimization_candidates_paged(
    run_id: UUID, limit: int = Query(default=10, ge=1, le=10),
    offset: int = Query(default=0, ge=0), repository=Depends(optimization_dependencies),
):
    if repository.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Optimization run not found")
    return page_response(repository.candidates(run_id, limit, offset), repository.count_candidates(run_id), limit, offset)


@app.get(
    "/optimizations/{run_id}/candidates/{candidate_id}", tags=["optimizations"]
)
def optimization_candidate(
    run_id: UUID,
    candidate_id: str,
    repository=Depends(optimization_dependencies),
):
    item = repository.candidate(run_id, candidate_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Optimization candidate not found")
    return item


@app.get("/optimizations/{run_id}/winner/trades", tags=["optimizations"])
def optimization_winner_trades(
    run_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    repository=Depends(optimization_dependencies),
):
    if repository.winner(run_id) is None:
        raise HTTPException(status_code=404, detail="Optimization winner not found")
    return repository.winner_trades(run_id, limit=limit, offset=offset)


@app.get("/optimizations/{run_id}/winner/trades/paged", tags=["optimizations"])
def optimization_winner_trades_paged(
    run_id: UUID, limit: int = Query(default=10, ge=1, le=10),
    offset: int = Query(default=0, ge=0), repository=Depends(optimization_dependencies),
):
    if repository.winner(run_id) is None:
        raise HTTPException(status_code=404, detail="Optimization winner not found")
    return page_response(repository.winner_trades(run_id, limit, offset), repository.count_winner_trades(run_id), limit, offset)


@app.get("/optimizations/{run_id}/winner/symbols", tags=["optimizations"])
def optimization_winner_symbols(
    run_id: UUID, repository=Depends(optimization_dependencies)
):
    if repository.winner(run_id) is None:
        raise HTTPException(status_code=404, detail="Optimization winner not found")
    return repository.winner_symbols(run_id)


@app.get("/optimizations/{run_id}/winner/symbols/paged", tags=["optimizations"])
def optimization_winner_symbols_paged(
    run_id: UUID, limit: int = Query(default=10, ge=1, le=10),
    offset: int = Query(default=0, ge=0), repository=Depends(optimization_dependencies),
):
    if repository.winner(run_id) is None:
        raise HTTPException(status_code=404, detail="Optimization winner not found")
    return page_response(repository.winner_symbols(run_id, limit, offset), repository.count_winner_symbols(run_id), limit, offset)
