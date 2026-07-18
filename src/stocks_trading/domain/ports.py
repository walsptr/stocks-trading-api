from collections.abc import Sequence
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from stocks_trading.domain.models import (
    CollectionRequest,
    DailyCandle,
    DailyIndicators,
    IndicatorRunRequest,
    IndicatorSymbolResult,
    DailyRules,
    RuleEvaluationInput,
    RuleRunRequest,
    RuleSymbolResult,
    StrategyResult,
    StrategyRunRequest,
    StrategySymbolResult,
    ScoreRunRequest,
    ScoreSymbolResult,
    DailyRanking,
    RankingDateResult,
    RankingRunRequest,
    AnalysisInput,
    AnalysisRunRequest,
    AnalysisSymbolResult,
    AlertEvent,
    AlertSourceState,
    DailyAnalysis,
    TechnicalScore,
    Security,
    SymbolCollectionResult,
)


class UniverseRepository(Protocol):
    def import_snapshot(
        self,
        *,
        snapshot_date: date,
        checksum: str,
        source: str,
        securities: Sequence[Security],
    ) -> tuple[int, int, int]: ...

    def list_securities(self, *, active_only: bool = False) -> list[Security]: ...


class MarketDataRepository(Protocol):
    def active_symbols(self) -> list[str]: ...

    def latest_trading_date(self, symbol: str) -> date | None: ...

    def upsert_candles(self, candles: Sequence[DailyCandle]) -> int: ...

    def cache_status(self, target_date: date) -> dict[str, object]: ...


class RunRepository(Protocol):
    def create_run(self, request: CollectionRequest) -> UUID: ...

    def record_symbol_result(
        self, run_id: UUID, result: SymbolCollectionResult
    ) -> None: ...

    def finish_run(self, run_id: UUID) -> None: ...

    def failed_symbols(self, run_id: UUID) -> list[str]: ...

    def get_run_summary(self, run_id: UUID) -> dict[str, object] | None: ...

    def abandon_run(self, run_id: UUID) -> None: ...


class MarketDataProvider(Protocol):
    def download(
        self, symbols: Sequence[str], start_date: date, end_date: date
    ) -> dict[str, list[DailyCandle]]: ...


class IndicatorRepository(Protocol):
    def active_symbols(self) -> list[str]: ...

    def load_candles(
        self,
        symbol: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        warmup_sessions: int = 0,
    ) -> list[DailyCandle]: ...

    def latest_indicator_date(
        self, symbol: str, calculation_version: str
    ) -> date | None: ...

    def source_update_times(
        self, symbol: str, trading_dates: Sequence[date]
    ) -> dict[date, datetime]: ...

    def upsert_indicators(self, indicators: Sequence[DailyIndicators]) -> int: ...


class IndicatorRunRepository(Protocol):
    def create_indicator_run(self, request: IndicatorRunRequest) -> UUID: ...

    def record_indicator_symbol_result(
        self, run_id: UUID, result: IndicatorSymbolResult
    ) -> None: ...

    def finish_indicator_run(self, run_id: UUID) -> None: ...

    def abandon_indicator_run(self, run_id: UUID) -> None: ...

    def get_indicator_run_summary(self, run_id: UUID) -> dict[str, object] | None: ...


