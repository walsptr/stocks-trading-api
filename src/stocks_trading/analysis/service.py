import asyncio
from datetime import UTC, date, datetime, timedelta

from stocks_trading.analysis.config import AnalysisConfiguration
from stocks_trading.analysis.evaluator import generate_analysis
from stocks_trading.config.settings import Settings
from stocks_trading.domain.models import (
    AnalysisRunMode, AnalysisRunRequest, AnalysisRunResult, AnalysisRunStatus,
    AnalysisSymbolResult, AnalysisSymbolStatus,
)
from stocks_trading.domain.ports import AnalysisRepository, AnalysisRunRepository
from stocks_trading.market_data.service import sanitize_error


class AnalysisService:
    def __init__(self, *, analysis_repository: AnalysisRepository,
                 run_repository: AnalysisRunRepository, settings: Settings,
                 configuration: AnalysisConfiguration) -> None:
        self.analysis_repository = analysis_repository
        self.run_repository = run_repository
        self.settings = settings
        self.configuration = configuration

    async def rebuild(self, *, start_date: date | None = None,
                      end_date: date | None = None) -> AnalysisRunResult:
        return await self._run(AnalysisRunMode.REBUILD, start_date, end_date)

    async def update(self, *, as_of: date | None = None) -> AnalysisRunResult:
        latest = await asyncio.to_thread(
            self.analysis_repository.latest_analysis_date,
            self.configuration.version, self.configuration.checksum,
        )
        start = latest - timedelta(days=self.settings.incremental_overlap_days) if latest else None
        return await self._run(AnalysisRunMode.UPDATE, start, as_of)

    async def _run(self, mode, start_date, end_date):
        if start_date and end_date and start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        dates = tuple(await asyncio.to_thread(
            self.analysis_repository.source_ranking_dates,
            self.configuration.source_versions["ranking_version"],
            self.configuration.source_versions["ranking_config_checksum"],
            start_date=start_date, end_date=end_date,
            minimum_score=self.configuration.minimum_score,
        ))
        inputs_by_date = []
        for trading_date in dates:
            inputs = await asyncio.to_thread(
                self.analysis_repository.load_analysis_inputs, trading_date,
                minimum_score=self.configuration.minimum_score,
                source_versions=self.configuration.source_versions,
            )
            inputs_by_date.append((trading_date, inputs))
        requested = sum(len(items) for _, items in inputs_by_date)
        run_id = self.run_repository.create_analysis_run(AnalysisRunRequest(
            mode=mode, analysis_version=self.configuration.version,
            analysis_config_checksum=self.configuration.checksum,
            start_date=start_date, end_date=end_date, requested_symbols=requested,
        ))
        started_at = datetime.now(UTC)
        results = []
        try:
            for trading_date, inputs in inputs_by_date:
                analyses = []
                date_results = []
                for source in inputs:
                    try:
                        analyses.append(generate_analysis(source, self.configuration))
                        date_results.append(AnalysisSymbolResult(
                            symbol=source.ranking.symbol, trading_date=trading_date,
                            status=AnalysisSymbolStatus.SUCCESS, rows_read=1,
                        ))
                    except Exception as error:
                        date_results.append(AnalysisSymbolResult(
                            symbol=source.ranking.symbol, trading_date=trading_date,
                            status=AnalysisSymbolStatus.FAILED, rows_read=1,
                            error=sanitize_error(error),
                        ))
                if not any(item.status == AnalysisSymbolStatus.FAILED for item in date_results):
                    written = await asyncio.to_thread(
                        self.analysis_repository.replace_analyses, trading_date,
                        self.configuration.version, self.configuration.checksum, analyses,
                    )
                    date_results = [
                        AnalysisSymbolResult(
                            symbol=item.symbol, trading_date=item.trading_date,
                            status=item.status, rows_read=item.rows_read,
                            rows_written=1 if written else 0, error=item.error,
                        ) for item in date_results
                    ]
                for item in date_results:
                    self.run_repository.record_analysis_symbol_result(run_id, item)
                results.extend(date_results)
            self.run_repository.finish_analysis_run(run_id)
        except BaseException:
            self.run_repository.abandon_analysis_run(run_id)
            raise
        failed = sum(item.status == AnalysisSymbolStatus.FAILED for item in results)
        status = AnalysisRunStatus.SUCCEEDED if failed == 0 else (
            AnalysisRunStatus.PARTIAL_FAILURE if failed < len(results) else AnalysisRunStatus.FAILED
        )
        return AnalysisRunResult(
            run_id=run_id, status=status, started_at=started_at,
            finished_at=datetime.now(UTC), symbols=tuple(results),
        )
