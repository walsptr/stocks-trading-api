import asyncio
from datetime import date

from stocks_trading.alerts.config import AlertConfiguration
from stocks_trading.alerts.evaluator import build_alert
from stocks_trading.alerts.telegram import TelegramClient
from stocks_trading.domain.models import AlertRunMode, AlertRunResult, AlertRunStatus
from stocks_trading.market_data.service import sanitize_error


class AlertService:
    def __init__(self, *, alert_repository, run_repository, configuration: AlertConfiguration,
                 telegram: TelegramClient) -> None:
        self.alert_repository = alert_repository
        self.run_repository = run_repository
        self.configuration = configuration
        self.telegram = telegram

    async def rebuild(self, *, start_date: date | None = None,
                      end_date: date | None = None) -> AlertRunResult:
        return await asyncio.to_thread(self._rebuild_sync, start_date, end_date)

    def _rebuild_sync(self, start_date: date | None, end_date: date | None) -> AlertRunResult:
        run_id = self.run_repository.create(AlertRunMode.REBUILD)
        generated = self._generate_sync(start_date=start_date, end_date=end_date)
        self.run_repository.finish(run_id, generated, 0, 0)
        return AlertRunResult(run_id, AlertRunStatus.SUCCEEDED, generated, 0, 0)

    async def update(self, *, as_of: date | None = None) -> AlertRunResult:
        run_id = self.run_repository.create(AlertRunMode.UPDATE)
        dates = self.alert_repository.source_dates(
            self.configuration.source_versions["analysis_version"],
            self.configuration.source_versions["analysis_config_checksum"],
            start_date=None, end_date=as_of,
        )
        watermark = self.alert_repository.get_watermark(
            self.configuration.version, self.configuration.checksum
        )
        generated = 0
        if watermark is None and dates:
            self.alert_repository.set_watermark(
                self.configuration.version, self.configuration.checksum, max(dates)
            )
        elif watermark is not None:
            for trading_date in [item for item in dates if item > watermark]:
                generated += await self._generate_date(trading_date)
                self.alert_repository.set_watermark(
                    self.configuration.version, self.configuration.checksum, trading_date
                )
        sent, failed = await self._deliver(limit=500)
        status = run_status(failed, generated + sent)
        self.run_repository.finish(run_id, generated, sent, failed)
        return AlertRunResult(run_id, status, generated, sent, failed)

    async def retry(self, *, limit: int = 100) -> AlertRunResult:
        run_id = self.run_repository.create(AlertRunMode.RETRY)
        sent, failed = await self._deliver(limit=limit)
        status = run_status(failed, sent)
        self.run_repository.finish(run_id, 0, sent, failed)
        return AlertRunResult(run_id, status, 0, sent, failed)

    async def _generate(self, *, start_date, end_date) -> int:
        return await asyncio.to_thread(
            self._generate_sync, start_date=start_date, end_date=end_date
        )

    def _generate_sync(self, *, start_date, end_date) -> int:
        dates = self.alert_repository.source_dates(
            self.configuration.source_versions["analysis_version"],
            self.configuration.source_versions["analysis_config_checksum"],
            start_date=start_date, end_date=end_date,
        )
        return sum(self._generate_date_sync(item) for item in dates)

    async def _generate_date(self, trading_date: date) -> int:
        return await asyncio.to_thread(self._generate_date_sync, trading_date)

    def _generate_date_sync(self, trading_date: date) -> int:
        generated = 0
        states = self.alert_repository.load_states(
            trading_date, self.configuration.source_versions
        )
        for current in states:
            previous = self.alert_repository.previous_state(
                current.symbol, trading_date, self.configuration.source_versions
            )
            event = build_alert(current, previous, self.configuration)
            if event is not None and self.alert_repository.save_event(event):
                generated += 1
        return generated

    async def _deliver(self, *, limit: int) -> tuple[int, int]:
        if not self.telegram.configured:
            return (0, 0)
        sent = failed = 0
        events = self.alert_repository.pending_events(
            self.configuration.maximum_attempts, limit
        )
        for event in events:
            try:
                await self.telegram.send(event.message)
                self.alert_repository.record_delivery(event.id, succeeded=True, error=None)
                sent += 1
            except Exception as error:
                self.alert_repository.record_delivery(
                    event.id, succeeded=False, error=sanitize_error(error)
                )
                failed += 1
                delay = self.configuration.retry_base_seconds * (2 ** event.delivery_attempts)
                if delay:
                    await asyncio.sleep(delay)
        return sent, failed


def run_status(failed: int, succeeded: int) -> AlertRunStatus:
    if failed == 0:
        return AlertRunStatus.SUCCEEDED
    return AlertRunStatus.PARTIAL_FAILURE if succeeded else AlertRunStatus.FAILED
