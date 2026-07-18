import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from stocks_trading.domain.models import (
    AlertDeliveryStatus,
    AlertRunMode,
    AlertRunStatus,
    BacktestRunStatus,
    OptimizationRunStatus,
    AnalysisRunMode,
    AnalysisRunStatus,
    AnalysisSymbolStatus,
    RiskRunMode,
    RiskRunStatus,
    RiskSymbolStatus,
    PositionStatus,
    PositionRunMode,
    PositionRunStatus,
    PortfolioTransactionType,
    IndicatorRunMode,
    IndicatorRunStatus,
    IndicatorSymbolStatus,
    RuleRunMode,
    RuleRunStatus,
    RuleSymbolStatus,
    RankingDateStatus,
    RankingRunMode,
    RankingRunStatus,
    ScoreRunMode,
    ScoreRunStatus,
    ScoreSymbolStatus,
    StrategyRunMode,
    StrategyRunStatus,
    StrategySymbolStatus,
    RunCommand,
    RunStatus,
    SymbolStatus,
)


class Base(DeclarativeBase):
    pass


def enum_values(enum_class: type[enum.Enum]) -> list[str]:
    return [str(member.value) for member in enum_class]


class UniverseSnapshotModel(Base):
    __tablename__ = "universe_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    source: Mapped[str] = mapped_column(String(512), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SecurityModel(Base):
    __tablename__ = "securities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    idx_code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    issuer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    board: Mapped[str | None] = mapped_column(String(64))
    sector: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    first_seen_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("universe_snapshots.id"), nullable=False
    )
    last_seen_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("universe_snapshots.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    daily_prices: Mapped[list["DailyPriceModel"]] = relationship(
        back_populates="security", cascade="all, delete-orphan"
    )


