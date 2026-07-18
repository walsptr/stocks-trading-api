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
from stocks_trading.sync.service import PipelineBusyError, PipelineCoordinator, execute_pipeline

logger = logging.getLogger("stocks_trading.scheduler")


def next_run(now: datetime, hour: int, minute: int) -> datetime:
    candidate = datetime.combine(now.date(), time(hour, minute), tzinfo=now.tzinfo)
    if candidate <= now:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
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
            )
            logger.info("scheduled IDX pipeline completed")
            return not partial
    except PipelineBusyError:
        logger.warning("scheduled pipeline skipped because another sync is running")
        return False


async def main() -> None:
    timezone = ZoneInfo(os.getenv("STOCKS_SCHEDULER_TIMEZONE", "Asia/Jakarta"))
    configure_logging(os.getenv("STOCKS_LOG_LEVEL", "INFO"), timezone)
    if os.getenv("STOCKS_SCHEDULER_ENABLED", "true").lower() not in {"1", "true", "yes", "on"}:
        logger.info("scheduler disabled")
        await asyncio.Event().wait()
    hour = int(os.getenv("STOCKS_SCHEDULER_HOUR", "18"))
    minute = int(os.getenv("STOCKS_SCHEDULER_MINUTE", "0"))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for selected_signal in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(selected_signal, stop.set)
    while not stop.is_set():
        now = datetime.now(timezone)
        scheduled = next_run(now, hour, minute)
        logger.info("next pipeline run at %s", scheduled.isoformat())
        try:
            await asyncio.wait_for(stop.wait(), timeout=max(0, (scheduled - now).total_seconds()))
        except TimeoutError:
            try:
                await run_pipeline()
            except Exception:
                logger.exception("scheduled pipeline failed")
