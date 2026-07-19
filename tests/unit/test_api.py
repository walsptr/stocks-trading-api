from fastapi.testclient import TestClient

from stocks_trading.api.app import app
from stocks_trading.api.app import (
    backtest_dependencies,
    alert_dependencies,
    analysis_dependencies,
    optimization_dependencies,
    market_data_dependencies,
    ranking_dependencies,
    rule_dependencies,
    score_dependencies,
    strategy_dependencies,
)
from stocks_trading.domain.models import AlertEvent, DailyAnalysis, DailyRanking, DailyRules, StrategyResult, TechnicalScore
from stocks_trading.alerts.config import load_alert_configuration
from uuid import uuid4
from stocks_trading.analysis.config import load_analysis_configuration
from stocks_trading.ranking.config import load_ranking_configuration
from stocks_trading.rules.config import load_rule_configuration
from stocks_trading.strategies.config import load_strategy_configuration
from stocks_trading.scoring.config import load_scoring_configuration
from pathlib import Path
from datetime import UTC, date, datetime
from decimal import Decimal

client = TestClient(app)


class FakeStockService:
    def list(self, *, search, limit, offset, min_turnover=None, liquidity_tiers=()):
        items = [
                {
                    "symbol": "BBCA.JK",
                    "idx_code": "BBCA",
                    "issuer_name": "Bank Central Asia Tbk",
                    "board": "Main",
                    "sector": "Financials",
                    "last_price": Decimal("9200"),
                    "daily_change": Decimal("100"),
                    "daily_change_percent": Decimal("1.0989"),
                    "volume": 12_000_000,
                    "trading_date": date(2026, 7, 17),
                    "avg_daily_turnover_value": Decimal("6000000000"),
                    "avg_daily_volume": Decimal("650000"),
                    "liquidity_tier": "high",
                }
            ]
        return {
            "stocks": items, "items": items,
            "total_stocks": 863, "filtered_count": 1,
            "filters_applied": {}, "as_of_date": date(2026, 7, 17),
            "total": 1,
            "limit": limit,
            "offset": offset,
        }

    def liquidity_breakdown(self, **kwargs):
        return {"as_of_date": date(2026, 7, 17), "breakdown": [], "unclassified_count": 9}

    async def detail(self, symbol, *, period, interval):
        if symbol != "BBCA.JK":
            from stocks_trading.stocks.service import StockNotFoundError

            raise StockNotFoundError(f"symbol {symbol} is not active in the IDX universe")
        return {
            "symbol": symbol,
            "idx_code": "BBCA",
            "issuer_name": "Bank Central Asia Tbk",
            "board": "Main",
            "sector": "Financials",
            "period": period,
            "interval": interval,
            "last_price": Decimal("9200"),
            "daily_change": Decimal("100"),
            "daily_change_percent": Decimal("1.0989"),
            "volume": 12_000_000,
            "trading_date": "2026-07-17",
            "candles": [
                {
                    "date": "2026-07-17",
                    "open": Decimal("9100"),
                    "high": Decimal("9250"),
                    "low": Decimal("9050"),
                    "close": Decimal("9200"),
                    "adjusted_close": Decimal("9200"),
                    "volume": 12_000_000,
                    "ma20": Decimal("9000"),
                    "ma50": Decimal("8800"),
                    "rsi14": Decimal("58.2"),
                }
            ],
        }


def test_stocks_listing_returns_chart_summary() -> None:
    from stocks_trading.api.app import stocks_dependencies

    app.dependency_overrides[stocks_dependencies] = lambda: FakeStockService()
    try:
        response = client.get("/stocks?search=BBCA")
        assert response.status_code == 200
        assert response.json()["items"][0]["symbol"] == "BBCA.JK"
        assert response.json()["items"][0]["daily_change_percent"] == 1.0989
    finally:
        app.dependency_overrides.clear()


