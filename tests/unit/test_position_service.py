from datetime import date
from pathlib import Path
from uuid import UUID

import pytest

from stocks_trading.domain.models import PositionRunMode
from stocks_trading.positions.config import load_position_configuration
from stocks_trading.positions.service import PositionService


class Repository:
    def latest_processed_date(self, configuration): return date(2026, 7, 17)
    def active_positions(self, configuration): return {}
    def existing_signals(self, configuration): return set()
    def source_dates(self, configuration, start_date, end_date):
        self.range = (start_date, end_date); return []
    def load_sources(self, trading_date, configuration): return []
    def save(self, positions, events): pass
    def rebuild(self, configuration): self.rebuilt = True


class Runs:
    def create(self, mode, configuration): self.mode = mode; return UUID(int=1)
    def finish(self, run_id, positions_count, events_count, failed=False): self.finished = not failed


@pytest.mark.asyncio
async def test_update_starts_at_latest_processed_date():
    repository = Repository(); runs = Runs()
    service = PositionService(repository, runs, load_position_configuration(Path("config/positions/swing-lifecycle-v1.yaml")))
    result = await service.update(as_of=date(2026, 7, 18))
    assert repository.range == (date(2026, 7, 17), date(2026, 7, 18))
    assert runs.mode == PositionRunMode.UPDATE
    assert result.positions == 0
