from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from stocks_trading.market_data.calendar import load_market_calendar
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


def test_next_run_skips_configured_market_closure(tmp_path: Path) -> None:
    calendar_path = tmp_path / "calendar.yaml"
    calendar_path.write_text(
        """calendar_version: test-v1
exchange: XIDX
timezone: Asia/Jakarta
coverage:
  2026:
    status: official
    closures:
      - date: '2026-07-20'
        name: Test closure
        type: exchange_holiday
""",
        encoding="utf-8",
    )
    timezone = ZoneInfo("Asia/Jakarta")
    friday_after_close = datetime(2026, 7, 17, 19, 0, tzinfo=timezone)

    scheduled = next_run(
        friday_after_close,
        18,
        0,
        load_market_calendar(calendar_path),
    )

    assert scheduled.isoformat() == "2026-07-21T18:00:00+07:00"


def test_next_run_skips_official_eid_closure_sequence() -> None:
    timezone = ZoneInfo("Asia/Jakarta")
    calendar = load_market_calendar(Path("config/market-calendar/idx-v2.yaml"))
    before_closures = datetime(2026, 3, 17, 19, 0, tzinfo=timezone)

    scheduled = next_run(before_closures, 18, 0, calendar)

    assert scheduled.isoformat() == "2026-03-25T18:00:00+07:00"


def test_next_run_skips_year_end_exchange_holiday() -> None:
    timezone = ZoneInfo("Asia/Jakarta")
    calendar = load_market_calendar(Path("config/market-calendar/idx-v2.yaml"))
    before_exchange_holiday = datetime(2026, 12, 30, 19, 0, tzinfo=timezone)

    scheduled = next_run(before_exchange_holiday, 18, 0, calendar)

    assert scheduled.isoformat() == "2027-01-01T18:00:00+07:00"
