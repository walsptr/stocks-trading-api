import asyncio
from datetime import UTC, date, datetime, timedelta

from stocks_trading.domain.models import (
    RiskRunMode, RiskRunRequest, RiskRunResult, RiskRunStatus,
    RiskSymbolResult, RiskSymbolStatus,
)
from stocks_trading.market_data.service import sanitize_error
from stocks_trading.risk.evaluator import generate_recommendation


class RiskService:
    def __init__(self, repository, run_repository, settings, configuration):
        self.repository = repository
        self.run_repository = run_repository
        self.settings = settings
        self.configuration = configuration

    async def rebuild(self, *, start_date: date | None = None, end_date: date | None = None):
        return await self._run(RiskRunMode.REBUILD, start_date, end_date)

    async def update(self, *, as_of: date | None = None):
        latest = await asyncio.to_thread(
            self.repository.latest_date, self.configuration.version, self.configuration.checksum
        )
        start = latest - timedelta(days=self.settings.incremental_overlap_days) if latest else None
        return await self._run(RiskRunMode.UPDATE, start, as_of)

    async def _run(self, mode, start_date, end_date):
        dates = await asyncio.to_thread(
            self.repository.source_dates, self.configuration, start_date, end_date
        )
        inputs_by_date = [(day, await asyncio.to_thread(self.repository.load_inputs, day, self.configuration)) for day in dates]
        run_id = self.run_repository.create_run(RiskRunRequest(
            mode, self.configuration.version, self.configuration.checksum,
            start_date, end_date, sum(len(items) for _, items in inputs_by_date),
        ))
        started_at = datetime.now(UTC)
        results = []
        try:
            for trading_date, inputs in inputs_by_date:
                recommendations = []
                date_results = []
                for source in inputs:
                    try:
                        recommendations.append(generate_recommendation(source, self.configuration))
                        date_results.append(RiskSymbolResult(source.ranking.symbol, trading_date, RiskSymbolStatus.SUCCESS, 1))
                    except ValueError as error:
                        date_results.append(RiskSymbolResult(source.ranking.symbol, trading_date, RiskSymbolStatus.NO_DATA, 1, error=sanitize_error(error)))
                    except Exception as error:
                        date_results.append(RiskSymbolResult(source.ranking.symbol, trading_date, RiskSymbolStatus.FAILED, 1, error=sanitize_error(error)))
                if not any(item.status == RiskSymbolStatus.FAILED for item in date_results):
                    await asyncio.to_thread(self.repository.replace, trading_date, self.configuration, recommendations)
                    date_results = [RiskSymbolResult(item.symbol, item.trading_date, item.status, item.rows_read, 1 if item.status == RiskSymbolStatus.SUCCESS else 0, item.error) for item in date_results]
                for item in date_results:
                    self.run_repository.record_result(run_id, item)
                results.extend(date_results)
            self.run_repository.finish_run(run_id)
        except BaseException:
            self.run_repository.abandon_run(run_id)
            raise
        failed = sum(item.status == RiskSymbolStatus.FAILED for item in results)
        status = RiskRunStatus.SUCCEEDED if failed == 0 else RiskRunStatus.PARTIAL_FAILURE if failed < len(results) else RiskRunStatus.FAILED
        return RiskRunResult(run_id, status, started_at, datetime.now(UTC), tuple(results))
