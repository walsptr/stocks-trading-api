from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from testcontainers.postgres import PostgresContainer

from stocks_trading.domain.models import (
    BacktestMetrics,
    BacktestResult,
    BacktestTrade,
    DailyCandle,
    DailyAnalysis,
    DailyIndicators,
    DailyRules,
    DailyRanking,
    Security,
    StrategyResult,
    TechnicalScore,
)
from stocks_trading.persistence.database import (
    create_database_engine,
    create_session_factory,
)
from stocks_trading.persistence.models import (
    DailyIndicatorModel,
    DailyAnalysisModel,
    DailyPriceModel,
    DailyRuleModel,
    DailyRankingModel,
    DailyStrategyResultModel,
    DailyTechnicalScoreModel,
    SecurityModel,
)
from stocks_trading.persistence.repositories import (
    SqlAlchemyIndicatorRepository,
    SqlAlchemyAnalysisRepository,
    SqlAlchemyMarketDataRepository,
    SqlAlchemyRuleRepository,
    SqlAlchemyRankingRepository,
    SqlAlchemyScoreRepository,
    SqlAlchemyStrategyRepository,
    SqlAlchemyUniverseRepository,
)
from stocks_trading.optimization.config import load_optimization_configuration
from pathlib import Path


@pytest.mark.integration
def test_migration_and_universe_reconciliation() -> None:
    try:
        container = PostgresContainer("postgres:17-alpine")
        container.start()
    except Exception as error:
        pytest.skip(f"Docker/PostgreSQL unavailable: {error}")

    try:
        database_url = container.get_connection_url().replace(
            "postgresql+psycopg2", "postgresql+psycopg"
        )
        alembic = Config("alembic.ini")
        alembic.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(alembic, "head")

        engine = create_database_engine(database_url)
        repository = SqlAlchemyUniverseRepository(create_session_factory(engine))
        first = [
            Security("BBCA.JK", "BBCA", "Bank Central Asia"),
            Security("TLKM.JK", "TLKM", "Telkom Indonesia"),
        ]
        assert repository.import_snapshot(
            snapshot_date=date(2026, 7, 15),
            checksum="a" * 64,
            source="test-one.csv",
            securities=first,
        ) == (2, 0, 0)
        assert repository.import_snapshot(
            snapshot_date=date(2026, 7, 15),
            checksum="a" * 64,
            source="test-one.csv",
            securities=first,
        ) == (0, 0, 0)
        assert repository.import_snapshot(
            snapshot_date=date(2026, 7, 16),
            checksum="b" * 64,
            source="test-two.csv",
            securities=[Security("BBCA.JK", "BBCA", "PT Bank Central Asia Tbk")],
        ) == (0, 1, 1)

        securities = repository.list_securities()
        assert [(item.symbol, item.is_active) for item in securities] == [
            ("BBCA.JK", True),
            ("TLKM.JK", False),
        ]
        with create_session_factory(engine)() as session:
            assert session.scalar(select(func.count(SecurityModel.id))) == 2
            assert session.scalar(select(func.count(DailyPriceModel.id))) == 0

        session_factory = create_session_factory(engine)
        market_repository = SqlAlchemyMarketDataRepository(session_factory)
        indicator_repository = SqlAlchemyIndicatorRepository(session_factory)
        rule_repository = SqlAlchemyRuleRepository(session_factory)
        strategy_repository = SqlAlchemyStrategyRepository(session_factory)
        score_repository = SqlAlchemyScoreRepository(session_factory)
        ranking_repository = SqlAlchemyRankingRepository(session_factory)
        analysis_repository = SqlAlchemyAnalysisRepository(session_factory)
        candle = DailyCandle(
            symbol="BBCA.JK",
            trading_date=date(2026, 7, 16),
            open=Decimal("9000"),
            high=Decimal("9200"),
            low=Decimal("8950"),
            close=Decimal("9150"),
            adjusted_close=Decimal("9100"),
            volume=1_000_000,
        )
        assert market_repository.upsert_candles([candle]) == 1
        indicator = DailyIndicators(
            symbol="BBCA.JK",
            trading_date=date(2026, 7, 16),
            sma_5=Decimal("9100"),
            sma_10=None,
            sma_20=None,
            sma_50=None,
            sma_200=None,
            volume_ma_20=None,
            volume_ratio=None,
            daily_change_percent=Decimal("1.25"),
            atr_14=None,
            highest_high_20=None,
            lowest_low_20=None,
            average_traded_value_20=Decimal("12000000000"),
        )
        assert indicator_repository.upsert_indicators([indicator]) == 1
        assert indicator_repository.upsert_indicators([indicator]) == 1
        assert indicator_repository.latest_indicator_date(
            "BBCA.JK", "technical-v2"
        ) == date(2026, 7, 16)
        rule = DailyRules(
            symbol="BBCA.JK",
            trading_date=date(2026, 7, 16),
            price_above_ma5=True,
            price_above_ma10=None,
            price_above_ma20=None,
            ma5_above_ma10=None,
            ma10_above_ma20=None,
            volume_spike=None,
            breakout_20=None,
            high_liquidity=True,
            positive_momentum=True,
            formula_version="rules-v1",
            config_checksum="c" * 64,
            indicator_version="technical-v2",
        )
        assert rule_repository.upsert_rules([rule]) == 1
        assert rule_repository.upsert_rules([rule]) == 1
        assert rule_repository.latest_rules(
            "BBCA.JK", "rules-v1", "c" * 64
        ) == rule
        strategy = StrategyResult(
            symbol="BBCA.JK",
            trading_date=date(2026, 7, 16),
            strategy_name="BSJP",
            strategy_version="bsjp-v1",
            strategy_config_checksum="d" * 64,
            passed=True,
            evaluation_details={"price_above_ma5": "passed"},
            source_rule_formula_version="rules-v1",
            source_rule_config_checksum="c" * 64,
        )
        assert strategy_repository.upsert_strategy_results([strategy]) == 1
        assert strategy_repository.upsert_strategy_results([strategy]) == 1
        assert strategy_repository.latest_strategy_result(
            "BBCA.JK", "BSJP", "bsjp-v1", "d" * 64
        ) == strategy
        score = TechnicalScore(
            symbol="BBCA.JK",
            trading_date=date(2026, 7, 16),
            scoring_version="technical-score-v1",
            scoring_config_checksum="e" * 64,
            score=80,
            rating="Buy",
            contributions={
                "price_above_ma5": {
                    "value": True,
                    "weight": 10,
                    "points": 10,
                }
            },
            source_rule_formula_version="rules-v1",
            source_rule_config_checksum="c" * 64,
            source_rule_evaluated_at=datetime(2026, 7, 16, 12, tzinfo=UTC),
        )
        assert score_repository.upsert_scores([score]) == 1
        assert score_repository.upsert_scores([score]) == 1
        assert score_repository.latest_score(
            "BBCA.JK", "technical-score-v1", "e" * 64
        ) == score
        ranking = DailyRanking(
            symbol="BBCA.JK", trading_date=date(2026, 7, 16), rank=1,
            score=80, rating="Buy", ranking_version="technical-ranking-v1",
            ranking_config_checksum="f" * 64,
            source_scoring_version="technical-score-v1",
            source_scoring_config_checksum="e" * 64,
        )
        assert ranking_repository.replace_rankings(
            date(2026, 7, 16), "technical-ranking-v1", "f" * 64, [ranking]
        ) == 1
        assert ranking_repository.replace_rankings(
            date(2026, 7, 16), "technical-ranking-v1", "f" * 64, [ranking]
        ) == 1
        assert ranking_repository.ranking_snapshot(
            "technical-ranking-v1", "f" * 64,
            trading_date=None, rating=None, limit=100,
        ) == (date(2026, 7, 16), [ranking])
        analysis = DailyAnalysis(
            symbol="BBCA.JK", trading_date=date(2026, 7, 16),
            analysis_version="technical-analysis-v1",
            analysis_config_checksum="g" * 64,
            narrative="Deterministic analysis.",
            bullish_reasons=("Price is above SMA5.",), caution_reasons=(),
            source_availability={"indicators": True, "rules": True, "strategy": True, "score": True, "ranking": True},
            strategy_status="passed", score=80, rating="Buy", rank=1,
            disclaimer="Informational only.", source_versions={"ranking_version": "technical-ranking-v1"},
        )
        assert analysis_repository.replace_analyses(
            date(2026, 7, 16), "technical-analysis-v1", "g" * 64, [analysis]
        ) == 1
        assert analysis_repository.replace_analyses(
            date(2026, 7, 16), "technical-analysis-v1", "g" * 64, [analysis]
        ) == 1
        assert analysis_repository.latest_analysis(
            "BBCA.JK", "technical-analysis-v1", "g" * 64
        ) == analysis
        with session_factory() as session:
            assert session.scalar(select(func.count(DailyIndicatorModel.id))) == 1
            assert session.scalar(select(func.count(DailyRuleModel.id))) == 1
            assert session.scalar(select(func.count(DailyStrategyResultModel.id))) == 1
            assert session.scalar(select(func.count(DailyTechnicalScoreModel.id))) == 1
            assert session.scalar(select(func.count(DailyRankingModel.id))) == 1
            assert session.scalar(select(func.count(DailyAnalysisModel.id))) == 1
    finally:
        container.stop()
    OptimizationCandidate,
    OptimizationResult,
    OptimizationCandidateModel,
    OptimizationRunModel,
    OptimizationWinnerSymbolModel,
    OptimizationWinnerTradeModel,
    SqlAlchemyOptimizationRepository,


