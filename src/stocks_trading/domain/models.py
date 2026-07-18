from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID


class RunCommand(StrEnum):
    BOOTSTRAP = "bootstrap"
    UPDATE = "update"
    RETRY = "retry"
    REFRESH = "refresh"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class SymbolStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    NO_NEW_DATA = "no_new_data"
    FAILED = "failed"


class PortfolioTransactionType(StrEnum):
    BUY = "buy"
    SELL = "sell"
    REVERSAL = "reversal"


class IndicatorRunMode(StrEnum):
    REBUILD = "rebuild"
    UPDATE = "update"


class IndicatorRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class IndicatorSymbolStatus(StrEnum):
    SUCCESS = "success"
    NO_DATA = "no_data"
    FAILED = "failed"


class RuleRunMode(StrEnum):
    REBUILD = "rebuild"
    UPDATE = "update"


class RuleRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class RuleSymbolStatus(StrEnum):
    SUCCESS = "success"
    NO_DATA = "no_data"
    FAILED = "failed"


class StrategyRunMode(StrEnum):
    REBUILD = "rebuild"
    UPDATE = "update"


class StrategyRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class StrategySymbolStatus(StrEnum):
    SUCCESS = "success"
    NO_DATA = "no_data"
    FAILED = "failed"


class ScoreRunMode(StrEnum):
    REBUILD = "rebuild"
    UPDATE = "update"


class ScoreRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class ScoreSymbolStatus(StrEnum):
    SUCCESS = "success"
    NO_DATA = "no_data"
    FAILED = "failed"


class RankingRunMode(StrEnum):
    REBUILD = "rebuild"
    UPDATE = "update"


class RankingRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class RankingDateStatus(StrEnum):
    SUCCESS = "success"
    NO_DATA = "no_data"
    FAILED = "failed"


class AnalysisRunMode(StrEnum):
    REBUILD = "rebuild"
    UPDATE = "update"


class AnalysisRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class AnalysisSymbolStatus(StrEnum):
    SUCCESS = "success"
    NO_DATA = "no_data"
    FAILED = "failed"


class RiskRunMode(StrEnum):
    REBUILD = "rebuild"
    UPDATE = "update"


class RiskRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class RiskSymbolStatus(StrEnum):
    SUCCESS = "success"
    NO_DATA = "no_data"
    FAILED = "failed"


class PositionStatus(StrEnum):
    PENDING_ENTRY = "pending_entry"
    OPEN = "open"
    PARTIAL = "partial"
    CLOSED = "closed"


class PositionRunMode(StrEnum):
    REBUILD = "rebuild"
    UPDATE = "update"


class PositionRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PortfolioTransaction:
    id: UUID
    transaction_type: PortfolioTransactionType
    symbol: str
    transaction_date: date
    quantity: Decimal
    price: Decimal
    fee: Decimal
    notes: str | None = None
    reversal_of_id: UUID | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PortfolioHolding:
    symbol: str
    quantity: Decimal
    average_price: Decimal
    cost_basis: Decimal
    latest_close: Decimal | None
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    unrealized_return: Decimal | None
    first_buy_date: date | None
    holding_days: int | None


@dataclass(frozen=True, slots=True)
class PortfolioSummary:
    portfolio_id: UUID
    initial_cash: Decimal
    cash_balance: Decimal
    invested_value: Decimal
    market_value: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal
    total_return: Decimal


class AlertDeliveryStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class AlertRunMode(StrEnum):
    REBUILD = "rebuild"
    UPDATE = "update"
    RETRY = "retry"


class AlertRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class BacktestRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class OptimizationRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Security:
    symbol: str
    idx_code: str
    issuer_name: str
    board: str | None = None
    sector: str | None = None
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class DailyCandle:
    symbol: str
    trading_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Decimal
    volume: int
    provider: str = "yahoo"
    interval: str = "1d"