class DailyPriceModel(Base):
    __tablename__ = "daily_prices"
    __table_args__ = (
        UniqueConstraint(
            "security_id",
            "provider",
            "interval",
            "trading_date",
            name="uq_daily_price_identity",
        ),
        Index("ix_daily_prices_trading_date", "trading_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    security_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("securities.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[str] = mapped_column(String(16), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    adjusted_close: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    security: Mapped[SecurityModel] = relationship(back_populates="daily_prices")


class CollectionRunModel(Base):
    __tablename__ = "collection_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    command: Mapped[RunCommand] = mapped_column(
        Enum(
            RunCommand,
            name="run_command",
            values_callable=enum_values,
            native_enum=True,
        ),
        nullable=False,
    )
    status: Mapped[RunStatus] = mapped_column(
        Enum(
            RunStatus,
            name="run_status",
            values_callable=enum_values,
            native_enum=True,
        ),
        nullable=False,
        default=RunStatus.RUNNING,
    )
    requested_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    requested_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    requested_symbols: Mapped[int] = mapped_column(Integer, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    no_data_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collection_runs.id")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    symbol_results: Mapped[list["CollectionSymbolResultModel"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class CollectionSymbolResultModel(Base):
    __tablename__ = "collection_symbol_results"
    __table_args__ = (
        UniqueConstraint("run_id", "symbol", name="uq_collection_run_symbol"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collection_runs.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[SymbolStatus] = mapped_column(
        Enum(
            SymbolStatus,
            name="symbol_status",
            values_callable=enum_values,
            native_enum=True,
        ),
        nullable=False,
        default=SymbolStatus.PENDING,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped[CollectionRunModel] = relationship(back_populates="symbol_results")


class DailyIndicatorModel(Base):
    __tablename__ = "daily_indicators"
    __table_args__ = (
        UniqueConstraint(
            "security_id",
            "provider",
            "interval",
            "trading_date",
            "calculation_version",
            name="uq_daily_indicator_identity",
        ),
        Index(
            "ix_daily_indicators_security_date",
            "security_id",
            "trading_date",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    security_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("securities.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[str] = mapped_column(String(16), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(64), nullable=False)
    sma_5: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    sma_10: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    sma_20: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    sma_50: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    sma_200: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    volume_ma_20: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    volume_ratio: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    daily_change_percent: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    atr_14: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    rsi_14: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    macd: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    macd_signal: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    macd_histogram: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    macd_bullish_crossover: Mapped[bool | None] = mapped_column(Boolean)
    higher_low_formed: Mapped[bool | None] = mapped_column(Boolean)
    highest_high_20: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    lowest_low_20: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    average_traded_value_20: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IndicatorRunModel(Base):
    __tablename__ = "indicator_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    mode: Mapped[IndicatorRunMode] = mapped_column(
        Enum(
            IndicatorRunMode,
            name="indicator_run_mode",
            values_callable=enum_values,
            native_enum=True,
        ),
        nullable=False,
    )
    status: Mapped[IndicatorRunStatus] = mapped_column(
        Enum(
            IndicatorRunStatus,
            name="indicator_run_status",
            values_callable=enum_values,
            native_enum=True,
        ),
        nullable=False,
        default=IndicatorRunStatus.RUNNING,
    )
    calculation_version: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_start_date: Mapped[date | None] = mapped_column(Date)
    requested_end_date: Mapped[date | None] = mapped_column(Date)
    requested_symbols: Mapped[int] = mapped_column(Integer, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    no_data_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    symbol_results: Mapped[list["IndicatorSymbolResultModel"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class IndicatorSymbolResultModel(Base):
    __tablename__ = "indicator_symbol_results"
    __table_args__ = (
        UniqueConstraint("run_id", "symbol", name="uq_indicator_run_symbol"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("indicator_runs.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[IndicatorSymbolStatus] = mapped_column(
        Enum(
            IndicatorSymbolStatus,
            name="indicator_symbol_status",
            values_callable=enum_values,
            native_enum=True,
        ),
        nullable=False,
    )
    rows_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped[IndicatorRunModel] = relationship(back_populates="symbol_results")


class DailyRuleModel(Base):
    __tablename__ = "daily_rules"
    __table_args__ = (
        UniqueConstraint(
            "security_id",
            "provider",
            "interval",
            "trading_date",
            "formula_version",
            "config_checksum",
            name="uq_daily_rule_identity",
        ),
        Index("ix_daily_rules_security_date", "security_id", "trading_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    security_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("securities.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[str] = mapped_column(String(16), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    formula_version: Mapped[str] = mapped_column(String(64), nullable=False)
    config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    indicator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    price_above_ma5: Mapped[bool | None] = mapped_column(Boolean)
    price_above_ma10: Mapped[bool | None] = mapped_column(Boolean)
    price_above_ma20: Mapped[bool | None] = mapped_column(Boolean)
    ma5_above_ma10: Mapped[bool | None] = mapped_column(Boolean)
    ma10_above_ma20: Mapped[bool | None] = mapped_column(Boolean)
    volume_spike: Mapped[bool | None] = mapped_column(Boolean)
    breakout_20: Mapped[bool | None] = mapped_column(Boolean)
    high_liquidity: Mapped[bool | None] = mapped_column(Boolean)
    positive_momentum: Mapped[bool | None] = mapped_column(Boolean)
    price_above_ma50: Mapped[bool | None] = mapped_column(Boolean)
    ma20_above_ma50: Mapped[bool | None] = mapped_column(Boolean)
    ma50_above_ma200: Mapped[bool | None] = mapped_column(Boolean)
    pullback_to_ma20: Mapped[bool | None] = mapped_column(Boolean)
    rsi_not_overbought: Mapped[bool | None] = mapped_column(Boolean)
    rsi_not_oversold: Mapped[bool | None] = mapped_column(Boolean)
    macd_bullish_crossover: Mapped[bool | None] = mapped_column(Boolean)
    higher_low_formed: Mapped[bool | None] = mapped_column(Boolean)
    volume_confirmation: Mapped[bool | None] = mapped_column(Boolean)
    ma20_below_ma50: Mapped[bool | None] = mapped_column(Boolean)
    rsi_extreme_overbought: Mapped[bool | None] = mapped_column(Boolean)
    candle_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    indicator_calculated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RuleRunModel(Base):
    __tablename__ = "rule_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    mode: Mapped[RuleRunMode] = mapped_column(
        Enum(
            RuleRunMode,
            name="rule_run_mode",
            values_callable=enum_values,
            native_enum=True,
        ),
        nullable=False,
    )
    status: Mapped[RuleRunStatus] = mapped_column(
        Enum(
            RuleRunStatus,
            name="rule_run_status",
            values_callable=enum_values,
            native_enum=True,
        ),
        nullable=False,
        default=RuleRunStatus.RUNNING,
    )
    formula_version: Mapped[str] = mapped_column(String(64), nullable=False)
    config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    indicator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_start_date: Mapped[date | None] = mapped_column(Date)
    requested_end_date: Mapped[date | None] = mapped_column(Date)
    requested_symbols: Mapped[int] = mapped_column(Integer, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    no_data_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    symbol_results: Mapped[list["RuleSymbolResultModel"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class RuleSymbolResultModel(Base):
    __tablename__ = "rule_symbol_results"
    __table_args__ = (
        UniqueConstraint("run_id", "symbol", name="uq_rule_run_symbol"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_runs.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[RuleSymbolStatus] = mapped_column(
        Enum(
            RuleSymbolStatus,
            name="rule_symbol_status",
            values_callable=enum_values,
            native_enum=True,
        ),
        nullable=False,
    )
    rows_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    run: Mapped[RuleRunModel] = relationship(back_populates="symbol_results")


class DailyStrategyResultModel(Base):
    __tablename__ = "daily_strategy_results"
    __table_args__ = (
        UniqueConstraint(
            "security_id", "provider", "interval", "trading_date",
            "strategy_name", "strategy_version", "strategy_config_checksum",
            name="uq_daily_strategy_result_identity",
        ),
        Index("ix_daily_strategy_results_security_date", "security_id", "trading_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    security_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("securities.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[str] = mapped_column(String(16), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    passed: Mapped[bool | None] = mapped_column(Boolean)
    evaluation_details: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    source_rule_formula_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_rule_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    source_rule_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StrategyRunModel(Base):
    __tablename__ = "strategy_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mode: Mapped[StrategyRunMode] = mapped_column(
        Enum(StrategyRunMode, name="strategy_run_mode", values_callable=enum_values, native_enum=True),
        nullable=False,
    )
    status: Mapped[StrategyRunStatus] = mapped_column(
        Enum(StrategyRunStatus, name="strategy_run_status", values_callable=enum_values, native_enum=True),
        nullable=False, default=StrategyRunStatus.RUNNING,
    )
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    source_rule_formula_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_rule_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_start_date: Mapped[date | None] = mapped_column(Date)
    requested_end_date: Mapped[date | None] = mapped_column(Date)
    requested_symbols: Mapped[int] = mapped_column(Integer, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    no_data_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    symbol_results: Mapped[list["StrategySymbolResultModel"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class StrategySymbolResultModel(Base):
    __tablename__ = "strategy_symbol_results"
    __table_args__ = (UniqueConstraint("run_id", "symbol", name="uq_strategy_run_symbol"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy_runs.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[StrategySymbolStatus] = mapped_column(
        Enum(StrategySymbolStatus, name="strategy_symbol_status", values_callable=enum_values, native_enum=True),
        nullable=False,
    )
    rows_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    run: Mapped[StrategyRunModel] = relationship(back_populates="symbol_results")


class DailyTechnicalScoreModel(Base):
    __tablename__ = "daily_technical_scores"
    __table_args__ = (
        UniqueConstraint(
            "security_id", "provider", "interval", "trading_date",
            "scoring_version", "scoring_config_checksum",
            name="uq_daily_technical_score_identity",
        ),
        Index("ix_daily_technical_scores_security_date", "security_id", "trading_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    security_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("securities.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[str] = mapped_column(String(16), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(64), nullable=False)
    scoring_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[int | None] = mapped_column(Integer)
    rating: Mapped[str | None] = mapped_column(String(32))
    contributions: Mapped[dict[str, dict[str, object]]] = mapped_column(JSON, nullable=False)
    source_rule_formula_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_rule_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    source_rule_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ScoreRunModel(Base):
    __tablename__ = "score_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mode: Mapped[ScoreRunMode] = mapped_column(
        Enum(ScoreRunMode, name="score_run_mode", values_callable=enum_values, native_enum=True), nullable=False
    )
    status: Mapped[ScoreRunStatus] = mapped_column(
        Enum(ScoreRunStatus, name="score_run_status", values_callable=enum_values, native_enum=True),
        nullable=False, default=ScoreRunStatus.RUNNING,
    )
    scoring_version: Mapped[str] = mapped_column(String(64), nullable=False)
    scoring_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    source_rule_formula_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_rule_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_start_date: Mapped[date | None] = mapped_column(Date)
    requested_end_date: Mapped[date | None] = mapped_column(Date)
    requested_symbols: Mapped[int] = mapped_column(Integer, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    no_data_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    symbol_results: Mapped[list["ScoreSymbolResultModel"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class ScoreSymbolResultModel(Base):
    __tablename__ = "score_symbol_results"
    __table_args__ = (UniqueConstraint("run_id", "symbol", name="uq_score_run_symbol"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("score_runs.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[ScoreSymbolStatus] = mapped_column(
        Enum(ScoreSymbolStatus, name="score_symbol_status", values_callable=enum_values, native_enum=True), nullable=False
    )
    rows_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    run: Mapped[ScoreRunModel] = relationship(back_populates="symbol_results")


class DailyRankingModel(Base):
    __tablename__ = "daily_rankings"
    __table_args__ = (
        UniqueConstraint(
            "security_id", "provider", "interval", "trading_date",
            "ranking_version", "ranking_config_checksum",
            name="uq_daily_ranking_identity",
        ),
        Index(
            "ix_daily_rankings_snapshot",
            "ranking_version", "ranking_config_checksum", "trading_date", "rank",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    security_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("securities.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[str] = mapped_column(String(16), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    ranking_version: Mapped[str] = mapped_column(String(64), nullable=False)
    ranking_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    rating: Mapped[str] = mapped_column(String(32), nullable=False)
    source_scoring_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_scoring_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    source_scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ranked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RankingRunModel(Base):
    __tablename__ = "ranking_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    mode: Mapped[RankingRunMode] = mapped_column(
        Enum(RankingRunMode, name="ranking_run_mode", values_callable=enum_values, native_enum=True),
        nullable=False,
    )
    status: Mapped[RankingRunStatus] = mapped_column(
        Enum(RankingRunStatus, name="ranking_run_status", values_callable=enum_values, native_enum=True),
        nullable=False, default=RankingRunStatus.RUNNING,
    )
    ranking_version: Mapped[str] = mapped_column(String(64), nullable=False)
    ranking_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    source_scoring_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_scoring_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_start_date: Mapped[date | None] = mapped_column(Date)
    requested_end_date: Mapped[date | None] = mapped_column(Date)
    requested_dates: Mapped[int] = mapped_column(Integer, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    no_data_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    date_results: Mapped[list["RankingDateResultModel"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class RankingDateResultModel(Base):
    __tablename__ = "ranking_date_results"
    __table_args__ = (
        UniqueConstraint("run_id", "trading_date", name="uq_ranking_run_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ranking_runs.id"), nullable=False
    )
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[RankingDateStatus] = mapped_column(
        Enum(RankingDateStatus, name="ranking_date_status", values_callable=enum_values, native_enum=True),
        nullable=False,
    )
    rows_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    run: Mapped[RankingRunModel] = relationship(back_populates="date_results")


class DailyAnalysisModel(Base):
    __tablename__ = "daily_analyses"
    __table_args__ = (
        UniqueConstraint(
            "security_id", "provider", "interval", "trading_date",
            "analysis_version", "analysis_config_checksum",
            name="uq_daily_analysis_identity",
        ),
        Index(
            "ix_daily_analyses_snapshot",
            "analysis_version", "analysis_config_checksum", "trading_date", "rank",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    security_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("securities.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[str] = mapped_column(String(16), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    analysis_version: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    bullish_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    caution_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_availability: Mapped[dict[str, bool]] = mapped_column(JSON, nullable=False)
    strategy_status: Mapped[str] = mapped_column(String(16), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    rating: Mapped[str] = mapped_column(String(32), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    disclaimer: Mapped[str] = mapped_column(Text, nullable=False)
    source_versions: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AnalysisRunModel(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    mode: Mapped[AnalysisRunMode] = mapped_column(
        Enum(AnalysisRunMode, name="analysis_run_mode", values_callable=enum_values, native_enum=True),
        nullable=False,
    )
    status: Mapped[AnalysisRunStatus] = mapped_column(
        Enum(AnalysisRunStatus, name="analysis_run_status", values_callable=enum_values, native_enum=True),
        nullable=False, default=AnalysisRunStatus.RUNNING,
    )
    analysis_version: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_start_date: Mapped[date | None] = mapped_column(Date)
    requested_end_date: Mapped[date | None] = mapped_column(Date)
    requested_symbols: Mapped[int] = mapped_column(Integer, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    no_data_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    symbol_results: Mapped[list["AnalysisSymbolResultModel"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class AnalysisSymbolResultModel(Base):
    __tablename__ = "analysis_symbol_results"
    __table_args__ = (
        UniqueConstraint("run_id", "symbol", "trading_date", name="uq_analysis_run_symbol_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_runs.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[AnalysisSymbolStatus] = mapped_column(
        Enum(AnalysisSymbolStatus, name="analysis_symbol_status", values_callable=enum_values, native_enum=True),
        nullable=False,
    )
    rows_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    run: Mapped[AnalysisRunModel] = relationship(back_populates="symbol_results")


class DailyRiskRecommendationModel(Base):
    __tablename__ = "daily_risk_recommendations"
    __table_args__ = (
        UniqueConstraint(
            "security_id", "provider", "interval", "trading_date",
            "risk_version", "risk_config_checksum",
            name="uq_daily_risk_recommendation_identity",
        ),
        Index(
            "ix_daily_risk_recommendations_snapshot",
            "risk_version", "risk_config_checksum", "trading_date", "rank",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    security_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("securities.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[str] = mapped_column(String(16), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    risk_version: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    atr_14: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    stop_loss: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    take_profit: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    take_profit_1: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    take_profit_2: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    risk_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    reward_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    reward_risk_ratio: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    suggested_position_size_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    rating: Mapped[str] = mapped_column(String(32), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    source_indicator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_ranking_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_ranking_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    disclaimer: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class VirtualPositionModel(Base):
    __tablename__ = "virtual_positions"
    __table_args__ = (
        Index("ix_virtual_positions_status_symbol", "status", "symbol"),
        Index("ix_virtual_positions_symbol_signal", "symbol", "signal_date"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[str] = mapped_column(String(16), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle_version: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[PositionStatus] = mapped_column(Enum(PositionStatus, name="position_status", values_callable=enum_values, native_enum=True), nullable=False)
    signal_date: Mapped[date] = mapped_column(Date, nullable=False)
    entry_date: Mapped[date | None] = mapped_column(Date)
    exit_date: Mapped[date | None] = mapped_column(Date)
    signal_atr: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    initial_stop: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    active_stop: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    take_profit_1: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    take_profit_2: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    highest_close: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    remaining_fraction: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    suggested_position_size_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    holding_sessions: Mapped[int] = mapped_column(Integer, nullable=False)
    queued_action: Mapped[str | None] = mapped_column(String(32))
    queued_action_date: Mapped[date | None] = mapped_column(Date)
    tp1_filled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    realized_gross_return: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    realized_net_return: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    unrealized_return: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    exit_reason: Mapped[str | None] = mapped_column(String(32))
    average_exit_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    last_processed_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PositionEventModel(Base):
    __tablename__ = "position_events"
    __table_args__ = (Index("ix_position_events_position_date", "position_id", "trading_date"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    position_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("virtual_positions.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    fraction: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    details: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PositionRunModel(Base):
    __tablename__ = "position_runs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mode: Mapped[PositionRunMode] = mapped_column(Enum(PositionRunMode, name="position_run_mode", values_callable=enum_values, native_enum=True), nullable=False)
    status: Mapped[PositionRunStatus] = mapped_column(Enum(PositionRunStatus, name="position_run_status", values_callable=enum_values, native_enum=True), nullable=False)
    lifecycle_version: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    positions_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    events_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PortfolioModel(Base):
    __tablename__ = "portfolios"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    initial_cash: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PortfolioTransactionModel(Base):
    __tablename__ = "portfolio_transactions"
    __table_args__ = (
        Index("ix_portfolio_transactions_date", "portfolio_id", "transaction_date", "id"),
        UniqueConstraint("reversal_of_id", name="uq_portfolio_transaction_reversal"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("portfolios.id"), nullable=False)
    transaction_type: Mapped[PortfolioTransactionType] = mapped_column(Enum(PortfolioTransactionType, name="portfolio_transaction_type", values_callable=enum_values, native_enum=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("portfolio_transactions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RiskRunModel(Base):
    __tablename__ = "risk_runs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mode: Mapped[RiskRunMode] = mapped_column(Enum(RiskRunMode, name="risk_run_mode", values_callable=enum_values, native_enum=True), nullable=False)
    status: Mapped[RiskRunStatus] = mapped_column(Enum(RiskRunStatus, name="risk_run_status", values_callable=enum_values, native_enum=True), nullable=False, default=RiskRunStatus.RUNNING)
    risk_version: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_start_date: Mapped[date | None] = mapped_column(Date)
    requested_end_date: Mapped[date | None] = mapped_column(Date)
    requested_symbols: Mapped[int] = mapped_column(Integer, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    no_data_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    symbol_results: Mapped[list["RiskSymbolResultModel"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class RiskSymbolResultModel(Base):
    __tablename__ = "risk_symbol_results"
    __table_args__ = (UniqueConstraint("run_id", "symbol", "trading_date", name="uq_risk_run_symbol_date"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("risk_runs.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[RiskSymbolStatus] = mapped_column(Enum(RiskSymbolStatus, name="risk_symbol_status", values_callable=enum_values, native_enum=True), nullable=False)
    rows_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    run: Mapped[RiskRunModel] = relationship(back_populates="symbol_results")


class AlertEventModel(Base):
    __tablename__ = "alert_events"
    __table_args__ = (
        UniqueConstraint("symbol", "trading_date", "alert_version", "alert_config_checksum", name="uq_alert_event_identity"),
        Index("ix_alert_events_date_status", "trading_date", "delivery_status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    alert_version: Mapped[str] = mapped_column(String(64), nullable=False)
    alert_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    triggers: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    current_score: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_score: Mapped[int | None] = mapped_column(Integer)
    current_rating: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_rating: Mapped[str | None] = mapped_column(String(32))
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy_status: Mapped[str] = mapped_column(String(16), nullable=False)
    bullish_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    caution_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_versions: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    delivery_status: Mapped[AlertDeliveryStatus] = mapped_column(
        Enum(AlertDeliveryStatus, name="alert_delivery_status", values_callable=enum_values, native_enum=True), nullable=False
    )
    delivery_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AlertDeliveryAttemptModel(Base):
    __tablename__ = "alert_delivery_attempts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    alert_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("alert_events.id"), nullable=False)
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AlertWatermarkModel(Base):
    __tablename__ = "alert_watermarks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    alert_version: Mapped[str] = mapped_column(String(64), nullable=False)
    alert_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    last_processed_date: Mapped[date] = mapped_column(Date, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AlertRunModel(Base):
    __tablename__ = "alert_runs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mode: Mapped[AlertRunMode] = mapped_column(Enum(AlertRunMode, name="alert_run_mode", values_callable=enum_values, native_enum=True), nullable=False)
    status: Mapped[AlertRunStatus] = mapped_column(Enum(AlertRunStatus, name="alert_run_status", values_callable=enum_values, native_enum=True), nullable=False)
    generated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BacktestRunModel(Base):
    __tablename__ = "backtest_runs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[BacktestRunStatus] = mapped_column(Enum(BacktestRunStatus, name="backtest_run_status", values_callable=enum_values, native_enum=True), nullable=False)
    backtest_version: Mapped[str] = mapped_column(String(64), nullable=False)
    backtest_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    metrics: Mapped[dict[str, object] | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BacktestTradeModel(Base):
    __tablename__ = "backtest_trades"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("backtest_runs.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    signal_date: Mapped[date] = mapped_column(Date, nullable=False)
    exit_date: Mapped[date] = mapped_column(Date, nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    exit_price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    gross_return: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    net_return: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    buy_fee: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    sell_fee: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    gross_profit: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    net_profit: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    holding_sessions: Mapped[int] = mapped_column(Integer, nullable=False)


class BacktestSymbolMetricModel(Base):
    __tablename__ = "backtest_symbol_metrics"
    __table_args__ = (UniqueConstraint("run_id", "symbol", name="uq_backtest_symbol_metric"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("backtest_runs.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    metrics: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class OptimizationRunModel(Base):
    __tablename__ = "optimization_runs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[OptimizationRunStatus] = mapped_column(Enum(OptimizationRunStatus, name="optimization_run_status", values_callable=enum_values, native_enum=True), nullable=False)
    optimization_version: Mapped[str] = mapped_column(String(64), nullable=False)
    optimization_config_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    training_start: Mapped[date] = mapped_column(Date, nullable=False)
    training_end: Mapped[date] = mapped_column(Date, nullable=False)
    validation_start: Mapped[date] = mapped_column(Date, nullable=False)
    validation_end: Mapped[date] = mapped_column(Date, nullable=False)
    winner_id: Mapped[str | None] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OptimizationCandidateModel(Base):
    __tablename__ = "optimization_candidates"
    __table_args__ = (UniqueConstraint("run_id", "candidate_id", name="uq_optimization_candidate"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("optimization_runs.id"), nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(16), nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ineligible_reason: Mapped[str | None] = mapped_column(String(64))
    rank: Mapped[int | None] = mapped_column(Integer)
    training_metrics: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    validation_metrics: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class OptimizationWinnerTradeModel(Base):
    __tablename__ = "optimization_winner_trades"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("optimization_runs.id"), nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    signal_date: Mapped[date] = mapped_column(Date, nullable=False)
    exit_date: Mapped[date] = mapped_column(Date, nullable=False)
    trade: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class OptimizationWinnerSymbolModel(Base):
    __tablename__ = "optimization_winner_symbols"
    __table_args__ = (UniqueConstraint("run_id", "symbol", name="uq_optimization_winner_symbol"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("optimization_runs.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    metrics: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class ResearchJobModel(Base):
    __tablename__ = "research_jobs"
    __table_args__ = (Index("ix_research_jobs_started_at", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False, default="queued")
    message: Mapped[str] = mapped_column(String(255), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
