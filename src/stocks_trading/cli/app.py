import asyncio
from datetime import date
from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer

from stocks_trading.config.logging import configure_logging
from stocks_trading.config.settings import get_settings
from stocks_trading.domain.models import (
    AnalysisRunStatus,
    IndicatorRunStatus,
    RuleRunStatus,
    RankingRunStatus,
    RunStatus,
    ScoreRunStatus,
    StrategyRunStatus,
)
from stocks_trading.indicators.service import IndicatorService
from stocks_trading.analysis.config import load_analysis_configuration
from stocks_trading.analysis.service import AnalysisService
from stocks_trading.alerts.config import load_alert_configuration
from stocks_trading.alerts.service import AlertService
from stocks_trading.alerts.telegram import TelegramClient
from stocks_trading.backtesting.config import load_backtest_configuration
from stocks_trading.backtesting.service import BacktestService
from stocks_trading.market_data.service import MarketDataCollector
from stocks_trading.market_data.yahoo import YahooFinanceProvider
from stocks_trading.optimization.config import load_optimization_configuration
from stocks_trading.optimization.service import OptimizationService
from stocks_trading.risk.config import load_risk_configuration
from stocks_trading.risk.service import RiskService
from stocks_trading.positions.config import load_position_configuration
from stocks_trading.positions.service import PositionService
from stocks_trading.persistence.database import (
    create_database_engine,
    create_session_factory,
)
from stocks_trading.persistence.repositories import (
    SqlAlchemyAnalysisRepository,
    SqlAlchemyAnalysisRunRepository,
    SqlAlchemyAlertRepository,
    SqlAlchemyAlertRunRepository,
    SqlAlchemyBacktestRepository,
    SqlAlchemyMarketDataRepository,
    SqlAlchemyOptimizationRepository,
    SqlAlchemyIndicatorRepository,
    SqlAlchemyIndicatorRunRepository,
    SqlAlchemyRuleRepository,
    SqlAlchemyRuleRunRepository,
    SqlAlchemyRankingRepository,
    SqlAlchemyRankingRunRepository,
    SqlAlchemyRiskRepository,
    SqlAlchemyRiskRunRepository,
    SqlAlchemyPositionRepository,
    SqlAlchemyPositionRunRepository,
    SqlAlchemyScoreRepository,
    SqlAlchemyScoreRunRepository,
    SqlAlchemyStrategyRepository,
    SqlAlchemyStrategyRunRepository,
    SqlAlchemyRunRepository,
    SqlAlchemyUniverseRepository,
    SqlAlchemyFundamentalRepository,
)
from stocks_trading.fundamentals.config import load_fundamental_configuration
from stocks_trading.fundamentals.service import FundamentalService
from stocks_trading.universe.service import UniverseService
from stocks_trading.rules.config import load_rule_configuration
from stocks_trading.rules.service import RuleService
from stocks_trading.scoring.config import load_scoring_configuration
from stocks_trading.scoring.service import ScoringService
from stocks_trading.ranking.config import load_ranking_configuration
from stocks_trading.ranking.service import RankingService
from stocks_trading.strategies.config import load_strategy_configuration
from stocks_trading.strategies.service import StrategyService

