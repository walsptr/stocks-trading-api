import asyncio
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from stocks_trading.config.settings import Settings
from stocks_trading.domain.models import (
    RuleRunMode,
    RuleRunRequest,
    RuleRunResult,
    RuleRunStatus,
    RuleSymbolResult,
    RuleSymbolStatus,
)
from stocks_trading.domain.ports import RuleRepository, RuleRunRepository
from stocks_trading.market_data.service import sanitize_error
from stocks_trading.rules.config import RuleConfiguration
from stocks_trading.rules.evaluator import evaluate_rules


class RuleService:
    def __init__(
        self,
        *,
        rule_repository: RuleRepository,
        run_repository: RuleRunRepository,
        settings: Settings,
        configuration: RuleConfiguration,
    ) -> None:
        self.rule_repository = rule_repository
        self.run_repository = run_repository
        self.settings = settings
        self.configuration = configuration

    async def rebuild(
        self,
        *,
        symbols: Sequence[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> RuleRunResult:
        return await self._run(
            mode=RuleRunMode.REBUILD,
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
        )

    async def update(
        self,
        *,
        symbols: Sequence[str] | None = None,
        as_of: date | None = None,
    ) -> RuleRunResult:
        return await self._run(
            mode=RuleRunMode.UPDATE,
            symbols=symbols,
            start_date=None,
            end_date=as_of,
        )

    async def _run(
        self,
        *,
        mode: RuleRunMode,
        symbols: Sequence[str] | None,
        start_date: date | None,
        end_date: date | None,
    ) -> RuleRunResult:
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        selected = tuple(self._select_symbols(symbols))
        request = RuleRunRequest(
            mode=mode,
            formula_version=self.configuration.formula_version,
            config_checksum=self.configuration.checksum,
            indicator_version=self.configuration.indicator_version,
            start_date=start_date,
            end_date=end_date,
            symbols=selected,
        )
        run_id = self.run_repository.create_rule_run(request)
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
            self.run_repository.finish_rule_run(run_id)
        except BaseException:
            self.run_repository.abandon_rule_run(run_id)
            raise

        failed = sum(item.status == RuleSymbolStatus.FAILED for item in results)
        status = (
            RuleRunStatus.SUCCEEDED
            if failed == 0
            else RuleRunStatus.PARTIAL_FAILURE
            if failed < len(results)
            else RuleRunStatus.FAILED
        )
        return RuleRunResult(
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
        mode: RuleRunMode,
        symbol: str,
        requested_start: date | None,
        requested_end: date | None,
        semaphore: asyncio.Semaphore,
    ) -> RuleSymbolResult:
        try:
            start_date = requested_start
            if mode == RuleRunMode.UPDATE:
                latest = await asyncio.to_thread(
                    self.rule_repository.latest_rule_date,
                    symbol,
                    self.configuration.formula_version,
                    self.configuration.checksum,
                )
                start_date = (
                    latest - timedelta(days=self.settings.incremental_overlap_days)
                    if latest is not None
                    else None
                )
            async with semaphore:
                inputs = await asyncio.to_thread(
                    self.rule_repository.load_rule_inputs,
                    symbol,
                    indicator_version=self.configuration.indicator_version,
                    start_date=start_date,
                    end_date=requested_end,
                )
                if not inputs:
                    result = RuleSymbolResult(
                        symbol=symbol, status=RuleSymbolStatus.NO_DATA
                    )
                else:
                    rules = [evaluate_rules(item, self.configuration) for item in inputs]
                    rows_written = await asyncio.to_thread(
                        self.rule_repository.upsert_rules, rules
                    )
                    result = RuleSymbolResult(
                        symbol=symbol,
                        status=RuleSymbolStatus.SUCCESS,
                        rows_read=len(inputs),
                        rows_written=rows_written,
                    )
        except Exception as error:
            result = RuleSymbolResult(
                symbol=symbol,
                status=RuleSymbolStatus.FAILED,
                error=sanitize_error(error),
            )
        self.run_repository.record_rule_symbol_result(run_id, result)
        return result

    def _select_symbols(self, symbols: Sequence[str] | None) -> list[str]:
        active = set(self.rule_repository.active_symbols())
        if symbols:
            selected = sorted({symbol.upper() for symbol in symbols})
            unknown = set(selected) - active
            if unknown:
                raise ValueError(
                    f"symbols are not active in the universe: {', '.join(sorted(unknown))}"
                )
            return selected
        return sorted(active)