@dataclass(frozen=True, slots=True)
class CollectionRequest:
    command: RunCommand
    start_date: date
    end_date: date
    symbols: tuple[str, ...]
    parent_run_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class SymbolCollectionResult:
    symbol: str
    status: SymbolStatus
    attempts: int
    rows_received: int = 0
    rows_written: int = 0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CollectionRunResult:
    run_id: UUID
    status: RunStatus
    started_at: datetime
    finished_at: datetime
    symbols: tuple[SymbolCollectionResult, ...] = field(default_factory=tuple)

    @property
    def failed_count(self) -> int:
        return sum(item.status == SymbolStatus.FAILED for item in self.symbols)


@dataclass(frozen=True, slots=True)
class DailyIndicators:
    symbol: str
    trading_date: date
    sma_5: Decimal | None
    sma_10: Decimal | None
    sma_20: Decimal | None
    sma_50: Decimal | None
    sma_200: Decimal | None
    volume_ma_20: Decimal | None
    volume_ratio: Decimal | None
    daily_change_percent: Decimal | None
    atr_14: Decimal | None
    highest_high_20: Decimal | None
    lowest_low_20: Decimal | None
    average_traded_value_20: Decimal | None = None
    rsi_14: Decimal | None = None
    macd: Decimal | None = None
    macd_signal: Decimal | None = None
    macd_histogram: Decimal | None = None
    macd_bullish_crossover: bool | None = None
    higher_low_formed: bool | None = None
    source_updated_at: datetime | None = None
    calculation_version: str = "technical-v2"
    provider: str = "yahoo"
    interval: str = "1d"


@dataclass(frozen=True, slots=True)
class IndicatorRunRequest:
    mode: IndicatorRunMode
    calculation_version: str
    start_date: date | None
    end_date: date | None
    symbols: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IndicatorSymbolResult:
    symbol: str
    status: IndicatorSymbolStatus
    rows_read: int = 0
    rows_written: int = 0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class IndicatorRunResult:
    run_id: UUID
    status: IndicatorRunStatus
    started_at: datetime
    finished_at: datetime
    symbols: tuple[IndicatorSymbolResult, ...] = field(default_factory=tuple)

    @property
    def failed_count(self) -> int:
        return sum(
            item.status == IndicatorSymbolStatus.FAILED for item in self.symbols
        )


@dataclass(frozen=True, slots=True)
class RuleEvaluationInput:
    candle: DailyCandle
    indicators: DailyIndicators
    candle_updated_at: datetime | None = None
    indicator_calculated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DailyRules:
    symbol: str
    trading_date: date
    price_above_ma5: bool | None
    price_above_ma10: bool | None
    price_above_ma20: bool | None
    ma5_above_ma10: bool | None
    ma10_above_ma20: bool | None
    volume_spike: bool | None
    breakout_20: bool | None
    high_liquidity: bool | None
    positive_momentum: bool | None
    formula_version: str
    config_checksum: str
    indicator_version: str
    candle_updated_at: datetime | None = None
    indicator_calculated_at: datetime | None = None
    provider: str = "yahoo"
    interval: str = "1d"
    price_above_ma50: bool | None = None
    ma20_above_ma50: bool | None = None
    ma50_above_ma200: bool | None = None
    pullback_to_ma20: bool | None = None
    rsi_not_overbought: bool | None = None
    rsi_not_oversold: bool | None = None
    macd_bullish_crossover: bool | None = None
    higher_low_formed: bool | None = None
    volume_confirmation: bool | None = None
    ma20_below_ma50: bool | None = None
    rsi_extreme_overbought: bool | None = None