app = typer.Typer(help="IDX market data and technical analysis CLI.", no_args_is_help=True)
universe_app = typer.Typer(help="Manage the IDX security universe.")
market_app = typer.Typer(help="Collect Yahoo Finance daily market data.")
runs_app = typer.Typer(help="Inspect collection runs.")
indicators_app = typer.Typer(help="Calculate persisted technical indicators.")
indicator_runs_app = typer.Typer(help="Inspect indicator calculation runs.")
rules_app = typer.Typer(help="Evaluate persisted reusable technical rules.")
rule_runs_app = typer.Typer(help="Inspect rule evaluation runs.")
strategies_app = typer.Typer(help="Evaluate configured trading strategies.")
strategy_runs_app = typer.Typer(help="Inspect strategy evaluation runs.")
scores_app = typer.Typer(help="Calculate persisted technical scores.")
score_runs_app = typer.Typer(help="Inspect score calculation runs.")
rankings_app = typer.Typer(help="Build persisted technical ranking snapshots.")
ranking_runs_app = typer.Typer(help="Inspect ranking calculation runs.")
analyses_app = typer.Typer(help="Generate persisted technical explanations.")
analysis_runs_app = typer.Typer(help="Inspect analysis generation runs.")
alerts_app = typer.Typer(help="Generate and deliver Telegram alerts.")
alert_runs_app = typer.Typer(help="Inspect alert runs.")
backtests_app = typer.Typer(help="Run and inspect historical strategy backtests.")
optimizations_app = typer.Typer(help="Run and inspect strategy optimizations.")
fundamentals_app = typer.Typer(help="Collect and score versioned company fundamentals.")
app.add_typer(universe_app, name="universe")
app.add_typer(market_app, name="market")
app.add_typer(runs_app, name="runs")
app.add_typer(indicators_app, name="indicators")
app.add_typer(indicator_runs_app, name="indicator-runs")
app.add_typer(rules_app, name="rules")
app.add_typer(rule_runs_app, name="rule-runs")
app.add_typer(strategies_app, name="strategies")
app.add_typer(strategy_runs_app, name="strategy-runs")
app.add_typer(scores_app, name="scores")
app.add_typer(score_runs_app, name="score-runs")
app.add_typer(rankings_app, name="rankings")
app.add_typer(ranking_runs_app, name="ranking-runs")
app.add_typer(analyses_app, name="analyses")
app.add_typer(analysis_runs_app, name="analysis-runs")
app.add_typer(alerts_app, name="alerts")
app.add_typer(alert_runs_app, name="alert-runs")
app.add_typer(backtests_app, name="backtests")
app.add_typer(optimizations_app, name="optimizations")
app.add_typer(fundamentals_app, name="fundamentals")


