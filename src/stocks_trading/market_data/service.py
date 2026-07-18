import asyncio
import logging
import random
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from stocks_trading.config.settings import Settings
from stocks_trading.domain.models import (
    CollectionRequest,
    CollectionRunResult,
    RunCommand,
    RunStatus,
    SymbolCollectionResult,
    SymbolStatus,
)
from stocks_trading.domain.ports import (
    MarketDataProvider,
    MarketDataRepository,
    RunRepository,
)
from stocks_trading.market_data.yahoo import latest_completed_market_date

logger = logging.getLogger(__name__)


class MarketDataCollector:
    def __init__(
        self,
        *,
        provider: MarketDataProvider,
        market_repository: MarketDataRepository,
        run_repository: RunRepository,
        settings: Settings,
    ) -> None:
        self.provider = provider
        self.market_repository = market_repository
        self.run_repository = run_repository
        self.settings = settings

    async def bootstrap(
        self,
        *,
        years: int = 5,
        symbols: Sequence[str] | None = None,
        as_of: date | None = None,
    ) -> CollectionRunResult:
        end_date = as_of or latest_completed_market_date(
            datetime.now(UTC), self.settings.market_timezone
        )
        start_date = end_date - timedelta(days=years * 365 + years // 4 + 5)
        return await self.collect(
            command=RunCommand.BOOTSTRAP,
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
        )

    async def update(
        self,
        *,
        symbols: Sequence[str] | None = None,
        as_of: date | None = None,
        parent_run_id=None,
        command: RunCommand = RunCommand.UPDATE,
    ) -> CollectionRunResult:
        selected = self._select_symbols(symbols)
        end_date = as_of or latest_completed_market_date(
            datetime.now(UTC), self.settings.market_timezone
        )
        start_dates = {
            symbol: self._incremental_start_date(symbol, end_date)
            for symbol in selected
        }
        cached = [symbol for symbol, start in start_dates.items() if start > end_date]
        pending = [symbol for symbol in selected if symbol not in cached]
        if not pending:
            return await self._record_cache_only_run(
                command=command, symbols=selected, end_date=end_date,
                parent_run_id=parent_run_id,
            )
        return await self.collect(
            command=command,
            symbols=pending,
            start_date=min((start_dates[symbol] for symbol in pending), default=end_date),
            end_date=end_date,
            parent_run_id=parent_run_id,
            symbol_start_dates=start_dates,
            cached_symbols=cached,
        )

    async def refresh(
        self, *, start_date: date, end_date: date,
        symbols: Sequence[str] | None = None,
    ) -> CollectionRunResult:
        return await self.collect(
            command=RunCommand.REFRESH, symbols=symbols,
            start_date=start_date, end_date=end_date,
        )

    def status(self, *, as_of: date | None = None) -> dict[str, object]:
        target = as_of or latest_completed_market_date(
            datetime.now(UTC), self.settings.market_timezone
        )
        return self.market_repository.cache_status(target)

    async def retry(self, run_id) -> CollectionRunResult:
        symbols = self.run_repository.failed_symbols(run_id)
        if not symbols:
            raise ValueError(f"run {run_id} has no failed symbols")
        return await self.update(
            symbols=symbols, parent_run_id=run_id, command=RunCommand.RETRY
        )

    async def collect(
        self,
        *,
        command: RunCommand,
        start_date: date,
        end_date: date,
        symbols: Sequence[str] | None = None,
        parent_run_id=None,
        symbol_start_dates: dict[str, date] | None = None,
        cached_symbols: Sequence[str] = (),
    ) -> CollectionRunResult:
        selected = tuple(self._select_symbols(symbols))
        requested_symbols = tuple(sorted(set(selected) | set(cached_symbols)))
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        request = CollectionRequest(
            command=command,
            start_date=start_date,
            end_date=end_date,
            symbols=requested_symbols,
            parent_run_id=parent_run_id,
        )
        run_id = self.run_repository.create_run(request)
        started_at = datetime.now(UTC)
        try:
            semaphore = asyncio.Semaphore(self.settings.max_workers)
            batches = []
            symbols_by_start: dict[date, list[str]] = {}
            for symbol in selected:
                symbol_start = (symbol_start_dates or {}).get(symbol, start_date)
                symbols_by_start.setdefault(symbol_start, []).append(symbol)
            for batch_start, grouped_symbols in symbols_by_start.items():
                for index in range(0, len(grouped_symbols), self.settings.batch_size):
                    batches.append((batch_start, grouped_symbols[index:index + self.settings.batch_size]))
            tasks = [
                self._collect_batch(
                    run_id=run_id,
                    symbols=batch,
                    start_date=batch_start,
                    end_date=end_date,
                    semaphore=semaphore,
                )
                for batch_start, batch in batches
            ]
            batch_results = await asyncio.gather(*tasks)
            results_by_symbol = {
                result.symbol: result
                for batch in batch_results
                for result in batch
            }
            cached_results = tuple(
                SymbolCollectionResult(
                    symbol=symbol, status=SymbolStatus.NO_NEW_DATA, attempts=0
                ) for symbol in cached_symbols
            )
            for result in cached_results:
                self.run_repository.record_symbol_result(run_id, result)
            results = tuple(results_by_symbol[symbol] for symbol in selected) + cached_results
            self.run_repository.finish_run(run_id)
        except BaseException as error:
            self.run_repository.abandon_run(run_id)
            raise
        failed = sum(result.status == SymbolStatus.FAILED for result in results)
        succeeded = len(results) - failed
        status = (
            RunStatus.SUCCEEDED
            if failed == 0
            else RunStatus.PARTIAL_FAILURE
            if succeeded > 0
            else RunStatus.FAILED
        )
        return CollectionRunResult(
            run_id=run_id,
            status=status,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            symbols=results,
        )

    async def _record_cache_only_run(
        self, *, command: RunCommand, symbols: Sequence[str], end_date: date,
        parent_run_id,
    ) -> CollectionRunResult:
        request = CollectionRequest(
            command=command, start_date=end_date, end_date=end_date,
            symbols=tuple(symbols), parent_run_id=parent_run_id,
        )
        run_id = self.run_repository.create_run(request)
        started_at = datetime.now(UTC)
        results = tuple(
            SymbolCollectionResult(
                symbol=symbol, status=SymbolStatus.NO_NEW_DATA, attempts=0
            ) for symbol in symbols
        )
        for result in results:
            self.run_repository.record_symbol_result(run_id, result)
        self.run_repository.finish_run(run_id)
        logger.info("market cache current for %s symbols through %s", len(symbols), end_date)
        return CollectionRunResult(
            run_id=run_id, status=RunStatus.SUCCEEDED,
            started_at=started_at, finished_at=datetime.now(UTC), symbols=results,
        )

    async def _collect_batch(
        self,
        *,
        run_id,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
        semaphore: asyncio.Semaphore,
    ) -> list[SymbolCollectionResult]:
        last_error: Exception | None = None
        for attempt in range(1, self.settings.max_attempts + 1):
            try:
                async with semaphore:
                    downloaded = await asyncio.to_thread(
                        self.provider.download, symbols, start_date, end_date
                    )
                results = []
                failed_results = []
                for symbol in symbols:
                    try:
                        candles = downloaded.get(symbol, [])
                        rows_written = await asyncio.to_thread(
                            self.market_repository.upsert_candles, candles
                        )
                        result = SymbolCollectionResult(
                            symbol=symbol,
                            status=(
                                SymbolStatus.SUCCESS
                                if candles
                                else SymbolStatus.NO_NEW_DATA
                            ),
                            attempts=attempt,
                            rows_received=len(candles),
                            rows_written=rows_written,
                        )
                        self.run_repository.record_symbol_result(run_id, result)
                        results.append(result)
                    except Exception as error:
                        logger.warning("persistence failed for %s: %s", symbol, error)
                        failed_results.append(
                            SymbolCollectionResult(
                                symbol=symbol,
                                status=SymbolStatus.FAILED,
                                attempts=attempt,
                                rows_received=len(downloaded.get(symbol, [])),
                                error=sanitize_error(error),
                            )
                        )
                for result in failed_results:
                    self.run_repository.record_symbol_result(run_id, result)
                return results + failed_results
            except Exception as error:
                last_error = error
                logger.warning(
                    "market data batch attempt failed for %s (%s/%s): %s",
                    ",".join(symbols),
                    attempt,
                    self.settings.max_attempts,
                    error,
                )
                if attempt < self.settings.max_attempts:
                    delay = self.settings.retry_base_seconds * (2 ** (attempt - 1))
                    await asyncio.sleep(delay + random.uniform(0, delay / 4 if delay else 0))

        results = []
        for symbol in symbols:
            result = SymbolCollectionResult(
                symbol=symbol,
                status=SymbolStatus.FAILED,
                attempts=self.settings.max_attempts,
                error=sanitize_error(last_error),
            )
            self.run_repository.record_symbol_result(run_id, result)
            results.append(result)
        return results

    def _select_symbols(self, symbols: Sequence[str] | None) -> list[str]:
        if symbols:
            normalized = sorted({symbol.upper() for symbol in symbols})
            active = set(self.market_repository.active_symbols())
            unknown = set(normalized) - active
            if unknown:
                raise ValueError(
                    f"symbols are not active in the universe: {', '.join(sorted(unknown))}"
                )
            return normalized
        return self.market_repository.active_symbols()

    def _incremental_start_date(self, symbol: str, end_date: date) -> date:
        latest = self.market_repository.latest_trading_date(symbol)
        if latest is None:
            return end_date - timedelta(days=5 * 366)
        return latest + timedelta(days=1)


def sanitize_error(error: BaseException | None) -> str | None:
    if error is None:
        return None
    message = " ".join(str(error).split())
    return message[:2000]
