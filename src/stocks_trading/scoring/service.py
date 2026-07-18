import asyncio
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from stocks_trading.config.settings import Settings
from stocks_trading.domain.models import (
    ScoreRunMode,
    ScoreRunRequest,
    ScoreRunResult,
    ScoreRunStatus,
    ScoreSymbolResult,
    ScoreSymbolStatus,
)
from stocks_trading.domain.ports import ScoreRepository, ScoreRunRepository
from stocks_trading.market_data.service import sanitize_error
from stocks_trading.scoring.config import ScoringConfiguration
from stocks_trading.scoring.evaluator import calculate_score


class ScoringService:
    def __init__(
        self,
        *,
        score_repository: ScoreRepository,
        run_repository: ScoreRunRepository,
        settings: Settings,
        configuration: ScoringConfiguration,
    ) -> None:
        self.score_repository = score_repository
        self.run_repository = run_repository
        self.settings = settings
        self.configuration = configuration

    async def rebuild(
        self,
        *,
        symbols: Sequence[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> ScoreRunResult:
        return await self._run(
            mode=ScoreRunMode.REBUILD,
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
        )

    async def update(
        self,
        *,
        symbols: Sequence[str] | None = None,
        as_of: date | None = None,
    ) -> ScoreRunResult:
        return await self._run(
            mode=ScoreRunMode.UPDATE,
            symbols=symbols,
            start_date=None,
            end_date=as_of,
        )

    async def _run(
        self,
        *,
        mode: ScoreRunMode,
        symbols: Sequence[str] | None,
        start_date: date | None,
        end_date: date | None,
    ) -> ScoreRunResult:
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        selected = tuple(self._select_symbols(symbols))
        request = ScoreRunRequest(
            mode=mode,
            scoring_version=self.configuration.version,
            scoring_config_checksum=self.configuration.checksum,
            source_rule_formula_version=self.configuration.source_rule_formula_version,
            source_rule_config_checksum=self.configuration.source_rule_config_checksum,
            start_date=start_date,
            end_date=end_date,
            symbols=selected,
        )
        run_id = self.run_repository.create_score_run(request)
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
            self.run_repository.finish_score_run(run_id)
        except BaseException:
            self.run_repository.abandon_score_run(run_id)
            raise
        failed = sum(item.status == ScoreSymbolStatus.FAILED for item in results)
        status = (
            ScoreRunStatus.SUCCEEDED
            if failed == 0
            else ScoreRunStatus.PARTIAL_FAILURE
            if failed < len(results)
            else ScoreRunStatus.FAILED
        )
        return ScoreRunResult(
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
        mode: ScoreRunMode,
        symbol: str,
        requested_start: date | None,
        requested_end: date | None,
        semaphore: asyncio.Semaphore,
    ) -> ScoreSymbolResult:
        try:
            start_date = requested_start
            if mode == ScoreRunMode.UPDATE:
                latest = await asyncio.to_thread(
                    self.score_repository.latest_score_date,
                    symbol,
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
                    self.score_repository.load_rule_results,
                    symbol,
                    formula_version=self.configuration.source_rule_formula_version,
                    config_checksum=self.configuration.source_rule_config_checksum,
                    start_date=start_date,
                    end_date=requested_end,
                )
                if not sources:
                    result = ScoreSymbolResult(
                        symbol=symbol, status=ScoreSymbolStatus.NO_DATA
                    )
                else:
                    scores = [
                        replace(
                            calculate_score(rules, self.configuration),
                            source_rule_evaluated_at=evaluated_at,
                        )
                        for rules, evaluated_at in sources
                    ]
                    rows_written = await asyncio.to_thread(
                        self.score_repository.upsert_scores, scores
                    )
                    result = ScoreSymbolResult(
                        symbol=symbol,
                        status=ScoreSymbolStatus.SUCCESS,
                        rows_read=len(sources),
                        rows_written=rows_written,
                    )
        except Exception as error:
            result = ScoreSymbolResult(
                symbol=symbol,
                status=ScoreSymbolStatus.FAILED,
                error=sanitize_error(error),
            )
        self.run_repository.record_score_symbol_result(run_id, result)
        return result

    def _select_symbols(self, symbols: Sequence[str] | None) -> list[str]:
        active = set(self.score_repository.active_symbols())
        if symbols:
            selected = sorted({symbol.upper() for symbol in symbols})
            unknown = set(selected) - active
            if unknown:
                raise ValueError(
                    f"symbols are not active in the universe: {', '.join(sorted(unknown))}"
                )
            return selected
        return sorted(active)
