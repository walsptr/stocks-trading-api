from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased, sessionmaker

from stocks_trading.domain.models import (
    AlertDeliveryStatus,
    AlertEvent,
    AlertRunMode,
    AlertRunStatus,
    AlertSourceState,
    BacktestMetrics,
    BacktestResult,
    BacktestRunStatus,
    BacktestTrade,
    OptimizationResult,
    OptimizationRunStatus,
    CollectionRequest,
    AnalysisInput,
    AnalysisRunRequest,
    AnalysisRunStatus,
    AnalysisSymbolResult,
    AnalysisSymbolStatus,
    DailyCandle,
    DailyAnalysis,
    DailyIndicators,
    DailyRules,
    IndicatorRunRequest,
    IndicatorRunStatus,
    IndicatorSymbolResult,
    IndicatorSymbolStatus,
    RuleEvaluationInput,
    RuleRunRequest,
    RuleRunStatus,
    RuleSymbolResult,
    RuleSymbolStatus,
    DailyRanking,
    DailyRiskRecommendation,
    RiskInput,
    RiskRunRequest,
    RiskRunStatus,
    RiskSymbolResult,
    RiskSymbolStatus,
    PositionEvent,
    PositionRunMode,
    PositionRunResult,
    PositionRunStatus,
    PositionSourceDay,
    PositionStatus,
    PortfolioTransaction,
    PortfolioTransactionType,
    VirtualPosition,
    RankingDateResult,
    RankingDateStatus,
    RankingRunRequest,
    RankingRunStatus,
    ScoreRunRequest,
    ScoreRunStatus,
    ScoreSymbolResult,
    ScoreSymbolStatus,
    StrategyResult,
    StrategyRunRequest,
    StrategyRunStatus,
    StrategySymbolResult,
    StrategySymbolStatus,
    RunStatus,
    Security,
    SymbolCollectionResult,
    SymbolStatus,
    TechnicalScore,
)
from stocks_trading.persistence.database import session_scope
from stocks_trading.persistence.models import (
    AlertDeliveryAttemptModel,
    AlertEventModel,
    AlertRunModel,
    AlertWatermarkModel,
    BacktestRunModel,
    BacktestSymbolMetricModel,
    BacktestTradeModel,
    OptimizationCandidateModel,
    OptimizationRunModel,
    OptimizationWinnerSymbolModel,
    OptimizationWinnerTradeModel,
    ResearchJobModel,
    HistoricalBackfillJobModel,
    HistoricalBackfillSymbolModel,
    FundamentalRunModel,
    FundamentalSnapshotModel,
    CombinedSyncRunModel,
    CollectionRunModel,
    AnalysisRunModel,
    AnalysisSymbolResultModel,
    DailyAnalysisModel,
    CollectionSymbolResultModel,
    DailyIndicatorModel,
    DailyPriceModel,
    DailyRuleModel,
    DailyRankingModel,
    DailyRiskRecommendationModel,
    DailyTechnicalScoreModel,
    DailyStrategyResultModel,
    IndicatorRunModel,
    IndicatorSymbolResultModel,
    RuleRunModel,
    RuleSymbolResultModel,
    RankingDateResultModel,
    RankingRunModel,
    RiskRunModel,
    RiskSymbolResultModel,
    PositionEventModel,
    PositionRunModel,
    VirtualPositionModel,
    PortfolioModel,
    PortfolioTransactionModel,
    ScoreRunModel,
    ScoreSymbolResultModel,
    StrategyRunModel,
    StrategySymbolResultModel,
    SecurityModel,
    UniverseSnapshotModel,
)


class SqlAlchemyFundamentalRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def active_securities(self, symbols: list[str] | None = None) -> list[dict[str, object]]:
        with session_scope(self.session_factory) as session:
            statement = select(SecurityModel.id, SecurityModel.symbol, SecurityModel.sector).where(SecurityModel.is_active.is_(True))
            if symbols:
                statement = statement.where(SecurityModel.symbol.in_(symbols))
            return [dict(row._mapping) for row in session.execute(statement.order_by(SecurityModel.symbol))]

    def create_run(self, version: str, checksum: str, requested_symbols: int) -> UUID:
        with session_scope(self.session_factory) as session:
            run = FundamentalRunModel(
                calculation_version=version, config_checksum=checksum,
                status="running", requested_symbols=requested_symbols,
            )
            session.add(run)
            session.flush()
            return run.id

    def finish_run(self, run_id: UUID, *, success: int, insufficient: int, failed: int, error: str | None = None) -> None:
        status = "succeeded" if failed == 0 else "partial_failure" if success + insufficient else "failed"
        with session_scope(self.session_factory) as session:
            session.execute(update(FundamentalRunModel).where(FundamentalRunModel.id == run_id).values(
                status=status, success_count=success, insufficient_count=insufficient,
                failure_count=failed, error=error, finished_at=datetime.now(UTC),
            ))

    def save_snapshots(self, rows: list[dict[str, object]]) -> int:
        if not rows:
            return 0
        with session_scope(self.session_factory) as session:
            statement = insert(FundamentalSnapshotModel).values(rows)
            statement = statement.on_conflict_do_update(
                constraint="uq_fundamental_snapshot_identity",
                set_={key: getattr(statement.excluded, key) for key in rows[0] if key not in {"security_id", "fundamental_data_as_of", "calculation_version", "config_checksum"}},
            )
            session.execute(statement)
            return len(rows)

    def latest_snapshot_date(self, version: str, checksum: str) -> date | None:
        with session_scope(self.session_factory) as session:
            return session.scalar(select(func.max(FundamentalSnapshotModel.fundamental_data_as_of)).where(
                FundamentalSnapshotModel.calculation_version == version,
                FundamentalSnapshotModel.config_checksum == checksum,
            ))

    def ranking_page(self, *, view: str, version: str, checksum: str, technical_version: str,
                     technical_checksum: str, technical_weight: Decimal, fundamental_weight: Decimal,
                     limit: int, offset: int, rating: str | None = None):
        with session_scope(self.session_factory) as session:
            fundamental_date = self.latest_snapshot_date(version, checksum)
            if fundamental_date is None:
                return None
            fundamental = aliased(FundamentalSnapshotModel)
            latest_fundamental = select(
                FundamentalSnapshotModel.security_id,
                func.max(FundamentalSnapshotModel.fundamental_data_as_of).label("latest_date"),
            ).where(
                FundamentalSnapshotModel.calculation_version == version,
                FundamentalSnapshotModel.config_checksum == checksum,
            ).group_by(FundamentalSnapshotModel.security_id).subquery()
            latest_conditions = [
                fundamental.security_id == latest_fundamental.c.security_id,
                fundamental.fundamental_data_as_of == latest_fundamental.c.latest_date,
                fundamental.calculation_version == version,
                fundamental.config_checksum == checksum,
                fundamental.fundamental_score.is_not(None),
                fundamental.data_status.in_(("complete", "partial")),
            ]
            if view == "fundamental":
                total = session.scalar(select(func.count()).select_from(fundamental).join(latest_fundamental, fundamental.security_id == latest_fundamental.c.security_id).where(*latest_conditions)) or 0
                rows = session.execute(select(fundamental, SecurityModel.symbol).join(latest_fundamental, fundamental.security_id == latest_fundamental.c.security_id).join(SecurityModel).where(*latest_conditions)
                    .order_by(fundamental.fundamental_score.desc(), SecurityModel.symbol).offset(offset).limit(limit)).all()
                return fundamental_date, None, rows, total
            technical_date = session.scalar(select(func.max(DailyTechnicalScoreModel.trading_date)).where(
                DailyTechnicalScoreModel.scoring_version == technical_version,
                DailyTechnicalScoreModel.scoring_config_checksum == technical_checksum,
            ))
            if technical_date is None:
                return None
            conditions = [
                *latest_conditions,
                fundamental.is_red_flagged.is_(False),
                DailyTechnicalScoreModel.trading_date == technical_date,
                DailyTechnicalScoreModel.scoring_version == technical_version,
                DailyTechnicalScoreModel.scoring_config_checksum == technical_checksum,
                DailyTechnicalScoreModel.score.is_not(None),
            ]
            statement = select(fundamental, DailyTechnicalScoreModel, SecurityModel.symbol).join(
                latest_fundamental, fundamental.security_id == latest_fundamental.c.security_id
            ).join(
                DailyTechnicalScoreModel, DailyTechnicalScoreModel.security_id == fundamental.security_id
            ).join(SecurityModel, SecurityModel.id == fundamental.security_id).where(*conditions)
            total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
            combined = (DailyTechnicalScoreModel.score * technical_weight + fundamental.fundamental_score * fundamental_weight) / 100
            rows = session.execute(statement.order_by(combined.desc(), SecurityModel.symbol).offset(offset).limit(limit)).all()
            return fundamental_date, technical_date, rows, total

    def latest_for_symbol(self, symbol: str, version: str, checksum: str):
        with session_scope(self.session_factory) as session:
            row = session.execute(select(FundamentalSnapshotModel, SecurityModel.symbol).join(SecurityModel).where(
                SecurityModel.symbol == symbol,
                FundamentalSnapshotModel.calculation_version == version,
                FundamentalSnapshotModel.config_checksum == checksum,
            ).order_by(FundamentalSnapshotModel.fundamental_data_as_of.desc()).limit(1)).first()
            return row

    def latest_run(self, version: str, checksum: str):
        with session_scope(self.session_factory) as session:
            run = session.scalar(select(FundamentalRunModel).where(
                FundamentalRunModel.calculation_version == version,
                FundamentalRunModel.config_checksum == checksum,
            ).order_by(FundamentalRunModel.started_at.desc()).limit(1))
            if run is None:
                return None
            return {column.name: getattr(run, column.name) for column in FundamentalRunModel.__table__.columns}

    def record_combined_run(self, *, status: str, technical_data_as_of: date | None,
                            fundamental_data_as_of: date | None, eligible_stocks: int,
                            error: str | None = None) -> dict[str, object]:
        with session_scope(self.session_factory) as session:
            run = CombinedSyncRunModel(
                status=status, technical_data_as_of=technical_data_as_of,
                fundamental_data_as_of=fundamental_data_as_of,
                eligible_stocks=eligible_stocks, error=error,
                finished_at=datetime.now(UTC),
            )
            session.add(run); session.flush()
            return {column.name: getattr(run, column.name) for column in CombinedSyncRunModel.__table__.columns}

    def latest_combined_run(self) -> dict[str, object] | None:
        with session_scope(self.session_factory) as session:
            run = session.scalar(select(CombinedSyncRunModel).order_by(CombinedSyncRunModel.started_at.desc()).limit(1))
            return {column.name: getattr(run, column.name) for column in CombinedSyncRunModel.__table__.columns} if run else None


class SqlAlchemyHistoricalBackfillRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def coverage(self, target_start_date: date) -> dict[str, object]:
        with session_scope(self.session_factory) as session:
            first_dates = (
                select(
                    SecurityModel.id.label("security_id"),
                    func.min(DailyPriceModel.trading_date).label("first_date"),
                    func.max(DailyPriceModel.trading_date).label("last_date"),
                    func.count(DailyPriceModel.id).label("rows"),
                )
                .join(DailyPriceModel, DailyPriceModel.security_id == SecurityModel.id, isouter=True)
                .where(SecurityModel.is_active.is_(True))
                .group_by(SecurityModel.id)
                .subquery()
            )
            row = session.execute(select(
                func.count(first_dates.c.security_id),
                func.count(first_dates.c.security_id).filter(first_dates.c.first_date.is_not(None)),
                func.count(first_dates.c.security_id).filter(first_dates.c.first_date <= target_start_date),
                func.min(first_dates.c.first_date),
                func.max(first_dates.c.last_date),
                func.coalesce(func.sum(first_dates.c.rows), 0),
            )).one()
            return {
                "active_symbols": row[0], "symbols_with_data": row[1],
                "symbols_meeting_target": row[2], "symbols_needing_backfill": row[0] - row[2],
                "earliest_date": row[3], "latest_date": row[4], "total_rows": row[5],
            }

    def candidates(self, target_start_date: date, target_end_date: date) -> list[dict[str, object]]:
        with session_scope(self.session_factory) as session:
            rows = session.execute(
                select(SecurityModel.symbol, func.min(DailyPriceModel.trading_date))
                .join(DailyPriceModel, DailyPriceModel.security_id == SecurityModel.id, isouter=True)
                .where(SecurityModel.is_active.is_(True))
                .group_by(SecurityModel.id, SecurityModel.symbol)
                .having((func.min(DailyPriceModel.trading_date).is_(None)) | (func.min(DailyPriceModel.trading_date) > target_start_date))
                .order_by(SecurityModel.symbol)
            ).all()
            return [
                {"symbol": symbol, "start_date": target_start_date,
                 "end_date": min(target_end_date, first_date - timedelta(days=1)) if first_date else target_end_date}
                for symbol, first_date in rows
            ]

    def create_job(self, target_years: int, start_date: date, end_date: date, symbols: list[dict[str, object]]):
        with session_scope(self.session_factory) as session:
            job = HistoricalBackfillJobModel(
                id=uuid4(), target_years=target_years, target_start_date=start_date,
                target_end_date=end_date, status="queued", stage="queued",
                message="Historical backfill queued", total_symbols=len(symbols),
            )
            session.add(job); session.flush()
            session.add_all([HistoricalBackfillSymbolModel(
                job_id=job.id, symbol=item["symbol"], requested_start_date=item["start_date"],
                requested_end_date=item["end_date"], status="pending",
            ) for item in symbols])
            session.flush()
            return backfill_job_to_dict(job)

    def update_job(self, job_id: UUID, **values):
        values["updated_at"] = datetime.now(UTC)
        with session_scope(self.session_factory) as session:
            session.execute(update(HistoricalBackfillJobModel).where(HistoricalBackfillJobModel.id == job_id).values(**values))
            job = session.get(HistoricalBackfillJobModel, job_id)
            return backfill_job_to_dict(job) if job else None

    def get_job(self, job_id: UUID):
        with session_scope(self.session_factory) as session:
            job = session.get(HistoricalBackfillJobModel, job_id)
            return backfill_job_to_dict(job) if job else None

    def current_job(self):
        with session_scope(self.session_factory) as session:
            job = session.scalar(select(HistoricalBackfillJobModel).where(
                HistoricalBackfillJobModel.status.in_(("queued", "running", "rebuilding"))
            ).order_by(HistoricalBackfillJobModel.started_at.desc()).limit(1))
            return backfill_job_to_dict(job) if job else None

    def latest_job(self):
        with session_scope(self.session_factory) as session:
            job = session.scalar(select(HistoricalBackfillJobModel).order_by(HistoricalBackfillJobModel.started_at.desc()).limit(1))
            return backfill_job_to_dict(job) if job else None

    def list_jobs(self, limit=10, offset=0):
        with session_scope(self.session_factory) as session:
            jobs = session.scalars(select(HistoricalBackfillJobModel).order_by(
                HistoricalBackfillJobModel.started_at.desc()).offset(offset).limit(limit)).all()
            return [backfill_job_to_dict(item) for item in jobs]

    def count_jobs(self):
        with session_scope(self.session_factory) as session:
            return session.scalar(select(func.count(HistoricalBackfillJobModel.id))) or 0

    def pending_symbols(self, job_id: UUID, resume: bool = False):
        statuses = ("failed", "partial", "interrupted") if resume else ("pending", "running", "interrupted")
        with session_scope(self.session_factory) as session:
            rows = session.scalars(select(HistoricalBackfillSymbolModel).where(
                HistoricalBackfillSymbolModel.job_id == job_id,
                HistoricalBackfillSymbolModel.status.in_(statuses),
            ).order_by(HistoricalBackfillSymbolModel.symbol)).all()
            return [backfill_symbol_to_dict(item) for item in rows]

    def update_symbol(self, job_id: UUID, symbol: str, **values):
        with session_scope(self.session_factory) as session:
            session.execute(update(HistoricalBackfillSymbolModel).where(
                HistoricalBackfillSymbolModel.job_id == job_id,
                HistoricalBackfillSymbolModel.symbol == symbol,
            ).values(**values))

    def symbols(self, job_id: UUID, status=None, limit=10, offset=0):
        with session_scope(self.session_factory) as session:
            statement = select(HistoricalBackfillSymbolModel).where(HistoricalBackfillSymbolModel.job_id == job_id)
            if status:
                statement = statement.where(HistoricalBackfillSymbolModel.status == status)
            rows = session.scalars(statement.order_by(HistoricalBackfillSymbolModel.symbol).offset(offset).limit(limit)).all()
            count_statement = select(func.count(HistoricalBackfillSymbolModel.id)).where(HistoricalBackfillSymbolModel.job_id == job_id)
            if status:
                count_statement = count_statement.where(HistoricalBackfillSymbolModel.status == status)
            return [backfill_symbol_to_dict(item) for item in rows], session.scalar(count_statement) or 0

    def refresh_counts(self, job_id: UUID):
        with session_scope(self.session_factory) as session:
            rows = session.execute(select(HistoricalBackfillSymbolModel.status, func.count(),
                func.coalesce(func.sum(HistoricalBackfillSymbolModel.rows_written), 0),
                func.coalesce(func.sum(HistoricalBackfillSymbolModel.invalid_rows_skipped), 0),
            ).where(HistoricalBackfillSymbolModel.job_id == job_id).group_by(HistoricalBackfillSymbolModel.status)).all()
            counts = {status: count for status, count, _, _ in rows}
            processed = sum(count for status, count in counts.items() if status not in {"pending", "running", "interrupted"})
            totals = session.execute(select(
                func.coalesce(func.sum(HistoricalBackfillSymbolModel.rows_written), 0),
                func.coalesce(func.sum(HistoricalBackfillSymbolModel.invalid_rows_skipped), 0),
            ).where(HistoricalBackfillSymbolModel.job_id == job_id)).one()
            values = {
                "processed_symbols": processed,
                "succeeded_symbols": counts.get("succeeded", 0),
                "partial_symbols": counts.get("partial", 0),
                "failed_symbols": counts.get("failed", 0),
                "no_data_symbols": counts.get("no_data", 0),
                "rows_written": totals[0], "invalid_rows_skipped": totals[1],
            }
            session.execute(update(HistoricalBackfillJobModel).where(HistoricalBackfillJobModel.id == job_id).values(**values, updated_at=datetime.now(UTC)))
            return values

    def reset_retryable(self, job_id: UUID) -> None:
        with session_scope(self.session_factory) as session:
            session.execute(update(HistoricalBackfillSymbolModel).where(
                HistoricalBackfillSymbolModel.job_id == job_id,
                HistoricalBackfillSymbolModel.status.in_(("failed", "partial", "interrupted")),
            ).values(status="pending", rows_received=0, rows_written=0,
                     invalid_rows_skipped=0, error=None, finished_at=None))

    def interrupt_active(self) -> list[UUID]:
        with session_scope(self.session_factory) as session:
            ids = list(session.scalars(select(HistoricalBackfillJobModel.id).where(
                HistoricalBackfillJobModel.status.in_(("queued", "running", "rebuilding")))).all())
            if ids:
                session.execute(update(HistoricalBackfillJobModel).where(HistoricalBackfillJobModel.id.in_(ids)).values(
                    status="interrupted", stage="interrupted", message="Backfill interrupted; resuming", updated_at=datetime.now(UTC)))
                session.execute(update(HistoricalBackfillSymbolModel).where(
                    HistoricalBackfillSymbolModel.job_id.in_(ids), HistoricalBackfillSymbolModel.status == "running"
                ).values(status="interrupted"))
            return ids


