import asyncio
from datetime import date
from types import SimpleNamespace
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from stocks_trading.research.service import ResearchManager, ResearchValidationError


class FakeRepository:
    def __init__(self):
        self.jobs = {}

    def availability(self, *args):
        return {
            "price_start": date(2021, 7, 12), "price_end": date(2026, 7, 17),
            "backtest_start": date(2021, 7, 12), "backtest_end": date(2026, 7, 17),
            "optimization_start": date(2021, 7, 12), "optimization_end": date(2026, 7, 17),
        }

    def interrupt_active(self): return 0
    def current_job(self): return next((item for item in self.jobs.values() if item["status"] in {"queued", "running"}), None)
    def create_job(self, job_type, start_date, end_date):
        job = {"id": uuid4(), "job_type": job_type, "status": "queued", "start_date": start_date,
               "end_date": end_date, "stage": "queued", "message": "queued", "progress": 0,
               "result_run_id": None, "error": None, "started_at": None, "finished_at": None}
        self.jobs[job["id"]] = job
        return dict(job)
    def update_job(self, job_id, **values): self.jobs[job_id].update(values); return dict(self.jobs[job_id])
    def get_job(self, job_id): return dict(self.jobs[job_id]) if job_id in self.jobs else None
    def list_jobs(self, limit=50): return list(self.jobs.values())[:limit]


class FakeSettings:
    database_url = "postgresql+psycopg://unused"
    market_timezone = ZoneInfo("Asia/Jakarta")


class FakeCoordinator:
    async def __aenter__(self): return self
    async def __aexit__(self, *args): return False
    def lock(self): return self


def services():
    backtest = SimpleNamespace(configuration=SimpleNamespace(
        strategy_name="Swing Trend Following", strategy_version="swing-trend-following-v1", strategy_config_checksum="checksum"
    ), run=lambda **kwargs: SimpleNamespace(run_id=UUID(int=1)))
    optimization = SimpleNamespace(configuration=SimpleNamespace(indicator_version="technical-v2"),
                                   run=lambda **kwargs: SimpleNamespace(run_id=UUID(int=2)))
    values = [None] * 26
    values[23] = backtest; values[25] = optimization
    return values


def manager():
    value = ResearchManager(FakeRepository(), services, FakeSettings())
    value.coordinator = FakeCoordinator()
    return value


def test_availability_builds_one_and_three_year_defaults():
    result = manager().availability()
    assert result["backtest_default_start"] == date(2025, 7, 17)
    assert result["optimization_default_start"] == date(2023, 7, 18)


def test_research_rejects_range_outside_persisted_data():
    with pytest.raises(ResearchValidationError, match="Technical tab"):
        manager()._validate("backtest", date(2020, 1, 1), date(2026, 7, 17))


@pytest.mark.asyncio
async def test_research_job_runs_and_persists_result():
    value = manager()
    job, created = await value.start("backtest", date(2025, 7, 17), date(2026, 7, 17))
    assert created is True
    await asyncio.sleep(0.05)
    saved = value.get(job["id"])
    assert saved["status"] == "succeeded"
    assert saved["result_run_id"] == UUID(int=1)


@pytest.mark.asyncio
async def test_research_returns_existing_active_job():
    value = manager()
    first, created = await value.start("backtest", date(2025, 7, 17), date(2026, 7, 17))
    second, created_again = await value.start("optimization", date(2023, 7, 18), date(2026, 7, 17))
    assert created is True
    assert created_again is False
    assert first["id"] == second["id"]
    await asyncio.sleep(0.05)
