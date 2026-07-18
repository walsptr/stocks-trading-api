import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from inspect import isawaitable
from typing import Awaitable, Callable
from uuid import UUID, uuid4

from sqlalchemy import text

from stocks_trading.config.settings import Settings
from stocks_trading.domain.models import RunStatus
from stocks_trading.persistence.database import create_database_engine

PIPELINE_LOCK_ID = 728194531
STAGES = (
    ("market_data", "Downloading market data"),
    ("indicators", "Calculating indicators"),
    ("rules", "Evaluating rules"),
    ("strategies", "Evaluating Swing Trend Following strategy"),
    ("scores", "Calculating technical scores"),
    ("rankings", "Building ranking snapshot"),
    ("analyses", "Generating stock analysis"),
    ("risk", "Generating ATR risk levels"),
    ("positions", "Updating virtual Swing positions"),
    ("alerts", "Updating alerts"),
)


class SyncStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


@dataclass(slots=True)
class SyncJob:
    id: UUID
    status: SyncStatus = SyncStatus.QUEUED
    stage: str = "queued"
    stage_index: int = 0
    stage_count: int = len(STAGES)
    message: str = "Preparing sync"
    market_run_id: UUID | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


ProgressCallback = Callable[[str, int, str], Awaitable[None]]


class PipelineBusyError(RuntimeError):
    pass


class PipelineCoordinator:
    def __init__(self, settings: Settings) -> None:
        self.engine = create_database_engine(settings.database_url)

    @asynccontextmanager
    async def lock(self):
        connection = await asyncio.to_thread(self.engine.connect)
        try:
            acquired = await asyncio.to_thread(
                connection.scalar, text("SELECT pg_try_advisory_lock(:key)"), {"key": PIPELINE_LOCK_ID}
            )
            if not acquired:
                raise PipelineBusyError("Another pipeline or research job is already running")
            yield
        finally:
            try:
                await asyncio.to_thread(
                    connection.execute,
                    text("SELECT pg_advisory_unlock(:key)"),
                    {"key": PIPELINE_LOCK_ID},
                )
            finally:
                await asyncio.to_thread(connection.close)


async def execute_pipeline(
    services,
    *,
    bootstrap_years: int,
    progress: ProgressCallback | None = None,
) -> tuple[bool, UUID | None]:
    async def report(stage: str, index: int, message: str) -> None:
        if progress:
            result = progress(stage, index, message)
            if isawaitable(result):
                await result

    collector = services[3]
    market_status = collector.status()
    await report("market_data", 1, "Downloading one year of IDX history" if market_status["symbols_with_data"] == 0 else "Updating missing local candles")
    market_result = (
        await collector.bootstrap(years=bootstrap_years)
        if market_status["symbols_with_data"] == 0
        else await collector.update()
    )
    if market_result.status == RunStatus.FAILED:
        raise RuntimeError("Market data collection failed")
    partial = market_result.status == RunStatus.PARTIAL_FAILURE
    stage_calls = (
        services[5].update,
        services[7].update,
        services[9].update,
        services[11].update,
        services[13].update,
        services[15].update,
        services[17].update,
        services[19].update,
        services[21].update,
    )
    for index, ((stage, message), stage_call) in enumerate(zip(STAGES[1:], stage_calls), start=2):
        await report(stage, index, message)
        result = await stage_call()
        status = getattr(result, "status", None)
        if status is not None:
            value = status.value
            if value == "failed":
                raise RuntimeError(f"{stage} stage failed")
            partial = partial or value == "partial_failure"
        elif getattr(result, "failed", 0):
            partial = True
    return partial, market_result.run_id


class SyncManager:
    def __init__(self, service_factory, settings: Settings) -> None:
        self.service_factory = service_factory
        self.settings = settings
        self.coordinator = PipelineCoordinator(settings)
        self.jobs: dict[UUID, SyncJob] = {}
        self.latest_job_id: UUID | None = None
        self.active_job_id: UUID | None = None
        self._manager_lock = asyncio.Lock()

    async def start(self, years: int | None = None) -> tuple[SyncJob, bool]:
        async with self._manager_lock:
            if self.active_job_id is not None:
                active = self.jobs[self.active_job_id]
                if active.status in {SyncStatus.QUEUED, SyncStatus.RUNNING}:
                    return active, False
            job = SyncJob(id=uuid4())
            self.jobs[job.id] = job
            self.latest_job_id = job.id
            self.active_job_id = job.id
            asyncio.create_task(self._run(job, years or self.settings.sync_bootstrap_years))
            return job, True

    def get(self, job_id: UUID) -> SyncJob | None:
        return self.jobs.get(job_id)

    def current(self) -> SyncJob | None:
        if self.active_job_id:
            active = self.jobs.get(self.active_job_id)
            if active and active.status in {SyncStatus.QUEUED, SyncStatus.RUNNING}:
                return active
        return self.jobs.get(self.latest_job_id) if self.latest_job_id else None

    async def _run(self, job: SyncJob, years: int) -> None:
        job.status = SyncStatus.RUNNING
        job.started_at = datetime.now(UTC)

        async def progress(stage: str, index: int, message: str) -> None:
            job.stage = stage
            job.stage_index = index
            job.message = message

        try:
            async with self.coordinator.lock():
                partial, market_run_id = await execute_pipeline(
                    self.service_factory(), bootstrap_years=years, progress=progress
                )
                job.market_run_id = market_run_id
                job.status = SyncStatus.PARTIAL_FAILURE if partial else SyncStatus.SUCCEEDED
                job.stage = "complete"
                job.stage_index = job.stage_count
                job.message = "Sync completed with some symbol failures" if partial else "Sync complete"
        except PipelineBusyError as error:
            job.status = SyncStatus.FAILED
            job.error = str(error)
            job.message = str(error)
        except Exception as error:
            job.status = SyncStatus.FAILED
            job.error = " ".join(str(error).split())[:1000]
            job.message = "Sync failed"
        finally:
            job.finished_at = datetime.now(UTC)
            async with self._manager_lock:
                if self.active_job_id == job.id:
                    self.active_job_id = None
