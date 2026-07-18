from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

from stocks_trading.alerts.config import load_alert_configuration
from stocks_trading.alerts.service import AlertService
from stocks_trading.domain.models import AlertSourceState


class FakeRepository:
    def __init__(self):
        self.watermark = None
        self.events = []
        self.dates = [date(2026, 7, 15), date(2026, 7, 16)]

    def source_dates(self, version, checksum, *, start_date, end_date):
        return self.dates

    def get_watermark(self, version, checksum):
        return self.watermark

    def set_watermark(self, version, checksum, trading_date):
        self.watermark = trading_date

    def load_states(self, trading_date, versions):
        return [AlertSourceState("BBCA.JK", trading_date, 95, "Strong Buy", 1, "passed", True, True, (), (), {})]

    def previous_state(self, symbol, before, versions):
        return AlertSourceState(symbol, date(2026, 7, 15), 80, "Buy", 2, "failed", False, False, (), (), {})

    def save_event(self, event):
        self.events.append(event)
        return True

    def pending_events(self, maximum_attempts, limit):
        return []

    def record_delivery(self, alert_id, *, succeeded, error):
        pass


class FakeRuns:
    def create(self, mode):
        return uuid4()
    def finish(self, run_id, generated, sent, failed):
        self.finished = (generated, sent, failed)


class FakeTelegram:
    configured = False


@pytest.mark.asyncio
async def test_first_update_establishes_baseline_without_alerts() -> None:
    repository = FakeRepository()
    result = await AlertService(
        alert_repository=repository, run_repository=FakeRuns(),
        configuration=load_alert_configuration(Path("config/alerts/technical-v1.yaml")),
        telegram=FakeTelegram(),
    ).update()
    assert result.generated == 0
    assert repository.watermark == date(2026, 7, 16)
    assert repository.events == []


@pytest.mark.asyncio
async def test_subsequent_update_processes_new_date() -> None:
    repository = FakeRepository()
    repository.watermark = date(2026, 7, 15)
    result = await AlertService(
        alert_repository=repository, run_repository=FakeRuns(),
        configuration=load_alert_configuration(Path("config/alerts/technical-v1.yaml")),
        telegram=FakeTelegram(),
    ).update()
    assert result.generated == 1
    assert repository.watermark == date(2026, 7, 16)