def dependencies():
    settings = get_settings()
    configure_logging(settings.log_level, settings.market_timezone)
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    universe_repository = SqlAlchemyUniverseRepository(session_factory)
    market_repository = SqlAlchemyMarketDataRepository(session_factory)
    run_repository = SqlAlchemyRunRepository(session_factory)
    indicator_repository = SqlAlchemyIndicatorRepository(session_factory)
    indicator_run_repository = SqlAlchemyIndicatorRunRepository(session_factory)
    rule_repository = SqlAlchemyRuleRepository(session_factory)
    rule_run_repository = SqlAlchemyRuleRunRepository(session_factory)
    strategy_repository = SqlAlchemyStrategyRepository(session_factory)
    strategy_run_repository = SqlAlchemyStrategyRunRepository(session_factory)
    score_repository = SqlAlchemyScoreRepository(session_factory)
    score_run_repository = SqlAlchemyScoreRunRepository(session_factory)
    ranking_repository = SqlAlchemyRankingRepository(session_factory)
    ranking_run_repository = SqlAlchemyRankingRunRepository(session_factory)
    analysis_repository = SqlAlchemyAnalysisRepository(session_factory)
    analysis_run_repository = SqlAlchemyAnalysisRunRepository(session_factory)
    risk_repository = SqlAlchemyRiskRepository(session_factory)
    risk_run_repository = SqlAlchemyRiskRunRepository(session_factory)
    position_repository = SqlAlchemyPositionRepository(session_factory)
    position_run_repository = SqlAlchemyPositionRunRepository(session_factory)
    alert_repository = SqlAlchemyAlertRepository(session_factory)
    alert_run_repository = SqlAlchemyAlertRunRepository(session_factory)
    backtest_repository = SqlAlchemyBacktestRepository(session_factory)
    optimization_repository = SqlAlchemyOptimizationRepository(session_factory)
    collector = MarketDataCollector(
        provider=YahooFinanceProvider(settings.market_timezone),
        market_repository=market_repository,
        run_repository=run_repository,
        settings=settings,
    )
    indicator_service = IndicatorService(
        indicator_repository=indicator_repository,
        run_repository=indicator_run_repository,
        settings=settings,
    )
    rule_service = RuleService(
        rule_repository=rule_repository,
        run_repository=rule_run_repository,
        settings=settings,
        configuration=load_rule_configuration(settings.rules_config_path),
    )
    strategy_configuration = load_strategy_configuration(
        settings.strategies_config_dir / "swing-trend-following-v1.yaml"
    )
    strategy_service = StrategyService(
        strategy_repository=strategy_repository,
        run_repository=strategy_run_repository,
        settings=settings,
        configuration=strategy_configuration,
    )
    scoring_service = ScoringService(
        score_repository=score_repository,
        run_repository=score_run_repository,
        settings=settings,
        configuration=load_scoring_configuration(settings.scoring_config_path),
    )
    ranking_service = RankingService(
        ranking_repository=ranking_repository,
        run_repository=ranking_run_repository,
        settings=settings,
        configuration=load_ranking_configuration(settings.ranking_config_path),
    )
    analysis_service = AnalysisService(
        analysis_repository=analysis_repository,
        run_repository=analysis_run_repository,
        settings=settings,
        configuration=load_analysis_configuration(settings.analysis_config_path),
    )
    risk_service = RiskService(
        risk_repository, risk_run_repository, settings,
        load_risk_configuration(settings.risk_config_path),
    )
    position_service = PositionService(
        position_repository, position_run_repository,
        load_position_configuration(settings.positions_config_path),
    )
    alert_service = AlertService(
        alert_repository=alert_repository,
        run_repository=alert_run_repository,
        configuration=load_alert_configuration(settings.alerts_config_path),
        telegram=TelegramClient(settings.telegram_bot_token, settings.telegram_chat_id),
    )
    backtest_service = BacktestService(
        backtest_repository,
        load_backtest_configuration(settings.backtest_config_path),
    )
    optimization_service = OptimizationService(
        optimization_repository,
        load_optimization_configuration(settings.optimization_config_path),
    )
    return (
        universe_repository,
        market_repository,
        run_repository,
        collector,
        indicator_run_repository,
        indicator_service,
        rule_run_repository,
        rule_service,
        strategy_run_repository,
        strategy_service,
        score_run_repository,
        scoring_service,
        ranking_run_repository,
        ranking_service,
        analysis_run_repository,
        analysis_service,
        risk_run_repository,
        risk_service,
        position_run_repository,
        position_service,
        alert_run_repository,
        alert_service,
        backtest_repository,
        backtest_service,
        optimization_repository,
        optimization_service,
    )


def fundamental_service() -> FundamentalService:
    settings = get_settings()
    repository = SqlAlchemyFundamentalRepository(
        create_session_factory(create_database_engine(settings.database_url))
    )
    return FundamentalService(
        repository,
        load_fundamental_configuration(settings.fundamental_config_path),
        settings.max_workers,
    )


@fundamentals_app.command("update")
def fundamentals_update(
    symbols: Annotated[list[str] | None, typer.Option("--symbol", "-s")] = None,
) -> None:
    result = asyncio.run(fundamental_service().update(symbols=symbols))
    for key, value in result.items():
        typer.echo(f"{key}: {value}")


@universe_app.command("import")
def import_universe(
    file: Annotated[Path, typer.Option("--file", exists=True, dir_okay=False)]
) -> None:
    universe_repository, *_ = dependencies()
    result = UniverseService(universe_repository).import_csv(file)
    typer.echo(
        f"Imported {result.total} securities for {result.snapshot_date}: "
        f"{result.inserted} new, {result.updated} updated, "
        f"{result.marked_inactive} inactive."
    )


@universe_app.command("list")
def list_universe(
    active_only: Annotated[bool, typer.Option("--active-only")] = False,
) -> None:
    universe_repository, *_ = dependencies()
    securities = universe_repository.list_securities(active_only=active_only)
    typer.echo("SYMBOL\tACTIVE\tISSUER")
    for security in securities:
        typer.echo(f"{security.symbol}\t{security.is_active}\t{security.issuer_name}")


