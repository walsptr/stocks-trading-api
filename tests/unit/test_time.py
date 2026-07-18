import json
import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from stocks_trading.config.logging import JsonFormatter
from stocks_trading.config.time import localize_datetime


def test_localize_datetime_converts_utc_to_jakarta() -> None:
    result = localize_datetime(
        datetime(2026, 7, 17, 11, 0, tzinfo=UTC), ZoneInfo("Asia/Jakarta")
    )

    assert result.isoformat() == "2026-07-17T18:00:00+07:00"


def test_localize_datetime_treats_database_naive_values_as_utc() -> None:
    result = localize_datetime(
        datetime(2026, 7, 17, 11, 0), ZoneInfo("Asia/Jakarta")
    )

    assert result.isoformat() == "2026-07-17T18:00:00+07:00"


def test_json_logs_include_jakarta_offset() -> None:
    formatter = JsonFormatter(ZoneInfo("Asia/Jakarta"))
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "ready", (), None)

    payload = json.loads(formatter.format(record))

    assert payload["timestamp"].endswith("+07:00")
