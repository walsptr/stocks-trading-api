from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
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
    SqlAlchemyMarketDataRepository,
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
from stocks_trading.sync.service import SyncManager
from stocks_trading.research.service import ResearchManager, ResearchValidationError
from stocks_trading.portfolio.service import PortfolioService, PortfolioValidationError


def research_dependencies() -> SqlAlchemyResearchRepository:
    settings = get_settings()
    return SqlAlchemyResearchRepository(
        create_session_factory(create_database_engine(settings.database_url))
    )


research_manager = ResearchManager(
    research_dependencies(),
    lambda: __import__("stocks_trading.cli.app", fromlist=["dependencies"]).dependencies(),
    get_settings(),
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    research_manager.recover_interrupted()
    yield


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


class ResearchRequest(BaseModel):
    start_date: date
    end_date: date


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


@app.get("/market-data/status", tags=["market-data"])
def market_data_status(
    as_of: date | None = None,
    repository=Depends(market_data_dependencies),
) -> dict[str, object]:
    settings = get_settings()
    target = as_of or latest_completed_market_date(
        datetime.now(UTC), settings.market_timezone
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
    trading_date: date | None = None,
    rating: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    dependencies=Depends(ranking_dependencies),
) -> dict[str, object]:
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
    trading_date: date | None = None,
    rating: str | None = None,
    limit: int = Query(default=10, ge=1, le=10),
    offset: int = Query(default=0, ge=0),
    dependencies=Depends(ranking_dependencies),
):
    repository, configuration = dependencies
    snapshot = repository.ranking_snapshot_page(
        configuration.version, configuration.checksum,
        trading_date=trading_date, rating=rating, limit=limit, offset=offset,
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Ranking snapshot not found")
    selected_date, items, total = snapshot
    return page_response(
        [ranking_response(item) for item in items], total, limit, offset,
        trading_date=selected_date, ranking_version=configuration.version,
        ranking_config_checksum=configuration.checksum,
        suggested_holding_period="3-20 trading days",
    )


def ranking_response(item) -> dict[str, object]:
    return {
        "rank": item.rank,
        "symbol": item.symbol,
        "score": item.score,
        "rating": item.rating,
        "suggested_holding_period": "3-20 trading days",
    }


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
    symbol: str, dependencies=Depends(analysis_dependencies)
) -> dict[str, object]:
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