@market_app.command("bootstrap")
def market_bootstrap(
    years: Annotated[int, typer.Option(min=1, max=20)] = 5,
    symbols: Annotated[list[str] | None, typer.Option("--symbol", "-s")] = None,
    as_of: Annotated[str | None, typer.Option("--as-of", help="ISO date (YYYY-MM-DD)")] = None,
) -> None:
    _, _, _, collector, *_ = dependencies()
    result = asyncio.run(
        collector.bootstrap(years=years, symbols=symbols, as_of=parse_date(as_of))
    )
    emit_run_result(result)


@market_app.command("update")
def market_update(
    symbols: Annotated[list[str] | None, typer.Option("--symbol", "-s")] = None,
    as_of: Annotated[str | None, typer.Option("--as-of", help="ISO date (YYYY-MM-DD)")] = None,
) -> None:
    _, _, _, collector, *_ = dependencies()
    result = asyncio.run(collector.update(symbols=symbols, as_of=parse_date(as_of)))
    emit_run_result(result)


@market_app.command("refresh")
def market_refresh(
    from_date: Annotated[str, typer.Option("--from")] = ...,
    to_date: Annotated[str, typer.Option("--to")] = ...,
    symbols: Annotated[list[str] | None, typer.Option("--symbol", "-s")] = None,
) -> None:
    _, _, _, collector, *_ = dependencies()
    result = asyncio.run(collector.refresh(
        start_date=parse_date(from_date), end_date=parse_date(to_date), symbols=symbols,
    ))
    emit_run_result(result)


@market_app.command("status")
def market_status(
    as_of: Annotated[str | None, typer.Option("--as-of")] = None,
) -> None:
    _, _, _, collector, *_ = dependencies()
    for key, value in collector.status(as_of=parse_date(as_of)).items():
        typer.echo(f"{key}: {value}")


@market_app.command("retry")
def market_retry(run_id: Annotated[UUID, typer.Option("--run-id")]) -> None:
    _, _, _, collector, *_ = dependencies()
    result = asyncio.run(collector.retry(run_id))
    emit_run_result(result)


@runs_app.command("show")
def show_run(run_id: UUID) -> None:
    _, _, run_repository, *_ = dependencies()
    run = run_repository.get_run_summary(run_id)
    if run is None:
        typer.echo(f"Run {run_id} was not found.", err=True)
        raise typer.Exit(code=2)
    for key, value in run.items():
        typer.echo(f"{key}: {value}")


@indicators_app.command("rebuild")
def indicators_rebuild(
    symbols: Annotated[list[str] | None, typer.Option("--symbol", "-s")] = None,
    from_date: Annotated[
        str | None, typer.Option("--from", help="ISO date (YYYY-MM-DD)")
    ] = None,
    to_date: Annotated[
        str | None, typer.Option("--to", help="ISO date (YYYY-MM-DD)")
    ] = None,
) -> None:
    indicator_service = dependencies()[5]
    result = asyncio.run(
        indicator_service.rebuild(
            symbols=symbols,
            start_date=parse_date(from_date),
            end_date=parse_date(to_date),
        )
    )
    emit_indicator_run_result(result)


@indicators_app.command("update")
def indicators_update(
    symbols: Annotated[list[str] | None, typer.Option("--symbol", "-s")] = None,
    as_of: Annotated[
        str | None, typer.Option("--as-of", help="ISO date (YYYY-MM-DD)")
    ] = None,
) -> None:
    indicator_service = dependencies()[5]
    result = asyncio.run(
        indicator_service.update(symbols=symbols, as_of=parse_date(as_of))
    )
    emit_indicator_run_result(result)