@dataclass(frozen=True, slots=True)
class RuleRunRequest:
    mode: RuleRunMode
    formula_version: str
    config_checksum: str
    indicator_version: str
    start_date: date | None
    end_date: date | None
    symbols: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RuleSymbolResult:
    symbol: str
    status: RuleSymbolStatus
    rows_read: int = 0
    rows_written: int = 0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RuleRunResult:
    run_id: UUID
    status: RuleRunStatus
    started_at: datetime
    finished_at: datetime
    symbols: tuple[RuleSymbolResult, ...] = field(default_factory=tuple)

    @property
    def failed_count(self) -> int:
        return sum(item.status == RuleSymbolStatus.FAILED for item in self.symbols)


@dataclass(frozen=True, slots=True)
class StrategyResult:
    symbol: str
    trading_date: date
    strategy_name: str
    strategy_version: str
    strategy_config_checksum: str
    passed: bool | None
    evaluation_details: dict[str, str]
    source_rule_formula_version: str
    source_rule_config_checksum: str
    source_rule_evaluated_at: datetime | None = None
    provider: str = "yahoo"
    interval: str = "1d"


@dataclass(frozen=True, slots=True)
class StrategyRunRequest:
    mode: StrategyRunMode
    strategy_name: str
    strategy_version: str
    strategy_config_checksum: str
    source_rule_formula_version: str
    source_rule_config_checksum: str
    start_date: date | None
    end_date: date | None
    symbols: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StrategySymbolResult:
    symbol: str
    status: StrategySymbolStatus
    rows_read: int = 0
    rows_written: int = 0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class StrategyRunResult:
    run_id: UUID
    status: StrategyRunStatus
    started_at: datetime
    finished_at: datetime
    symbols: tuple[StrategySymbolResult, ...] = field(default_factory=tuple)

    @property
    def failed_count(self) -> int:
        return sum(
            item.status == StrategySymbolStatus.FAILED for item in self.symbols
        )


@dataclass(frozen=True, slots=True)
class TechnicalScore:
    symbol: str
    trading_date: date
    scoring_version: str
    scoring_config_checksum: str
    score: int | None
    rating: str | None
    contributions: dict[str, dict[str, object]]
    source_rule_formula_version: str
    source_rule_config_checksum: str
    source_rule_evaluated_at: datetime | None = None
    provider: str = "yahoo"
    interval: str = "1d"


@dataclass(frozen=True, slots=True)
class ScoreRunRequest:
    mode: ScoreRunMode
    scoring_version: str
    scoring_config_checksum: str
    source_rule_formula_version: str
    source_rule_config_checksum: str
    start_date: date | None
    end_date: date | None
    symbols: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScoreSymbolResult:
    symbol: str
    status: ScoreSymbolStatus
    rows_read: int = 0
    rows_written: int = 0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ScoreRunResult:
    run_id: UUID
    status: ScoreRunStatus
    started_at: datetime
    finished_at: datetime
    symbols: tuple[ScoreSymbolResult, ...] = field(default_factory=tuple)

    @property
    def failed_count(self) -> int:
        return sum(item.status == ScoreSymbolStatus.FAILED for item in self.symbols)


@dataclass(frozen=True, slots=True)
class DailyRanking:
    symbol: str
    trading_date: date
    rank: int
    score: int
    rating: str
    ranking_version: str
    ranking_config_checksum: str
    source_scoring_version: str
    source_scoring_config_checksum: str
    source_scored_at: datetime | None = None
    provider: str = "yahoo"
    interval: str = "1d"


@dataclass(frozen=True, slots=True)
class RankingRunRequest:
    mode: RankingRunMode
    ranking_version: str
    ranking_config_checksum: str
    source_scoring_version: str
    source_scoring_config_checksum: str
    start_date: date | None
    end_date: date | None
    requested_dates: int


@dataclass(frozen=True, slots=True)
class RankingDateResult:
    trading_date: date
    status: RankingDateStatus
    rows_read: int = 0
    rows_written: int = 0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RankingRunResult:
    run_id: UUID
    status: RankingRunStatus
    started_at: datetime
    finished_at: datetime
    dates: tuple[RankingDateResult, ...] = field(default_factory=tuple)

    @property
    def failed_count(self) -> int:
        return sum(item.status == RankingDateStatus.FAILED for item in self.dates)