def backfill_job_to_dict(item):
    return {column.name: getattr(item, column.name) for column in item.__table__.columns}


def backfill_symbol_to_dict(item):
    return {column.name: getattr(item, column.name) for column in item.__table__.columns}


class SqlAlchemyResearchRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def availability(self, strategy_name: str, strategy_version: str, strategy_checksum: str, indicator_version: str):
        with session_scope(self.session_factory) as session:
            price_range = session.execute(select(
                func.min(DailyPriceModel.trading_date), func.max(DailyPriceModel.trading_date)
            )).one()
            strategy_range = session.execute(select(
                func.min(DailyStrategyResultModel.trading_date), func.max(DailyStrategyResultModel.trading_date)
            ).where(
                DailyStrategyResultModel.strategy_name == strategy_name,
                DailyStrategyResultModel.strategy_version == strategy_version,
                DailyStrategyResultModel.strategy_config_checksum == strategy_checksum,
            )).one()
            indicator_range = session.execute(select(
                func.min(DailyIndicatorModel.trading_date), func.max(DailyIndicatorModel.trading_date)
            ).where(DailyIndicatorModel.calculation_version == indicator_version)).one()
            return {
                "price_start": price_range[0], "price_end": price_range[1],
                "backtest_start": max(filter(None, (price_range[0], strategy_range[0])), default=None),
                "backtest_end": min(filter(None, (price_range[1], strategy_range[1])), default=None),
                "optimization_start": max(filter(None, (price_range[0], indicator_range[0])), default=None),
                "optimization_end": min(filter(None, (price_range[1], indicator_range[1])), default=None,
                ),
            }

    def interrupt_active(self) -> int:
        with session_scope(self.session_factory) as session:
            result = session.execute(update(ResearchJobModel).where(
                ResearchJobModel.status.in_(("queued", "running"))
            ).values(
                status="interrupted", stage="interrupted",
                message="Job interrupted by application restart",
                error="Application restarted before the job completed",
                finished_at=datetime.now(UTC),
            ))
            return result.rowcount

    def create_job(self, job_type: str, start_date: date, end_date: date):
        with session_scope(self.session_factory) as session:
            job = ResearchJobModel(
                id=uuid4(),
                job_type=job_type, status="queued", start_date=start_date, end_date=end_date,
                stage="queued", message="Research job queued", progress=0,
            )
            session.add(job); session.flush()
            return research_job_to_dict(job)

    def update_job(self, job_id: UUID, **values):
        with session_scope(self.session_factory) as session:
            session.execute(update(ResearchJobModel).where(ResearchJobModel.id == job_id).values(**values))
            job = session.get(ResearchJobModel, job_id)
            return research_job_to_dict(job) if job else None

    def get_job(self, job_id: UUID):
        with session_scope(self.session_factory) as session:
            job = session.get(ResearchJobModel, job_id)
            return research_job_to_dict(job) if job else None

    def current_job(self):
        with session_scope(self.session_factory) as session:
            job = session.scalar(select(ResearchJobModel).where(
                ResearchJobModel.status.in_(("queued", "running"))
            ).order_by(ResearchJobModel.started_at.desc()).limit(1))
            return research_job_to_dict(job) if job else None

    def list_jobs(self, limit: int = 50, offset: int = 0):
        with session_scope(self.session_factory) as session:
            jobs = session.scalars(select(ResearchJobModel).order_by(
                ResearchJobModel.started_at.desc()
            ).offset(offset).limit(limit)).all()
            return [research_job_to_dict(job) for job in jobs]

    def count_jobs(self) -> int:
        with session_scope(self.session_factory) as session:
            return session.scalar(select(func.count(ResearchJobModel.id))) or 0


def research_job_to_dict(job):
    return {
        "id": job.id, "job_type": job.job_type, "status": job.status,
        "start_date": job.start_date, "end_date": job.end_date,
        "stage": job.stage, "message": job.message, "progress": job.progress,
        "result_run_id": job.result_run_id, "error": job.error,
        "started_at": job.started_at, "finished_at": job.finished_at,
    }


class SqlAlchemyUniverseRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def import_snapshot(
        self,
        *,
        snapshot_date: date,
        checksum: str,
        source: str,
        securities: Sequence[Security],
    ) -> tuple[int, int, int]:
        with session_scope(self.session_factory) as session:
            existing_snapshot = session.scalar(
                select(UniverseSnapshotModel).where(
                    UniverseSnapshotModel.checksum == checksum
                )
            )
            if existing_snapshot is not None:
                return (0, 0, 0)

            latest_date = session.scalar(
                select(func.max(UniverseSnapshotModel.snapshot_date))
            )
            if latest_date is not None and snapshot_date < latest_date:
                raise ValueError(
                    f"snapshot date {snapshot_date} predates latest import {latest_date}"
                )

            snapshot = UniverseSnapshotModel(
                snapshot_date=snapshot_date, checksum=checksum, source=source
            )
            session.add(snapshot)
            session.flush()

            existing_by_symbol = {
                item.symbol: item
                for item in session.scalars(select(SecurityModel)).all()
            }
            imported_symbols = {security.symbol for security in securities}
            inserted = 0
            updated_count = 0
            for security in securities:
                model = existing_by_symbol.get(security.symbol)
                if model is None:
                    session.add(
                        SecurityModel(
                            symbol=security.symbol,
                            idx_code=security.idx_code,
                            issuer_name=security.issuer_name,
                            board=security.board,
                            sector=security.sector,
                            is_active=True,
                            first_seen_snapshot_id=snapshot.id,
                            last_seen_snapshot_id=snapshot.id,
                        )
                    )
                    inserted += 1
                    continue

                changed = (
                    model.idx_code != security.idx_code
                    or model.issuer_name != security.issuer_name
                    or model.board != security.board
                    or model.sector != security.sector
                    or not model.is_active
                )
                model.idx_code = security.idx_code
                model.issuer_name = security.issuer_name
                model.board = security.board
                model.sector = security.sector
                model.is_active = True
                model.last_seen_snapshot_id = snapshot.id
                updated_count += int(changed)

            inactive_result = session.execute(
                update(SecurityModel)
                .where(
                    SecurityModel.is_active.is_(True),
                    SecurityModel.symbol.not_in(imported_symbols),
                )
                .values(is_active=False)
            )
            return inserted, updated_count, inactive_result.rowcount or 0

    def list_securities(self, *, active_only: bool = False) -> list[Security]:
        with session_scope(self.session_factory) as session:
            statement = select(SecurityModel).order_by(SecurityModel.symbol)
            if active_only:
                statement = statement.where(SecurityModel.is_active.is_(True))
            return [
                Security(
                    symbol=item.symbol,
                    idx_code=item.idx_code,
                    issuer_name=item.issuer_name,
                    board=item.board,
                    sector=item.sector,
                    is_active=item.is_active,
                )
                for item in session.scalars(statement).all()
            ]


class SqlAlchemyMarketDataRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def active_symbols(self) -> list[str]:
        with session_scope(self.session_factory) as session:
            return list(
                session.scalars(
                    select(SecurityModel.symbol)
                    .where(SecurityModel.is_active.is_(True))
                    .order_by(SecurityModel.symbol)
                ).all()
            )

    def stock_exists(self, symbol: str) -> bool:
        with session_scope(self.session_factory) as session:
            return session.scalar(
                select(SecurityModel.id).where(
                    SecurityModel.symbol == symbol,
                    SecurityModel.is_active.is_(True),
                )
            ) is not None

    def liquidity_snapshot_date(self, indicator_version: str) -> date | None:
        with session_scope(self.session_factory) as session:
            return session.scalar(select(func.max(DailyIndicatorModel.trading_date)).where(
                DailyIndicatorModel.calculation_version == indicator_version,
                DailyIndicatorModel.provider == "yahoo",
                DailyIndicatorModel.interval == "1d",
            ))

    def list_stock_summaries(
        self, *, search: str | None = None, limit: int = 100, offset: int = 0,
        indicator_version: str = "technical-v3", as_of_date: date | None = None,
        min_turnover: Decimal | None = None, liquidity_tiers: tuple[str, ...] = (),
        liquidity_thresholds: dict[str, Decimal] | None = None,
    ) -> tuple[list[dict[str, object]], int, int]:
        with session_scope(self.session_factory) as session:
            universe_filters = [SecurityModel.is_active.is_(True)]
            total_stocks = session.scalar(select(func.count(SecurityModel.id)).where(*universe_filters)) or 0
            filters = list(universe_filters)
            if search:
                pattern = f"%{search.strip()}%"
                filters.append(
                    SecurityModel.symbol.ilike(pattern)
                    | SecurityModel.idx_code.ilike(pattern)
                    | SecurityModel.issuer_name.ilike(pattern)
                )
            latest_close = (
                select(DailyPriceModel.close)
                .where(
                    DailyPriceModel.security_id == SecurityModel.id,
                    DailyPriceModel.provider == "yahoo",
                    DailyPriceModel.interval == "1d",
                )
                .order_by(DailyPriceModel.trading_date.desc())
                .limit(1)
                .correlate(SecurityModel)
                .scalar_subquery()
            )
            previous_close = (
                select(DailyPriceModel.close)
                .where(
                    DailyPriceModel.security_id == SecurityModel.id,
                    DailyPriceModel.provider == "yahoo",
                    DailyPriceModel.interval == "1d",
                )
                .order_by(DailyPriceModel.trading_date.desc())
                .offset(1)
                .limit(1)
                .correlate(SecurityModel)
                .scalar_subquery()
            )
            latest_volume = (
                select(DailyPriceModel.volume)
                .where(
                    DailyPriceModel.security_id == SecurityModel.id,
                    DailyPriceModel.provider == "yahoo",
                    DailyPriceModel.interval == "1d",
                )
                .order_by(DailyPriceModel.trading_date.desc())
                .limit(1)
                .correlate(SecurityModel)
                .scalar_subquery()
            )
            latest_date = (
                select(DailyPriceModel.trading_date)
                .where(
                    DailyPriceModel.security_id == SecurityModel.id,
                    DailyPriceModel.provider == "yahoo",
                    DailyPriceModel.interval == "1d",
                )
                .order_by(DailyPriceModel.trading_date.desc())
                .limit(1)
                .correlate(SecurityModel)
                .scalar_subquery()
            )
            indicator = aliased(DailyIndicatorModel)
            statement = select(
                SecurityModel.symbol,
                SecurityModel.idx_code,
                SecurityModel.issuer_name,
                SecurityModel.board,
                SecurityModel.sector,
                latest_close.label("last_price"),
                previous_close.label("previous_close"),
                latest_volume.label("volume"),
                latest_date.label("trading_date"),
                indicator.average_traded_value_20.label("avg_daily_turnover_value"),
                indicator.volume_ma_20.label("avg_daily_volume"),
            ).outerjoin(indicator, (
                indicator.security_id == SecurityModel.id
            ) & (
                indicator.calculation_version == indicator_version
            ) & (
                indicator.provider == "yahoo"
            ) & (
                indicator.interval == "1d"
            ) & (
                indicator.trading_date == as_of_date
            )).where(*filters)
            if min_turnover is not None:
                statement = statement.where(indicator.average_traded_value_20 >= min_turnover)
            if liquidity_tiers:
                thresholds = liquidity_thresholds or {}
                tier_conditions = []
                if "high" in liquidity_tiers:
                    tier_conditions.append(indicator.average_traded_value_20 >= thresholds["high"])
                if "medium" in liquidity_tiers:
                    tier_conditions.append(
                        (indicator.average_traded_value_20 >= thresholds["medium"])
                        & (indicator.average_traded_value_20 < thresholds["high"])
                    )
                if "low" in liquidity_tiers:
                    tier_conditions.append(
                        (indicator.average_traded_value_20 >= thresholds["low"])
                        & (indicator.average_traded_value_20 < thresholds["medium"])
                    )
                statement = statement.where(or_(*tier_conditions))
            filtered_count = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
            rows = session.execute(
                statement.order_by(SecurityModel.symbol).offset(offset).limit(limit)
            ).all()
            return [dict(row._mapping) for row in rows], total_stocks, filtered_count

    def liquidity_breakdown(self, *, as_of_date: date, indicator_version: str,
                            scoring_version: str, scoring_config_checksum: str):
        with session_scope(self.session_factory) as session:
            rows = session.execute(select(
                SecurityModel.symbol,
                DailyIndicatorModel.average_traded_value_20,
                DailyIndicatorModel.volume_ma_20,
                DailyTechnicalScoreModel.score,
            ).select_from(SecurityModel).outerjoin(DailyIndicatorModel, (
                DailyIndicatorModel.security_id == SecurityModel.id
            ) & (DailyIndicatorModel.trading_date == as_of_date)
              & (DailyIndicatorModel.calculation_version == indicator_version)
              & (DailyIndicatorModel.provider == "yahoo")
              & (DailyIndicatorModel.interval == "1d")
            ).outerjoin(DailyTechnicalScoreModel, (
                DailyTechnicalScoreModel.security_id == SecurityModel.id
            ) & (DailyTechnicalScoreModel.trading_date == as_of_date)
              & (DailyTechnicalScoreModel.scoring_version == scoring_version)
              & (DailyTechnicalScoreModel.scoring_config_checksum == scoring_config_checksum)
            ).where(SecurityModel.is_active.is_(True))).all()
            return [dict(row._mapping) for row in rows]

    def stock_metadata(self, symbol: str) -> dict[str, object] | None:
        with session_scope(self.session_factory) as session:
            security = session.scalar(
                select(SecurityModel).where(
                    SecurityModel.symbol == symbol,
                    SecurityModel.is_active.is_(True),
                )
            )
            if security is None:
                return None
            return {
                "symbol": security.symbol,
                "idx_code": security.idx_code,
                "issuer_name": security.issuer_name,
                "board": security.board,
                "sector": security.sector,
            }

    def load_stock_candles(
        self, symbol: str, *, start_date: date | None, end_date: date
    ) -> list[DailyCandle]:
        with session_scope(self.session_factory) as session:
            statement = (
                select(DailyPriceModel)
                .join(SecurityModel)
                .where(
                    SecurityModel.symbol == symbol,
                    DailyPriceModel.provider == "yahoo",
                    DailyPriceModel.interval == "1d",
                    DailyPriceModel.trading_date <= end_date,
                )
                .order_by(DailyPriceModel.trading_date)
            )
            if start_date is not None:
                statement = statement.where(DailyPriceModel.trading_date >= start_date)
            return [
                DailyCandle(
                    symbol=symbol,
                    trading_date=item.trading_date,
                    open=item.open,
                    high=item.high,
                    low=item.low,
                    close=item.close,
                    adjusted_close=item.adjusted_close,
                    volume=item.volume,
                    provider=item.provider,
                    interval=item.interval,
                )
                for item in session.scalars(statement).all()
            ]

    def load_stock_indicators(
        self,
        symbol: str,
        *,
        start_date: date | None,
        end_date: date,
        calculation_version: str,
    ) -> dict[date, dict[str, object]]:
        with session_scope(self.session_factory) as session:
            statement = (
                select(DailyIndicatorModel)
                .join(SecurityModel)
                .where(
                    SecurityModel.symbol == symbol,
                    DailyIndicatorModel.provider == "yahoo",
                    DailyIndicatorModel.interval == "1d",
                    DailyIndicatorModel.calculation_version == calculation_version,
                    DailyIndicatorModel.trading_date <= end_date,
                )
            )
            if start_date is not None:
                statement = statement.where(DailyIndicatorModel.trading_date >= start_date)
            return {
                item.trading_date: {
                    "ma20": item.sma_20,
                    "ma50": item.sma_50,
                    "ma200": item.sma_200,
                    "rsi14": item.rsi_14,
                    "macd": item.macd,
                    "macd_signal": item.macd_signal,
                    "atr14": item.atr_14,
                }
                for item in session.scalars(statement).all()
            }

    def latest_trading_date(self, symbol: str) -> date | None:
        with session_scope(self.session_factory) as session:
            return session.scalar(
                select(func.max(DailyPriceModel.trading_date))
                .join(SecurityModel)
                .where(
                    SecurityModel.symbol == symbol,
                    DailyPriceModel.provider == "yahoo",
                    DailyPriceModel.interval == "1d",
                )
            )

    def cache_status(self, target_date: date) -> dict[str, object]:
        with session_scope(self.session_factory) as session:
            active_count = session.scalar(
                select(func.count(SecurityModel.id)).where(SecurityModel.is_active.is_(True))
            ) or 0
            covered_count = session.scalar(
                select(func.count(func.distinct(DailyPriceModel.security_id)))
                .join(SecurityModel)
                .where(
                    SecurityModel.is_active.is_(True),
                    DailyPriceModel.provider == "yahoo",
                    DailyPriceModel.interval == "1d",
                )
            ) or 0
            latest_date = session.scalar(
                select(func.max(DailyPriceModel.trading_date)).where(
                    DailyPriceModel.provider == "yahoo",
                    DailyPriceModel.interval == "1d",
                )
            )
            stale_count = session.scalar(
                select(func.count(SecurityModel.id))
                .where(SecurityModel.is_active.is_(True))
                .where(
                    ~select(DailyPriceModel.security_id)
                    .where(
                        DailyPriceModel.security_id == SecurityModel.id,
                        DailyPriceModel.provider == "yahoo",
                        DailyPriceModel.interval == "1d",
                        DailyPriceModel.trading_date >= target_date,
                    )
                    .exists()
                )
            ) or 0
            last_run = session.scalar(
                select(CollectionRunModel).order_by(CollectionRunModel.started_at.desc()).limit(1)
            )
            return {
                "target_date": target_date,
                "active_symbols": active_count,
                "symbols_with_data": covered_count,
                "symbols_without_target_date": stale_count,
                "latest_trading_date": latest_date,
                "is_current": latest_date is not None and latest_date >= target_date,
                "last_collection_status": last_run.status.value if last_run else None,
                "last_collection_started_at": last_run.started_at if last_run else None,
                "last_collection_finished_at": last_run.finished_at if last_run else None,
            }

    def upsert_candles(self, candles: Sequence[DailyCandle]) -> int:
        if not candles:
            return 0
        with session_scope(self.session_factory) as session:
            symbols = {candle.symbol for candle in candles}
            security_ids = dict(
                session.execute(
                    select(SecurityModel.symbol, SecurityModel.id).where(
                        SecurityModel.symbol.in_(symbols)
                    )
                ).all()
            )
            missing = symbols - security_ids.keys()
            if missing:
                raise ValueError(f"unknown securities: {', '.join(sorted(missing))}")

            rows = [
                {
                    "security_id": security_ids[candle.symbol],
                    "provider": candle.provider,
                    "interval": candle.interval,
                    "trading_date": candle.trading_date,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "adjusted_close": candle.adjusted_close,
                    "volume": candle.volume,
                }
                for candle in candles
            ]
            statement = insert(DailyPriceModel).values(rows)
            statement = statement.on_conflict_do_update(
                constraint="uq_daily_price_identity",
                set_={
                    "open": statement.excluded.open,
                    "high": statement.excluded.high,
                    "low": statement.excluded.low,
                    "close": statement.excluded.close,
                    "adjusted_close": statement.excluded.adjusted_close,
                    "volume": statement.excluded.volume,
                    "updated_at": func.now(),
                },
            )
            session.execute(statement)
            return len(rows)


class SqlAlchemyRunRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create_run(self, request: CollectionRequest) -> UUID:
        with session_scope(self.session_factory) as session:
            run = CollectionRunModel(
                command=request.command,
                status=RunStatus.RUNNING,
                requested_start_date=request.start_date,
                requested_end_date=request.end_date,
                requested_symbols=len(request.symbols),
                parent_run_id=request.parent_run_id,
            )
            session.add(run)
            session.flush()
            return run.id

    def record_symbol_result(
        self, run_id: UUID, result: SymbolCollectionResult
    ) -> None:
        with session_scope(self.session_factory) as session:
            session.add(
                CollectionSymbolResultModel(
                    run_id=run_id,
                    symbol=result.symbol,
                    status=result.status,
                    attempts=result.attempts,
                    rows_received=result.rows_received,
                    rows_written=result.rows_written,
                    error=result.error,
                )
            )

    def finish_run(self, run_id: UUID) -> None:
        with session_scope(self.session_factory) as session:
            counts = dict(
                session.execute(
                    select(
                        CollectionSymbolResultModel.status,
                        func.count(CollectionSymbolResultModel.id),
                    )
                    .where(CollectionSymbolResultModel.run_id == run_id)
                    .group_by(CollectionSymbolResultModel.status)
                ).all()
            )
            success_count = counts.get(SymbolStatus.SUCCESS, 0)
            no_data_count = counts.get(SymbolStatus.NO_NEW_DATA, 0)
            failure_count = counts.get(SymbolStatus.FAILED, 0)
            status = (
                RunStatus.SUCCEEDED
                if failure_count == 0
                else RunStatus.PARTIAL_FAILURE
                if success_count + no_data_count > 0
                else RunStatus.FAILED
            )
            session.execute(
                update(CollectionRunModel)
                .where(CollectionRunModel.id == run_id)
                .values(
                    status=status,
                    success_count=success_count,
                    no_data_count=no_data_count,
                    failure_count=failure_count,
                    finished_at=datetime.now(UTC),
                )
            )

    def failed_symbols(self, run_id: UUID) -> list[str]:
        with session_scope(self.session_factory) as session:
            return list(
                session.scalars(
                    select(CollectionSymbolResultModel.symbol)
                    .where(
                        CollectionSymbolResultModel.run_id == run_id,
                        CollectionSymbolResultModel.status == SymbolStatus.FAILED,
                    )
                    .order_by(CollectionSymbolResultModel.symbol)
                ).all()
            )

    def get_run_summary(self, run_id: UUID) -> dict[str, object] | None:
        with session_scope(self.session_factory) as session:
            run = session.get(CollectionRunModel, run_id)
            if run is None:
                return None
            return {
                "id": run.id,
                "command": run.command.value,
                "status": run.status.value,
                "requested_start_date": run.requested_start_date,
                "requested_end_date": run.requested_end_date,
                "requested_symbols": run.requested_symbols,
                "success_count": run.success_count,
                "no_data_count": run.no_data_count,
                "failure_count": run.failure_count,
                "parent_run_id": run.parent_run_id,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
            }

    def abandon_run(self, run_id: UUID) -> None:
        with session_scope(self.session_factory) as session:
            session.execute(
                update(CollectionRunModel)
                .where(CollectionRunModel.id == run_id)
                .values(
                    status=RunStatus.FAILED,
                    failure_count=1,
                    finished_at=datetime.now(UTC),
                )
            )


class SqlAlchemyIndicatorRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def active_symbols(self) -> list[str]:
        with session_scope(self.session_factory) as session:
            return list(
                session.scalars(
                    select(SecurityModel.symbol)
                    .where(SecurityModel.is_active.is_(True))
                    .order_by(SecurityModel.symbol)
                ).all()
            )

    def load_candles(
        self,
        symbol: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        warmup_sessions: int = 0,
    ) -> list[DailyCandle]:
        with session_scope(self.session_factory) as session:
            effective_start = start_date
            if start_date is not None and warmup_sessions > 0:
                warmup_dates = list(
                    session.scalars(
                        select(DailyPriceModel.trading_date)
                        .join(SecurityModel)
                        .where(
                            SecurityModel.symbol == symbol,
                            DailyPriceModel.provider == "yahoo",
                            DailyPriceModel.interval == "1d",
                            DailyPriceModel.trading_date < start_date,
                        )
                        .order_by(DailyPriceModel.trading_date.desc())
                        .limit(warmup_sessions)
                    ).all()
                )
                if warmup_dates:
                    effective_start = min(warmup_dates)

            statement = (
                select(DailyPriceModel)
                .join(SecurityModel)
                .where(
                    SecurityModel.symbol == symbol,
                    DailyPriceModel.provider == "yahoo",
                    DailyPriceModel.interval == "1d",
                )
                .order_by(DailyPriceModel.trading_date)
            )
            if effective_start is not None:
                statement = statement.where(
                    DailyPriceModel.trading_date >= effective_start
                )
            if end_date is not None:
                statement = statement.where(DailyPriceModel.trading_date <= end_date)
            return [
                DailyCandle(
                    symbol=symbol,
                    trading_date=item.trading_date,
                    open=item.open,
                    high=item.high,
                    low=item.low,
                    close=item.close,
                    adjusted_close=item.adjusted_close,
                    volume=item.volume,
                    provider=item.provider,
                    interval=item.interval,
                )
                for item in session.scalars(statement).all()
            ]

    def latest_indicator_date(
        self, symbol: str, calculation_version: str
    ) -> date | None:
        with session_scope(self.session_factory) as session:
            return session.scalar(
                select(func.max(DailyIndicatorModel.trading_date))
                .join(SecurityModel)
                .where(
                    SecurityModel.symbol == symbol,
                    DailyIndicatorModel.provider == "yahoo",
                    DailyIndicatorModel.interval == "1d",
                    DailyIndicatorModel.calculation_version == calculation_version,
                )
            )

    def source_update_times(
        self, symbol: str, trading_dates: Sequence[date]
    ) -> dict[date, datetime]:
        if not trading_dates:
            return {}
        with session_scope(self.session_factory) as session:
            return dict(
                session.execute(
                    select(DailyPriceModel.trading_date, DailyPriceModel.updated_at)
                    .join(SecurityModel)
                    .where(
                        SecurityModel.symbol == symbol,
                        DailyPriceModel.provider == "yahoo",
                        DailyPriceModel.interval == "1d",
                        DailyPriceModel.trading_date.in_(trading_dates),
                    )
                ).all()
            )

    def upsert_indicators(self, indicators: Sequence[DailyIndicators]) -> int:
        if not indicators:
            return 0
        with session_scope(self.session_factory) as session:
            symbols = {item.symbol for item in indicators}
            security_ids = dict(
                session.execute(
                    select(SecurityModel.symbol, SecurityModel.id).where(
                        SecurityModel.symbol.in_(symbols)
                    )
                ).all()
            )
            missing = symbols - security_ids.keys()
            if missing:
                raise ValueError(f"unknown securities: {', '.join(sorted(missing))}")

            rows = [
                {
                    "security_id": security_ids[item.symbol],
                    "provider": item.provider,
                    "interval": item.interval,
                    "trading_date": item.trading_date,
                    "calculation_version": item.calculation_version,
                    "sma_5": item.sma_5,
                    "sma_10": item.sma_10,
                    "sma_20": item.sma_20,
                    "sma_50": item.sma_50,
                    "sma_200": item.sma_200,
                    "volume_ma_20": item.volume_ma_20,
                    "volume_ratio": item.volume_ratio,
                    "daily_change_percent": item.daily_change_percent,
                    "atr_14": item.atr_14,
                    "rsi_14": item.rsi_14,
                    "macd": item.macd,
                    "macd_signal": item.macd_signal,
                    "macd_histogram": item.macd_histogram,
                    "macd_bullish_crossover": item.macd_bullish_crossover,
                    "higher_low_formed": item.higher_low_formed,
                    "highest_high_20": item.highest_high_20,
                    "lowest_low_20": item.lowest_low_20,
                    "average_traded_value_20": item.average_traded_value_20,
                    "source_updated_at": item.source_updated_at,
                }
                for item in indicators
            ]
            statement = insert(DailyIndicatorModel).values(rows)
            statement = statement.on_conflict_do_update(
                constraint="uq_daily_indicator_identity",
                set_={
                    "sma_5": statement.excluded.sma_5,
                    "sma_10": statement.excluded.sma_10,
                    "sma_20": statement.excluded.sma_20,
                    "sma_50": statement.excluded.sma_50,
                    "sma_200": statement.excluded.sma_200,
                    "volume_ma_20": statement.excluded.volume_ma_20,
                    "volume_ratio": statement.excluded.volume_ratio,
                    "daily_change_percent": statement.excluded.daily_change_percent,
                    "atr_14": statement.excluded.atr_14,
                    "rsi_14": statement.excluded.rsi_14,
                    "macd": statement.excluded.macd,
                    "macd_signal": statement.excluded.macd_signal,
                    "macd_histogram": statement.excluded.macd_histogram,
                    "macd_bullish_crossover": statement.excluded.macd_bullish_crossover,
                    "higher_low_formed": statement.excluded.higher_low_formed,
                    "highest_high_20": statement.excluded.highest_high_20,
                    "lowest_low_20": statement.excluded.lowest_low_20,
                    "average_traded_value_20": statement.excluded.average_traded_value_20,
                    "source_updated_at": statement.excluded.source_updated_at,
                    "calculated_at": func.now(),
                },
            )
            session.execute(statement)
            return len(rows)


class SqlAlchemyIndicatorRunRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create_indicator_run(self, request: IndicatorRunRequest) -> UUID:
        with session_scope(self.session_factory) as session:
            run = IndicatorRunModel(
                mode=request.mode,
                status=IndicatorRunStatus.RUNNING,
                calculation_version=request.calculation_version,
                requested_start_date=request.start_date,
                requested_end_date=request.end_date,
                requested_symbols=len(request.symbols),
            )
            session.add(run)
            session.flush()
            return run.id

    def record_indicator_symbol_result(
        self, run_id: UUID, result: IndicatorSymbolResult
    ) -> None:
        with session_scope(self.session_factory) as session:
            session.add(
                IndicatorSymbolResultModel(
                    run_id=run_id,
                    symbol=result.symbol,
                    status=result.status,
                    rows_read=result.rows_read,
                    rows_written=result.rows_written,
                    error=result.error,
                )
            )

    def finish_indicator_run(self, run_id: UUID) -> None:
        with session_scope(self.session_factory) as session:
            counts = dict(
                session.execute(
                    select(
                        IndicatorSymbolResultModel.status,
                        func.count(IndicatorSymbolResultModel.id),
                    )
                    .where(IndicatorSymbolResultModel.run_id == run_id)
                    .group_by(IndicatorSymbolResultModel.status)
                ).all()
            )
            success_count = counts.get(IndicatorSymbolStatus.SUCCESS, 0)
            no_data_count = counts.get(IndicatorSymbolStatus.NO_DATA, 0)
            failure_count = counts.get(IndicatorSymbolStatus.FAILED, 0)
            status = (
                IndicatorRunStatus.SUCCEEDED
                if failure_count == 0
                else IndicatorRunStatus.PARTIAL_FAILURE
                if success_count + no_data_count > 0
                else IndicatorRunStatus.FAILED
            )
            session.execute(
                update(IndicatorRunModel)
                .where(IndicatorRunModel.id == run_id)
                .values(
                    status=status,
                    success_count=success_count,
                    no_data_count=no_data_count,
                    failure_count=failure_count,
                    finished_at=datetime.now(UTC),
                )
            )

    def abandon_indicator_run(self, run_id: UUID) -> None:
        with session_scope(self.session_factory) as session:
            session.execute(
                update(IndicatorRunModel)
                .where(IndicatorRunModel.id == run_id)
                .values(
                    status=IndicatorRunStatus.FAILED,
                    failure_count=1,
                    finished_at=datetime.now(UTC),
                )
            )

    def get_indicator_run_summary(self, run_id: UUID) -> dict[str, object] | None:
        with session_scope(self.session_factory) as session:
            run = session.get(IndicatorRunModel, run_id)
            if run is None:
                return None
            return {
                "id": run.id,
                "mode": run.mode.value,
                "status": run.status.value,
                "calculation_version": run.calculation_version,
                "requested_start_date": run.requested_start_date,
                "requested_end_date": run.requested_end_date,
                "requested_symbols": run.requested_symbols,
                "success_count": run.success_count,
                "no_data_count": run.no_data_count,
                "failure_count": run.failure_count,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
            }


class SqlAlchemyRuleRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def active_symbols(self) -> list[str]:
        with session_scope(self.session_factory) as session:
            return list(
                session.scalars(
                    select(SecurityModel.symbol)
                    .where(SecurityModel.is_active.is_(True))
                    .order_by(SecurityModel.symbol)
                ).all()
            )

    def load_rule_inputs(
        self,
        symbol: str,
        *,
        indicator_version: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[RuleEvaluationInput]:
        with session_scope(self.session_factory) as session:
            statement = (
                select(DailyPriceModel, DailyIndicatorModel)
                .join(SecurityModel, DailyPriceModel.security_id == SecurityModel.id)
                .join(
                    DailyIndicatorModel,
                    (DailyIndicatorModel.security_id == DailyPriceModel.security_id)
                    & (DailyIndicatorModel.provider == DailyPriceModel.provider)
                    & (DailyIndicatorModel.interval == DailyPriceModel.interval)
                    & (DailyIndicatorModel.trading_date == DailyPriceModel.trading_date),
                )
                .where(
                    SecurityModel.symbol == symbol,
                    DailyPriceModel.provider == "yahoo",
                    DailyPriceModel.interval == "1d",
                    DailyIndicatorModel.calculation_version == indicator_version,
                )
                .order_by(DailyPriceModel.trading_date)
            )
            if start_date is not None:
                statement = statement.where(DailyPriceModel.trading_date >= start_date)
            if end_date is not None:
                statement = statement.where(DailyPriceModel.trading_date <= end_date)
            return [
                RuleEvaluationInput(
                    candle=DailyCandle(
                        symbol=symbol,
                        trading_date=price.trading_date,
                        open=price.open,
                        high=price.high,
                        low=price.low,
                        close=price.close,
                        adjusted_close=price.adjusted_close,
                        volume=price.volume,
                        provider=price.provider,
                        interval=price.interval,
                    ),
                    indicators=indicator_model_to_domain(symbol, indicator),
                    candle_updated_at=price.updated_at,
                    indicator_calculated_at=indicator.calculated_at,
                )
                for price, indicator in session.execute(statement).all()
            ]

    def latest_rule_date(
        self, symbol: str, formula_version: str, config_checksum: str
    ) -> date | None:
        with session_scope(self.session_factory) as session:
            return session.scalar(
                select(func.max(DailyRuleModel.trading_date))
                .join(SecurityModel)
                .where(
                    SecurityModel.symbol == symbol,
                    DailyRuleModel.formula_version == formula_version,
                    DailyRuleModel.config_checksum == config_checksum,
                )
            )

    def upsert_rules(self, rules: Sequence[DailyRules]) -> int:
        if not rules:
            return 0
        with session_scope(self.session_factory) as session:
            symbols = {item.symbol for item in rules}
            security_ids = dict(
                session.execute(
                    select(SecurityModel.symbol, SecurityModel.id).where(
                        SecurityModel.symbol.in_(symbols)
                    )
                ).all()
            )
            rows = [daily_rule_to_row(item, security_ids[item.symbol]) for item in rules]
            statement = insert(DailyRuleModel).values(rows)
            statement = statement.on_conflict_do_update(
                constraint="uq_daily_rule_identity",
                set_={
                    field: getattr(statement.excluded, field)
                    for field in RULE_BOOLEAN_FIELDS
                }
                | {
                    "indicator_version": statement.excluded.indicator_version,
                    "candle_updated_at": statement.excluded.candle_updated_at,
                    "indicator_calculated_at": statement.excluded.indicator_calculated_at,
                    "evaluated_at": func.now(),
                },
            )
            session.execute(statement)
            return len(rows)

    def latest_rules(
        self, symbol: str, formula_version: str, config_checksum: str
    ) -> DailyRules | None:
        history = self.rule_history(
            symbol,
            formula_version,
            config_checksum,
            limit=1,
            before=None,
        )
        return history[0] if history else None

    def rule_history(
        self,
        symbol: str,
        formula_version: str,
        config_checksum: str,
        *,
        limit: int,
        before: date | None,
    ) -> list[DailyRules]:
        with session_scope(self.session_factory) as session:
            statement = (
                select(DailyRuleModel)
                .join(SecurityModel)
                .where(
                    SecurityModel.symbol == symbol,
                    DailyRuleModel.formula_version == formula_version,
                    DailyRuleModel.config_checksum == config_checksum,
                )
                .order_by(DailyRuleModel.trading_date.desc())
                .limit(limit)
            )
            if before is not None:
                statement = statement.where(DailyRuleModel.trading_date < before)
            return [daily_rule_model_to_domain(symbol, item) for item in session.scalars(statement)]


class SqlAlchemyRuleRunRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create_rule_run(self, request: RuleRunRequest) -> UUID:
        with session_scope(self.session_factory) as session:
            run = RuleRunModel(
                mode=request.mode,
                status=RuleRunStatus.RUNNING,
                formula_version=request.formula_version,
                config_checksum=request.config_checksum,
                indicator_version=request.indicator_version,
                requested_start_date=request.start_date,
                requested_end_date=request.end_date,
                requested_symbols=len(request.symbols),
            )
            session.add(run)
            session.flush()
            return run.id

    def record_rule_symbol_result(self, run_id: UUID, result: RuleSymbolResult) -> None:
        with session_scope(self.session_factory) as session:
            session.add(
                RuleSymbolResultModel(
                    run_id=run_id,
                    symbol=result.symbol,
                    status=result.status,
                    rows_read=result.rows_read,
                    rows_written=result.rows_written,
                    error=result.error,
                )
            )

    def finish_rule_run(self, run_id: UUID) -> None:
        with session_scope(self.session_factory) as session:
            counts = dict(
                session.execute(
                    select(
                        RuleSymbolResultModel.status,
                        func.count(RuleSymbolResultModel.id),
                    )
                    .where(RuleSymbolResultModel.run_id == run_id)
                    .group_by(RuleSymbolResultModel.status)
                ).all()
            )
            success_count = counts.get(RuleSymbolStatus.SUCCESS, 0)
            no_data_count = counts.get(RuleSymbolStatus.NO_DATA, 0)
            failure_count = counts.get(RuleSymbolStatus.FAILED, 0)
            status = (
                RuleRunStatus.SUCCEEDED
                if failure_count == 0
                else RuleRunStatus.PARTIAL_FAILURE
                if success_count + no_data_count > 0
                else RuleRunStatus.FAILED
            )
            session.execute(
                update(RuleRunModel)
                .where(RuleRunModel.id == run_id)
                .values(
                    status=status,
                    success_count=success_count,
                    no_data_count=no_data_count,
                    failure_count=failure_count,
                    finished_at=datetime.now(UTC),
                )
            )

    def abandon_rule_run(self, run_id: UUID) -> None:
        with session_scope(self.session_factory) as session:
            session.execute(
                update(RuleRunModel)
                .where(RuleRunModel.id == run_id)
                .values(
                    status=RuleRunStatus.FAILED,
                    failure_count=1,
                    finished_at=datetime.now(UTC),
                )
            )

    def get_rule_run_summary(self, run_id: UUID) -> dict[str, object] | None:
        with session_scope(self.session_factory) as session:
            run = session.get(RuleRunModel, run_id)
            if run is None:
                return None
            return {
                "id": run.id,
                "mode": run.mode.value,
                "status": run.status.value,
                "formula_version": run.formula_version,
                "config_checksum": run.config_checksum,
                "indicator_version": run.indicator_version,
                "requested_start_date": run.requested_start_date,
                "requested_end_date": run.requested_end_date,
                "requested_symbols": run.requested_symbols,
                "success_count": run.success_count,
                "no_data_count": run.no_data_count,
                "failure_count": run.failure_count,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
            }


class SqlAlchemyStrategyRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def active_symbols(self) -> list[str]:
        with session_scope(self.session_factory) as session:
            return list(session.scalars(
                select(SecurityModel.symbol).where(SecurityModel.is_active.is_(True)).order_by(SecurityModel.symbol)
            ).all())

    def load_rule_results(
        self, symbol: str, *, formula_version: str, config_checksum: str,
        start_date: date | None = None, end_date: date | None = None,
    ) -> list[tuple[DailyRules, datetime | None]]:
        with session_scope(self.session_factory) as session:
            statement = (
                select(DailyRuleModel).join(SecurityModel).where(
                    SecurityModel.symbol == symbol,
                    DailyRuleModel.formula_version == formula_version,
                    DailyRuleModel.config_checksum == config_checksum,
                ).order_by(DailyRuleModel.trading_date)
            )
            if start_date is not None:
                statement = statement.where(DailyRuleModel.trading_date >= start_date)
            if end_date is not None:
                statement = statement.where(DailyRuleModel.trading_date <= end_date)
            return [
                (daily_rule_model_to_domain(symbol, item), item.evaluated_at)
                for item in session.scalars(statement).all()
            ]

    def latest_strategy_date(
        self, symbol: str, strategy_name: str, strategy_version: str,
        strategy_config_checksum: str,
    ) -> date | None:
        with session_scope(self.session_factory) as session:
            return session.scalar(
                select(func.max(DailyStrategyResultModel.trading_date)).join(SecurityModel).where(
                    SecurityModel.symbol == symbol,
                    DailyStrategyResultModel.strategy_name == strategy_name,
                    DailyStrategyResultModel.strategy_version == strategy_version,
                    DailyStrategyResultModel.strategy_config_checksum == strategy_config_checksum,
                )
            )

    def upsert_strategy_results(self, results: Sequence[StrategyResult]) -> int:
        if not results:
            return 0
        with session_scope(self.session_factory) as session:
            symbols = {item.symbol for item in results}
            security_ids = dict(session.execute(
                select(SecurityModel.symbol, SecurityModel.id).where(SecurityModel.symbol.in_(symbols))
            ).all())
            rows = [strategy_result_to_row(item, security_ids[item.symbol]) for item in results]
            statement = insert(DailyStrategyResultModel).values(rows)
            statement = statement.on_conflict_do_update(
                constraint="uq_daily_strategy_result_identity",
                set_={
                    "passed": statement.excluded.passed,
                    "evaluation_details": statement.excluded.evaluation_details,
                    "source_rule_formula_version": statement.excluded.source_rule_formula_version,
                    "source_rule_config_checksum": statement.excluded.source_rule_config_checksum,
                    "source_rule_evaluated_at": statement.excluded.source_rule_evaluated_at,
                    "evaluated_at": func.now(),
                },
            )
            session.execute(statement)
            return len(rows)

    def latest_strategy_result(
        self, symbol: str, strategy_name: str, strategy_version: str,
        strategy_config_checksum: str,
    ) -> StrategyResult | None:
        history = self.strategy_history(
            symbol, strategy_name, strategy_version, strategy_config_checksum,
            limit=1, before=None,
        )
        return history[0] if history else None

    def strategy_history(
        self, symbol: str, strategy_name: str, strategy_version: str,
        strategy_config_checksum: str, *, limit: int, before: date | None,
    ) -> list[StrategyResult]:
        with session_scope(self.session_factory) as session:
            statement = (
                select(DailyStrategyResultModel).join(SecurityModel).where(
                    SecurityModel.symbol == symbol,
                    DailyStrategyResultModel.strategy_name == strategy_name,
                    DailyStrategyResultModel.strategy_version == strategy_version,
                    DailyStrategyResultModel.strategy_config_checksum == strategy_config_checksum,
                ).order_by(DailyStrategyResultModel.trading_date.desc()).limit(limit)
            )
            if before is not None:
                statement = statement.where(DailyStrategyResultModel.trading_date < before)
            return [strategy_model_to_domain(symbol, item) for item in session.scalars(statement).all()]


class SqlAlchemyStrategyRunRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create_strategy_run(self, request: StrategyRunRequest) -> UUID:
        with session_scope(self.session_factory) as session:
            run = StrategyRunModel(
                mode=request.mode, status=StrategyRunStatus.RUNNING,
                strategy_name=request.strategy_name, strategy_version=request.strategy_version,
                strategy_config_checksum=request.strategy_config_checksum,
                source_rule_formula_version=request.source_rule_formula_version,
                source_rule_config_checksum=request.source_rule_config_checksum,
                requested_start_date=request.start_date, requested_end_date=request.end_date,
                requested_symbols=len(request.symbols),
            )
            session.add(run)
            session.flush()
            return run.id

    def record_strategy_symbol_result(self, run_id: UUID, result: StrategySymbolResult) -> None:
        with session_scope(self.session_factory) as session:
            session.add(StrategySymbolResultModel(
                run_id=run_id, symbol=result.symbol, status=result.status,
                rows_read=result.rows_read, rows_written=result.rows_written, error=result.error,
            ))

    def finish_strategy_run(self, run_id: UUID) -> None:
        with session_scope(self.session_factory) as session:
            counts = dict(session.execute(
                select(StrategySymbolResultModel.status, func.count(StrategySymbolResultModel.id))
                .where(StrategySymbolResultModel.run_id == run_id)
                .group_by(StrategySymbolResultModel.status)
            ).all())
            success_count = counts.get(StrategySymbolStatus.SUCCESS, 0)
            no_data_count = counts.get(StrategySymbolStatus.NO_DATA, 0)
            failure_count = counts.get(StrategySymbolStatus.FAILED, 0)
            status = StrategyRunStatus.SUCCEEDED if failure_count == 0 else (
                StrategyRunStatus.PARTIAL_FAILURE if success_count + no_data_count > 0 else StrategyRunStatus.FAILED
            )
            session.execute(update(StrategyRunModel).where(StrategyRunModel.id == run_id).values(
                status=status, success_count=success_count, no_data_count=no_data_count,
                failure_count=failure_count, finished_at=datetime.now(UTC),
            ))

    def abandon_strategy_run(self, run_id: UUID) -> None:
        with session_scope(self.session_factory) as session:
            session.execute(update(StrategyRunModel).where(StrategyRunModel.id == run_id).values(
                status=StrategyRunStatus.FAILED, failure_count=1, finished_at=datetime.now(UTC),
            ))

    def get_strategy_run_summary(self, run_id: UUID) -> dict[str, object] | None:
        with session_scope(self.session_factory) as session:
            run = session.get(StrategyRunModel, run_id)
            if run is None:
                return None
            return {
                "id": run.id, "mode": run.mode.value, "status": run.status.value,
                "strategy_name": run.strategy_name, "strategy_version": run.strategy_version,
                "strategy_config_checksum": run.strategy_config_checksum,
                "source_rule_formula_version": run.source_rule_formula_version,
                "source_rule_config_checksum": run.source_rule_config_checksum,
                "requested_start_date": run.requested_start_date, "requested_end_date": run.requested_end_date,
                "requested_symbols": run.requested_symbols, "success_count": run.success_count,
                "no_data_count": run.no_data_count, "failure_count": run.failure_count,
                "started_at": run.started_at, "finished_at": run.finished_at,
            }


class SqlAlchemyScoreRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def active_symbols(self) -> list[str]:
        with session_scope(self.session_factory) as session:
            return list(session.scalars(
                select(SecurityModel.symbol).where(SecurityModel.is_active.is_(True)).order_by(SecurityModel.symbol)
            ).all())

    def load_rule_results(
        self, symbol: str, *, formula_version: str, config_checksum: str,
        start_date: date | None = None, end_date: date | None = None,
    ) -> list[tuple[DailyRules, datetime | None]]:
        with session_scope(self.session_factory) as session:
            statement = select(DailyRuleModel).join(SecurityModel).where(
                SecurityModel.symbol == symbol,
                DailyRuleModel.formula_version == formula_version,
                DailyRuleModel.config_checksum == config_checksum,
            ).order_by(DailyRuleModel.trading_date)
            if start_date is not None:
                statement = statement.where(DailyRuleModel.trading_date >= start_date)
            if end_date is not None:
                statement = statement.where(DailyRuleModel.trading_date <= end_date)
            return [(daily_rule_model_to_domain(symbol, item), item.evaluated_at) for item in session.scalars(statement).all()]

    def latest_score_date(
        self, symbol: str, scoring_version: str, scoring_config_checksum: str
    ) -> date | None:
        with session_scope(self.session_factory) as session:
            return session.scalar(select(func.max(DailyTechnicalScoreModel.trading_date)).join(SecurityModel).where(
                SecurityModel.symbol == symbol,
                DailyTechnicalScoreModel.scoring_version == scoring_version,
                DailyTechnicalScoreModel.scoring_config_checksum == scoring_config_checksum,
            ))

    def upsert_scores(self, scores: Sequence[TechnicalScore]) -> int:
        if not scores:
            return 0
        with session_scope(self.session_factory) as session:
            symbols = {item.symbol for item in scores}
            security_ids = dict(session.execute(
                select(SecurityModel.symbol, SecurityModel.id).where(SecurityModel.symbol.in_(symbols))
            ).all())
            rows = [technical_score_to_row(item, security_ids[item.symbol]) for item in scores]
            statement = insert(DailyTechnicalScoreModel).values(rows)
            statement = statement.on_conflict_do_update(
                constraint="uq_daily_technical_score_identity",
                set_={
                    "score": statement.excluded.score,
                    "rating": statement.excluded.rating,
                    "contributions": statement.excluded.contributions,
                    "source_rule_formula_version": statement.excluded.source_rule_formula_version,
                    "source_rule_config_checksum": statement.excluded.source_rule_config_checksum,
                    "source_rule_evaluated_at": statement.excluded.source_rule_evaluated_at,
                    "scored_at": func.now(),
                },
            )
            session.execute(statement)
            return len(rows)

    def latest_score(
        self, symbol: str, scoring_version: str, scoring_config_checksum: str
    ) -> TechnicalScore | None:
        history = self.score_history(symbol, scoring_version, scoring_config_checksum, limit=1, before=None)
        return history[0] if history else None

    def score_history(
        self, symbol: str, scoring_version: str, scoring_config_checksum: str,
        *, limit: int, before: date | None,
    ) -> list[TechnicalScore]:
        with session_scope(self.session_factory) as session:
            statement = select(DailyTechnicalScoreModel).join(SecurityModel).where(
                SecurityModel.symbol == symbol,
                DailyTechnicalScoreModel.scoring_version == scoring_version,
                DailyTechnicalScoreModel.scoring_config_checksum == scoring_config_checksum,
            ).order_by(DailyTechnicalScoreModel.trading_date.desc()).limit(limit)
            if before is not None:
                statement = statement.where(DailyTechnicalScoreModel.trading_date < before)
            return [technical_score_model_to_domain(symbol, item) for item in session.scalars(statement).all()]


class SqlAlchemyScoreRunRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create_score_run(self, request: ScoreRunRequest) -> UUID:
        with session_scope(self.session_factory) as session:
            run = ScoreRunModel(
                mode=request.mode, status=ScoreRunStatus.RUNNING,
                scoring_version=request.scoring_version,
                scoring_config_checksum=request.scoring_config_checksum,
                source_rule_formula_version=request.source_rule_formula_version,
                source_rule_config_checksum=request.source_rule_config_checksum,
                requested_start_date=request.start_date, requested_end_date=request.end_date,
                requested_symbols=len(request.symbols),
            )
            session.add(run)
            session.flush()
            return run.id

    def record_score_symbol_result(self, run_id: UUID, result: ScoreSymbolResult) -> None:
        with session_scope(self.session_factory) as session:
            session.add(ScoreSymbolResultModel(
                run_id=run_id, symbol=result.symbol, status=result.status,
                rows_read=result.rows_read, rows_written=result.rows_written, error=result.error,
            ))

    def finish_score_run(self, run_id: UUID) -> None:
        with session_scope(self.session_factory) as session:
            counts = dict(session.execute(
                select(ScoreSymbolResultModel.status, func.count(ScoreSymbolResultModel.id))
                .where(ScoreSymbolResultModel.run_id == run_id).group_by(ScoreSymbolResultModel.status)
            ).all())
            success_count = counts.get(ScoreSymbolStatus.SUCCESS, 0)
            no_data_count = counts.get(ScoreSymbolStatus.NO_DATA, 0)
            failure_count = counts.get(ScoreSymbolStatus.FAILED, 0)
            status = ScoreRunStatus.SUCCEEDED if failure_count == 0 else (
                ScoreRunStatus.PARTIAL_FAILURE if success_count + no_data_count > 0 else ScoreRunStatus.FAILED
            )
            session.execute(update(ScoreRunModel).where(ScoreRunModel.id == run_id).values(
                status=status, success_count=success_count, no_data_count=no_data_count,
                failure_count=failure_count, finished_at=datetime.now(UTC),
            ))

    def abandon_score_run(self, run_id: UUID) -> None:
        with session_scope(self.session_factory) as session:
            session.execute(update(ScoreRunModel).where(ScoreRunModel.id == run_id).values(
                status=ScoreRunStatus.FAILED, failure_count=1, finished_at=datetime.now(UTC),
            ))

    def get_score_run_summary(self, run_id: UUID) -> dict[str, object] | None:
        with session_scope(self.session_factory) as session:
            run = session.get(ScoreRunModel, run_id)
            if run is None:
                return None
            return {
                "id": run.id, "mode": run.mode.value, "status": run.status.value,
                "scoring_version": run.scoring_version,
                "scoring_config_checksum": run.scoring_config_checksum,
                "source_rule_formula_version": run.source_rule_formula_version,
                "source_rule_config_checksum": run.source_rule_config_checksum,
                "requested_start_date": run.requested_start_date, "requested_end_date": run.requested_end_date,
                "requested_symbols": run.requested_symbols, "success_count": run.success_count,
                "no_data_count": run.no_data_count, "failure_count": run.failure_count,
                "started_at": run.started_at, "finished_at": run.finished_at,
            }


class SqlAlchemyRankingRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def liquidity_snapshot_date(self, indicator_version: str) -> date | None:
        with session_scope(self.session_factory) as session:
            return session.scalar(select(func.max(DailyIndicatorModel.trading_date)).where(
                DailyIndicatorModel.calculation_version == indicator_version,
                DailyIndicatorModel.provider == "yahoo",
                DailyIndicatorModel.interval == "1d",
            ))

    def source_score_dates(
        self, scoring_version: str, scoring_config_checksum: str,
        *, start_date: date | None, end_date: date | None,
    ) -> list[date]:
        with session_scope(self.session_factory) as session:
            statement = select(DailyTechnicalScoreModel.trading_date).join(SecurityModel).where(
                SecurityModel.is_active.is_(True),
                DailyTechnicalScoreModel.scoring_version == scoring_version,
                DailyTechnicalScoreModel.scoring_config_checksum == scoring_config_checksum,
            ).distinct().order_by(DailyTechnicalScoreModel.trading_date)
            if start_date is not None:
                statement = statement.where(DailyTechnicalScoreModel.trading_date >= start_date)
            if end_date is not None:
                statement = statement.where(DailyTechnicalScoreModel.trading_date <= end_date)
            return list(session.scalars(statement).all())

    def load_scores_for_date(
        self, trading_date: date, scoring_version: str, scoring_config_checksum: str,
    ) -> list[tuple[TechnicalScore, datetime | None]]:
        with session_scope(self.session_factory) as session:
            statement = select(DailyTechnicalScoreModel, SecurityModel.symbol).join(SecurityModel).where(
                SecurityModel.is_active.is_(True),
                DailyTechnicalScoreModel.trading_date == trading_date,
                DailyTechnicalScoreModel.scoring_version == scoring_version,
                DailyTechnicalScoreModel.scoring_config_checksum == scoring_config_checksum,
            ).order_by(SecurityModel.symbol)
            return [
                (technical_score_model_to_domain(symbol, item), item.scored_at)
                for item, symbol in session.execute(statement).all()
            ]

    def latest_ranking_date(
        self, ranking_version: str, ranking_config_checksum: str
    ) -> date | None:
        with session_scope(self.session_factory) as session:
            return session.scalar(select(func.max(DailyRankingModel.trading_date)).where(
                DailyRankingModel.ranking_version == ranking_version,
                DailyRankingModel.ranking_config_checksum == ranking_config_checksum,
            ))

    def latest_completed_run(self, ranking_version: str, ranking_config_checksum: str) -> dict[str, object] | None:
        with session_scope(self.session_factory) as session:
            run = session.scalar(select(RankingRunModel).where(
                RankingRunModel.ranking_version == ranking_version,
                RankingRunModel.ranking_config_checksum == ranking_config_checksum,
                RankingRunModel.finished_at.is_not(None),
            ).order_by(RankingRunModel.finished_at.desc()).limit(1))
            if run is None:
                return None
            return {
                "id": run.id, "status": run.status.value, "started_at": run.started_at,
                "finished_at": run.finished_at, "success_count": run.success_count,
                "no_data_count": run.no_data_count, "failure_count": run.failure_count,
            }

    def replace_rankings(
        self, trading_date: date, ranking_version: str,
        ranking_config_checksum: str, rankings: Sequence[DailyRanking],
    ) -> int:
        with session_scope(self.session_factory) as session:
            session.execute(delete(DailyRankingModel).where(
                DailyRankingModel.trading_date == trading_date,
                DailyRankingModel.ranking_version == ranking_version,
                DailyRankingModel.ranking_config_checksum == ranking_config_checksum,
            ))
            if not rankings:
                return 0
            symbols = {item.symbol for item in rankings}
            security_ids = dict(session.execute(
                select(SecurityModel.symbol, SecurityModel.id).where(SecurityModel.symbol.in_(symbols))
            ).all())
            session.execute(insert(DailyRankingModel).values([
                daily_ranking_to_row(item, security_ids[item.symbol]) for item in rankings
            ]))
            return len(rankings)

    def ranking_snapshot(
        self, ranking_version: str, ranking_config_checksum: str,
        *, trading_date: date | None, rating: str | None, limit: int,
    ) -> tuple[date, list[DailyRanking]] | None:
        with session_scope(self.session_factory) as session:
            selected_date = trading_date
            if selected_date is None:
                selected_date = session.scalar(select(func.max(DailyRankingModel.trading_date)).where(
                    DailyRankingModel.ranking_version == ranking_version,
                    DailyRankingModel.ranking_config_checksum == ranking_config_checksum,
                ))
            if selected_date is None:
                return None
            statement = select(DailyRankingModel, SecurityModel.symbol).join(SecurityModel).where(
                DailyRankingModel.trading_date == selected_date,
                DailyRankingModel.ranking_version == ranking_version,
                DailyRankingModel.ranking_config_checksum == ranking_config_checksum,
            )
            if rating is not None:
                statement = statement.where(func.lower(DailyRankingModel.rating) == rating.lower())
            statement = statement.order_by(DailyRankingModel.rank, SecurityModel.symbol).limit(limit)
            rows = [
                daily_ranking_model_to_domain(symbol, item)
                for item, symbol in session.execute(statement).all()
            ]
            if not rows:
                return None
            return (selected_date, rows)

    def ranking_snapshot_page(
        self, ranking_version: str, ranking_config_checksum: str,
        *, trading_date: date | None, rating: str | None, limit: int, offset: int,
        liquidity_as_of_date: date | None = None, indicator_version: str | None = None,
        min_turnover: Decimal | None = None, liquidity_tiers: tuple[str, ...] = (),
        liquidity_thresholds: dict[str, Decimal] | None = None,
    ):
        with session_scope(self.session_factory) as session:
            selected_date = trading_date or session.scalar(select(func.max(DailyRankingModel.trading_date)).where(
                DailyRankingModel.ranking_version == ranking_version,
                DailyRankingModel.ranking_config_checksum == ranking_config_checksum,
            ))
            if selected_date is None:
                return None
            conditions = [
                DailyRankingModel.trading_date == selected_date,
                DailyRankingModel.ranking_version == ranking_version,
                DailyRankingModel.ranking_config_checksum == ranking_config_checksum,
            ]
            if rating is not None:
                conditions.append(func.lower(DailyRankingModel.rating) == rating.lower())
            unfiltered_total = session.scalar(select(func.count(DailyRankingModel.id)).where(*conditions)) or 0
            statement = select(DailyRankingModel, SecurityModel.symbol).join(SecurityModel)
            if min_turnover is not None or liquidity_tiers:
                indicator = aliased(DailyIndicatorModel)
                statement = statement.join(indicator, (
                    indicator.security_id == DailyRankingModel.security_id
                ) & (indicator.trading_date == liquidity_as_of_date)
                  & (indicator.calculation_version == indicator_version)
                  & (indicator.provider == "yahoo") & (indicator.interval == "1d"))
                if min_turnover is not None:
                    statement = statement.where(indicator.average_traded_value_20 >= min_turnover)
                if liquidity_tiers:
                    thresholds = liquidity_thresholds or {}
                    tier_conditions = []
                    if "high" in liquidity_tiers:
                        tier_conditions.append(indicator.average_traded_value_20 >= thresholds["high"])
                    if "medium" in liquidity_tiers:
                        tier_conditions.append((indicator.average_traded_value_20 >= thresholds["medium"]) & (indicator.average_traded_value_20 < thresholds["high"]))
                    if "low" in liquidity_tiers:
                        tier_conditions.append((indicator.average_traded_value_20 >= thresholds["low"]) & (indicator.average_traded_value_20 < thresholds["medium"]))
                    statement = statement.where(or_(*tier_conditions))
            filtered = statement.where(*conditions)
            total = session.scalar(select(func.count()).select_from(filtered.subquery())) or 0
            rows = session.execute(filtered.order_by(DailyRankingModel.rank, SecurityModel.symbol).offset(offset).limit(limit)).all()
            total_stocks = session.scalar(select(func.count(SecurityModel.id)).where(SecurityModel.is_active.is_(True))) or 0
            return selected_date, [daily_ranking_model_to_domain(symbol, item) for item, symbol in rows], total, unfiltered_total, total_stocks


class SqlAlchemyRankingRunRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create_ranking_run(self, request: RankingRunRequest) -> UUID:
        with session_scope(self.session_factory) as session:
            run = RankingRunModel(
                mode=request.mode,
                status=RankingRunStatus.RUNNING,
                ranking_version=request.ranking_version,
                ranking_config_checksum=request.ranking_config_checksum,
                source_scoring_version=request.source_scoring_version,
                source_scoring_config_checksum=request.source_scoring_config_checksum,
                requested_start_date=request.start_date,
                requested_end_date=request.end_date,
                requested_dates=request.requested_dates,
            )
            session.add(run)
            session.flush()
            return run.id

    def record_ranking_date_result(self, run_id: UUID, result: RankingDateResult) -> None:
        with session_scope(self.session_factory) as session:
            session.add(RankingDateResultModel(
                run_id=run_id, trading_date=result.trading_date, status=result.status,
                rows_read=result.rows_read, rows_written=result.rows_written, error=result.error,
            ))

    def finish_ranking_run(self, run_id: UUID) -> None:
        with session_scope(self.session_factory) as session:
            counts = dict(session.execute(select(
                RankingDateResultModel.status, func.count(RankingDateResultModel.id)
            ).where(RankingDateResultModel.run_id == run_id).group_by(RankingDateResultModel.status)).all())
            success_count = counts.get(RankingDateStatus.SUCCESS, 0)
            no_data_count = counts.get(RankingDateStatus.NO_DATA, 0)
            failure_count = counts.get(RankingDateStatus.FAILED, 0)
            status = (
                RankingRunStatus.SUCCEEDED if failure_count == 0
                else RankingRunStatus.PARTIAL_FAILURE if success_count + no_data_count > 0
                else RankingRunStatus.FAILED
            )
            session.execute(update(RankingRunModel).where(RankingRunModel.id == run_id).values(
                status=status, success_count=success_count, no_data_count=no_data_count,
                failure_count=failure_count, finished_at=datetime.now(UTC),
            ))

    def abandon_ranking_run(self, run_id: UUID) -> None:
        with session_scope(self.session_factory) as session:
            session.execute(update(RankingRunModel).where(RankingRunModel.id == run_id).values(
                status=RankingRunStatus.FAILED, failure_count=1, finished_at=datetime.now(UTC),
            ))

    def get_ranking_run_summary(self, run_id: UUID) -> dict[str, object] | None:
        with session_scope(self.session_factory) as session:
            run = session.get(RankingRunModel, run_id)
            if run is None:
                return None
            return {
                "id": run.id, "mode": run.mode.value, "status": run.status.value,
                "ranking_version": run.ranking_version,
                "ranking_config_checksum": run.ranking_config_checksum,
                "source_scoring_version": run.source_scoring_version,
                "source_scoring_config_checksum": run.source_scoring_config_checksum,
                "requested_start_date": run.requested_start_date,
                "requested_end_date": run.requested_end_date,
                "requested_dates": run.requested_dates,
                "success_count": run.success_count, "no_data_count": run.no_data_count,
                "failure_count": run.failure_count, "started_at": run.started_at,
                "finished_at": run.finished_at,
            }


class SqlAlchemyAnalysisRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def source_ranking_dates(
        self, ranking_version: str, ranking_config_checksum: str,
        *, start_date: date | None, end_date: date | None, minimum_score: int,
    ) -> list[date]:
        with session_scope(self.session_factory) as session:
            statement = select(DailyRankingModel.trading_date).where(
                DailyRankingModel.ranking_version == ranking_version,
                DailyRankingModel.ranking_config_checksum == ranking_config_checksum,
                DailyRankingModel.score >= minimum_score,
            ).distinct().order_by(DailyRankingModel.trading_date)
            if start_date is not None:
                statement = statement.where(DailyRankingModel.trading_date >= start_date)
            if end_date is not None:
                statement = statement.where(DailyRankingModel.trading_date <= end_date)
            return list(session.scalars(statement).all())

    def load_analysis_inputs(
        self, trading_date: date, *, minimum_score: int,
        source_versions: dict[str, str],
    ) -> list[AnalysisInput]:
        with session_scope(self.session_factory) as session:
            ranking_rows = session.execute(
                select(DailyRankingModel, SecurityModel.symbol).join(SecurityModel).where(
                    DailyRankingModel.trading_date == trading_date,
                    DailyRankingModel.ranking_version == source_versions["ranking_version"],
                    DailyRankingModel.ranking_config_checksum == source_versions["ranking_config_checksum"],
                    DailyRankingModel.score >= minimum_score,
                ).order_by(DailyRankingModel.rank, SecurityModel.symbol)
            ).all()
            results = []
            for ranking_model, symbol in ranking_rows:
                indicator = session.scalar(select(DailyIndicatorModel).join(SecurityModel).where(
                    SecurityModel.symbol == symbol,
                    DailyIndicatorModel.trading_date == trading_date,
                    DailyIndicatorModel.calculation_version == source_versions["indicator_version"],
                ))
                rule = session.scalar(select(DailyRuleModel).join(SecurityModel).where(
                    SecurityModel.symbol == symbol,
                    DailyRuleModel.trading_date == trading_date,
                    DailyRuleModel.formula_version == source_versions["rule_formula_version"],
                    DailyRuleModel.config_checksum == source_versions["rule_config_checksum"],
                ))
                strategy = session.scalar(select(DailyStrategyResultModel).join(SecurityModel).where(
                    SecurityModel.symbol == symbol,
                    DailyStrategyResultModel.trading_date == trading_date,
                    DailyStrategyResultModel.strategy_name == source_versions["strategy_name"],
                    DailyStrategyResultModel.strategy_version == source_versions["strategy_version"],
                    DailyStrategyResultModel.strategy_config_checksum == source_versions["strategy_config_checksum"],
                ))
                results.append(AnalysisInput(
                    ranking=daily_ranking_model_to_domain(symbol, ranking_model),
                    indicators=indicator_model_to_domain(symbol, indicator) if indicator else None,
                    rules=daily_rule_model_to_domain(symbol, rule) if rule else None,
                    strategy=strategy_model_to_domain(symbol, strategy) if strategy else None,
                ))
            return results

    def latest_analysis_date(
        self, analysis_version: str, analysis_config_checksum: str
    ) -> date | None:
        with session_scope(self.session_factory) as session:
            return session.scalar(select(func.max(DailyAnalysisModel.trading_date)).where(
                DailyAnalysisModel.analysis_version == analysis_version,
                DailyAnalysisModel.analysis_config_checksum == analysis_config_checksum,
            ))

    def replace_analyses(
        self, trading_date: date, analysis_version: str,
        analysis_config_checksum: str, analyses: Sequence[DailyAnalysis],
    ) -> int:
        with session_scope(self.session_factory) as session:
            session.execute(delete(DailyAnalysisModel).where(
                DailyAnalysisModel.trading_date == trading_date,
                DailyAnalysisModel.analysis_version == analysis_version,
                DailyAnalysisModel.analysis_config_checksum == analysis_config_checksum,
            ))
            if not analyses:
                return 0
            symbols = {item.symbol for item in analyses}
            security_ids = dict(session.execute(select(
                SecurityModel.symbol, SecurityModel.id
            ).where(SecurityModel.symbol.in_(symbols))).all())
            session.execute(insert(DailyAnalysisModel).values([
                daily_analysis_to_row(item, security_ids[item.symbol]) for item in analyses
            ]))
            return len(analyses)

    def latest_analysis(
        self, symbol: str, analysis_version: str, analysis_config_checksum: str
    ) -> DailyAnalysis | None:
        values = self.analysis_history(
            symbol, analysis_version, analysis_config_checksum, limit=1, before=None
        )
        return values[0] if values else None

    def analysis_history(
        self, symbol: str, analysis_version: str, analysis_config_checksum: str,
        *, limit: int, before: date | None,
    ) -> list[DailyAnalysis]:
        with session_scope(self.session_factory) as session:
            statement = select(DailyAnalysisModel).join(SecurityModel).where(
                SecurityModel.symbol == symbol,
                DailyAnalysisModel.analysis_version == analysis_version,
                DailyAnalysisModel.analysis_config_checksum == analysis_config_checksum,
            ).order_by(DailyAnalysisModel.trading_date.desc()).limit(limit)
            if before is not None:
                statement = statement.where(DailyAnalysisModel.trading_date < before)
            return [daily_analysis_model_to_domain(symbol, item) for item in session.scalars(statement).all()]

    def analysis_snapshot(
        self, analysis_version: str, analysis_config_checksum: str,
        *, trading_date: date | None, rating: str | None,
        strategy_status: str | None, limit: int,
    ) -> tuple[date, list[DailyAnalysis]] | None:
        with session_scope(self.session_factory) as session:
            selected_date = trading_date or session.scalar(select(func.max(
                DailyAnalysisModel.trading_date
            )).where(
                DailyAnalysisModel.analysis_version == analysis_version,
                DailyAnalysisModel.analysis_config_checksum == analysis_config_checksum,
            ))
            if selected_date is None:
                return None
            statement = select(DailyAnalysisModel, SecurityModel.symbol).join(SecurityModel).where(
                DailyAnalysisModel.trading_date == selected_date,
                DailyAnalysisModel.analysis_version == analysis_version,
                DailyAnalysisModel.analysis_config_checksum == analysis_config_checksum,
            )
            if rating is not None:
                statement = statement.where(func.lower(DailyAnalysisModel.rating) == rating.lower())
            if strategy_status is not None:
                statement = statement.where(DailyAnalysisModel.strategy_status == strategy_status.lower())
            statement = statement.order_by(DailyAnalysisModel.rank, SecurityModel.symbol).limit(limit)
            values = [daily_analysis_model_to_domain(symbol, item) for item, symbol in session.execute(statement).all()]
            return (selected_date, values) if values else None


class SqlAlchemyAnalysisRunRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create_analysis_run(self, request: AnalysisRunRequest) -> UUID:
        with session_scope(self.session_factory) as session:
            run = AnalysisRunModel(
                mode=request.mode, status=AnalysisRunStatus.RUNNING,
                analysis_version=request.analysis_version,
                analysis_config_checksum=request.analysis_config_checksum,
                requested_start_date=request.start_date, requested_end_date=request.end_date,
                requested_symbols=request.requested_symbols,
            )
            session.add(run)
            session.flush()
            return run.id

    def record_analysis_symbol_result(self, run_id: UUID, result: AnalysisSymbolResult) -> None:
        with session_scope(self.session_factory) as session:
            session.add(AnalysisSymbolResultModel(
                run_id=run_id, symbol=result.symbol, trading_date=result.trading_date,
                status=result.status, rows_read=result.rows_read,
                rows_written=result.rows_written, error=result.error,
            ))

    def finish_analysis_run(self, run_id: UUID) -> None:
        with session_scope(self.session_factory) as session:
            counts = dict(session.execute(select(
                AnalysisSymbolResultModel.status, func.count(AnalysisSymbolResultModel.id)
            ).where(AnalysisSymbolResultModel.run_id == run_id).group_by(
                AnalysisSymbolResultModel.status
            )).all())
            success = counts.get(AnalysisSymbolStatus.SUCCESS, 0)
            no_data = counts.get(AnalysisSymbolStatus.NO_DATA, 0)
            failed = counts.get(AnalysisSymbolStatus.FAILED, 0)
            status = AnalysisRunStatus.SUCCEEDED if failed == 0 else (
                AnalysisRunStatus.PARTIAL_FAILURE if success + no_data else AnalysisRunStatus.FAILED
            )
            session.execute(update(AnalysisRunModel).where(AnalysisRunModel.id == run_id).values(
                status=status, success_count=success, no_data_count=no_data,
                failure_count=failed, finished_at=datetime.now(UTC),
            ))

    def abandon_analysis_run(self, run_id: UUID) -> None:
        with session_scope(self.session_factory) as session:
            session.execute(update(AnalysisRunModel).where(AnalysisRunModel.id == run_id).values(
                status=AnalysisRunStatus.FAILED, failure_count=1, finished_at=datetime.now(UTC),
            ))

    def get_analysis_run_summary(self, run_id: UUID) -> dict[str, object] | None:
        with session_scope(self.session_factory) as session:
            run = session.get(AnalysisRunModel, run_id)
            if run is None:
                return None
            return {
                "id": run.id, "mode": run.mode.value, "status": run.status.value,
                "analysis_version": run.analysis_version,
                "analysis_config_checksum": run.analysis_config_checksum,
                "requested_start_date": run.requested_start_date,
                "requested_end_date": run.requested_end_date,
                "requested_symbols": run.requested_symbols,
                "success_count": run.success_count, "no_data_count": run.no_data_count,
                "failure_count": run.failure_count, "started_at": run.started_at,
                "finished_at": run.finished_at,
            }


class SqlAlchemyRiskRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def source_dates(self, configuration, start_date=None, end_date=None):
        with session_scope(self.session_factory) as session:
            statement = select(DailyRankingModel.trading_date).where(
                DailyRankingModel.ranking_version == configuration.ranking_version,
                DailyRankingModel.ranking_config_checksum == configuration.ranking_config_checksum,
                DailyRankingModel.score >= configuration.minimum_score,
            ).distinct().order_by(DailyRankingModel.trading_date)
            if start_date is not None:
                statement = statement.where(DailyRankingModel.trading_date >= start_date)
            if end_date is not None:
                statement = statement.where(DailyRankingModel.trading_date <= end_date)
            return list(session.scalars(statement).all())

    def load_inputs(self, trading_date, configuration):
        with session_scope(self.session_factory) as session:
            rows = session.execute(
                select(DailyRankingModel, DailyPriceModel, DailyIndicatorModel, SecurityModel.symbol)
                .join(SecurityModel, DailyRankingModel.security_id == SecurityModel.id)
                .join(DailyPriceModel, (DailyPriceModel.security_id == DailyRankingModel.security_id) & (DailyPriceModel.trading_date == DailyRankingModel.trading_date))
                .outerjoin(DailyIndicatorModel, (DailyIndicatorModel.security_id == DailyRankingModel.security_id) & (DailyIndicatorModel.trading_date == DailyRankingModel.trading_date) & (DailyIndicatorModel.calculation_version == configuration.indicator_version))
                .where(
                    DailyRankingModel.trading_date == trading_date,
                    DailyRankingModel.ranking_version == configuration.ranking_version,
                    DailyRankingModel.ranking_config_checksum == configuration.ranking_config_checksum,
                    DailyRankingModel.score >= configuration.minimum_score,
                    DailyPriceModel.provider == "yahoo", DailyPriceModel.interval == "1d",
                ).order_by(DailyRankingModel.rank, SecurityModel.symbol)
            ).all()
            return [RiskInput(
                daily_ranking_model_to_domain(symbol, ranking), price.close,
                indicator.atr_14 if indicator else None,
            ) for ranking, price, indicator, symbol in rows]

    def latest_date(self, risk_version, risk_config_checksum):
        with session_scope(self.session_factory) as session:
            return session.scalar(select(func.max(DailyRiskRecommendationModel.trading_date)).where(
                DailyRiskRecommendationModel.risk_version == risk_version,
                DailyRiskRecommendationModel.risk_config_checksum == risk_config_checksum,
            ))

    def replace(self, trading_date, configuration, recommendations):
        with session_scope(self.session_factory) as session:
            session.execute(delete(DailyRiskRecommendationModel).where(
                DailyRiskRecommendationModel.trading_date == trading_date,
                DailyRiskRecommendationModel.risk_version == configuration.version,
                DailyRiskRecommendationModel.risk_config_checksum == configuration.checksum,
            ))
            symbols = {item.symbol for item in recommendations}
            security_ids = dict(session.execute(select(SecurityModel.symbol, SecurityModel.id).where(SecurityModel.symbol.in_(symbols))).all()) if symbols else {}
            session.add_all([DailyRiskRecommendationModel(
                security_id=security_ids[item.symbol], provider=item.provider, interval=item.interval,
                trading_date=item.trading_date, risk_version=item.risk_version,
                risk_config_checksum=item.risk_config_checksum, entry_price=item.entry_price,
                atr_14=item.atr_14, stop_loss=item.stop_loss, take_profit=item.take_profit,
                risk_amount=item.risk_amount, reward_amount=item.reward_amount,
                take_profit_1=item.take_profit_1, take_profit_2=item.take_profit_2,
                reward_risk_ratio=item.reward_risk_ratio, score=item.score, rating=item.rating,
                suggested_position_size_pct=item.suggested_position_size_pct,
                rank=item.rank, source_indicator_version=item.source_indicator_version,
                source_ranking_version=item.source_ranking_version,
                source_ranking_config_checksum=item.source_ranking_config_checksum,
                disclaimer=item.disclaimer,
            ) for item in recommendations])
            return len(recommendations)

    def list(self, configuration, *, trading_date=None, rating=None, minimum_score=None, limit=10, offset=0):
        with session_scope(self.session_factory) as session:
            resolved_date = trading_date or session.scalar(select(func.max(DailyRiskRecommendationModel.trading_date)).where(
                DailyRiskRecommendationModel.risk_version == configuration.version,
                DailyRiskRecommendationModel.risk_config_checksum == configuration.checksum,
            ))
            if resolved_date is None:
                return None, []
            statement = select(DailyRiskRecommendationModel, SecurityModel.symbol).join(SecurityModel).where(
                DailyRiskRecommendationModel.trading_date == resolved_date,
                DailyRiskRecommendationModel.risk_version == configuration.version,
                DailyRiskRecommendationModel.risk_config_checksum == configuration.checksum,
            )
            if rating:
                statement = statement.where(DailyRiskRecommendationModel.rating == rating)
            if minimum_score is not None:
                statement = statement.where(DailyRiskRecommendationModel.score >= minimum_score)
            rows = session.execute(statement.order_by(DailyRiskRecommendationModel.rank, SecurityModel.symbol).offset(offset).limit(limit)).all()
            return resolved_date, [risk_model_to_dict(item, symbol) for item, symbol in rows]

    def count(self, configuration, *, trading_date=None, rating=None, minimum_score=None):
        with session_scope(self.session_factory) as session:
            resolved_date = trading_date or session.scalar(select(func.max(DailyRiskRecommendationModel.trading_date)).where(
                DailyRiskRecommendationModel.risk_version == configuration.version,
                DailyRiskRecommendationModel.risk_config_checksum == configuration.checksum,
            ))
            if resolved_date is None:
                return 0
            statement = select(func.count(DailyRiskRecommendationModel.id)).where(
                DailyRiskRecommendationModel.trading_date == resolved_date,
                DailyRiskRecommendationModel.risk_version == configuration.version,
                DailyRiskRecommendationModel.risk_config_checksum == configuration.checksum,
            )
            if rating:
                statement = statement.where(DailyRiskRecommendationModel.rating == rating)
            if minimum_score is not None:
                statement = statement.where(DailyRiskRecommendationModel.score >= minimum_score)
            return session.scalar(statement) or 0

    def latest_for_symbol(self, symbol, configuration):
        with session_scope(self.session_factory) as session:
            row = session.execute(select(DailyRiskRecommendationModel).join(SecurityModel).where(
                SecurityModel.symbol == symbol,
                DailyRiskRecommendationModel.risk_version == configuration.version,
                DailyRiskRecommendationModel.risk_config_checksum == configuration.checksum,
            ).order_by(DailyRiskRecommendationModel.trading_date.desc()).limit(1)).scalar_one_or_none()
            return risk_model_to_dict(row, symbol) if row else None

    def history(self, symbol, configuration, limit=10, offset=0):
        with session_scope(self.session_factory) as session:
            rows = session.scalars(select(DailyRiskRecommendationModel).join(SecurityModel).where(
                SecurityModel.symbol == symbol,
                DailyRiskRecommendationModel.risk_version == configuration.version,
                DailyRiskRecommendationModel.risk_config_checksum == configuration.checksum,
            ).order_by(DailyRiskRecommendationModel.trading_date.desc()).offset(offset).limit(limit)).all()
            return [risk_model_to_dict(item, symbol) for item in rows]

    def count_history(self, symbol, configuration):
        with session_scope(self.session_factory) as session:
            return session.scalar(select(func.count(DailyRiskRecommendationModel.id)).join(SecurityModel).where(
                SecurityModel.symbol == symbol,
                DailyRiskRecommendationModel.risk_version == configuration.version,
                DailyRiskRecommendationModel.risk_config_checksum == configuration.checksum,
            )) or 0


class SqlAlchemyRiskRunRepository:
    def __init__(self, session_factory): self.session_factory = session_factory

    def create_run(self, request: RiskRunRequest):
        with session_scope(self.session_factory) as session:
            run = RiskRunModel(mode=request.mode, status=RiskRunStatus.RUNNING,
                risk_version=request.risk_version, risk_config_checksum=request.risk_config_checksum,
                requested_start_date=request.start_date, requested_end_date=request.end_date,
                requested_symbols=request.requested_symbols, success_count=0, no_data_count=0, failure_count=0)
            session.add(run); session.flush(); return run.id

    def record_result(self, run_id, item: RiskSymbolResult):
        with session_scope(self.session_factory) as session:
            session.add(RiskSymbolResultModel(run_id=run_id, symbol=item.symbol, trading_date=item.trading_date,
                status=item.status, rows_read=item.rows_read, rows_written=item.rows_written, error=item.error))

    def finish_run(self, run_id):
        with session_scope(self.session_factory) as session:
            run = session.get(RiskRunModel, run_id)
            counts = dict(session.execute(select(RiskSymbolResultModel.status, func.count()).where(RiskSymbolResultModel.run_id == run_id).group_by(RiskSymbolResultModel.status)).all())
            failed = counts.get(RiskSymbolStatus.FAILED, 0)
            run.success_count = counts.get(RiskSymbolStatus.SUCCESS, 0)
            run.no_data_count = counts.get(RiskSymbolStatus.NO_DATA, 0)
            run.failure_count = failed
            run.status = RiskRunStatus.SUCCEEDED if failed == 0 else RiskRunStatus.PARTIAL_FAILURE if failed < sum(counts.values()) else RiskRunStatus.FAILED
            run.finished_at = datetime.now(UTC)

    def abandon_run(self, run_id):
        with session_scope(self.session_factory) as session:
            session.execute(update(RiskRunModel).where(RiskRunModel.id == run_id).values(status=RiskRunStatus.FAILED, finished_at=datetime.now(UTC)))


RULE_BOOLEAN_FIELDS = (
    "price_above_ma5",
    "price_above_ma10",
    "price_above_ma20",
    "ma5_above_ma10",
    "ma10_above_ma20",
    "volume_spike",
    "breakout_20",
    "high_liquidity",
    "positive_momentum",
    "price_above_ma50",
    "ma20_above_ma50",
    "ma50_above_ma200",
    "pullback_to_ma20",
    "rsi_not_overbought",
    "rsi_not_oversold",
    "macd_bullish_crossover",
    "higher_low_formed",
    "volume_confirmation",
    "ma20_below_ma50",
    "rsi_extreme_overbought",
)


def indicator_model_to_domain(symbol: str, item: DailyIndicatorModel) -> DailyIndicators:
    return DailyIndicators(
        symbol=symbol,
        trading_date=item.trading_date,
        sma_5=item.sma_5,
        sma_10=item.sma_10,
        sma_20=item.sma_20,
        sma_50=item.sma_50,
        sma_200=item.sma_200,
        volume_ma_20=item.volume_ma_20,
        volume_ratio=item.volume_ratio,
        daily_change_percent=item.daily_change_percent,
        atr_14=item.atr_14,
        rsi_14=item.rsi_14,
        macd=item.macd,
        macd_signal=item.macd_signal,
        macd_histogram=item.macd_histogram,
        macd_bullish_crossover=item.macd_bullish_crossover,
        higher_low_formed=item.higher_low_formed,
        highest_high_20=item.highest_high_20,
        lowest_low_20=item.lowest_low_20,
        average_traded_value_20=item.average_traded_value_20,
        source_updated_at=item.source_updated_at,
        calculation_version=item.calculation_version,
        provider=item.provider,
        interval=item.interval,
    )


def risk_model_to_dict(item: DailyRiskRecommendationModel, symbol: str) -> dict[str, object]:
    return {
        "symbol": symbol,
        "trading_date": item.trading_date,
        "risk_version": item.risk_version,
        "risk_config_checksum": item.risk_config_checksum,
        "entry_price": str(item.entry_price),
        "atr_14": str(item.atr_14),
        "stop_loss": str(item.stop_loss),
        "take_profit": str(item.take_profit),
        "take_profit_1": str(item.take_profit_1),
        "take_profit_2": str(item.take_profit_2),
        "risk_amount": str(item.risk_amount),
        "reward_amount": str(item.reward_amount),
        "reward_risk_ratio": str(item.reward_risk_ratio),
        "suggested_position_size_pct": str(item.suggested_position_size_pct),
        "score": item.score,
        "rating": item.rating,
        "rank": item.rank,
        "source_indicator_version": item.source_indicator_version,
        "source_ranking_version": item.source_ranking_version,
        "source_ranking_config_checksum": item.source_ranking_config_checksum,
        "disclaimer": item.disclaimer,
        "generated_at": item.generated_at,
    }


def daily_rule_to_row(item: DailyRules, security_id: UUID) -> dict[str, object]:
    return {
        "security_id": security_id,
        "provider": item.provider,
        "interval": item.interval,
        "trading_date": item.trading_date,
        "formula_version": item.formula_version,
        "config_checksum": item.config_checksum,
        "indicator_version": item.indicator_version,
        **{field: getattr(item, field) for field in RULE_BOOLEAN_FIELDS},
        "candle_updated_at": item.candle_updated_at,
        "indicator_calculated_at": item.indicator_calculated_at,
    }


def daily_rule_model_to_domain(symbol: str, item: DailyRuleModel) -> DailyRules:
    return DailyRules(
        symbol=symbol,
        trading_date=item.trading_date,
        formula_version=item.formula_version,
        config_checksum=item.config_checksum,
        indicator_version=item.indicator_version,
        candle_updated_at=item.candle_updated_at,
        indicator_calculated_at=item.indicator_calculated_at,
        provider=item.provider,
        interval=item.interval,
        **{field: getattr(item, field) for field in RULE_BOOLEAN_FIELDS},
    )


def strategy_result_to_row(item: StrategyResult, security_id: UUID) -> dict[str, object]:
    return {
        "security_id": security_id, "provider": item.provider, "interval": item.interval,
        "trading_date": item.trading_date, "strategy_name": item.strategy_name,
        "strategy_version": item.strategy_version,
        "strategy_config_checksum": item.strategy_config_checksum, "passed": item.passed,
        "evaluation_details": item.evaluation_details,
        "source_rule_formula_version": item.source_rule_formula_version,
        "source_rule_config_checksum": item.source_rule_config_checksum,
        "source_rule_evaluated_at": item.source_rule_evaluated_at,
    }


def strategy_model_to_domain(symbol: str, item: DailyStrategyResultModel) -> StrategyResult:
    return StrategyResult(
        symbol=symbol, trading_date=item.trading_date, strategy_name=item.strategy_name,
        strategy_version=item.strategy_version,
        strategy_config_checksum=item.strategy_config_checksum, passed=item.passed,
        evaluation_details=item.evaluation_details,
        source_rule_formula_version=item.source_rule_formula_version,
        source_rule_config_checksum=item.source_rule_config_checksum,
        source_rule_evaluated_at=item.source_rule_evaluated_at,
        provider=item.provider, interval=item.interval,
    )


def technical_score_to_row(item: TechnicalScore, security_id: UUID) -> dict[str, object]:
    return {
        "security_id": security_id, "provider": item.provider, "interval": item.interval,
        "trading_date": item.trading_date, "scoring_version": item.scoring_version,
        "scoring_config_checksum": item.scoring_config_checksum, "score": item.score,
        "rating": item.rating, "contributions": item.contributions,
        "source_rule_formula_version": item.source_rule_formula_version,
        "source_rule_config_checksum": item.source_rule_config_checksum,
        "source_rule_evaluated_at": item.source_rule_evaluated_at,
    }


def technical_score_model_to_domain(symbol: str, item: DailyTechnicalScoreModel) -> TechnicalScore:
    return TechnicalScore(
        symbol=symbol, trading_date=item.trading_date, scoring_version=item.scoring_version,
        scoring_config_checksum=item.scoring_config_checksum, score=item.score,
        rating=item.rating, contributions=item.contributions,
        source_rule_formula_version=item.source_rule_formula_version,
        source_rule_config_checksum=item.source_rule_config_checksum,
        source_rule_evaluated_at=item.source_rule_evaluated_at,
        provider=item.provider, interval=item.interval,
    )


def daily_ranking_to_row(item: DailyRanking, security_id: UUID) -> dict[str, object]:
    return {
        "security_id": security_id, "provider": item.provider, "interval": item.interval,
        "trading_date": item.trading_date, "ranking_version": item.ranking_version,
        "ranking_config_checksum": item.ranking_config_checksum, "rank": item.rank,
        "score": item.score, "rating": item.rating,
        "source_scoring_version": item.source_scoring_version,
        "source_scoring_config_checksum": item.source_scoring_config_checksum,
        "source_scored_at": item.source_scored_at,
    }


def daily_ranking_model_to_domain(symbol: str, item: DailyRankingModel) -> DailyRanking:
    return DailyRanking(
        symbol=symbol, trading_date=item.trading_date, rank=item.rank,
        score=item.score, rating=item.rating, ranking_version=item.ranking_version,
        ranking_config_checksum=item.ranking_config_checksum,
        source_scoring_version=item.source_scoring_version,
        source_scoring_config_checksum=item.source_scoring_config_checksum,
        source_scored_at=item.source_scored_at, provider=item.provider, interval=item.interval,
    )


def daily_analysis_to_row(item: DailyAnalysis, security_id: UUID) -> dict[str, object]:
    return {
        "security_id": security_id, "provider": item.provider, "interval": item.interval,
        "trading_date": item.trading_date, "analysis_version": item.analysis_version,
        "analysis_config_checksum": item.analysis_config_checksum,
        "narrative": item.narrative, "bullish_reasons": list(item.bullish_reasons),
        "caution_reasons": list(item.caution_reasons),
        "source_availability": item.source_availability,
        "strategy_status": item.strategy_status, "score": item.score,
        "rating": item.rating, "rank": item.rank, "disclaimer": item.disclaimer,
        "source_versions": item.source_versions,
    }


def daily_analysis_model_to_domain(symbol: str, item: DailyAnalysisModel) -> DailyAnalysis:
    return DailyAnalysis(
        symbol=symbol, trading_date=item.trading_date,
        analysis_version=item.analysis_version,
        analysis_config_checksum=item.analysis_config_checksum,
        narrative=item.narrative, bullish_reasons=tuple(item.bullish_reasons),
        caution_reasons=tuple(item.caution_reasons),
        source_availability=item.source_availability,
        strategy_status=item.strategy_status, score=item.score, rating=item.rating,
        rank=item.rank, disclaimer=item.disclaimer, source_versions=item.source_versions,
        provider=item.provider, interval=item.interval,
    )


class SqlAlchemyAlertRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def source_dates(self, analysis_version: str, analysis_checksum: str, *, start_date=None, end_date=None) -> list[date]:
        with session_scope(self.session_factory) as session:
            statement = select(DailyAnalysisModel.trading_date).where(
                DailyAnalysisModel.analysis_version == analysis_version,
                DailyAnalysisModel.analysis_config_checksum == analysis_checksum,
            ).distinct().order_by(DailyAnalysisModel.trading_date)
            if start_date is not None:
                statement = statement.where(DailyAnalysisModel.trading_date >= start_date)
            if end_date is not None:
                statement = statement.where(DailyAnalysisModel.trading_date <= end_date)
            return list(session.scalars(statement).all())

    def load_states(self, trading_date: date, source_versions: dict[str, str]) -> list[AlertSourceState]:
        with session_scope(self.session_factory) as session:
            analyses = session.execute(select(DailyAnalysisModel, SecurityModel.symbol).join(SecurityModel).where(
                DailyAnalysisModel.trading_date == trading_date,
                DailyAnalysisModel.analysis_version == source_versions["analysis_version"],
                DailyAnalysisModel.analysis_config_checksum == source_versions["analysis_config_checksum"],
            ).order_by(SecurityModel.symbol)).all()
            states = []
            for analysis, symbol in analyses:
                rule = session.scalar(select(DailyRuleModel).join(SecurityModel).where(
                    SecurityModel.symbol == symbol,
                    DailyRuleModel.trading_date == trading_date,
                    DailyRuleModel.formula_version == source_versions["rule_formula_version"],
                    DailyRuleModel.config_checksum == source_versions["rule_config_checksum"],
                ))
                states.append(AlertSourceState(
                    symbol=symbol, trading_date=trading_date, score=analysis.score,
                    rating=analysis.rating, rank=analysis.rank,
                    strategy_status=analysis.strategy_status,
                    breakout_20=rule.breakout_20 if rule else None,
                    volume_spike=rule.volume_spike if rule else None,
                    ma20_below_ma50=rule.ma20_below_ma50 if rule else None,
                    bullish_reasons=tuple(analysis.bullish_reasons),
                    caution_reasons=tuple(analysis.caution_reasons),
                    source_versions=analysis.source_versions,
                    close=self._alert_close(session, symbol, trading_date),
                    stop_loss=self._alert_risk(session, symbol, trading_date, "stop_loss"),
                    take_profit_1=self._alert_risk(session, symbol, trading_date, "take_profit_1"),
                    take_profit_2=self._alert_risk(session, symbol, trading_date, "take_profit_2"),
                    position_event_types=tuple(session.scalars(select(PositionEventModel.event_type).where(
                        PositionEventModel.symbol == symbol,
                        PositionEventModel.trading_date == trading_date,
                    )).all()),
                ))
            return states

    @staticmethod
    def _alert_close(session, symbol: str, trading_date: date):
        return session.scalar(select(DailyPriceModel.close).join(SecurityModel).where(
            SecurityModel.symbol == symbol, DailyPriceModel.trading_date == trading_date
        ))

    @staticmethod
    def _alert_risk(session, symbol: str, trading_date: date, field: str):
        model = session.scalar(select(DailyRiskRecommendationModel).join(SecurityModel).where(
            SecurityModel.symbol == symbol,
            DailyRiskRecommendationModel.trading_date == trading_date,
        ).order_by(DailyRiskRecommendationModel.id.desc()))
        return getattr(model, field, None) if model else None

    def previous_state(self, symbol: str, before: date, source_versions: dict[str, str]) -> AlertSourceState | None:
        with session_scope(self.session_factory) as session:
            previous_date = session.scalar(select(func.max(DailyAnalysisModel.trading_date)).join(SecurityModel).where(
                SecurityModel.symbol == symbol,
                DailyAnalysisModel.trading_date < before,
                DailyAnalysisModel.analysis_version == source_versions["analysis_version"],
                DailyAnalysisModel.analysis_config_checksum == source_versions["analysis_config_checksum"],
            ))
        if previous_date is None:
            return None
        return next((item for item in self.load_states(previous_date, source_versions) if item.symbol == symbol), None)

    def save_event(self, event: AlertEvent) -> bool:
        with session_scope(self.session_factory) as session:
            statement = insert(AlertEventModel).values(alert_event_to_row(event)).on_conflict_do_nothing(
                constraint="uq_alert_event_identity"
            )
            return bool(session.execute(statement).rowcount)

    def get_watermark(self, version: str, checksum: str) -> date | None:
        with session_scope(self.session_factory) as session:
            model = session.get(AlertWatermarkModel, 1)
            if model is None or model.alert_version != version or model.alert_config_checksum != checksum:
                return None
            return model.last_processed_date

    def set_watermark(self, version: str, checksum: str, trading_date: date) -> None:
        with session_scope(self.session_factory) as session:
            statement = insert(AlertWatermarkModel).values(
                id=1, alert_version=version, alert_config_checksum=checksum,
                last_processed_date=trading_date,
            ).on_conflict_do_update(index_elements=[AlertWatermarkModel.id], set_={
                "alert_version": version, "alert_config_checksum": checksum,
                "last_processed_date": trading_date, "updated_at": func.now(),
            })
            session.execute(statement)

    def pending_events(self, maximum_attempts: int, limit: int) -> list[AlertEvent]:
        with session_scope(self.session_factory) as session:
            statement = select(AlertEventModel).where(
                AlertEventModel.delivery_status.in_([AlertDeliveryStatus.PENDING, AlertDeliveryStatus.FAILED]),
                AlertEventModel.delivery_attempts < maximum_attempts,
            ).order_by(AlertEventModel.trading_date, AlertEventModel.symbol).limit(limit)
            return [alert_model_to_domain(item) for item in session.scalars(statement).all()]

    def record_delivery(self, alert_id: UUID, *, succeeded: bool, error: str | None) -> None:
        with session_scope(self.session_factory) as session:
            session.add(AlertDeliveryAttemptModel(alert_id=alert_id, succeeded=succeeded, error=error))
            session.execute(update(AlertEventModel).where(AlertEventModel.id == alert_id).values(
                delivery_status=AlertDeliveryStatus.SENT if succeeded else AlertDeliveryStatus.FAILED,
                delivery_attempts=AlertEventModel.delivery_attempts + 1,
                last_error=None if succeeded else error,
                sent_at=datetime.now(UTC) if succeeded else None,
            ))

    def list_alerts(self, *, trading_date=None, symbol=None, trigger=None, delivery_status=None, limit=100) -> list[AlertEvent]:
        with session_scope(self.session_factory) as session:
            statement = select(AlertEventModel)
            if trading_date is not None:
                statement = statement.where(AlertEventModel.trading_date == trading_date)
            if symbol is not None:
                statement = statement.where(AlertEventModel.symbol == symbol)
            if trigger is not None:
                statement = statement.where(AlertEventModel.triggers.contains([trigger]))
            if delivery_status is not None:
                statement = statement.where(AlertEventModel.delivery_status == delivery_status)
            statement = statement.order_by(AlertEventModel.trading_date.desc(), AlertEventModel.symbol).limit(limit)
            return [alert_model_to_domain(item) for item in session.scalars(statement).all()]

    def get_alert(self, alert_id: UUID) -> AlertEvent | None:
        with session_scope(self.session_factory) as session:
            item = session.get(AlertEventModel, alert_id)
            return alert_model_to_domain(item) if item else None


class SqlAlchemyAlertRunRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create(self, mode: AlertRunMode) -> UUID:
        with session_scope(self.session_factory) as session:
            model = AlertRunModel(mode=mode, status=AlertRunStatus.RUNNING)
            session.add(model)
            session.flush()
            return model.id

    def finish(self, run_id: UUID, generated: int, sent: int, failed: int) -> None:
        status = AlertRunStatus.SUCCEEDED if failed == 0 else (
            AlertRunStatus.PARTIAL_FAILURE if generated or sent else AlertRunStatus.FAILED
        )
        with session_scope(self.session_factory) as session:
            session.execute(update(AlertRunModel).where(AlertRunModel.id == run_id).values(
                status=status, generated_count=generated, sent_count=sent,
                failure_count=failed, finished_at=datetime.now(UTC),
            ))

    def get(self, run_id: UUID) -> dict[str, object] | None:
        with session_scope(self.session_factory) as session:
            run = session.get(AlertRunModel, run_id)
            if not run:
                return None
            return {"id": run.id, "mode": run.mode.value, "status": run.status.value,
                    "generated_count": run.generated_count, "sent_count": run.sent_count,
                    "failure_count": run.failure_count, "started_at": run.started_at,
                    "finished_at": run.finished_at}


def alert_event_to_row(item: AlertEvent) -> dict[str, object]:
    return {"id": item.id, "symbol": item.symbol, "trading_date": item.trading_date,
            "alert_version": item.alert_version, "alert_config_checksum": item.alert_config_checksum,
            "triggers": list(item.triggers), "message": item.message,
            "current_score": item.current_score, "previous_score": item.previous_score,
            "current_rating": item.current_rating, "previous_rating": item.previous_rating,
            "rank": item.rank, "strategy_status": item.strategy_status,
            "bullish_reasons": list(item.bullish_reasons), "caution_reasons": list(item.caution_reasons),
            "source_versions": item.source_versions, "delivery_status": item.delivery_status,
            "delivery_attempts": item.delivery_attempts, "last_error": item.last_error,
            "sent_at": item.sent_at}


def alert_model_to_domain(item: AlertEventModel) -> AlertEvent:
    return AlertEvent(id=item.id, symbol=item.symbol, trading_date=item.trading_date,
        alert_version=item.alert_version, alert_config_checksum=item.alert_config_checksum,
        triggers=tuple(item.triggers), message=item.message, current_score=item.current_score,
        previous_score=item.previous_score, current_rating=item.current_rating,
        previous_rating=item.previous_rating, rank=item.rank, strategy_status=item.strategy_status,
        bullish_reasons=tuple(item.bullish_reasons), caution_reasons=tuple(item.caution_reasons),
        source_versions=item.source_versions, delivery_status=item.delivery_status,
        delivery_attempts=item.delivery_attempts, last_error=item.last_error, sent_at=item.sent_at)


class SqlAlchemyBacktestRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def load_sources(self, strategy_name, strategy_version, strategy_checksum, start_date, end_date):
        with session_scope(self.session_factory) as session:
            signal_rows = session.execute(select(DailyStrategyResultModel, SecurityModel.symbol).join(SecurityModel).where(
                DailyStrategyResultModel.strategy_name == strategy_name,
                DailyStrategyResultModel.strategy_version == strategy_version,
                DailyStrategyResultModel.strategy_config_checksum == strategy_checksum,
                DailyStrategyResultModel.trading_date >= start_date,
                DailyStrategyResultModel.trading_date <= end_date,
            ).order_by(SecurityModel.symbol, DailyStrategyResultModel.trading_date)).all()
            signals = [strategy_model_to_domain(symbol, item) for item, symbol in signal_rows]
            if strategy_name.casefold() == "swing trend following":
                enriched = []
                for signal in signals:
                    indicator = session.scalar(select(DailyIndicatorModel).join(SecurityModel).where(
                        SecurityModel.symbol == signal.symbol,
                        DailyIndicatorModel.trading_date == signal.trading_date,
                        DailyIndicatorModel.calculation_version == "technical-v3",
                    ))
                    details = dict(signal.evaluation_details)
                    if indicator and indicator.atr_14 is not None:
                        details["atr_14"] = str(indicator.atr_14)
                    enriched.append(StrategyResult(
                        signal.symbol, signal.trading_date, signal.strategy_name,
                        signal.strategy_version, signal.strategy_config_checksum,
                        signal.passed, details, signal.source_rule_formula_version,
                        signal.source_rule_config_checksum, signal.source_rule_evaluated_at,
                        signal.provider, signal.interval,
                    ))
                signals = enriched
            symbols = sorted({item.symbol for item in signals})
            candles = {}
            for symbol in symbols:
                rows = session.scalars(select(DailyPriceModel).join(SecurityModel).where(
                    SecurityModel.symbol == symbol,
                    DailyPriceModel.trading_date >= start_date,
                ).order_by(DailyPriceModel.trading_date)).all()
                candles[symbol] = [DailyCandle(symbol, item.trading_date, item.open, item.high, item.low, item.close, item.adjusted_close, item.volume, item.provider, item.interval) for item in rows]
            return signals, candles

    def save_run(self, configuration, start_date, end_date, result: BacktestResult) -> UUID:
        with session_scope(self.session_factory) as session:
            run = BacktestRunModel(status=BacktestRunStatus.SUCCEEDED,
                backtest_version=configuration.version, backtest_config_checksum=configuration.checksum,
                strategy_name=configuration.strategy_name, strategy_version=configuration.strategy_version,
                strategy_config_checksum=configuration.strategy_config_checksum,
                start_date=start_date, end_date=end_date, metrics=metrics_to_dict(result.aggregate),
                finished_at=datetime.now(UTC))
            session.add(run); session.flush()
            session.add_all([BacktestTradeModel(run_id=run.id, **trade_to_dict(item)) for item in result.trades])
            session.add_all([BacktestSymbolMetricModel(run_id=run.id, symbol=symbol, metrics=metrics_to_dict(metrics)) for symbol, metrics in result.symbols.items()])
            return run.id

    def list_runs(self, limit=100):
        with session_scope(self.session_factory) as session:
            return [backtest_run_to_dict(item) for item in session.scalars(select(BacktestRunModel).order_by(BacktestRunModel.started_at.desc()).limit(limit)).all()]

    def get_run(self, run_id):
        with session_scope(self.session_factory) as session:
            item = session.get(BacktestRunModel, run_id)
            return backtest_run_to_dict(item) if item else None

    def symbol_metrics(self, run_id, limit=None, offset=0):
        with session_scope(self.session_factory) as session:
            statement = select(BacktestSymbolMetricModel).where(BacktestSymbolMetricModel.run_id == run_id).order_by(BacktestSymbolMetricModel.symbol).offset(offset)
            if limit is not None:
                statement = statement.limit(limit)
            return [{"symbol": item.symbol, **item.metrics} for item in session.scalars(statement).all()]

    def count_symbol_metrics(self, run_id):
        with session_scope(self.session_factory) as session:
            return session.scalar(select(func.count(BacktestSymbolMetricModel.id)).where(BacktestSymbolMetricModel.run_id == run_id)) or 0

    def trades(self, run_id, *, symbol=None, limit=100, offset=0):
        with session_scope(self.session_factory) as session:
            statement = select(BacktestTradeModel).where(BacktestTradeModel.run_id == run_id)
            if symbol: statement = statement.where(BacktestTradeModel.symbol == symbol)
            statement = statement.order_by(BacktestTradeModel.exit_date, BacktestTradeModel.symbol).offset(offset).limit(limit)
            return [trade_model_to_dict(item) for item in session.scalars(statement).all()]

    def count_trades(self, run_id, *, symbol=None):
        with session_scope(self.session_factory) as session:
            statement = select(func.count(BacktestTradeModel.id)).where(BacktestTradeModel.run_id == run_id)
            if symbol:
                statement = statement.where(BacktestTradeModel.symbol == symbol)
            return session.scalar(statement) or 0


def decimal_json(value):
    return None if value is None else str(value)


def metrics_to_dict(item: BacktestMetrics):
    return {"signal_count": item.signal_count, "completed_trades": item.completed_trades,
        "unclosed_signals": item.unclosed_signals, "wins": item.wins, "losses": item.losses,
        "win_rate": decimal_json(item.win_rate), "average_gross_return": decimal_json(item.average_gross_return),
        "average_net_return": decimal_json(item.average_net_return), "total_compounded_return": decimal_json(item.total_compounded_return),
        "gross_profit": decimal_json(item.gross_profit), "gross_loss": decimal_json(item.gross_loss),
        "profit_factor": decimal_json(item.profit_factor), "maximum_drawdown": decimal_json(item.maximum_drawdown),
        "sharpe_ratio": decimal_json(item.sharpe_ratio)}


def trade_to_dict(item: BacktestTrade):
    return {"symbol": item.symbol, "signal_date": item.signal_date, "exit_date": item.exit_date,
        "entry_price": item.entry_price, "exit_price": item.exit_price, "gross_return": item.gross_return,
        "net_return": item.net_return, "buy_fee": item.buy_fee, "sell_fee": item.sell_fee,
        "gross_profit": item.gross_profit, "net_profit": item.net_profit, "holding_sessions": item.holding_sessions}


def trade_model_to_dict(item):
    return {"symbol": item.symbol, "signal_date": item.signal_date, "exit_date": item.exit_date,
        "entry_price": str(item.entry_price), "exit_price": str(item.exit_price), "gross_return": str(item.gross_return),
        "net_return": str(item.net_return), "buy_fee": str(item.buy_fee), "sell_fee": str(item.sell_fee),
        "gross_profit": str(item.gross_profit), "net_profit": str(item.net_profit), "holding_sessions": item.holding_sessions}


def backtest_run_to_dict(item):
    return {"id": item.id, "status": item.status.value, "backtest_version": item.backtest_version,
        "backtest_config_checksum": item.backtest_config_checksum, "strategy": item.strategy_name,
        "strategy_version": item.strategy_version, "strategy_config_checksum": item.strategy_config_checksum,
        "start_date": item.start_date, "end_date": item.end_date, "metrics": item.metrics,
        "started_at": item.started_at, "finished_at": item.finished_at}


class SqlAlchemyOptimizationRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def load_sources(self, indicator_version: str, start_date: date, end_date: date):
        with session_scope(self.session_factory) as session:
            rows = session.execute(select(DailyPriceModel, DailyIndicatorModel, SecurityModel.symbol)
                .join(SecurityModel, DailyPriceModel.security_id == SecurityModel.id)
                .join(DailyIndicatorModel, (DailyIndicatorModel.security_id == DailyPriceModel.security_id) &
                      (DailyIndicatorModel.trading_date == DailyPriceModel.trading_date))
                .where(DailyPriceModel.trading_date >= start_date,
                       DailyPriceModel.trading_date <= end_date,
                       DailyIndicatorModel.calculation_version == indicator_version,
                       DailyPriceModel.provider == "yahoo",
                       DailyPriceModel.interval == "1d",
                       DailyIndicatorModel.provider == "yahoo",
                       DailyIndicatorModel.interval == "1d")
                .order_by(SecurityModel.symbol, DailyPriceModel.trading_date)).all()
            sources = []
            symbols = set()
            for price, indicator, symbol in rows:
                candle = DailyCandle(symbol, price.trading_date, price.open, price.high, price.low,
                    price.close, price.adjusted_close, price.volume, price.provider, price.interval)
                sources.append((candle, indicator_model_to_domain(symbol, indicator)))
                symbols.add(symbol)
            candles = {}
            for symbol in symbols:
                price_rows = session.scalars(select(DailyPriceModel).join(SecurityModel).where(
                    SecurityModel.symbol == symbol,
                    DailyPriceModel.trading_date >= start_date,
                    DailyPriceModel.provider == "yahoo",
                    DailyPriceModel.interval == "1d",
                ).order_by(DailyPriceModel.trading_date)).all()
                candles[symbol] = [DailyCandle(symbol, item.trading_date, item.open, item.high, item.low,
                    item.close, item.adjusted_close, item.volume, item.provider, item.interval) for item in price_rows]
            return sources, candles

    def save_result(self, configuration, strategy_name, start_date, end_date, result: OptimizationResult) -> UUID:
        with session_scope(self.session_factory) as session:
            run = OptimizationRunModel(status=OptimizationRunStatus.SUCCEEDED,
                optimization_version=configuration.version,
                optimization_config_checksum=configuration.checksum,
                strategy_name=strategy_name, start_date=start_date, end_date=end_date,
                training_start=result.training_start, training_end=result.training_end,
                validation_start=result.validation_start, validation_end=result.validation_end,
                winner_id=result.winner_id, finished_at=datetime.now(UTC))
            session.add(run); session.flush()
            session.add_all([OptimizationCandidateModel(
                run_id=run.id, candidate_id=item.candidate_id, parameters=item.parameters,
                eligible=item.eligible, ineligible_reason=item.ineligible_reason, rank=item.rank,
                training_metrics=metrics_to_dict(item.training_metrics),
                validation_metrics=metrics_to_dict(item.validation_metrics),
            ) for item in result.candidates])
            if result.winner_id and result.winner_backtest:
                session.add_all([OptimizationWinnerTradeModel(
                    run_id=run.id, candidate_id=result.winner_id, symbol=item.symbol,
                    signal_date=item.signal_date, exit_date=item.exit_date,
                    trade=trade_to_json(item),
                ) for item in result.winner_backtest.trades])
                session.add_all([OptimizationWinnerSymbolModel(
                    run_id=run.id, symbol=symbol, metrics=metrics_to_dict(metrics)
                ) for symbol, metrics in result.winner_backtest.symbols.items()])
            return run.id

    def list_runs(self, limit=100):
        with session_scope(self.session_factory) as session:
            return [optimization_run_to_dict(item) for item in session.scalars(
                select(OptimizationRunModel).order_by(OptimizationRunModel.started_at.desc()).limit(limit)
            ).all()]

    def get_run(self, run_id):
        with session_scope(self.session_factory) as session:
            item = session.get(OptimizationRunModel, run_id)
            return optimization_run_to_dict(item) if item else None

    def candidates(self, run_id, limit=100, offset=0):
        with session_scope(self.session_factory) as session:
            rows = session.scalars(select(OptimizationCandidateModel).where(
                OptimizationCandidateModel.run_id == run_id).order_by(
                OptimizationCandidateModel.eligible.desc(),
                OptimizationCandidateModel.rank.asc().nulls_last(),
                OptimizationCandidateModel.candidate_id,
            ).offset(offset).limit(limit)).all()
            return [optimization_candidate_to_dict(item) for item in rows]

    def count_candidates(self, run_id):
        with session_scope(self.session_factory) as session:
            return session.scalar(select(func.count(OptimizationCandidateModel.id)).where(OptimizationCandidateModel.run_id == run_id)) or 0

    def candidate(self, run_id, candidate_id):
        with session_scope(self.session_factory) as session:
            item = session.scalar(select(OptimizationCandidateModel).where(
                OptimizationCandidateModel.run_id == run_id,
                OptimizationCandidateModel.candidate_id == candidate_id,
            ))
            return optimization_candidate_to_dict(item) if item else None

    def winner(self, run_id):
        run = self.get_run(run_id)
        return self.candidate(run_id, run["winner_id"]) if run and run["winner_id"] else None

    def winner_trades(self, run_id, limit=100, offset=0):
        with session_scope(self.session_factory) as session:
            return [item.trade for item in session.scalars(select(OptimizationWinnerTradeModel).where(
                OptimizationWinnerTradeModel.run_id == run_id).order_by(
                OptimizationWinnerTradeModel.exit_date, OptimizationWinnerTradeModel.symbol
            ).offset(offset).limit(limit)).all()]

    def count_winner_trades(self, run_id):
        with session_scope(self.session_factory) as session:
            return session.scalar(select(func.count(OptimizationWinnerTradeModel.id)).where(OptimizationWinnerTradeModel.run_id == run_id)) or 0

    def winner_symbols(self, run_id, limit=None, offset=0):
        with session_scope(self.session_factory) as session:
            statement = select(OptimizationWinnerSymbolModel).where(
                    OptimizationWinnerSymbolModel.run_id == run_id
                ).order_by(OptimizationWinnerSymbolModel.symbol).offset(offset)
            if limit is not None:
                statement = statement.limit(limit)
            return [{"symbol": item.symbol, **item.metrics} for item in session.scalars(statement).all()]

    def count_winner_symbols(self, run_id):
        with session_scope(self.session_factory) as session:
            return session.scalar(select(func.count(OptimizationWinnerSymbolModel.id)).where(OptimizationWinnerSymbolModel.run_id == run_id)) or 0


def trade_to_json(item):
    return {
        key: value.isoformat() if isinstance(value, (date, datetime))
        else str(value) if isinstance(value, Decimal)
        else value
        for key, value in trade_to_dict(item).items()
    }


def optimization_run_to_dict(item):
    return {"id": item.id, "status": item.status.value,
        "optimization_version": item.optimization_version,
        "optimization_config_checksum": item.optimization_config_checksum,
        "strategy": item.strategy_name, "start_date": item.start_date, "end_date": item.end_date,
        "training_start": item.training_start, "training_end": item.training_end,
        "validation_start": item.validation_start, "validation_end": item.validation_end,
        "winner_id": item.winner_id, "started_at": item.started_at, "finished_at": item.finished_at}


def optimization_candidate_to_dict(item):
    return {"candidate_id": item.candidate_id, "parameters": item.parameters,
        "eligible": item.eligible, "ineligible_reason": item.ineligible_reason,
        "rank": item.rank, "training_metrics": item.training_metrics,
        "validation_metrics": item.validation_metrics}


class SqlAlchemyPositionRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def rebuild(self, configuration) -> None:
        with session_scope(self.session_factory) as session:
            ids = list(session.scalars(select(VirtualPositionModel.id).where(
                VirtualPositionModel.lifecycle_version == configuration.version,
                VirtualPositionModel.lifecycle_config_checksum == configuration.checksum,
            )).all())
            if ids:
                session.execute(delete(PositionEventModel).where(PositionEventModel.position_id.in_(ids)))
                session.execute(delete(VirtualPositionModel).where(VirtualPositionModel.id.in_(ids)))

    def source_dates(self, configuration, start_date=None, end_date=None) -> list[date]:
        with session_scope(self.session_factory) as session:
            statement = select(DailyPriceModel.trading_date).where(
                DailyPriceModel.provider == "yahoo",
                DailyPriceModel.interval == "1d",
            ).distinct().order_by(DailyPriceModel.trading_date)
            if start_date is not None:
                statement = statement.where(DailyPriceModel.trading_date >= start_date)
            if end_date is not None:
                statement = statement.where(DailyPriceModel.trading_date <= end_date)
            return list(session.scalars(statement).all())

    def load_sources(self, trading_date: date, configuration) -> list[PositionSourceDay]:
        with session_scope(self.session_factory) as session:
            strategy = aliased(DailyStrategyResultModel)
            indicator = aliased(DailyIndicatorModel)
            rule = aliased(DailyRuleModel)
            risk = aliased(DailyRiskRecommendationModel)
            rows = session.execute(
                select(
                    DailyPriceModel,
                    SecurityModel.symbol,
                    strategy.passed,
                    indicator.atr_14,
                    rule.ma20_below_ma50,
                    rule.rsi_extreme_overbought,
                    risk.suggested_position_size_pct,
                )
                .join(SecurityModel, SecurityModel.id == DailyPriceModel.security_id)
                .outerjoin(
                    strategy,
                    (strategy.security_id == DailyPriceModel.security_id)
                    & (strategy.provider == DailyPriceModel.provider)
                    & (strategy.interval == DailyPriceModel.interval)
                    & (strategy.trading_date == DailyPriceModel.trading_date)
                    & (strategy.strategy_name == configuration.strategy_name)
                    & (strategy.strategy_version == configuration.strategy_version)
                    & (strategy.strategy_config_checksum == configuration.strategy_config_checksum),
                )
                .outerjoin(
                    indicator,
                    (indicator.security_id == DailyPriceModel.security_id)
                    & (indicator.provider == DailyPriceModel.provider)
                    & (indicator.interval == DailyPriceModel.interval)
                    & (indicator.trading_date == DailyPriceModel.trading_date)
                    & (indicator.calculation_version == configuration.indicator_version),
                )
                .outerjoin(
                    rule,
                    (rule.security_id == DailyPriceModel.security_id)
                    & (rule.provider == DailyPriceModel.provider)
                    & (rule.interval == DailyPriceModel.interval)
                    & (rule.trading_date == DailyPriceModel.trading_date)
                    & (rule.formula_version == configuration.rule_formula_version)
                    & (rule.config_checksum == configuration.rule_config_checksum),
                )
                .outerjoin(
                    risk,
                    (risk.security_id == DailyPriceModel.security_id)
                    & (risk.provider == DailyPriceModel.provider)
                    & (risk.interval == DailyPriceModel.interval)
                    & (risk.trading_date == DailyPriceModel.trading_date)
                    & (risk.risk_version == configuration.risk_version)
                    & (risk.risk_config_checksum == configuration.risk_config_checksum),
                )
                .where(
                    DailyPriceModel.trading_date == trading_date,
                    DailyPriceModel.provider == "yahoo",
                    DailyPriceModel.interval == "1d",
                    SecurityModel.is_active.is_(True),
                )
                .order_by(SecurityModel.symbol)
            ).all()
            return [
                PositionSourceDay(
                    candle=DailyCandle(
                        symbol, candle_model.trading_date, candle_model.open,
                        candle_model.high, candle_model.low, candle_model.close,
                        candle_model.adjusted_close, candle_model.volume,
                        candle_model.provider, candle_model.interval,
                    ),
                    strategy_passed=strategy_passed is True,
                    atr_14=atr_14,
                    ma20_below_ma50=ma20_below_ma50,
                    rsi_extreme_overbought=rsi_extreme_overbought,
                    suggested_position_size_pct=suggested_position_size_pct,
                )
                for (
                    candle_model,
                    symbol,
                    strategy_passed,
                    atr_14,
                    ma20_below_ma50,
                    rsi_extreme_overbought,
                    suggested_position_size_pct,
                ) in rows
            ]

    def active_positions(self, configuration) -> dict[str, VirtualPosition]:
        with session_scope(self.session_factory) as session:
            models = session.scalars(select(VirtualPositionModel).where(
                VirtualPositionModel.lifecycle_version == configuration.version,
                VirtualPositionModel.lifecycle_config_checksum == configuration.checksum,
                VirtualPositionModel.status != PositionStatus.CLOSED,
            )).all()
            return {item.symbol: position_model_to_domain(item) for item in models}

    def existing_signals(self, configuration) -> set[tuple[str, date]]:
        with session_scope(self.session_factory) as session:
            return set(session.execute(select(
                VirtualPositionModel.symbol, VirtualPositionModel.signal_date,
            ).where(
                VirtualPositionModel.lifecycle_version == configuration.version,
                VirtualPositionModel.lifecycle_config_checksum == configuration.checksum,
            )).all())

    def latest_processed_date(self, configuration) -> date | None:
        with session_scope(self.session_factory) as session:
            return session.scalar(select(func.max(VirtualPositionModel.last_processed_date)).where(
                VirtualPositionModel.lifecycle_version == configuration.version,
                VirtualPositionModel.lifecycle_config_checksum == configuration.checksum,
            ))

    def save(self, positions: Sequence[VirtualPosition], events: Sequence[PositionEvent]) -> None:
        if not positions and not events:
            return
        with session_scope(self.session_factory) as session:
            for position in positions:
                values = position_to_row(position)
                statement = insert(VirtualPositionModel).values(values).on_conflict_do_update(
                    index_elements=[VirtualPositionModel.id],
                    set_={key: value for key, value in values.items() if key != "id"} | {"updated_at": func.now()},
                )
                session.execute(statement)
            if events:
                session.execute(insert(PositionEventModel).values([position_event_to_row(item) for item in events]).on_conflict_do_nothing())

    def list(self, configuration, *, status=None, limit=10, offset=0):
        with session_scope(self.session_factory) as session:
            statement = select(VirtualPositionModel).where(
                VirtualPositionModel.lifecycle_version == configuration.version,
                VirtualPositionModel.lifecycle_config_checksum == configuration.checksum,
            ).order_by(VirtualPositionModel.signal_date.desc(), VirtualPositionModel.symbol).limit(limit).offset(offset)
            if status:
                statement = statement.where(VirtualPositionModel.status == PositionStatus(status))
            return [position_to_dict(position_model_to_domain(item)) for item in session.scalars(statement).all()]

    def count(self, configuration, *, status=None):
        with session_scope(self.session_factory) as session:
            statement = select(func.count(VirtualPositionModel.id)).where(
                VirtualPositionModel.lifecycle_version == configuration.version,
                VirtualPositionModel.lifecycle_config_checksum == configuration.checksum,
            )
            if status:
                statement = statement.where(VirtualPositionModel.status == PositionStatus(status))
            return int(session.scalar(statement) or 0)

    def latest_for_symbol(self, symbol, configuration):
        with session_scope(self.session_factory) as session:
            item = session.scalar(select(VirtualPositionModel).where(
                VirtualPositionModel.symbol == symbol,
                VirtualPositionModel.lifecycle_version == configuration.version,
                VirtualPositionModel.lifecycle_config_checksum == configuration.checksum,
            ).order_by(VirtualPositionModel.signal_date.desc()).limit(1))
            return position_to_dict(position_model_to_domain(item)) if item else None

    def history(self, symbol, configuration, limit=10, offset=0):
        with session_scope(self.session_factory) as session:
            items = session.scalars(select(VirtualPositionModel).where(
                VirtualPositionModel.symbol == symbol,
                VirtualPositionModel.lifecycle_version == configuration.version,
                VirtualPositionModel.lifecycle_config_checksum == configuration.checksum,
            ).order_by(VirtualPositionModel.signal_date.desc()).limit(limit).offset(offset)).all()
            return [position_to_dict(position_model_to_domain(item)) for item in items]

    def count_history(self, symbol, configuration):
        with session_scope(self.session_factory) as session:
            return int(session.scalar(select(func.count(VirtualPositionModel.id)).where(
                VirtualPositionModel.symbol == symbol,
                VirtualPositionModel.lifecycle_version == configuration.version,
                VirtualPositionModel.lifecycle_config_checksum == configuration.checksum,
            )) or 0)

    def events(self, symbol, configuration, position_id=None, limit=10, offset=0):
        with session_scope(self.session_factory) as session:
            statement = select(PositionEventModel).join(VirtualPositionModel).where(
                VirtualPositionModel.symbol == symbol,
                VirtualPositionModel.lifecycle_version == configuration.version,
                VirtualPositionModel.lifecycle_config_checksum == configuration.checksum,
            ).order_by(PositionEventModel.trading_date.desc(), PositionEventModel.created_at.desc()).limit(limit).offset(offset)
            if position_id:
                statement = statement.where(PositionEventModel.position_id == position_id)
            return [position_event_to_dict(item) for item in session.scalars(statement).all()]

    def count_events(self, symbol, configuration, position_id=None):
        with session_scope(self.session_factory) as session:
            statement = select(func.count(PositionEventModel.id)).join(VirtualPositionModel).where(
                VirtualPositionModel.symbol == symbol,
                VirtualPositionModel.lifecycle_version == configuration.version,
                VirtualPositionModel.lifecycle_config_checksum == configuration.checksum,
            )
            if position_id:
                statement = statement.where(PositionEventModel.position_id == position_id)
            return int(session.scalar(statement) or 0)


class SqlAlchemyPositionRunRepository:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def create(self, mode, configuration):
        with session_scope(self.session_factory) as session:
            model = PositionRunModel(mode=mode, status=PositionRunStatus.RUNNING,
                                     lifecycle_version=configuration.version,
                                     lifecycle_config_checksum=configuration.checksum)
            session.add(model); session.flush(); return model.id

    def finish(self, run_id, positions_count, events_count, failed=False):
        with session_scope(self.session_factory) as session:
            session.execute(update(PositionRunModel).where(PositionRunModel.id == run_id).values(
                status=PositionRunStatus.FAILED if failed else PositionRunStatus.SUCCEEDED,
                positions_count=positions_count, events_count=events_count,
                finished_at=datetime.now(UTC),
            ))


def position_to_row(item: VirtualPosition):
    return {field: getattr(item, field) for field in item.__dataclass_fields__}


def position_event_to_row(item: PositionEvent):
    return {field: getattr(item, field) for field in item.__dataclass_fields__}


def position_model_to_domain(item):
    return VirtualPosition(**{field: getattr(item, field) for field in VirtualPosition.__dataclass_fields__})


def position_to_dict(item: VirtualPosition):
    payload = {field: getattr(item, field) for field in item.__dataclass_fields__}
    payload["status"] = item.status.value
    for key, value in list(payload.items()):
        if isinstance(value, Decimal): payload[key] = str(value)
    return payload


def position_event_to_dict(item):
    return {"id": item.id, "position_id": item.position_id, "symbol": item.symbol,
            "trading_date": item.trading_date, "event_type": item.event_type,
            "price": str(item.price) if item.price is not None else None,
            "fraction": str(item.fraction) if item.fraction is not None else None,
            "details": item.details}


PORTFOLIO_ID = UUID("00000000-0000-0000-0000-000000000001")


class SqlAlchemyPortfolioRepository:
    def __init__(self, session_factory: sessionmaker[Session], initial_cash: Decimal) -> None:
        self.session_factory = session_factory
        self.initial_cash = initial_cash

    def ensure_portfolio(self):
        with session_scope(self.session_factory) as session:
            item = session.get(PortfolioModel, PORTFOLIO_ID)
            if item is None:
                item = PortfolioModel(id=PORTFOLIO_ID, name="Local Paper Portfolio", initial_cash=self.initial_cash)
                session.add(item)
            return {"id": item.id, "name": item.name, "initial_cash": item.initial_cash}

    def transactions(self, *, limit=10, offset=0):
        with session_scope(self.session_factory) as session:
            rows = session.scalars(select(PortfolioTransactionModel).where(
                PortfolioTransactionModel.portfolio_id == PORTFOLIO_ID
            ).order_by(PortfolioTransactionModel.transaction_date.desc(), PortfolioTransactionModel.created_at.desc(), PortfolioTransactionModel.id.desc()).limit(limit).offset(offset)).all()
            return [portfolio_transaction_to_dict(item) for item in rows]

    def count_transactions(self):
        with session_scope(self.session_factory) as session:
            return int(session.scalar(select(func.count(PortfolioTransactionModel.id)).where(PortfolioTransactionModel.portfolio_id == PORTFOLIO_ID)) or 0)

    def create_transaction(self, transaction: PortfolioTransaction):
        with session_scope(self.session_factory) as session:
            session.add(PortfolioTransactionModel(
                id=transaction.id, portfolio_id=PORTFOLIO_ID,
                transaction_type=transaction.transaction_type, symbol=transaction.symbol,
                transaction_date=transaction.transaction_date, quantity=transaction.quantity,
                price=transaction.price, fee=transaction.fee, notes=transaction.notes,
                reversal_of_id=transaction.reversal_of_id,
            ))
        return portfolio_transaction_to_dict(transaction)

    def symbol_exists(self, symbol: str) -> bool:
        with session_scope(self.session_factory) as session:
            return bool(session.scalar(select(SecurityModel.id).where(SecurityModel.symbol == symbol)))

    def get_transaction(self, transaction_id):
        with session_scope(self.session_factory) as session:
            item = session.get(PortfolioTransactionModel, transaction_id)
            return item

    def has_reversal(self, transaction_id):
        with session_scope(self.session_factory) as session:
            return session.scalar(select(PortfolioTransactionModel.id).where(PortfolioTransactionModel.reversal_of_id == transaction_id)) is not None

    def latest_closes(self, symbols):
        if not symbols:
            return {}
        with session_scope(self.session_factory) as session:
            latest_date = session.scalar(select(func.max(DailyPriceModel.trading_date)))
            if latest_date is None:
                return {}
            rows = session.execute(select(SecurityModel.symbol, DailyPriceModel.close).join(DailyPriceModel).where(SecurityModel.symbol.in_(symbols), DailyPriceModel.trading_date == latest_date)).all()
            return dict(rows)

    def all_transactions(self):
        with session_scope(self.session_factory) as session:
            return list(session.scalars(select(PortfolioTransactionModel).where(PortfolioTransactionModel.portfolio_id == PORTFOLIO_ID).order_by(PortfolioTransactionModel.transaction_date, PortfolioTransactionModel.created_at, PortfolioTransactionModel.id)).all())

    def summary(self):
        transactions = self.all_transactions()
        return portfolio_projection(self.ensure_portfolio(), transactions, self.latest_closes({item.symbol for item in transactions}))

    def holdings(self, *, limit=10, offset=0):
        projection = self.summary()
        items = projection["holdings"]
        return items[offset:offset + limit], len(items)

    def performance(self):
        projection = self.summary()
        return {key: value for key, value in projection.items() if key != "holdings"}


def portfolio_transaction_to_dict(item):
    return {"id": item.id, "transaction_type": item.transaction_type.value if hasattr(item.transaction_type, "value") else item.transaction_type,
            "symbol": item.symbol, "transaction_date": item.transaction_date, "quantity": str(item.quantity),
            "price": str(item.price), "fee": str(item.fee), "notes": item.notes,
            "reversal_of_id": item.reversal_of_id, "created_at": getattr(item, "created_at", None)}


def portfolio_projection(portfolio, transactions, closes):
    holdings = {}
    cash = Decimal(str(portfolio["initial_cash"]))
    realized = Decimal("0")
    by_id = {item.id: item for item in transactions}
    for item in transactions:
        quantity = Decimal(str(item.quantity)); price = Decimal(str(item.price)); fee = Decimal(str(item.fee))
        key = item.symbol
        state = holdings.setdefault(key, {"quantity": Decimal("0"), "average_price": Decimal("0"), "first_buy_date": None})
        kind = item.transaction_type.value if hasattr(item.transaction_type, "value") else item.transaction_type
        if kind == PortfolioTransactionType.REVERSAL.value:
            original = by_id.get(item.reversal_of_id)
            if original is None:
                continue
            original_kind = original.transaction_type.value if hasattr(original.transaction_type, "value") else original.transaction_type
            if original_kind == PortfolioTransactionType.BUY.value:
                if state["quantity"] < quantity:
                    continue
                state["quantity"] -= quantity
                cash += quantity * price + Decimal(str(original.fee))
                if state["quantity"] == 0:
                    state["average_price"] = Decimal("0")
                    state["first_buy_date"] = None
                continue
            if original_kind == PortfolioTransactionType.SELL.value:
                previous_average = state["average_price"]
                total_cost = state["quantity"] * previous_average + quantity * price
                state["quantity"] += quantity
                state["average_price"] = total_cost / state["quantity"]
                state["first_buy_date"] = state["first_buy_date"] or item.transaction_date
                cash -= quantity * price - Decimal(str(original.fee))
                realized -= (price - previous_average) * quantity - Decimal(str(original.fee))
                continue
        if kind == "buy":
            total_cost = state["quantity"] * state["average_price"] + quantity * price
            state["quantity"] += quantity
            state["average_price"] = total_cost / state["quantity"]
            state["first_buy_date"] = state["first_buy_date"] or item.transaction_date
            cash -= quantity * price + fee
        else:
            if state["quantity"] <= 0 or quantity > state["quantity"]:
                continue
            realized += (price - state["average_price"]) * quantity - fee
            cash += quantity * price - fee
            state["quantity"] -= quantity
            if state["quantity"] == 0:
                state["average_price"] = Decimal("0"); state["first_buy_date"] = None
    output = []
    market_value = Decimal("0"); invested = Decimal("0"); unrealized = Decimal("0")
    today = datetime.now(ZoneInfo("Asia/Jakarta")).date()
    for symbol, state in sorted(holdings.items()):
        if state["quantity"] <= 0: continue
        close = closes.get(symbol); value = state["quantity"] * close if close is not None else None
        pnl = value - state["quantity"] * state["average_price"] if value is not None else None
        ret = pnl / (state["quantity"] * state["average_price"]) if pnl is not None and state["average_price"] else None
        if value is not None: market_value += value; invested += state["quantity"] * state["average_price"]
        if pnl is not None: unrealized += pnl
        output.append({"symbol": symbol, "quantity": str(state["quantity"]), "average_price": str(state["average_price"]), "cost_basis": str(state["quantity"] * state["average_price"]), "latest_close": str(close) if close is not None else None, "market_value": str(value) if value is not None else None, "unrealized_pnl": str(pnl) if pnl is not None else None, "unrealized_return": str(ret) if ret is not None else None, "first_buy_date": state["first_buy_date"], "holding_days": (today - state["first_buy_date"]).days if state["first_buy_date"] else None})
    total = realized + unrealized
    initial = Decimal(str(portfolio["initial_cash"]))
    return {"portfolio_id": portfolio["id"], "initial_cash": str(initial), "cash_balance": str(cash), "invested_value": str(invested), "market_value": str(market_value), "realized_pnl": str(realized), "unrealized_pnl": str(unrealized), "total_pnl": str(total), "total_return": str(total / initial if initial else Decimal("0")), "holdings": output}