@indicator_runs_app.command("show")
def show_indicator_run(run_id: UUID) -> None:
    indicator_run_repository = dependencies()[4]
    run = indicator_run_repository.get_indicator_run_summary(run_id)
    if run is None:
        typer.echo(f"Indicator run {run_id} was not found.", err=True)
        raise typer.Exit(code=2)
    for key, value in run.items():
        typer.echo(f"{key}: {value}")


@rules_app.command("rebuild")
def rules_rebuild(
    symbols: Annotated[list[str] | None, typer.Option("--symbol", "-s")] = None,
    from_date: Annotated[
        str | None, typer.Option("--from", help="ISO date (YYYY-MM-DD)")
    ] = None,
    to_date: Annotated[
        str | None, typer.Option("--to", help="ISO date (YYYY-MM-DD)")
    ] = None,
) -> None:
    rule_service = dependencies()[7]
    result = asyncio.run(
        rule_service.rebuild(
            symbols=symbols,
            start_date=parse_date(from_date),
            end_date=parse_date(to_date),
        )
    )
    emit_rule_run_result(result)


@rules_app.command("update")
def rules_update(
    symbols: Annotated[list[str] | None, typer.Option("--symbol", "-s")] = None,
    as_of: Annotated[
        str | None, typer.Option("--as-of", help="ISO date (YYYY-MM-DD)")
    ] = None,
) -> None:
    rule_service = dependencies()[7]
    result = asyncio.run(rule_service.update(symbols=symbols, as_of=parse_date(as_of)))
    emit_rule_run_result(result)


@rule_runs_app.command("show")
def show_rule_run(run_id: UUID) -> None:
    rule_run_repository = dependencies()[6]
    run = rule_run_repository.get_rule_run_summary(run_id)
    if run is None:
        typer.echo(f"Rule run {run_id} was not found.", err=True)
        raise typer.Exit(code=2)
    for key, value in run.items():
        typer.echo(f"{key}: {value}")


@strategies_app.command("rebuild")
def strategies_rebuild(
    strategy: Annotated[str, typer.Option("--strategy")] = "Swing Trend Following",
    symbols: Annotated[list[str] | None, typer.Option("--symbol", "-s")] = None,
    from_date: Annotated[str | None, typer.Option("--from")] = None,
    to_date: Annotated[str | None, typer.Option("--to")] = None,
) -> None:
    validate_strategy_name(strategy)
    strategy_service = dependencies()[9]
    result = asyncio.run(strategy_service.rebuild(
        symbols=symbols, start_date=parse_date(from_date), end_date=parse_date(to_date)
    ))
    emit_strategy_run_result(result)


@strategies_app.command("update")
def strategies_update(
    strategy: Annotated[str, typer.Option("--strategy")] = "Swing Trend Following",
    symbols: Annotated[list[str] | None, typer.Option("--symbol", "-s")] = None,
    as_of: Annotated[str | None, typer.Option("--as-of")] = None,
) -> None:
    validate_strategy_name(strategy)
    strategy_service = dependencies()[9]
    result = asyncio.run(strategy_service.update(symbols=symbols, as_of=parse_date(as_of)))
    emit_strategy_run_result(result)


@strategy_runs_app.command("show")
def show_strategy_run(run_id: UUID) -> None:
    strategy_run_repository = dependencies()[8]
    run = strategy_run_repository.get_strategy_run_summary(run_id)
    if run is None:
        typer.echo(f"Strategy run {run_id} was not found.", err=True)
        raise typer.Exit(code=2)
    for key, value in run.items():
        typer.echo(f"{key}: {value}")


@scores_app.command("rebuild")
def scores_rebuild(
    symbols: Annotated[list[str] | None, typer.Option("--symbol", "-s")] = None,
    from_date: Annotated[str | None, typer.Option("--from")] = None,
    to_date: Annotated[str | None, typer.Option("--to")] = None,
) -> None:
    scoring_service = dependencies()[11]
    result = asyncio.run(scoring_service.rebuild(
        symbols=symbols, start_date=parse_date(from_date), end_date=parse_date(to_date)
    ))
    emit_score_run_result(result)


