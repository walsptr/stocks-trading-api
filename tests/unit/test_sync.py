import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from stocks_trading.domain.models import RunStatus
from stocks_trading.sync.service import SyncManager, SyncStatus, execute_pipeline


class FakeCollector:
    def __init__(self, empty=True):
        self.empty = empty
        self.calls = []

    def status(self):
        return {"symbols_with_data": 0 if self.empty else 2}

    async def bootstrap(self, years):
        self.calls.append(("bootstrap", years))
        return SimpleNamespace(status=RunStatus.SUCCEEDED, run_id=UUID(int=1))

    async def update(self):
        self.calls.append(("update",))
        return SimpleNamespace(status=RunStatus.SUCCEEDED, run_id=UUID(int=2))


class FakeStage:
    def __init__(self, name):
        self.name = name
        self.calls = 0

    async def update(self):
        self.calls += 1
        return SimpleNamespace(status=SimpleNamespace(value="succeeded"))


class FakeSettings:
    sync_bootstrap_years = 1
    database_url = "postgresql+psycopg://unused"


@pytest.mark.asyncio
async def test_pipeline_bootstraps_empty_database_and_runs_all_stages(monkeypatch):
    collector = FakeCollector(empty=True)
    stages = [FakeStage(str(index)) for index in range(9)]
    services = [None, None, None, collector, None, stages[0], None, stages[1], None, stages[2], None, stages[3], None, stages[4], None, stages[5], None, stages[6], None, stages[7], None, stages[8]]
    progress = []

    partial, run_id = await execute_pipeline(
        services,
        bootstrap_years=1,
        progress=lambda stage, index, message: progress.append((stage, index)),
    )

    assert partial is False
    assert run_id == UUID(int=1)
    assert collector.calls == [("bootstrap", 1)]
    assert [item[0] for item in progress] == ["market_data", "indicators", "rules", "strategies", "scores", "rankings", "analyses", "risk", "positions", "alerts"]
    assert all(stage.calls == 1 for stage in stages)


@pytest.mark.asyncio
async def test_pipeline_uses_incremental_update_when_cache_exists():
    collector = FakeCollector(empty=False)
    stages = [FakeStage(str(index)) for index in range(9)]
    services = [None, None, None, collector, None, stages[0], None, stages[1], None, stages[2], None, stages[3], None, stages[4], None, stages[5], None, stages[6], None, stages[7], None, stages[8]]

    await execute_pipeline(services, bootstrap_years=1)

    assert collector.calls == [("update",)]


@pytest.mark.asyncio
async def test_manual_technical_pipeline_stops_after_ranking():
    collector = FakeCollector(empty=False)
    stages = [FakeStage(str(index)) for index in range(9)]
    services = [None, None, None, collector, None, stages[0], None, stages[1], None, stages[2], None, stages[3], None, stages[4], None, stages[5], None, stages[6], None, stages[7], None, stages[8]]
    progress = []

    await execute_pipeline(
        services,
        bootstrap_years=1,
        include_downstream=False,
        progress=lambda stage, index, message: progress.append(stage),
    )

    assert progress == ["market_data", "indicators", "rules", "strategies", "scores", "rankings"]
    assert all(stage.calls == 1 for stage in stages[:5])
    assert all(stage.calls == 0 for stage in stages[5:])


@pytest.mark.asyncio
async def test_sync_manager_returns_same_active_job():
    manager = SyncManager(lambda: None, FakeSettings())
    manager._run = lambda job, years: asyncio.sleep(3600)

    first, created = await manager.start()
    second, created_again = await manager.start()

    assert created is True
    assert created_again is False
    assert first.id == second.id
    task = next(iter(asyncio.all_tasks() - {asyncio.current_task()}))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
