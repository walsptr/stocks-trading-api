import asyncio
from datetime import date
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from stocks_trading.backfill.service import HistoricalBackfillManager


class FakeRepository:
    def __init__(self):
        self.jobs = {}
        self.symbols_by_job = {}

    def coverage(self, target_start_date):
        return {
            "active_symbols": 2, "symbols_with_data": 2,
            "symbols_meeting_target": 1, "symbols_needing_backfill": 1,
            "earliest_date": date(2021, 7, 12), "latest_date": date(2026, 7, 17),
            "total_rows": 100,
        }

    def candidates(self, start_date, end_date):
        return [{"symbol": "BBCA.JK", "start_date": start_date, "end_date": date(2025, 7, 10)}]

    def create_job(self, years, start_date, end_date, symbols):
        job_id = uuid4()
        job = {
            "id": job_id, "target_years": years, "target_start_date": start_date,
            "target_end_date": end_date, "status": "queued", "stage": "queued",
            "message": "queued", "progress": 0, "total_symbols": len(symbols),
            "processed_symbols": 0, "succeeded_symbols": 0, "partial_symbols": 0,
            "failed_symbols": 0, "no_data_symbols": 0, "rows_written": 0,
            "invalid_rows_skipped": 0, "current_symbol": None, "error": None,
            "started_at": None, "finished_at": None, "updated_at": None,
        }
        self.jobs[job_id] = job
        self.symbols_by_job[job_id] = [
            {"id": 1, "job_id": job_id, "symbol": item["symbol"],
             "requested_start_date": item["start_date"], "requested_end_date": item["end_date"],
             "status": "pending", "attempts": 0, "rows_received": 0,
             "rows_written": 0, "invalid_rows_skipped": 0, "error": None,
             "collection_run_id": None, "finished_at": None}
            for item in symbols
        ]
        return dict(job)

    def update_job(self, job_id, **values):
        self.jobs[job_id].update(values)
        return dict(self.jobs[job_id])

    def get_job(self, job_id): return dict(self.jobs[job_id]) if job_id in self.jobs else None
    def current_job(self): return next((dict(job) for job in self.jobs.values() if job["status"] in {"queued", "running", "rebuilding"}), None)
    def latest_job(self): return dict(next(reversed(self.jobs.values()))) if self.jobs else None
    def list_jobs(self, limit=10, offset=0): return list(self.jobs.values())[offset:offset + limit]
    def count_jobs(self): return len(self.jobs)
    def interrupt_active(self): return []

    def pending_symbols(self, job_id, resume=False):
        statuses = {"failed", "partial", "interrupted"} if resume else {"pending", "running", "interrupted"}
        return [dict(item) for item in self.symbols_by_job[job_id] if item["status"] in statuses]

    def update_symbol(self, job_id, symbol, **values):
        next(item for item in self.symbols_by_job[job_id] if item["symbol"] == symbol).update(values)

    def reset_retryable(self, job_id):
        for item in self.symbols_by_job[job_id]:
            if item["status"] in {"failed", "partial", "interrupted"}:
                item.update(status="pending", error=None)

    def refresh_counts(self, job_id):
        symbols = self.symbols_by_job[job_id]
        values = {
            "processed_symbols": sum(item["status"] not in {"pending", "running", "interrupted"} for item in symbols),
            "succeeded_symbols": sum(item["status"] == "succeeded" for item in symbols),
            "partial_symbols": sum(item["status"] == "partial" for item in symbols),
            "failed_symbols": sum(item["status"] == "failed" for item in symbols),
            "no_data_symbols": sum(item["status"] == "no_data" for item in symbols),
            "rows_written": sum(item["rows_written"] for item in symbols),
            "invalid_rows_skipped": sum(item["invalid_rows_skipped"] for item in symbols),
        }
        self.jobs[job_id].update(values)
        return values

    def symbols(self, job_id, status=None, limit=10, offset=0):
        values = [item for item in self.symbols_by_job[job_id] if not status or item["status"] == status]
        return values[offset:offset + limit], len(values)


class FakeCoordinator:
    def lock(self): return self
    async def __aenter__(self): return self
    async def __aexit__(self, *args): return False


class FakeProvider:
    def download_with_report(self, symbols, start_date, end_date):
        return {symbols[0]: [SimpleNamespace()]}, {symbols[0]: ("invalid row",)}


class FakeMarketRepository:
    def upsert_candles(self, candles): return len(candles)


class FakeService:
    def __init__(self, calls, name): self.calls = calls; self.name = name
    async def rebuild(self, **kwargs):
        self.calls.append((self.name, kwargs))
        progress = kwargs.get("progress")
        if progress:
            progress(date(2026, 7, 17), 1, 1)
        return SimpleNamespace(status=SimpleNamespace(value="succeeded"))


class FakeSettings:
    database_url = "postgresql+psycopg://unused"
    market_timezone = ZoneInfo("Asia/Jakarta")
    market_calendar_config_path = "config/market-calendar/idx-v2.yaml"
    backfill_batch_delay_seconds = 0


def make_manager():
    repository = FakeRepository()
    rebuild_calls = []
    services = [None] * 22
    services[3] = SimpleNamespace(provider=FakeProvider(), market_repository=FakeMarketRepository())
    for index, name in zip((5, 7, 9, 11, 13, 15, 17, 19, 21),
                           ("indicators", "rules", "strategies", "scores", "rankings", "analyses", "risk", "positions", "alerts")):
        services[index] = FakeService(rebuild_calls, name)
    manager = HistoricalBackfillManager(repository, lambda: services, FakeSettings())
    manager.coordinator = FakeCoordinator()
    manager._target_range = lambda years: (date(2021, 7, 11), date(2026, 7, 17))
    return manager, repository, rebuild_calls


@pytest.mark.asyncio
async def test_backfill_persists_partial_rows_and_rebuilds_all_stages():
    manager, repository, rebuild_calls = make_manager()

    job, created = await manager.start(5)
    assert created is True
    await asyncio.sleep(0.05)

    saved = manager.get(job["id"])
    assert saved["status"] == "partial_failure"
    assert saved["rows_written"] == 1
    assert saved["invalid_rows_skipped"] == 1
    assert [name for name, _ in rebuild_calls] == [
        "indicators", "rules", "strategies", "scores", "rankings",
        "analyses", "risk", "positions", "alerts",
    ]
    assert repository.jobs[job["id"]]["message"] in {
        "Backfill completed with review items", "Backfill complete"
    }


@pytest.mark.asyncio
async def test_resume_resets_only_retryable_symbols():
    manager, repository, _ = make_manager()
    job = repository.create_job(5, date(2021, 7, 11), date(2026, 7, 17), repository.candidates(date(2021, 7, 11), date(2026, 7, 17)))
    repository.update_job(job["id"], status="partial_failure")
    repository.update_symbol(job["id"], "BBCA.JK", status="failed", error="rate limited")

    resumed, created = await manager.resume(job["id"])
    assert created is True
    assert resumed["status"] == "queued"
    await asyncio.sleep(0.05)
    assert manager.get(job["id"])["status"] == "partial_failure"