@scores_app.command("update")
def scores_update(
    symbols: Annotated[list[str] | None, typer.Option("--symbol", "-s")] = None,
    as_of: Annotated[str | None, typer.Option("--as-of")] = None,
) -> None:
    scoring_service = dependencies()[11]
    result = asyncio.run(scoring_service.update(symbols=symbols, as_of=parse_date(as_of)))
    emit_score_run_result(result)


@score_runs_app.command("show")
def show_score_run(run_id: UUID) -> None:
    score_run_repository = dependencies()[10]
    run = score_run_repository.get_score_run_summary(run_id)
    if run is None:
        typer.echo(f"Score run {run_id} was not found.", err=True)
        raise typer.Exit(code=2)
    for key, value in run.items():
        typer.echo(f"{key}: {value}")


@rankings_app.command("rebuild")
def rankings_rebuild(
    from_date: Annotated[str | None, typer.Option("--from")] = None,
    to_date: Annotated[str | None, typer.Option("--to")] = None,
) -> None:
    result = asyncio.run(
        dependencies()[13].rebuild(
            start_date=parse_date(from_date), end_date=parse_date(to_date)
        )
    )
    emit_ranking_run_result(result)


@rankings_app.command("update")
def rankings_update(
    as_of: Annotated[str | None, typer.Option("--as-of")] = None,
) -> None:
    result = asyncio.run(dependencies()[13].update(as_of=parse_date(as_of)))
    emit_ranking_run_result(result)


@ranking_runs_app.command("show")
def show_ranking_run(run_id: UUID) -> None:
    run = dependencies()[12].get_ranking_run_summary(run_id)
    if run is None:
        typer.echo(f"Ranking run {run_id} was not found.", err=True)
        raise typer.Exit(code=2)
    for key, value in run.items():
        typer.echo(f"{key}: {value}")


@analyses_app.command("rebuild")
def analyses_rebuild(
    from_date: Annotated[str | None, typer.Option("--from")] = None,
    to_date: Annotated[str | None, typer.Option("--to")] = None,
) -> None:
    result = asyncio.run(dependencies()[15].rebuild(
        start_date=parse_date(from_date), end_date=parse_date(to_date)
    ))
    emit_analysis_run_result(result)


@analyses_app.command("update")
def analyses_update(
    as_of: Annotated[str | None, typer.Option("--as-of")] = None,
) -> None:
    result = asyncio.run(dependencies()[15].update(as_of=parse_date(as_of)))
    emit_analysis_run_result(result)


@analysis_runs_app.command("show")
def show_analysis_run(run_id: UUID) -> None:
    run = dependencies()[14].get_analysis_run_summary(run_id)
    if run is None:
        typer.echo(f"Analysis run {run_id} was not found.", err=True)
        raise typer.Exit(code=2)
    for key, value in run.items():
        typer.echo(f"{key}: {value}")


@alerts_app.command("rebuild")
def alerts_rebuild(
    from_date: Annotated[str | None, typer.Option("--from")] = None,
    to_date: Annotated[str | None, typer.Option("--to")] = None,
) -> None:
    emit_alert_run_result(asyncio.run(dependencies()[17].rebuild(
        start_date=parse_date(from_date), end_date=parse_date(to_date)
    )))


@alerts_app.command("update")
def alerts_update(as_of: Annotated[str | None, typer.Option("--as-of")] = None) -> None:
    emit_alert_run_result(asyncio.run(dependencies()[21].update(as_of=parse_date(as_of))))


@alerts_app.command("retry")
def alerts_retry(limit: Annotated[int, typer.Option(min=1, max=1000)] = 100) -> None:
    emit_alert_run_result(asyncio.run(dependencies()[21].retry(limit=limit)))


@alert_runs_app.command("show")
def show_alert_run(run_id: UUID) -> None:
    run = dependencies()[20].get(run_id)
    if run is None:
        typer.echo(f"Alert run {run_id} was not found.", err=True)
        raise typer.Exit(code=2)
    for key, value in run.items():
        typer.echo(f"{key}: {value}")