class RuleRepository(Protocol):
    def active_symbols(self) -> list[str]: ...

    def load_rule_inputs(
        self,
        symbol: str,
        *,
        indicator_version: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[RuleEvaluationInput]: ...

    def latest_rule_date(
        self, symbol: str, formula_version: str, config_checksum: str
    ) -> date | None: ...

    def upsert_rules(self, rules: Sequence[DailyRules]) -> int: ...

    def latest_rules(
        self, symbol: str, formula_version: str, config_checksum: str
    ) -> DailyRules | None: ...

    def rule_history(
        self,
        symbol: str,
        formula_version: str,
        config_checksum: str,
        *,
        limit: int,
        before: date | None,
    ) -> list[DailyRules]: ...


class RuleRunRepository(Protocol):
    def create_rule_run(self, request: RuleRunRequest) -> UUID: ...

    def record_rule_symbol_result(
        self, run_id: UUID, result: RuleSymbolResult
    ) -> None: ...

    def finish_rule_run(self, run_id: UUID) -> None: ...

    def abandon_rule_run(self, run_id: UUID) -> None: ...

    def get_rule_run_summary(self, run_id: UUID) -> dict[str, object] | None: ...


class StrategyRepository(Protocol):
    def active_symbols(self) -> list[str]: ...

    def load_rule_results(
        self,
        symbol: str,
        *,
        formula_version: str,
        config_checksum: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[tuple[object, datetime | None]]: ...

    def latest_strategy_date(
        self,
        symbol: str,
        strategy_name: str,
        strategy_version: str,
        strategy_config_checksum: str,
    ) -> date | None: ...

    def upsert_strategy_results(self, results: Sequence[StrategyResult]) -> int: ...

    def latest_strategy_result(
        self,
        symbol: str,
        strategy_name: str,
        strategy_version: str,
        strategy_config_checksum: str,
    ) -> StrategyResult | None: ...

    def strategy_history(
        self,
        symbol: str,
        strategy_name: str,
        strategy_version: str,
        strategy_config_checksum: str,
        *,
        limit: int,
        before: date | None,
    ) -> list[StrategyResult]: ...


class StrategyRunRepository(Protocol):
    def create_strategy_run(self, request: StrategyRunRequest) -> UUID: ...

    def record_strategy_symbol_result(
        self, run_id: UUID, result: StrategySymbolResult
    ) -> None: ...

    def finish_strategy_run(self, run_id: UUID) -> None: ...

    def abandon_strategy_run(self, run_id: UUID) -> None: ...

    def get_strategy_run_summary(self, run_id: UUID) -> dict[str, object] | None: ...


class ScoreRepository(Protocol):
    def active_symbols(self) -> list[str]: ...

    def load_rule_results(
        self,
        symbol: str,
        *,
        formula_version: str,
        config_checksum: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[tuple[object, datetime | None]]: ...

    def latest_score_date(
        self, symbol: str, scoring_version: str, scoring_config_checksum: str
    ) -> date | None: ...

    def upsert_scores(self, scores: Sequence[TechnicalScore]) -> int: ...

    def latest_score(
        self, symbol: str, scoring_version: str, scoring_config_checksum: str
    ) -> TechnicalScore | None: ...

    def score_history(
        self,
        symbol: str,
        scoring_version: str,
        scoring_config_checksum: str,
        *,
        limit: int,
        before: date | None,
    ) -> list[TechnicalScore]: ...


class ScoreRunRepository(Protocol):
    def create_score_run(self, request: ScoreRunRequest) -> UUID: ...

    def record_score_symbol_result(
        self, run_id: UUID, result: ScoreSymbolResult
    ) -> None: ...

    def finish_score_run(self, run_id: UUID) -> None: ...

    def abandon_score_run(self, run_id: UUID) -> None: ...

    def get_score_run_summary(self, run_id: UUID) -> dict[str, object] | None: ...


class RankingRepository(Protocol):
    def source_score_dates(
        self,
        scoring_version: str,
        scoring_config_checksum: str,
        *,
        start_date: date | None,
        end_date: date | None,
    ) -> list[date]: ...

    def load_scores_for_date(
        self,
        trading_date: date,
        scoring_version: str,
        scoring_config_checksum: str,
    ) -> list[tuple[TechnicalScore, datetime | None]]: ...

    def latest_ranking_date(
        self, ranking_version: str, ranking_config_checksum: str
    ) -> date | None: ...

    def replace_rankings(
        self,
        trading_date: date,
        ranking_version: str,
        ranking_config_checksum: str,
        rankings: Sequence[DailyRanking],
    ) -> int: ...

    def ranking_snapshot(
        self,
        ranking_version: str,
        ranking_config_checksum: str,
        *,
        trading_date: date | None,
        rating: str | None,
        limit: int,
    ) -> tuple[date, list[DailyRanking]] | None: ...


class RankingRunRepository(Protocol):
    def create_ranking_run(self, request: RankingRunRequest) -> UUID: ...

    def record_ranking_date_result(
        self, run_id: UUID, result: RankingDateResult
    ) -> None: ...

    def finish_ranking_run(self, run_id: UUID) -> None: ...

    def abandon_ranking_run(self, run_id: UUID) -> None: ...

    def get_ranking_run_summary(self, run_id: UUID) -> dict[str, object] | None: ...


class AnalysisRepository(Protocol):
    def source_ranking_dates(
        self,
        ranking_version: str,
        ranking_config_checksum: str,
        *,
        start_date: date | None,
        end_date: date | None,
        minimum_score: int,
    ) -> list[date]: ...

    def load_analysis_inputs(
        self,
        trading_date: date,
        *,
        minimum_score: int,
        source_versions: dict[str, str],
    ) -> list[AnalysisInput]: ...

    def latest_analysis_date(
        self, analysis_version: str, analysis_config_checksum: str
    ) -> date | None: ...

    def replace_analyses(
        self,
        trading_date: date,
        analysis_version: str,
        analysis_config_checksum: str,
        analyses: Sequence[DailyAnalysis],
    ) -> int: ...

    def latest_analysis(
        self, symbol: str, analysis_version: str, analysis_config_checksum: str
    ) -> DailyAnalysis | None: ...

    def analysis_history(
        self,
        symbol: str,
        analysis_version: str,
        analysis_config_checksum: str,
        *,
        limit: int,
        before: date | None,
    ) -> list[DailyAnalysis]: ...

    def analysis_snapshot(
        self,
        analysis_version: str,
        analysis_config_checksum: str,
        *,
        trading_date: date | None,
        rating: str | None,
        strategy_status: str | None,
        limit: int,
    ) -> tuple[date, list[DailyAnalysis]] | None: ...


class AnalysisRunRepository(Protocol):
    def create_analysis_run(self, request: AnalysisRunRequest) -> UUID: ...

    def record_analysis_symbol_result(
        self, run_id: UUID, result: AnalysisSymbolResult
    ) -> None: ...

    def finish_analysis_run(self, run_id: UUID) -> None: ...

    def abandon_analysis_run(self, run_id: UUID) -> None: ...

    def get_analysis_run_summary(self, run_id: UUID) -> dict[str, object] | None: ...


class AlertRepository(Protocol):
    def source_dates(self, analysis_version: str, analysis_checksum: str, *, start_date: date | None, end_date: date | None) -> list[date]: ...
    def load_states(self, trading_date: date, source_versions: dict[str, str]) -> list[AlertSourceState]: ...
    def previous_state(self, symbol: str, before: date, source_versions: dict[str, str]) -> AlertSourceState | None: ...
    def save_event(self, event: AlertEvent) -> bool: ...
    def get_watermark(self, version: str, checksum: str) -> date | None: ...
    def set_watermark(self, version: str, checksum: str, trading_date: date) -> None: ...
    def pending_events(self, maximum_attempts: int, limit: int) -> list[AlertEvent]: ...
    def record_delivery(self, alert_id: UUID, *, succeeded: bool, error: str | None) -> None: ...
