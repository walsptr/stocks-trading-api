import asyncio
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from stocks_trading.config.settings import Settings
from stocks_trading.domain.models import (
    StrategyRunMode,
    StrategyRunRequest,
    StrategyRunResult,
    StrategyRunStatus,
    StrategySymbolResult,
    StrategySymbolStatus,
)
from stocks_trading.domain.ports import StrategyRepository, StrategyRunRepository
from stocks_trading.market_data.service import sanitize_error
from stocks_trading.strategies.config import StrategyConfiguration
from stocks_trading.strategies.evaluator import evaluate_strategy


class StrategyService:
    def __init__(
        self,
        *,
        strategy_repository: StrategyRepository,
        run_repository: StrategyRunRepository,
        settings: Settings,
        configuration: StrategyConfiguration,
    ) -> None:
        self.strategy_repository = strategy_repository
        self.run_repository = run_repository
        self.settings = settings
        self.configuration = configuration

    async def rebuild(
        self,
        *,
        symbols: Sequence[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> StrategyRunResult:
        return await self._run(
            mode=StrategyRunMode.REBUILD,
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
        )

    async def update(
        self,
        *,
        symbols: Sequence[str] | None = None,
        as_of: date | None = None,
    ) -> StrategyRunResult:
        return await self._run(
            mode=StrategyRunMode.UPDATE,
            symbols=symbols,
            start_date=None,
            end_date=as_of,
        )

    async def _run(
        self,
        *,
        mode: StrategyRunMode,
        symbols: Sequence[str] | None,
        start_date: date | None,
        end_date: date | None,
    ) -> StrategyRunResult:
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        selected = tuple(self._select_symbols(symbols))
        request = StrategyRunRequest(
            mode=mode,
            strategy_name=self.configuration.name,
            strategy_version=self.configuration.version,
            strategy_config_checksum=self.configuration.checksum,
            source_rule_formula_version=self.configuration.source_rule_formula_version,
            source_rule_config_checksum=self.configuration.source_rule_config_checksum,
            start_date=start_date,
            end_date=end_date,
            symbols=selected,
        )
        run_id = self.run_repository.create_strategy_run(request)
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
            self.run_repository.finish_strategy_run(run_id)
        except BaseException:
            self.run_repository.abandon_strategy_run(run_id)
            raise
        failed = sum(item.status == StrategySymbolStatus.FAILED for item in results)
        status = (
            StrategyRunStatus.SUCCEEDED
            if failed == 0
            else StrategyRunStatus.PARTIAL_FAILURE
            if failed < len(results)
            else StrategyRunStatus.FAILED
        )
        return StrategyRunResult(
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
        mode: StrategyRunMode,
        symbol: str,
        requested_start: date | None,
        requested_end: date | None,
        semaphore: asyncio.Semaphore,
    ) -> StrategySymbolResult:
        try:
            start_date = requested_start
            if mode == StrategyRunMode.UPDATE:
                latest = await asyncio.to_thread(
                    self.strategy_repository.latest_strategy_date,
                    symbol,
                    self.configuration.name,
                    self.configuration.version,
                    self.configuration.checksum,
                )
                start_date = (
                    latest - timedelta(days=self.settings.incremental_overlap_days)
                    if latest is not None
                    else None
                )
            async with semaphore:
                sources = await asyncio.to_thread(
                    self.strategy_repository.load_rule_results,
                    symbol,
                    formula_version=self.configuration.source_rule_formula_version,
                    config_checksum=self.configuration.source_rule_config_checksum,
                    start_date=start_date,
                    end_date=requested_end,
                )
                if not sources:
                    result = StrategySymbolResult(
                        symbol=symbol, status=StrategySymbolStatus.NO_DATA
                    )
                else:
                    evaluated = [
                        replace(
                            evaluate_strategy(rules, self.configuration),
                            source_rule_evaluated_at=evaluated_at,
                        )
                        for rules, evaluated_at in sources
                    ]
                    rows_written = await asyncio.to_thread(
                        self.strategy_repository.upsert_strategy_results, evaluated
                    )
                    result = StrategySymbolResult(
                        symbol=symbol,
                        status=StrategySymbolStatus.SUCCESS,
                        rows_read=len(sources),
                        rows_written=rows_written,
                    )
        except Exception as error:
            result = StrategySymbolResult(
                symbol=symbol,
                status=StrategySymbolStatus.FAILED,
                error=sanitize_error(error),
            )
        self.run_repository.record_strategy_symbol_result(run_id, result)
        return result

    def _select_symbols(self, symbols: Sequence[str] | None) -> list[str]:
        active = set(self.strategy_repository.active_symbols())
        if symbols:
            selected = sorted({symbol.upper() for symbol in symbols})
            unknown = set(selected) - active
            if unknown:
                raise ValueError(
                    f"symbols are not active in the universe: {', '.join(sorted(unknown))}"
                )
            return selected
        return sorted(active)
