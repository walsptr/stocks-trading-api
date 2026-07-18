import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Callable
from uuid import UUID

from stocks_trading.config.settings import Settings
from stocks_trading.config.time import localize_datetime
from stocks_trading.sync.service import PipelineBusyError, PipelineCoordinator


class ResearchValidationError(ValueError):
    pass


class ResearchManager:
    def __init__(self, repository, service_factory: Callable, settings: Settings) -> None:
        self.repository = repository
        self.service_factory = service_factory
        self.settings = settings
        self.coordinator = PipelineCoordinator(settings)
        self._manager_lock = asyncio.Lock()

    def recover_interrupted(self) -> int:
        return self.repository.interrupt_active()

    def availability(self) -> dict[str, object]:
        services = self.service_factory()
        backtest_configuration = services[23].configuration
        optimization_configuration = services[25].configuration
        values = self.repository.availability(
            backtest_configuration.strategy_name,
            backtest_configuration.strategy_version,
            backtest_configuration.strategy_config_checksum,
            optimization_configuration.indicator_version,
        )
        backtest_end = values["backtest_end"]
        optimization_end = values["optimization_end"]
        return {
            **values,
            "backtest_default_start": self._bounded_start(backtest_end, values["backtest_start"], 365),
            "backtest_default_end": backtest_end,
            "optimization_default_start": self._bounded_start(optimization_end, values["optimization_start"], 365 * 3),
            "optimization_default_end": optimization_end,
        }

    async def start(self, job_type: str, start_date: date, end_date: date):
        self._validate(job_type, start_date, end_date)
        async with self._manager_lock:
            current = self.repository.current_job()
            if current:
                return current, False
            job = self.repository.create_job(job_type, start_date, end_date)
            asyncio.create_task(self._run(job["id"]))
            return job, True

    def get(self, job_id: UUID):
        return self.repository.get_job(job_id)

    def current(self):
        return self.repository.current_job()

    def list(self, limit: int = 50, offset: int = 0):
        return self.repository.list_jobs(limit, offset)

    def response(self, job):
        if job is None:
            return None
        payload = dict(job)
        payload["started_at"] = localize_datetime(payload.get("started_at"), self.settings.market_timezone)
        payload["finished_at"] = localize_datetime(payload.get("finished_at"), self.settings.market_timezone)
        return payload

    async def _run(self, job_id: UUID) -> None:
        job = self.repository.get_job(job_id)
        if not job:
            return
        self.repository.update_job(
            job_id, status="running", stage="waiting_for_lock",
            message="Waiting for exclusive research lock", progress=10,
        )
        try:
            async with self.coordinator.lock():
                self.repository.update_job(
                    job_id, stage="loading_data", message="Loading persisted market data",
                    progress=30,
                )
                services = self.service_factory()
                service = services[23] if job["job_type"] == "backtest" else services[25]
                self.repository.update_job(
                    job_id, stage="evaluating",
                    message="Running legacy BSJP backtest" if job["job_type"] == "backtest" else "Evaluating legacy BSJP optimizer candidates",
                    progress=55,
                )
                result = await asyncio.to_thread(
                    service.run, start_date=job["start_date"], end_date=job["end_date"]
                )
                self.repository.update_job(
                    job_id, status="succeeded", stage="complete", message="Research complete",
                    progress=100, result_run_id=result.run_id, finished_at=datetime.now(UTC),
                )
        except PipelineBusyError as error:
            self.repository.update_job(
                job_id, status="failed", stage="failed", message=str(error),
                error=str(error), finished_at=datetime.now(UTC),
            )
        except Exception as error:
            message = " ".join(str(error).split())[:1000]
            self.repository.update_job(
                job_id, status="failed", stage="failed", message="Research failed",
                error=message, finished_at=datetime.now(UTC),
            )

    def _validate(self, job_type: str, start_date: date, end_date: date) -> None:
        if job_type not in {"backtest", "optimization"}:
            raise ResearchValidationError("unsupported research job type")
        if start_date > end_date:
            raise ResearchValidationError("start_date must not be after end_date")
        availability = self.availability()
        available_start = availability[f"{job_type}_start"]
        available_end = availability[f"{job_type}_end"]
        if available_start is None or available_end is None:
            raise ResearchValidationError("required persisted pipeline data is unavailable; run Sync first")
        if start_date < available_start or end_date > available_end:
            raise ResearchValidationError(
                f"requested range must be between {available_start} and {available_end}; run Sync first for newer data"
            )

    @staticmethod
    def _bounded_start(end_date: date | None, minimum: date | None, days: int):
        if end_date is None or minimum is None:
            return None
        return max(minimum, end_date - timedelta(days=days))