def test_stocks_rejects_invalid_liquidity_tier() -> None:
    from stocks_trading.api.app import stocks_dependencies

    app.dependency_overrides[stocks_dependencies] = lambda: FakeStockService()
    try:
        response = client.get("/stocks?liquidity_tier=high,unknown")
        assert response.status_code == 422
        assert response.json()["detail"] == "unsupported liquidity tier: unknown"
    finally:
        app.dependency_overrides.clear()


def test_stock_detail_normalizes_symbol_and_returns_chart_rows() -> None:
    from stocks_trading.api.app import stocks_dependencies

    app.dependency_overrides[stocks_dependencies] = lambda: FakeStockService()
    try:
        response = client.get("/stocks/bbca?period=6mo&interval=1d")
        assert response.status_code == 200
        assert response.json()["symbol"] == "BBCA.JK"
        assert response.json()["candles"][0]["ma20"] == 9000
    finally:
        app.dependency_overrides.clear()


def test_stock_detail_returns_clear_not_found_error() -> None:
    from stocks_trading.api.app import stocks_dependencies

    app.dependency_overrides[stocks_dependencies] = lambda: FakeStockService()
    try:
        response = client.get("/stocks/unknown")
        assert response.status_code == 404
        assert "not active" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


class FakeLiveRepository:
    def stock_metadata(self, symbol):
        return {"symbol": symbol} if symbol == "BBCA.JK" else None


class FakeLiveManager:
    async def stream(self, symbol):
        yield {"event": "tick", "data": {"symbol": symbol, "price": 9200}}

    def snapshot(self, symbol):
        return {"symbol": symbol, "status": "connected", "tick_count": 1, "ticks": []}


def test_live_tick_snapshot_and_symbol_validation() -> None:
    from stocks_trading.api.app import live_stream_dependencies

    app.dependency_overrides[live_stream_dependencies] = lambda: (FakeLiveManager(), FakeLiveRepository())
    try:
        response = client.get("/debug/live/ticks/bbca")
        assert response.status_code == 200
        assert response.json()["symbol"] == "BBCA.JK"
        assert client.get("/debug/live/ticks/unknown").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_live_stream_returns_sse_headers_and_tick_event() -> None:
    from stocks_trading.api.app import live_stream_dependencies

    app.dependency_overrides[live_stream_dependencies] = lambda: (FakeLiveManager(), FakeLiveRepository())
    try:
        response = client.get("/stocks/BBCA/live")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "event: tick" in response.text
        assert '"price":9200' in response.text
    finally:
        app.dependency_overrides.clear()


def test_root_describes_application() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert response.json()["docs"] == "/docs"


