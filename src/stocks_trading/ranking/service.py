import asyncio
from datetime import UTC, date, datetime, timedelta

from stocks_trading.config.settings import Settings
from stocks_trading.domain.models import (
    RankingDateResult,
    RankingDateStatus,
    RankingRunMode,
    RankingRunRequest,
    RankingRunResult,
    RankingRunStatus,
)
from stocks_trading.domain.ports import RankingRepository, RankingRunRepository
from stocks_trading.market_data.service import sanitize_error
from stocks_trading.ranking.config import RankingConfiguration
from stocks_trading.ranking.evaluator import rank_scores


class RankingService:
    def __init__(
        self,
        *,
        ranking_repository: RankingRepository,
        run_repository: RankingRunRepository,
        settings: Settings,
        configuration: RankingConfiguration,
    ) -> None:
        self.ranking_repository = ranking_repository
        self.run_repository = run_repository
        self.settings = settings
        self.configuration = configuration

    async def rebuild(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> RankingRunResult:
        return await self._run(RankingRunMode.REBUILD, start_date, end_date)

    async def update(self, *, as_of: date | None = None) -> RankingRunResult:
        latest = await asyncio.to_thread(
            self.ranking_repository.latest_ranking_date,
            self.configuration.version,
            self.configuration.checksum,
        )
        start_date = (
            latest - timedelta(days=self.settings.incremental_overlap_days)
            if latest is not None
            else None
        )
        return await self._run(RankingRunMode.UPDATE, start_date, as_of)

    async def _run(
        self,
        mode: RankingRunMode,
        start_date: date | None,
        end_date: date | None,
    ) -> RankingRunResult:
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        dates = tuple(
            await asyncio.to_thread(
                self.ranking_repository.source_score_dates,
                self.configuration.source_scoring_version,
                self.configuration.source_scoring_config_checksum,
                start_date=start_date,
                end_date=end_date,
            )
        )
        if not dates:
            if start_date is not None:
                dates = (start_date,)
            elif end_date is not None:
                dates = (end_date,)
        request = RankingRunRequest(
            mode=mode,
            ranking_version=self.configuration.version,
            ranking_config_checksum=self.configuration.checksum,
            source_scoring_version=self.configuration.source_scoring_version,
            source_scoring_config_checksum=self.configuration.source_scoring_config_checksum,
            start_date=start_date,
            end_date=end_date,
            requested_dates=len(dates),
        )
        run_id = self.run_repository.create_ranking_run(request)
        started_at = datetime.now(UTC)
        semaphore = asyncio.Semaphore(self.settings.max_workers)
        try:
            results = tuple(
                await asyncio.gather(
                    *[self._process_date(run_id, item, semaphore) for item in dates]
                )
            )
            self.run_repository.finish_ranking_run(run_id)
        except BaseException:
            self.run_repository.abandon_ranking_run(run_id)
            raise
        failed = sum(item.status == RankingDateStatus.FAILED for item in results)
        status = (
            RankingRunStatus.SUCCEEDED
            if failed == 0
            else RankingRunStatus.PARTIAL_FAILURE
            if failed < len(results)
            else RankingRunStatus.FAILED
        )
        return RankingRunResult(
            run_id=run_id,
            status=status,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            dates=results,
        )

    async def _process_date(self, run_id, trading_date, semaphore):
        try:
            async with semaphore:
                sources = await asyncio.to_thread(
                    self.ranking_repository.load_scores_for_date,
                    trading_date,
                    self.configuration.source_scoring_version,
                    self.configuration.source_scoring_config_checksum,
                )
                if not sources:
                    result = RankingDateResult(
                        trading_date=trading_date,
                        status=RankingDateStatus.NO_DATA,
                    )
                    await asyncio.to_thread(
                        self.run_repository.record_ranking_date_result, run_id, result
                    )
                    return result
                rankings = rank_scores(sources, self.configuration)
                written = await asyncio.to_thread(
                    self.ranking_repository.replace_rankings,
                    trading_date,
                    self.configuration.version,
                    self.configuration.checksum,
                    rankings,
                )
            result = RankingDateResult(
                trading_date=trading_date,
                status=RankingDateStatus.SUCCESS if rankings else RankingDateStatus.NO_DATA,
                rows_read=len(sources),
                rows_written=written,
            )
        except Exception as error:
            result = RankingDateResult(
                trading_date=trading_date,
                status=RankingDateStatus.FAILED,
                error=sanitize_error(error),
            )
        await asyncio.to_thread(
            self.run_repository.record_ranking_date_result, run_id, result
        )
        return result
