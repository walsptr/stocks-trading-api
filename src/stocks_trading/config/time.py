from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def localize_datetime(value: datetime | None, timezone: ZoneInfo) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(timezone)
