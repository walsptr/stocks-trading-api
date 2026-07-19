import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Callable
from uuid import UUID

from stocks_trading.config.settings import Settings
from stocks_trading.config.time import localize_datetime
from stocks_trading.market_data.calendar import load_market_calendar
from stocks_trading.market_data.service import sanitize_error
from stocks_trading.market_data.yahoo import latest_completed_market_date
from stocks_trading.sync.service import PipelineBusyError, PipelineCoordinator


class BackfillValidationError(ValueError):
    pass


class HistoricalBackfillManager:
    def __init__(self, repository, service_factory: Callable, settings: Settings) -> None:
        self.repository = repository
        self.service_factory = service_factory
        self.settings = settings
        self.coordinator = PipelineCoordinator(settings)
        self._manager_lock = asyncio.Lock()

    def recover_interrupted(self) -> int:
        job_ids = self.repository.interrupt_active()
        for job_id in job_ids:
            asyncio.create_task(self._run(job_id, resume=False))
        return len(job_ids)

    def availability(self, target_years: int = 5) -> dict[str, object]:
        self._validate_years(target_years)
        start_date, end_date = self._target_range(target_years)
        return {
            "target_years": target_years,
            "target_start_date": start_date,
            "target_end_date": end_date,
            **self.repository.coverage(start_date),
        }

    async def start(self, target_years: int = 5):
        self._validate_years(target_years)
        async with self._manager_lock:
            current = self.repository.current_job()
            if current:
                return current, False
            start_date, end_date = self._target_range(target_years)
            candidates = self.repository.candidates(start_date, end_date)
            job = self.repository.create_job(target_years, start_date, end_date, candidates)
            asyncio.create_task(self._run(job["id"], resume=False))
            return job, True

    async def resume(self, job_id: UUID):
        async with self._manager_lock:
            current = self.repository.current_job()
            if current:
                return current, False
            job = self.repository.get_job(job_id)
            if not job:
                raise BackfillValidationError("backfill job not found")
            retryable = self.repository.pending_symbols(job_id, resume=True)
            if not retryable:
                raise BackfillValidationError("backfill job has no failed or partial symbols")
            self.repository.reset_retryable(job_id)
            self.repository.update_job(
                job_id, status="queued", stage="queued", message="Backfill resume queued",
                progress=0, finished_at=None, error=None,
            )
            asyncio.create_task(self._run(job_id, resume=False))
            return self.repository.get_job(job_id), True

    def get(self, job_id: UUID):
        return self.repository.get_job(job_id)

    def current(self):
        return self.repository.current_job() or self.repository.latest_job()

    def list(self, limit=10, offset=0):
        return self.repository.list_jobs(limit, offset)

    def count(self):
        return self.repository.count_jobs()

    def symbols(self, job_id: UUID, status=None, limit=10, offset=0):
        return self.repository.symbols(job_id, status, limit, offset)

    def response(self, job):
        if job is None:
            return None
        payload = dict(job)
        for key in ("started_at", "finished_at", "updated_at"):
            payload[key] = localize_datetime(payload.get(key), self.settings.market_timezone)
        return payload

    async def _run(self, job_id: UUID, *, resume: bool) -> None:
        self.repository.update_job(
            job_id, status="running", stage="waiting_for_lock",
            message="Waiting for exclusive pipeline lock", progress=1,
        )
        try:
            async with self.coordinator.lock():
                await self._download(job_id, resume=resume)
                await self._rebuild(job_id)
                counts = self.repository.refresh_counts(job_id)
                partial = counts["failed_symbols"] > 0 or counts["partial_symbols"] > 0
                self.repository.update_job(
                    job_id, status="partial_failure" if partial else "succeeded",
                    stage="complete", message="Backfill completed with review items" if partial else "Backfill complete",
                    progress=100, current_symbol=None, finished_at=datetime.now(UTC),
                )
        except PipelineBusyError as error:
            self.repository.update_job(
                job_id, status="failed", stage="failed", message=str(error),
                error=str(error), finished_at=datetime.now(UTC),
            )
        except Exception as error:
            self.repository.update_job(
                job_id, status="failed", stage="failed", message="Historical backfill failed",
                error=sanitize_error(error), finished_at=datetime.now(UTC),
            )

    async def _download(self, job_id: UUID, *, resume: bool) -> None:
        services = self.service_factory()
        collector = services[3]
        symbols = self.repository.pending_symbols(job_id, resume=resume)
        total = max(1, len(symbols))
        self.repository.update_job(
            job_id, stage="downloading", message="Downloading missing historical candles", progress=5,
        )
        for index, item in enumerate(symbols, start=1):
            symbol = item["symbol"]
            self.repository.update_job(job_id, current_symbol=symbol, progress=5 + int(index / total * 60))
            self.repository.update_symbol(job_id, symbol, status="running", attempts=item["attempts"] + 1, error=None)
            try:
                candles, invalid = await asyncio.to_thread(
                    collector.provider.download_with_report,
                    [symbol], item["requested_start_date"], item["requested_end_date"],
                )
                values = candles.get(symbol, [])
                invalid_messages = invalid.get(symbol, ())
                rows_written = await asyncio.to_thread(collector.market_repository.upsert_candles, values)
                status = "partial" if invalid_messages else "succeeded" if values else "no_data"
                self.repository.update_symbol(
                    job_id, symbol, status=status, rows_received=len(values), rows_written=rows_written,
                    invalid_rows_skipped=len(invalid_messages),
                    error="; ".join(invalid_messages)[:2000] if invalid_messages else None,
                    finished_at=datetime.now(UTC),
                )
            except Exception as error:
                self.repository.update_symbol(
                    job_id, symbol, status="failed", error=sanitize_error(error), finished_at=datetime.now(UTC),
                )
            self.repository.refresh_counts(job_id)
            if self.settings.backfill_batch_delay_seconds:
                await asyncio.sleep(self.settings.backfill_batch_delay_seconds)

    async def _rebuild(self, job_id: UUID) -> None:
        job = self.repository.get_job(job_id)
        coverage = self.repository.coverage(job["target_start_date"])
        start_date = coverage["earliest_date"] or job["target_start_date"]
        end_date = coverage["latest_date"] or job["target_end_date"]
        services = self.service_factory()
        stages = (
            ("indicators", services[5]), ("rules", services[7]),
            ("strategies", services[9]), ("scores", services[11]),
            ("rankings", services[13]), ("analyses", services[15]),
            ("risk", services[17]), ("positions", services[19]),
            ("alerts", services[21]),
        )
        self.repository.update_job(job_id, status="rebuilding", stage="rebuilding", message="Rebuilding historical derived data", progress=68)
        for index, (stage, service) in enumerate(stages, start=1):
            self.repository.update_job(
                job_id, stage=stage, message=f"Rebuilding historical {stage}",
                progress=68 + int(index / len(stages) * 30), current_symbol=None,
            )
            if stage == "positions":
                def report_position_progress(trading_date, completed, total):
                    self.repository.update_job(
                        job_id,
                        message=f"Rebuilding historical positions: {trading_date}",
                        progress=68 + int((index - 1 + completed / max(total, 1)) / len(stages) * 30),
                    )

                result = await service.rebuild(
                    start_date=start_date,
                    end_date=end_date,
                    progress=report_position_progress,
                )
            else:
                result = await service.rebuild(start_date=start_date, end_date=end_date)
            status = getattr(getattr(result, "status", None), "value", None)
            if status == "failed":
                raise RuntimeError(f"historical {stage} rebuild failed")

    def _target_range(self, target_years: int) -> tuple[date, date]:
        calendar = load_market_calendar(self.settings.market_calendar_config_path)
        end_date = latest_completed_market_date(datetime.now(UTC), self.settings.market_timezone, calendar)
        start_date = end_date - timedelta(days=target_years * 365 + target_years // 4 + 5)
        return start_date, end_date

    @staticmethod
    def _validate_years(target_years: int) -> None:
        if target_years < 1 or target_years > 5:
            raise BackfillValidationError("target_years must be between 1 and 5")
