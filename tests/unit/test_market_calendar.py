from datetime import date
from pathlib import Path

import pytest

from stocks_trading.market_data.calendar import (
    MarketCalendarConfigurationError,
    load_market_calendar,
)


def write_calendar(tmp_path: Path, coverage: str) -> Path:
    path = tmp_path / "calendar.yaml"
    path.write_text(
        "\n".join(
            (
                "calendar_version: test-v1",
                "exchange: XIDX",
                "timezone: Asia/Jakarta",
                "coverage:",
                coverage,
            )
        ),
        encoding="utf-8",
    )
    return path


def test_official_closures_and_consecutive_non_trading_days(tmp_path: Path) -> None:
    path = write_calendar(
        tmp_path,
        """  2026:
    status: official
    closures:
      - date: '2026-07-16'
        name: First closure
        type: exchange_holiday
      - date: '2026-07-17'
        name: Second closure
        type: special_closure""",
    )

    calendar = load_market_calendar(path)

    assert calendar.official_years == (2026,)
    assert calendar.is_trading_day(date(2026, 7, 16)) is False
    assert calendar.next_trading_day(date(2026, 7, 15)) == date(2026, 7, 20)
    assert calendar.previous_trading_day(date(2026, 7, 20)) == date(2026, 7, 15)


def test_pending_year_uses_weekend_only_fallback(tmp_path: Path) -> None:
    path = write_calendar(
        tmp_path,
        """  2027:
    status: pending
    closures: []""",
    )

    calendar = load_market_calendar(path)

    assert calendar.pending_years == (2027,)
    assert calendar.is_trading_day(date(2027, 1, 1)) is True
    assert calendar.is_trading_day(date(2027, 1, 2)) is False
    assert calendar.next_trading_day(date(2027, 1, 1)) == date(2027, 1, 4)


def test_repository_calendar_has_official_2026_closures_and_source() -> None:
    calendar = load_market_calendar(Path("config/market-calendar/idx-v2.yaml"))

    assert calendar.calendar_version == "idx-v2"
    assert calendar.official_years == (2026,)
    assert calendar.pending_years == (2027, 2028)
    assert calendar.source_reference == "PENG-0002/DIR/KSEI/0126"
    assert calendar.source_published_date == date(2026, 1, 8)
    assert len(calendar.closures_for_year(2026)) == 22
    assert calendar.is_trading_day(date(2026, 3, 20)) is False
    assert calendar.next_trading_day(date(2026, 3, 17)) == date(2026, 3, 25)
    assert calendar.is_trading_day(date(2026, 12, 31)) is False


@pytest.mark.parametrize(
    "coverage, message",
    (
        (
            """  2026:
    status: official
    closures:
      - date: '2026-01-01'
        name: One
        type: exchange_holiday
      - date: '2026-01-01'
        name: Duplicate
        type: special_closure""",
            "duplicate market closure date",
        ),
        (
            """  2026:
    status: official
    closures:
      - date: '2026-01-01'
        name: Invalid type
        type: early_close""",
            "unsupported closure type",
        ),
        (
            """  2026:
    status: pending
    closures:
      - date: '2026-01-01'
        name: Not verified
        type: exchange_holiday""",
            "pending coverage 2026 must not contain closures",
        ),
    ),
)
def test_invalid_calendar_configuration_is_rejected(
    tmp_path: Path, coverage: str, message: str
) -> None:
    path = write_calendar(tmp_path, coverage)

    with pytest.raises(MarketCalendarConfigurationError, match=message):
        load_market_calendar(path)