@dataclass(frozen=True, slots=True)
class AnalysisInput:
    ranking: DailyRanking
    indicators: DailyIndicators | None
    rules: DailyRules | None
    strategy: StrategyResult | None


@dataclass(frozen=True, slots=True)
class DailyAnalysis:
    symbol: str
    trading_date: date
    analysis_version: str
    analysis_config_checksum: str
    narrative: str
    bullish_reasons: tuple[str, ...]
    caution_reasons: tuple[str, ...]
    source_availability: dict[str, bool]
    strategy_status: str
    score: int
    rating: str
    rank: int
    disclaimer: str
    source_versions: dict[str, str]
    provider: str = "yahoo"
    interval: str = "1d"


@dataclass(frozen=True, slots=True)
class RiskInput:
    ranking: DailyRanking
    close: Decimal
    atr_14: Decimal | None


@dataclass(frozen=True, slots=True)
class DailyRiskRecommendation:
    symbol: str
    trading_date: date
    risk_version: str
    risk_config_checksum: str
    entry_price: Decimal
    atr_14: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    risk_amount: Decimal
    reward_amount: Decimal
    reward_risk_ratio: Decimal
    score: int
    rating: str
    rank: int
    source_indicator_version: str
    source_ranking_version: str
    source_ranking_config_checksum: str
    disclaimer: str
    provider: str = "yahoo"
    interval: str = "1d"
    take_profit_1: Decimal = Decimal("0")
    take_profit_2: Decimal = Decimal("0")
    suggested_position_size_pct: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class VirtualPosition:
    id: UUID
    symbol: str
    strategy_name: str
    strategy_version: str
    lifecycle_version: str
    lifecycle_config_checksum: str
    status: PositionStatus
    signal_date: date
    entry_date: date | None
    exit_date: date | None
    signal_atr: Decimal | None
    entry_price: Decimal | None
    initial_stop: Decimal | None
    active_stop: Decimal | None
    take_profit_1: Decimal | None
    take_profit_2: Decimal | None
    highest_close: Decimal | None
    remaining_fraction: Decimal
    suggested_position_size_pct: Decimal
    holding_sessions: int
    queued_action: str | None
    queued_action_date: date | None
    tp1_filled: bool
    realized_gross_return: Decimal
    realized_net_return: Decimal
    unrealized_return: Decimal | None
    exit_reason: str | None
    average_exit_price: Decimal | None
    last_processed_date: date
    provider: str = "yahoo"
    interval: str = "1d"


@dataclass(frozen=True, slots=True)
class PositionEvent:
    id: UUID
    position_id: UUID
    symbol: str
    trading_date: date
    event_type: str
    price: Decimal | None
    fraction: Decimal | None
    details: dict[str, object]


@dataclass(frozen=True, slots=True)
class PositionSourceDay:
    candle: DailyCandle
    strategy_passed: bool
    atr_14: Decimal | None
    ma20_below_ma50: bool | None
    rsi_extreme_overbought: bool | None
    suggested_position_size_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class PositionRunResult:
    run_id: UUID
    status: PositionRunStatus
    positions: int
    events: int


@dataclass(frozen=True, slots=True)
class RiskRunRequest:
    mode: RiskRunMode
    risk_version: str
    risk_config_checksum: str
    start_date: date | None
    end_date: date | None
    requested_symbols: int


