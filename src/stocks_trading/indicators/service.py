import asyncio
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from stocks_trading.config.settings import Settings
from stocks_trading.domain.models import (
    IndicatorRunMode,
    IndicatorRunRequest,
    IndicatorRunResult,
    IndicatorRunStatus,
    IndicatorSymbolResult,
    IndicatorSymbolStatus,
)
from stocks_trading.domain.ports import IndicatorRepository, IndicatorRunRepository
from stocks_trading.indicators import CALCULATION_VERSION
from stocks_trading.indicators.calculator import calculate_indicators
from stocks_trading.market_data.service import sanitize_error

WARMUP_SESSIONS = 260


class IndicatorService:
    def __init__(
        self,
        *,
        indicator_repository: IndicatorRepository,
        run_repository: IndicatorRunRepository,
        settings: Settings,
        calculation_version: str = CALCULATION_VERSION,
    ) -> None:
        self.indicator_repository = indicator_repository
        self.run_repository = run_repository
        self.settings = settings
        self.calculation_version = calculation_version

    async def rebuild(
        self,
        *,
        symbols: Sequence[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> IndicatorRunResult:
        return await self._run(
            mode=IndicatorRunMode.REBUILD,
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
        )

    async def update(
        self,
        *,
        symbols: Sequence[str] | None = None,
        as_of: date | None = None,
    ) -> IndicatorRunResult:
        return await self._run(
            mode=IndicatorRunMode.UPDATE,
            symbols=symbols,
            start_date=None,
            end_date=as_of,
        )

    async def _run(
        self,
        *,
        mode: IndicatorRunMode,
        symbols: Sequence[str] | None,
        start_date: date | None,
        end_date: date | None,
    ) -> IndicatorRunResult:
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        selected = tuple(self._select_symbols(symbols))
        request = IndicatorRunRequest(
            mode=mode,
            calculation_version=self.calculation_version,
            start_date=start_date,
            end_date=end_date,
            symbols=selected,
        )
        run_id = self.run_repository.create_indicator_run(request)
        started_at = datetime.now(UTC)
        semaphore = asyncio.Semaphore(self.settings.max_workers)
        try:
            results = tuple(
                await asyncio.gather(
                    *[
                        self._process_symbol(
                            run_id=run_id,
                            mode=mode,
                            symbol=symbol,
                            requested_start=start_date,
                            requested_end=end_date,
                            semaphore=semaphore,
                        )
                        for symbol in selected
                    ]
                )
            )
            self.run_repository.finish_indicator_run(run_id)
        except BaseException:
            self.run_repository.abandon_indicator_run(run_id)
            raise

        failed = sum(
            result.status == IndicatorSymbolStatus.FAILED for result in results
        )
        successful = len(results) - failed
        status = (
            IndicatorRunStatus.SUCCEEDED
            if failed == 0
            else IndicatorRunStatus.PARTIAL_FAILURE
            if successful > 0
            else IndicatorRunStatus.FAILED
        )
        return IndicatorRunResult(
            run_id=run_id,
            status=status,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            symbols=results,
        )

    async def _process_symbol(
        self,
        *,
        run_id,
        mode: IndicatorRunMode,
        symbol: str,
        requested_start: date | None,
        requested_end: date | None,
        semaphore: asyncio.Semaphore,
    ) -> IndicatorSymbolResult:
        try:
            write_start = requested_start
            calculation_start = requested_start
            if mode == IndicatorRunMode.UPDATE:
                latest = await asyncio.to_thread(
                    self.indicator_repository.latest_indicator_date,
                    symbol,
                    self.calculation_version,
                )
                write_start = (
                    latest - timedelta(days=self.settings.incremental_overlap_days)
                    if latest is not None
                    else None
                )
                calculation_start = write_start

            async with semaphore:
                candles = await asyncio.to_thread(
                    self.indicator_repository.load_candles,
                    symbol,
                    start_date=calculation_start,
                    end_date=requested_end,
                    warmup_sessions=(
                        WARMUP_SESSIONS if calculation_start is not None else 0
                    ),
                )
                if not candles:
                    result = IndicatorSymbolResult(
                        symbol=symbol, status=IndicatorSymbolStatus.NO_DATA
                    )
                else:
                    calculated = await asyncio.to_thread(
                        calculate_indicators,
                        candles,
                        calculation_version=self.calculation_version,
                    )
                    source_timestamps = await asyncio.to_thread(
                        self.indicator_repository.source_update_times,
                        symbol,
                        [item.trading_date for item in calculated],
                    )
                    calculated = [
                        replace(
                            item,
                            source_updated_at=source_timestamps.get(item.trading_date),
                        )
                        for item in calculated
                        if write_start is None or item.trading_date >= write_start
                    ]
                    rows_written = await asyncio.to_thread(
                        self.indicator_repository.upsert_indicators, calculated
                    )
                    result = IndicatorSymbolResult(
                        symbol=symbol,
                        status=IndicatorSymbolStatus.SUCCESS,
                        rows_read=len(candles),
                        rows_written=rows_written,
                    )
        except Exception as error:
            result = IndicatorSymbolResult(
                symbol=symbol,
                status=IndicatorSymbolStatus.FAILED,
                error=sanitize_error(error),
            )
        self.run_repository.record_indicator_symbol_result(run_id, result)
        return result

    def _select_symbols(self, symbols: Sequence[str] | None) -> list[str]:
        active = set(self.indicator_repository.active_symbols())
        if symbols:
            selected = sorted({symbol.upper() for symbol in symbols})
            unknown = set(selected) - active
            if unknown:
                raise ValueError(
                    f"symbols are not active in the universe: {', '.join(sorted(unknown))}"
                )
            return selected
        return sorted(active)
