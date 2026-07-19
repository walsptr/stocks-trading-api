import asyncio
from datetime import date
from collections.abc import Callable

from stocks_trading.domain.models import PositionRunMode, PositionRunResult, PositionRunStatus
from stocks_trading.positions.evaluator import new_pending_position, process_position


class PositionService:
    def __init__(self, repository, run_repository, configuration):
        self.repository = repository
        self.run_repository = run_repository
        self.configuration = configuration

    async def rebuild(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        progress: Callable[[date, int, int], None] | None = None,
    ):
        return await asyncio.to_thread(
            self._rebuild_sync, start_date, end_date, progress
        )

    async def update(self, *, as_of: date | None = None):
        return await asyncio.to_thread(self._update_sync, as_of)

    def _rebuild_sync(self, start_date, end_date, progress):
        self.repository.rebuild(self.configuration)
        return self._run_sync(PositionRunMode.REBUILD, start_date, end_date, progress)

    def _update_sync(self, as_of):
        latest = self.repository.latest_processed_date(self.configuration)
        return self._run_sync(PositionRunMode.UPDATE, latest, as_of, None)

    def _run_sync(self, mode, start_date, end_date, progress):
        run_id = self.run_repository.create(mode, self.configuration)
        positions_count = events_count = 0
        try:
            active = self.repository.active_positions(self.configuration)
            existing_signals = self.repository.existing_signals(self.configuration)
            dates = self.repository.source_dates(self.configuration, start_date, end_date)
            total_dates = len(dates)
            for date_index, trading_date in enumerate(dates, start=1):
                changed = []
                events = []
                for source in self.repository.load_sources(trading_date, self.configuration):
                    current = active.get(source.candle.symbol)
                    if current is not None:
                        updated, generated = process_position(current, source, self.configuration)
                        if updated != current:
                            changed.append(updated)
                            active[source.candle.symbol] = updated
                            if updated.status.value == "closed":
                                active.pop(source.candle.symbol, None)
                        events.extend(generated)
                    elif source.strategy_passed and (source.candle.symbol, trading_date) not in existing_signals:
                        pending, generated = new_pending_position(source, self.configuration)
                        changed.append(pending)
                        active[source.candle.symbol] = pending
                        existing_signals.add((source.candle.symbol, trading_date))
                        events.append(generated)
                self.repository.save(changed, events)
                positions_count += len(changed)
                events_count += len(events)
                if progress and (date_index == 1 or date_index % 10 == 0 or date_index == total_dates):
                    progress(trading_date, date_index, total_dates)
            self.run_repository.finish(run_id, positions_count, events_count)
            return PositionRunResult(run_id, PositionRunStatus.SUCCEEDED, positions_count, events_count)
        except BaseException:
            self.run_repository.finish(run_id, positions_count, events_count, failed=True)
            raise
