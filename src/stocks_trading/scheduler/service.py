import asyncio
import logging
import os
import signal
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from stocks_trading.cli.app import dependencies
from stocks_trading.config.logging import configure_logging
from stocks_trading.config.settings import get_settings
from stocks_trading.domain.models import RunStatus
from stocks_trading.market_data.calendar import MarketCalendar, load_market_calendar
from stocks_trading.sync.service import PipelineBusyError, PipelineCoordinator, execute_pipeline
from stocks_trading.fundamentals.config import load_fundamental_configuration
from stocks_trading.fundamentals.service import FundamentalService
from stocks_trading.persistence.database import create_database_engine, create_session_factory
from stocks_trading.persistence.repositories import SqlAlchemyFundamentalRepository

logger = logging.getLogger("stocks_trading.scheduler")


def next_run(
    now: datetime,
    hour: int,
    minute: int,
    market_calendar: MarketCalendar | None = None,
) -> datetime:
    candidate = datetime.combine(now.date(), time(hour, minute), tzinfo=now.tzinfo)
    if candidate <= now:
        candidate += timedelta(days=1)
    while (
        not market_calendar.is_trading_day(candidate.date())
        if market_calendar is not None
        else candidate.weekday() >= 5
    ):
        candidate += timedelta(days=1)
    return candidate


async def run_pipeline() -> bool:
    logger.info("starting scheduled IDX pipeline")
    coordinator = PipelineCoordinator(get_settings())
    try:
        async with coordinator.lock():
            partial, _ = await execute_pipeline(
                dependencies(),
                bootstrap_years=get_settings().sync_bootstrap_years,
                include_downstream=True,
            )
            logger.info("scheduled IDX pipeline completed")
            return not partial
    except PipelineBusyError:
        logger.warning("scheduled pipeline skipped because another sync is running")
        return False


def next_monthly_run(now: datetime, day: int, hour: int, minute: int) -> datetime:
    year, month = now.year, now.month
    candidate = datetime(year, month, day, hour, minute, tzinfo=now.tzinfo)
    if candidate <= now:
        month += 1
        if month == 13:
            year, month = year + 1, 1
        candidate = datetime(year, month, day, hour, minute, tzinfo=now.tzinfo)
    return candidate


async def run_fundamental_pipeline() -> bool:
    settings = get_settings()
    coordinator = PipelineCoordinator(settings)
    repository = SqlAlchemyFundamentalRepository(create_session_factory(create_database_engine(settings.database_url)))
    service = FundamentalService(repository, load_fundamental_configuration(settings.fundamental_config_path), settings.max_workers)
    try:
        async with coordinator.lock():
            result = await service.update()
        logger.info("scheduled fundamental pipeline completed: %s", result)
        return result["status"] == "succeeded"
    except PipelineBusyError:
        logger.warning("scheduled fundamental pipeline skipped because another job is running")
        return False


async def main() -> None:
    timezone = ZoneInfo(os.getenv("STOCKS_SCHEDULER_TIMEZONE", "Asia/Jakarta"))
    configure_logging(os.getenv("STOCKS_LOG_LEVEL", "INFO"), timezone)
    if os.getenv("STOCKS_SCHEDULER_ENABLED", "true").lower() not in {"1", "true", "yes", "on"}:
        logger.info("scheduler disabled")
        await asyncio.Event().wait()
    hour = int(os.getenv("STOCKS_SCHEDULER_HOUR", "18"))
    minute = int(os.getenv("STOCKS_SCHEDULER_MINUTE", "0"))
    market_calendar = load_market_calendar(
        get_settings().market_calendar_config_path
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for selected_signal in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(selected_signal, stop.set)
    fundamental_enabled = os.getenv("STOCKS_FUNDAMENTAL_SCHEDULER_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    fundamental_day = int(os.getenv("STOCKS_FUNDAMENTAL_SCHEDULER_DAY", "10"))
    fundamental_hour = int(os.getenv("STOCKS_FUNDAMENTAL_SCHEDULER_HOUR", "20"))
    fundamental_minute = int(os.getenv("STOCKS_FUNDAMENTAL_SCHEDULER_MINUTE", "0"))
    last_fundamental_month: tuple[int, int] | None = None
    while not stop.is_set():
        now = datetime.now(timezone)
        scheduled = next_run(now, hour, minute, market_calendar)
        fundamental_scheduled = next_monthly_run(now, fundamental_day, fundamental_hour, fundamental_minute) if fundamental_enabled else None
        wake_at = min(scheduled, fundamental_scheduled) if fundamental_scheduled else scheduled
        logger.info("next pipeline run at %s", scheduled.isoformat())
        if fundamental_scheduled:
            logger.info("next fundamental pipeline run at %s", fundamental_scheduled.isoformat())
        try:
            await asyncio.wait_for(stop.wait(), timeout=max(0, (wake_at - now).total_seconds()))
        except TimeoutError:
            try:
                current = datetime.now(timezone)
                if fundamental_scheduled and wake_at == fundamental_scheduled and last_fundamental_month != (current.year, current.month):
                    await run_fundamental_pipeline()
                    last_fundamental_month = (current.year, current.month)
                else:
                    await run_pipeline()
            except Exception:
                logger.exception("scheduled pipeline failed")