@backtests_app.command("run")
def backtests_run(
    strategy: Annotated[str, typer.Option("--strategy")] = "Swing Trend Following",
    from_date: Annotated[str, typer.Option("--from")] = ...,
    to_date: Annotated[str, typer.Option("--to")] = ...,
) -> None:
    validate_strategy_name(strategy)
    result = dependencies()[23].run(
        start_date=parse_date(from_date), end_date=parse_date(to_date)
    )
    typer.echo(f"Backtest {result.run_id}: {result.status.value}; trades={result.metrics.completed_trades}")


@backtests_app.command("list")
def backtests_list(limit: Annotated[int, typer.Option(min=1, max=500)] = 100) -> None:
    for item in dependencies()[22].list_runs(limit):
        typer.echo(f"{item['id']}\t{item['strategy']}\t{item['start_date']}\t{item['end_date']}\t{item['status']}")


@backtests_app.command("show")
def backtests_show(run_id: UUID) -> None:
    item = dependencies()[22].get_run(run_id)
    if item is None:
        raise typer.Exit(code=2)
    for key, value in item.items():
        typer.echo(f"{key}: {value}")


@backtests_app.command("trades")
def backtests_trades(
    run_id: UUID,
    symbol: Annotated[str | None, typer.Option("--symbol", "-s")] = None,
    limit: Annotated[int, typer.Option(min=1, max=500)] = 100,
) -> None:
    for item in dependencies()[22].trades(
        run_id, symbol=normalize_cli_symbol(symbol) if symbol else None, limit=limit
    ):
        typer.echo(f"{item['symbol']}\t{item['signal_date']}\t{item['exit_date']}\t{item['net_return']}")


@optimizations_app.command("run")
def optimizations_run(
    strategy: Annotated[str, typer.Option("--strategy")] = "Swing Trend Following",
    from_date: Annotated[str, typer.Option("--from")] = ...,
    to_date: Annotated[str, typer.Option("--to")] = ...,
) -> None:
    validate_strategy_name(strategy)
    result = dependencies()[25].run(
        start_date=parse_date(from_date), end_date=parse_date(to_date)
    )
    typer.echo(
        f"Optimization {result.run_id}: {result.status.value}; "
        f"candidates={result.candidate_count}; winner={result.winner_id or 'none'}"
    )


@optimizations_app.command("list")
def optimizations_list(
    limit: Annotated[int, typer.Option(min=1, max=500)] = 100,
) -> None:
    for item in dependencies()[24].list_runs(limit):
        typer.echo(
            f"{item['id']}\t{item['strategy']}\t{item['start_date']}\t"
            f"{item['end_date']}\t{item['status']}\t{item['winner_id'] or '-'}"
        )


@optimizations_app.command("show")
def optimizations_show(run_id: UUID) -> None:
    item = dependencies()[24].get_run(run_id)
    if item is None:
        typer.echo(f"Optimization run {run_id} was not found.", err=True)
        raise typer.Exit(code=2)
    for key, value in item.items():
        typer.echo(f"{key}: {value}")


@optimizations_app.command("candidates")
def optimizations_candidates(
    run_id: UUID,
    limit: Annotated[int, typer.Option(min=1, max=500)] = 100,
) -> None:
    for item in dependencies()[24].candidates(run_id, limit=limit):
        typer.echo(
            f"{item['candidate_id']}\t{item['rank'] or '-'}\t"
            f"{item['eligible']}\t{item['parameters']}"
        )


@optimizations_app.command("candidate")
def optimizations_candidate(run_id: UUID, candidate_id: str) -> None:
    item = dependencies()[24].candidate(run_id, candidate_id)
    if item is None:
        typer.echo(
            f"Optimization candidate {candidate_id} was not found in run {run_id}.",
            err=True,
        )
        raise typer.Exit(code=2)
    for key, value in item.items():
        typer.echo(f"{key}: {value}")