def test_health_endpoint() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_frontend_origin_is_allowed_for_read_requests() -> None:
    response = client.options(
        "/ranking",
        headers={
            "Origin": "http://localhost:21231",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:21231"
    assert "GET" in response.headers["access-control-allow-methods"]


class FakeMarketDataRepository:
    def cache_status(self, target_date):
        return {
            "target_date": target_date,
            "active_symbols": 863,
            "symbols_with_data": 2,
            "symbols_without_target_date": 861,
            "latest_trading_date": date(2026, 7, 16),
            "is_current": True,
            "last_collection_status": "succeeded",
            "last_collection_started_at": datetime(2026, 7, 17, 10, 0, tzinfo=UTC),
            "last_collection_finished_at": datetime(2026, 7, 17, 10, 5, tzinfo=UTC),
        }


def test_market_data_status_endpoint() -> None:
    app.dependency_overrides[market_data_dependencies] = lambda: FakeMarketDataRepository()
    try:
        response = client.get("/market-data/status?as_of=2026-07-16")
        assert response.status_code == 200
        assert response.json()["symbols_with_data"] == 2
        assert response.json()["is_current"] is True
        assert response.json()["last_collection_finished_at"] == "2026-07-17T17:05:00+07:00"
    finally:
        app.dependency_overrides.clear()


def test_market_calendar_endpoint_reports_coverage_and_trading_dates() -> None:
    response = client.get("/market-calendar?as_of=2027-01-02")

    assert response.status_code == 200
    payload = response.json()
    assert payload["calendar_version"] == "idx-v2"
    assert payload["source_reference"] == "PENG-0002/DIR/KSEI/0126"
    assert payload["timezone"] == "Asia/Jakarta"
    assert payload["coverage"]["2027"]["status"] == "pending"
    assert payload["coverage_status"] == "pending"
    assert payload["selected_date"] == "2027-01-02"
    assert payload["is_trading_day"] is False
    assert payload["next_trading_day"] == "2027-01-04"
    assert payload["previous_trading_day"] == "2027-01-01"


def test_operations_status_endpoint_reports_calendar_scheduler_cache_and_sync() -> None:
    from stocks_trading.api import app as api_module

    original_availability = api_module.backfill_manager.availability
    original_current = api_module.backfill_manager.current
    api_module.backfill_manager.availability = lambda years: {
        "target_years": years, "target_start_date": date(2021, 7, 11),
        "target_end_date": date(2026, 7, 17), "active_symbols": 863,
        "symbols_with_data": 817, "symbols_meeting_target": 112,
        "symbols_needing_backfill": 751, "earliest_date": date(2021, 7, 12),
        "latest_date": date(2026, 7, 17), "total_rows": 324727,
    }
    api_module.backfill_manager.current = lambda: None
    try:
        response = client.get("/operations/status")
    finally:
        api_module.backfill_manager.availability = original_availability
        api_module.backfill_manager.current = original_current

    assert response.status_code == 200
    payload = response.json()
    assert payload["api_status"] == "healthy"
    assert payload["calendar"]["timezone"] == "Asia/Jakarta"
    assert payload["calendar"]["official_years"] == [2026]
    assert payload["calendar"]["pending_years"] == [2027, 2028]
    assert payload["calendar"]["coverage"]["2026"] == {
        "status": "official",
        "closure_count": 22,
    }
    assert payload["scheduler"]["enabled"] is True
    assert payload["scheduler"]["next_run_at"] is not None
    assert "target_date" in payload["market_data"]
    assert "status" in payload["sync"]
    assert set(payload["scoped_sync"]) == {"technical", "fundamental", "combined"}
    assert "status" in payload["scoped_sync"]["technical"]
    assert "status" in payload["scoped_sync"]["fundamental"]
    assert payload["scoped_sync"]["combined"]["status"] == "idle"


def test_scoped_backtest_endpoint_is_available() -> None:
    response = client.post(
        "/sync/backtest",
        json={"start_date": "1900-01-01", "end_date": "1900-01-02"},
    )

    assert response.status_code == 422
    assert "Technical tab" in response.json()["detail"]


class FakeRuleRepository:
    def latest_rules(self, symbol, formula_version, config_checksum):
        return rule(symbol, date(2026, 7, 16)) if symbol == "BBCA.JK" else None

    def rule_history(
        self, symbol, formula_version, config_checksum, *, limit, before
    ):
        values = [rule(symbol, date(2026, 7, 16)), rule(symbol, date(2026, 7, 15))]
        if before is not None:
            values = [item for item in values if item.trading_date < before]
        return values[:limit]


def rule(symbol, trading_date):
    config = load_rule_configuration(Path("config/rules-v1.yaml"))
    return DailyRules(
        symbol=symbol,
        trading_date=trading_date,
        price_above_ma5=True,
        price_above_ma10=True,
        price_above_ma20=True,
        ma5_above_ma10=True,
        ma10_above_ma20=True,
        volume_spike=False,
        breakout_20=True,
        high_liquidity=True,
        positive_momentum=True,
        formula_version=config.formula_version,
        config_checksum=config.checksum,
        indicator_version=config.indicator_version,
    )


def rule_dependency_override():
    return FakeRuleRepository(), load_rule_configuration(Path("config/rules-v1.yaml"))


def test_latest_rule_endpoint_normalizes_symbol() -> None:
    app.dependency_overrides[rule_dependencies] = rule_dependency_override
    try:
        response = client.get("/rules/bbca")
        assert response.status_code == 200
        assert response.json()["symbol"] == "BBCA.JK"
        assert response.json()["rules"]["breakout_20"] is True
    finally:
        app.dependency_overrides.clear()


def test_rule_history_uses_exclusive_cursor() -> None:
    app.dependency_overrides[rule_dependencies] = rule_dependency_override
    try:
        response = client.get("/rules/BBCA/history?before=2026-07-16&limit=1")
        assert response.status_code == 200
        assert response.json()[0]["trading_date"] == "2026-07-15"
    finally:
        app.dependency_overrides.clear()


class FakeStrategyRepository:
    def latest_strategy_result(self, symbol, name, version, checksum):
        return strategy_result(symbol, date(2026, 7, 16)) if symbol == "BBCA.JK" else None

    def strategy_history(self, symbol, name, version, checksum, *, limit, before):
        values = [
            strategy_result(symbol, date(2026, 7, 16)),
            strategy_result(symbol, date(2026, 7, 15)),
        ]
        if before is not None:
            values = [item for item in values if item.trading_date < before]
        return values[:limit]


def strategy_result(symbol, trading_date):
    config = load_strategy_configuration(Path("config/strategies/swing-trend-following-v1.yaml"))
    return StrategyResult(
        symbol=symbol,
        trading_date=trading_date,
        strategy_name=config.name,
        strategy_version=config.version,
        strategy_config_checksum=config.checksum,
        passed=True,
        evaluation_details={name: "passed" for name in config.required_rules},
        source_rule_formula_version=config.source_rule_formula_version,
        source_rule_config_checksum=config.source_rule_config_checksum,
    )


def strategy_dependency_override():
    return (
        FakeStrategyRepository(),
        load_strategy_configuration(Path("config/strategies/swing-trend-following-v1.yaml")),
    )


def test_strategy_listing_and_latest_result() -> None:
    app.dependency_overrides[strategy_dependencies] = strategy_dependency_override
    try:
        listing = client.get("/strategies")
        latest = client.get("/strategies/Swing%20Trend%20Following/bbca")
        assert listing.status_code == 200
        assert listing.json()[0]["name"] == "Swing Trend Following"
        assert listing.json()[0]["enabled"] is True
        assert listing.json()[0]["default"] is True
        assert latest.status_code == 200
        assert latest.json()["passed"] is True
    finally:
        app.dependency_overrides.clear()


def test_strategy_history_and_unknown_strategy() -> None:
    app.dependency_overrides[strategy_dependencies] = strategy_dependency_override
    try:
        history = client.get("/strategies/Swing%20Trend%20Following/BBCA/history?before=2026-07-16&limit=1")
        missing = client.get("/strategies/BSJP/BBCA")
        assert history.status_code == 200
        assert history.json()[0]["trading_date"] == "2026-07-15"
        assert missing.status_code == 404
    finally:
        app.dependency_overrides.clear()


class FakeScoreRepository:
    def latest_score(self, symbol, version, checksum):
        return score_result(symbol, date(2026, 7, 16)) if symbol == "BBCA.JK" else None

    def score_history(self, symbol, version, checksum, *, limit, before):
        values = [score_result(symbol, date(2026, 7, 16)), score_result(symbol, date(2026, 7, 15))]
        if before is not None:
            values = [item for item in values if item.trading_date < before]
        return values[:limit]


def score_result(symbol, trading_date):
    config = load_scoring_configuration(Path("config/scoring/technical-v1.yaml"))
    return TechnicalScore(
        symbol=symbol, trading_date=trading_date, scoring_version=config.version,
        scoring_config_checksum=config.checksum, score=90, rating="Strong Buy",
        contributions={"price_above_ma5": {"value": True, "weight": 10, "awarded": 10}},
        source_rule_formula_version=config.source_rule_formula_version,
        source_rule_config_checksum=config.source_rule_config_checksum,
    )


def score_dependency_override():
    return FakeScoreRepository(), load_scoring_configuration(Path("config/scoring/technical-v1.yaml"))


def test_latest_score_and_history() -> None:
    app.dependency_overrides[score_dependencies] = score_dependency_override
    try:
        latest = client.get("/scores/bbca")
        history = client.get("/scores/BBCA/history?before=2026-07-16&limit=1")
        assert latest.status_code == 200
        assert latest.json()["rating"] == "Strong Buy"
        assert history.status_code == 200
        assert history.json()[0]["trading_date"] == "2026-07-15"
    finally:
        app.dependency_overrides.clear()


class FakeRankingRepository:
    def liquidity_snapshot_date(self, indicator_version):
        return date(2026, 7, 16)

    def ranking_snapshot(self, version, checksum, *, trading_date, rating, limit):
        selected = trading_date or date(2026, 7, 16)
        values = [
            ranking_result("BBCA.JK", selected, 1, 95, "Strong Buy"),
            ranking_result("TLKM.JK", selected, 2, 80, "Buy"),
        ]
        if rating is not None:
            values = [item for item in values if item.rating.lower() == rating.lower()]
        return selected, values[:limit]

    def ranking_snapshot_page(self, version, checksum, *, trading_date, rating, limit, offset, **kwargs):
        selected, values = self.ranking_snapshot(version, checksum, trading_date=trading_date, rating=rating, limit=500)
        return selected, values[offset:offset + limit], len(values), len(values), 863


def ranking_result(symbol, trading_date, rank, score, rating):
    config = load_ranking_configuration(Path("config/ranking/technical-v1.yaml"))
    return DailyRanking(
        symbol=symbol, trading_date=trading_date, rank=rank, score=score, rating=rating,
        ranking_version=config.version, ranking_config_checksum=config.checksum,
        source_scoring_version=config.source_scoring_version,
        source_scoring_config_checksum=config.source_scoring_config_checksum,
    )


def ranking_dependency_override():
    return (
        FakeRankingRepository(),
        load_ranking_configuration(Path("config/ranking/technical-v1.yaml")),
    )


def test_ranking_defaults_to_latest_and_filters_rating() -> None:
    app.dependency_overrides[ranking_dependencies] = ranking_dependency_override
    try:
        response = client.get("/ranking?rating=Buy&limit=1")
        assert response.status_code == 200
        assert response.json()["trading_date"] == "2026-07-16"
        assert response.json()["items"] == [
            {
                "rank": 2,
                "symbol": "TLKM.JK",
                "score": 80,
                "rating": "Buy",
                "suggested_holding_period": "3-20 trading days",
            }
        ]
    finally:
        app.dependency_overrides.clear()


def test_ranking_paged_returns_metadata_and_enforces_page_size() -> None:
    app.dependency_overrides[ranking_dependencies] = ranking_dependency_override
    try:
        response = client.get("/ranking/paged?limit=10&offset=0")
        assert response.status_code == 200
        assert response.json()["items"][0]["symbol"] == "BBCA.JK"
        assert response.json()["total"] == 2
        assert response.json()["limit"] == 10
        assert client.get("/ranking/paged?limit=11").status_code == 422
    finally:
        app.dependency_overrides.clear()


class FakeAnalysisRepository:
    def latest_analysis(self, symbol, version, checksum):
        return analysis_result(symbol, date(2026, 7, 16))

    def analysis_history(self, symbol, version, checksum, *, limit, before):
        values = [analysis_result(symbol, date(2026, 7, 16)), analysis_result(symbol, date(2026, 7, 15))]
        if before is not None:
            values = [item for item in values if item.trading_date < before]
        return values[:limit]

    def analysis_snapshot(self, version, checksum, *, trading_date, rating, strategy_status, limit):
        selected = trading_date or date(2026, 7, 16)
        values = [analysis_result("BBCA.JK", selected)]
        return selected, values[:limit]


def analysis_result(symbol, trading_date):
    config = load_analysis_configuration(Path("config/analysis/technical-v1.yaml"))
    return DailyAnalysis(
        symbol=symbol, trading_date=trading_date, analysis_version=config.version,
        analysis_config_checksum=config.checksum, narrative="Deterministic analysis.",
        bullish_reasons=("Price is above SMA5.",), caution_reasons=(),
        source_availability={"indicators": True, "rules": True, "strategy": True, "score": True, "ranking": True},
        strategy_status="passed", score=90, rating="Strong Buy", rank=1,
        disclaimer=config.disclaimer, source_versions=config.source_versions,
    )


def analysis_dependency_override():
    return FakeAnalysisRepository(), load_analysis_configuration(Path("config/analysis/technical-v1.yaml"))


def test_analysis_latest_history_and_listing() -> None:
    app.dependency_overrides[analysis_dependencies] = analysis_dependency_override
    try:
        latest = client.get("/analysis/bbca")
        history = client.get("/analysis/BBCA/history?before=2026-07-16&limit=1")
        listing = client.get("/analysis?strategy_status=passed")
        assert latest.status_code == 200
        assert latest.json()["strategy_status"] == "passed"
        assert history.json()[0]["trading_date"] == "2026-07-15"
        assert listing.json()["items"][0]["rank"] == 1
    finally:
        app.dependency_overrides.clear()


class FakeAlertRepository:
    def __init__(self):
        self.event = AlertEvent(
            id=uuid4(), symbol="BBCA.JK", trading_date=date(2026, 7, 16),
            alert_version="technical-alerts-v1", alert_config_checksum="x",
            triggers=("new_strong_buy",), message="Alert", current_score=95,
            previous_score=80, current_rating="Strong Buy", previous_rating="Buy",
            rank=1, strategy_status="passed", bullish_reasons=(), caution_reasons=(),
            source_versions={},
        )
    def list_alerts(self, **kwargs):
        return [self.event]
    def get_alert(self, alert_id):
        return self.event if alert_id == self.event.id else None


fake_alert_repository = FakeAlertRepository()


def alert_dependency_override():
    return fake_alert_repository, load_alert_configuration(Path("config/alerts/technical-v1.yaml"))


def test_alert_list_and_detail() -> None:
    app.dependency_overrides[alert_dependencies] = alert_dependency_override
    try:
        listing = client.get("/alerts?symbol=bbca")
        detail = client.get(f"/alerts/{fake_alert_repository.event.id}")
        assert listing.status_code == 200
        assert listing.json()[0]["triggers"] == ["new_strong_buy"]
        assert detail.status_code == 200
        assert detail.json()["symbol"] == "BBCA.JK"
    finally:
        app.dependency_overrides.clear()


class FakeBacktestRepository:
    run_id = uuid4()
    def list_runs(self, limit):
        return [self.get_run(self.run_id)]
    def get_run(self, run_id):
        return {
            "id": run_id, "status": "succeeded", "metrics": {"completed_trades": 1},
            "started_at": datetime(2026, 7, 18, 1, 0, tzinfo=UTC), "finished_at": None,
        }
    def symbol_metrics(self, run_id):
        return [{"symbol": "BBCA.JK", "completed_trades": 1}]
    def trades(self, run_id, **kwargs):
        return [{"symbol": "BBCA.JK", "signal_date": date(2026, 7, 15), "exit_date": date(2026, 7, 16)}]


fake_backtest_repository = FakeBacktestRepository()


def test_backtest_endpoints() -> None:
    app.dependency_overrides[backtest_dependencies] = lambda: fake_backtest_repository
    try:
        assert client.get("/backtests").status_code == 200
        assert client.get(f"/backtests/{fake_backtest_repository.run_id}/metrics").json()["completed_trades"] == 1
        assert client.get(f"/backtests/{fake_backtest_repository.run_id}/symbols").json()[0]["symbol"] == "BBCA.JK"
        assert client.get(f"/backtests/{fake_backtest_repository.run_id}/trades?symbol=bbca").status_code == 200
    finally:
        app.dependency_overrides.clear()


class FakeOptimizationRepository:
    run_id = uuid4()
    candidate_id = "0123456789abcdef"

    def list_runs(self, limit):
        return [self.get_run(self.run_id)]

    def get_run(self, run_id):
        if run_id != self.run_id:
            return None
        return {
            "id": run_id,
            "status": "succeeded",
            "strategy": "Swing Trend Following",
            "winner_id": self.candidate_id,
            "started_at": datetime(2026, 7, 18, 1, 0, tzinfo=UTC),
            "finished_at": None,
        }

    def candidates(self, run_id, **kwargs):
        return [self.candidate(run_id, self.candidate_id)]

    def candidate(self, run_id, candidate_id):
        if run_id != self.run_id or candidate_id != self.candidate_id:
            return None
        return {
            "candidate_id": candidate_id,
            "eligible": True,
            "rank": 1,
            "parameters": {"require_breakout": True},
        }

    def winner(self, run_id):
        return self.candidate(run_id, self.candidate_id)

    def winner_trades(self, run_id, **kwargs):
        return [{"symbol": "BBCA.JK", "signal_date": date(2026, 7, 15)}]

    def winner_symbols(self, run_id):
        return [{"symbol": "BBCA.JK", "completed_trades": 30}]


fake_optimization_repository = FakeOptimizationRepository()


def test_optimization_endpoints() -> None:
    app.dependency_overrides[optimization_dependencies] = (
        lambda: fake_optimization_repository
    )
    run_id = fake_optimization_repository.run_id
    candidate_id = fake_optimization_repository.candidate_id
    try:
        assert client.get("/optimizations").status_code == 200
        assert client.get(f"/optimizations/{run_id}").json()["strategy"] == "Swing Trend Following"
        assert client.get(f"/optimizations/{run_id}/winner").json()["rank"] == 1
        assert client.get(f"/optimizations/{run_id}/candidates").json()[0]["candidate_id"] == candidate_id
        assert client.get(f"/optimizations/{run_id}/candidates/{candidate_id}").status_code == 200
        assert client.get(f"/optimizations/{run_id}/winner/trades").json()[0]["symbol"] == "BBCA.JK"
        assert client.get(f"/optimizations/{run_id}/winner/symbols").json()[0]["completed_trades"] == 30
        assert client.get(f"/optimizations/{uuid4()}").status_code == 404
        assert client.get(f"/optimizations/{run_id}/candidates/missing").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_sync_start_and_status_endpoints(monkeypatch) -> None:
    from stocks_trading.api import app as api_module
    from stocks_trading.sync.service import SyncJob, SyncStatus

    job = SyncJob(
        id=uuid4(), status=SyncStatus.RUNNING, stage="market_data", stage_index=1,
        started_at=datetime(2026, 7, 17, 11, 0, tzinfo=UTC),
    )
    async def fake_start(years):
        return job, True
    monkeypatch.setattr(api_module.sync_manager, "start", fake_start)
    monkeypatch.setattr(api_module.sync_manager, "get", lambda job_id: job)
    try:
        response = client.post("/sync?years=1")
        assert response.status_code == 202
        assert response.json()["id"] == str(job.id)
        assert response.json()["started_at"] == "2026-07-17T18:00:00+07:00"
        assert client.get(f"/sync/{job.id}").json()["stage"] == "market_data"
    finally:
        monkeypatch.undo()


def test_research_endpoints(monkeypatch) -> None:
    from stocks_trading.api import app as api_module

    job_id = uuid4()
    run_id = uuid4()
    job = {
        "id": job_id, "job_type": "backtest", "status": "running",
        "start_date": date(2025, 7, 17), "end_date": date(2026, 7, 17),
        "stage": "evaluating", "message": "Running Swing Trend Following backtest", "progress": 55,
        "result_run_id": run_id, "error": None,
        "started_at": datetime(2026, 7, 18, 1, 0, tzinfo=UTC), "finished_at": None,
    }

    monkeypatch.setattr(api_module.research_manager, "availability", lambda: {
        "backtest_start": date(2021, 7, 12), "backtest_end": date(2026, 7, 17),
        "backtest_default_start": date(2025, 7, 17), "backtest_default_end": date(2026, 7, 17),
        "optimization_start": date(2021, 7, 12), "optimization_end": date(2026, 7, 17),
        "optimization_default_start": date(2023, 7, 18), "optimization_default_end": date(2026, 7, 17),
    })
    async def fake_start(job_type, start_date, end_date): return job, True
    monkeypatch.setattr(api_module.research_manager, "start", fake_start)
    monkeypatch.setattr(api_module.research_manager, "get", lambda selected: job if selected == job_id else None)
    monkeypatch.setattr(api_module.research_manager, "current", lambda: job)
    monkeypatch.setattr(api_module.research_manager, "list", lambda limit: [job])
    try:
        assert client.get("/research/availability").json()["backtest_end"] == "2026-07-17"
        response = client.post("/research/backtests", json={"start_date": "2025-07-17", "end_date": "2026-07-17"})
        assert response.status_code == 202
        assert response.json()["progress"] == 55
        assert client.get("/research/jobs/current").json()["id"] == str(job_id)
        assert client.get(f"/research/jobs/{job_id}").status_code == 200
        assert client.get("/research/jobs").json()[0]["job_type"] == "backtest"
    finally:
        monkeypatch.undo()


def test_research_result_run_timestamps_are_jakarta() -> None:
    app.dependency_overrides[backtest_dependencies] = lambda: FakeBacktestRepository()
    try:
        response = client.get(f"/backtests/{fake_backtest_repository.run_id}")
        assert response.status_code == 200
        assert response.json()["started_at"].endswith("+07:00")
    finally:
        app.dependency_overrides.clear()


class FakePositionRepository:
    def list(self, configuration, *, status=None, limit=10, offset=0):
        return [{"id": "00000000-0000-0000-0000-000000000001", "symbol": "BBCA.JK", "status": "open"}]
    def count(self, configuration, *, status=None): return 1
    def latest_for_symbol(self, symbol, configuration): return self.list(configuration)[0] if symbol == "BBCA.JK" else None
    def history(self, symbol, configuration, limit=10, offset=0): return self.list(configuration) if symbol == "BBCA.JK" else []
    def count_history(self, symbol, configuration): return 1 if symbol == "BBCA.JK" else 0
    def events(self, symbol, configuration, position_id=None, limit=10, offset=0):
        return [{"event_type": "entry_filled", "symbol": symbol}]
    def count_events(self, symbol, configuration, position_id=None): return 1


def position_dependency_override():
    from stocks_trading.positions.config import load_position_configuration
    return FakePositionRepository(), load_position_configuration(Path("config/positions/swing-lifecycle-v1.yaml"))


def test_position_endpoints():
    from stocks_trading.api.app import position_dependencies
    app.dependency_overrides[position_dependencies] = position_dependency_override
    try:
        assert client.get("/positions?limit=10&offset=0").json()["total"] == 1
        assert client.get("/positions/bbca").json()["status"] == "open"
        assert client.get("/positions/bbca/history").json()["total"] == 1
        assert client.get("/positions/bbca/events").json()["items"][0]["event_type"] == "entry_filled"
        assert client.get("/positions/tlkm").status_code == 404
    finally:
        app.dependency_overrides.clear()
