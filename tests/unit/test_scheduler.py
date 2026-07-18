from datetime import datetime
from zoneinfo import ZoneInfo

from stocks_trading.scheduler.service import next_run


def test_next_run_uses_weekday_schedule() -> None:
    timezone = ZoneInfo("Asia/Jakarta")
    friday_after_close = datetime(2026, 7, 17, 19, 0, tzinfo=timezone)

    scheduled = next_run(friday_after_close, 18, 0)

    assert scheduled.isoformat() == "2026-07-20T18:00:00+07:00"


def test_next_run_keeps_same_day_before_schedule() -> None:
    timezone = ZoneInfo("Asia/Jakarta")
    friday_before_schedule = datetime(2026, 7, 17, 17, 59, tzinfo=timezone)

    scheduled = next_run(friday_before_schedule, 18, 0)

    assert scheduled.isoformat() == "2026-07-17T18:00:00+07:00"