@dataclass(frozen=True, slots=True)
class RiskSymbolResult:
    symbol: str
    trading_date: date
    status: RiskSymbolStatus
    rows_read: int = 0
    rows_written: int = 0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RiskRunResult:
    run_id: UUID
    status: RiskRunStatus
    started_at: datetime
    finished_at: datetime
    symbols: tuple[RiskSymbolResult, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class AnalysisRunRequest:
    mode: AnalysisRunMode
    analysis_version: str
    analysis_config_checksum: str
    start_date: date | None
    end_date: date | None
    requested_symbols: int


@dataclass(frozen=True, slots=True)
class AnalysisSymbolResult:
    symbol: str
    trading_date: date
    status: AnalysisSymbolStatus
    rows_read: int = 0
    rows_written: int = 0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class AnalysisRunResult:
    run_id: UUID
    status: AnalysisRunStatus
    started_at: datetime
    finished_at: datetime
    symbols: tuple[AnalysisSymbolResult, ...] = field(default_factory=tuple)

    @property
    def failed_count(self) -> int:
        return sum(item.status == AnalysisSymbolStatus.FAILED for item in self.symbols)


@dataclass(frozen=True, slots=True)
class AlertSourceState:
    symbol: str
    trading_date: date
    score: int
    rating: str
    rank: int
    strategy_status: str
    breakout_20: bool | None
    volume_spike: bool | None
    bullish_reasons: tuple[str, ...]
    caution_reasons: tuple[str, ...]
    source_versions: dict[str, str]
    ma20_below_ma50: bool | None = None
    close: Decimal | None = None
    stop_loss: Decimal | None = None
    take_profit_1: Decimal | None = None
    take_profit_2: Decimal | None = None
    position_event_types: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AlertEvent:
    id: UUID
    symbol: str
    trading_date: date
    alert_version: str
    alert_config_checksum: str
    triggers: tuple[str, ...]
    message: str
    current_score: int
    previous_score: int | None
    current_rating: str
    previous_rating: str | None
    rank: int
    strategy_status: str
    bullish_reasons: tuple[str, ...]
    caution_reasons: tuple[str, ...]
    source_versions: dict[str, str]
    delivery_status: AlertDeliveryStatus = AlertDeliveryStatus.PENDING
    delivery_attempts: int = 0
    last_error: str | None = None
    sent_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AlertRunResult:
    run_id: UUID
    status: AlertRunStatus
    generated: int
    sent: int
    failed: int


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    symbol: str
    signal_date: date
    exit_date: date
    entry_price: Decimal
    exit_price: Decimal
    gross_return: Decimal
    net_return: Decimal
    buy_fee: Decimal
    sell_fee: Decimal
    gross_profit: Decimal
    net_profit: Decimal
    holding_sessions: int = 1


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    signal_count: int
    completed_trades: int
    unclosed_signals: int
    wins: int
    losses: int
    win_rate: Decimal | None
    average_gross_return: Decimal | None
    average_net_return: Decimal | None
    total_compounded_return: Decimal | None
    gross_profit: Decimal
    gross_loss: Decimal
    profit_factor: Decimal | None
    maximum_drawdown: Decimal | None
    sharpe_ratio: Decimal | None


@dataclass(frozen=True, slots=True)
class BacktestResult:
    trades: tuple[BacktestTrade, ...]
    aggregate: BacktestMetrics
    symbols: dict[str, BacktestMetrics]


@dataclass(frozen=True, slots=True)
class BacktestRunResult:
    run_id: UUID
    status: BacktestRunStatus
    metrics: BacktestMetrics


@dataclass(frozen=True, slots=True)
class OptimizationCandidate:
    candidate_id: str
    parameters: dict[str, object]
    eligible: bool
    ineligible_reason: str | None
    training_metrics: BacktestMetrics
    validation_metrics: BacktestMetrics
    rank: int | None = None


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    candidates: tuple[OptimizationCandidate, ...]
    winner_id: str | None
    training_start: date
    training_end: date
    validation_start: date
    validation_end: date
    winner_backtest: BacktestResult | None


@dataclass(frozen=True, slots=True)
class OptimizationRunResult:
    run_id: UUID
    status: OptimizationRunStatus
    candidate_count: int
    winner_id: str | None