@pytest.mark.integration
def test_optimizer_migration_and_candidate_persistence() -> None:
    try:
        container = PostgresContainer("postgres:17-alpine")
        container.start()
    except Exception as error:
        pytest.skip(f"Docker/PostgreSQL unavailable: {error}")

    try:
        database_url = container.get_connection_url().replace(
            "postgresql+psycopg2", "postgresql+psycopg"
        )
        alembic = Config("alembic.ini")
        alembic.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(alembic, "head")
        session_factory = create_session_factory(create_database_engine(database_url))
        repository = SqlAlchemyOptimizationRepository(session_factory)
        configuration = load_optimization_configuration(
            Path("config/optimization/bsjp-v1.yaml")
        )
        metrics = BacktestMetrics(
            signal_count=30, completed_trades=30, unclosed_signals=0,
            wins=20, losses=10, win_rate=Decimal("0.6667"),
            average_gross_return=Decimal("0.02"), average_net_return=Decimal("0.015"),
            total_compounded_return=Decimal("0.5"), gross_profit=Decimal("500000"),
            gross_loss=Decimal("-100000"), profit_factor=Decimal("5"),
            maximum_drawdown=Decimal("-0.1"), sharpe_ratio=Decimal("1.5"),
        )
        trade = BacktestTrade(
            symbol="BBCA.JK", signal_date=date(2026, 7, 15), exit_date=date(2026, 7, 16),
            entry_price=Decimal("100"), exit_price=Decimal("105"),
            gross_return=Decimal("0.05"), net_return=Decimal("0.046"),
            buy_fee=Decimal("1500"), sell_fee=Decimal("2625"),
            gross_profit=Decimal("50000"), net_profit=Decimal("45875"),
        )
        candidate = OptimizationCandidate(
            candidate_id="0123456789abcdef",
            parameters={"require_breakout": True}, eligible=True,
            ineligible_reason=None, training_metrics=metrics,
            validation_metrics=metrics, rank=1,
        )
        result = OptimizationResult(
            candidates=(candidate,), winner_id=candidate.candidate_id,
            training_start=date(2026, 1, 1), training_end=date(2026, 5, 31),
            validation_start=date(2026, 6, 1), validation_end=date(2026, 7, 16),
            winner_backtest=BacktestResult((trade,), metrics, {"BBCA.JK": metrics}),
        )

        run_id = repository.save_result(
            configuration, "BSJP", date(2026, 1, 1), date(2026, 7, 16), result
        )

        assert repository.get_run(run_id)["winner_id"] == candidate.candidate_id
        assert repository.candidates(run_id)[0]["rank"] == 1
        assert repository.winner(run_id)["candidate_id"] == candidate.candidate_id
        assert repository.winner_trades(run_id)[0]["symbol"] == "BBCA.JK"
        assert repository.winner_symbols(run_id)[0]["completed_trades"] == 30
        with session_factory() as session:
            assert session.scalar(select(func.count(OptimizationRunModel.id))) == 1
            assert session.scalar(select(func.count(OptimizationCandidateModel.id))) == 1
            assert session.scalar(select(func.count(OptimizationWinnerTradeModel.id))) == 1
            assert session.scalar(select(func.count(OptimizationWinnerSymbolModel.id))) == 1
    finally:
        container.stop()