def emit_run_result(result) -> None:
    success = sum(item.status.value == "success" for item in result.symbols)
    no_data = sum(item.status.value == "no_new_data" for item in result.symbols)
    failed = result.failed_count
    typer.echo(
        f"Run {result.run_id}: {result.status.value}; "
        f"success={success}, no_data={no_data}, failed={failed}"
    )
    if result.status != RunStatus.SUCCEEDED:
        raise typer.Exit(code=1)


def emit_indicator_run_result(result) -> None:
    success = sum(item.status.value == "success" for item in result.symbols)
    no_data = sum(item.status.value == "no_data" for item in result.symbols)
    failed = result.failed_count
    typer.echo(
        f"Indicator run {result.run_id}: {result.status.value}; "
        f"success={success}, no_data={no_data}, failed={failed}"
    )
    if result.status != IndicatorRunStatus.SUCCEEDED:
        raise typer.Exit(code=1)


def emit_rule_run_result(result) -> None:
    success = sum(item.status.value == "success" for item in result.symbols)
    no_data = sum(item.status.value == "no_data" for item in result.symbols)
    failed = result.failed_count
    typer.echo(
        f"Rule run {result.run_id}: {result.status.value}; "
        f"success={success}, no_data={no_data}, failed={failed}"
    )
    if result.status != RuleRunStatus.SUCCEEDED:
        raise typer.Exit(code=1)


def emit_strategy_run_result(result) -> None:
    success = sum(item.status.value == "success" for item in result.symbols)
    no_data = sum(item.status.value == "no_data" for item in result.symbols)
    failed = result.failed_count
    typer.echo(
        f"Strategy run {result.run_id}: {result.status.value}; "
        f"success={success}, no_data={no_data}, failed={failed}"
    )
    if result.status != StrategyRunStatus.SUCCEEDED:
        raise typer.Exit(code=1)


def emit_score_run_result(result) -> None:
    success = sum(item.status.value == "success" for item in result.symbols)
    no_data = sum(item.status.value == "no_data" for item in result.symbols)
    failed = result.failed_count
    typer.echo(
        f"Score run {result.run_id}: {result.status.value}; "
        f"success={success}, no_data={no_data}, failed={failed}"
    )
    if result.status != ScoreRunStatus.SUCCEEDED:
        raise typer.Exit(code=1)


def emit_ranking_run_result(result) -> None:
    success = sum(item.status.value == "success" for item in result.dates)
    no_data = sum(item.status.value == "no_data" for item in result.dates)
    failed = result.failed_count
    typer.echo(
        f"Ranking run {result.run_id}: {result.status.value}; "
        f"success={success}, no_data={no_data}, failed={failed}"
    )
    if result.status != RankingRunStatus.SUCCEEDED:
        raise typer.Exit(code=1)


def emit_analysis_run_result(result) -> None:
    success = sum(item.status.value == "success" for item in result.symbols)
    no_data = sum(item.status.value == "no_data" for item in result.symbols)
    failed = result.failed_count
    typer.echo(
        f"Analysis run {result.run_id}: {result.status.value}; "
        f"success={success}, no_data={no_data}, failed={failed}"
    )
    if result.status != AnalysisRunStatus.SUCCEEDED:
        raise typer.Exit(code=1)


def emit_alert_run_result(result) -> None:
    typer.echo(
        f"Alert run {result.run_id}: {result.status.value}; generated={result.generated}, "
        f"sent={result.sent}, failed={result.failed}"
    )
    if result.failed:
        raise typer.Exit(code=1)


def validate_strategy_name(value: str) -> None:
    if value.strip().casefold() not in {"swing trend following", "swing-trend-following"}:
        raise typer.BadParameter("only the active Swing Trend Following strategy is supported")


def parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter("must use YYYY-MM-DD") from error


def normalize_cli_symbol(value: str) -> str:
    normalized = value.strip().upper()
    return normalized if normalized.endswith(".JK") else f"{normalized}.JK"


if __name__ == "__main__":
    app()
