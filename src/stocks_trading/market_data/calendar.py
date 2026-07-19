import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml


class MarketCalendarConfigurationError(ValueError):
    pass


SUPPORTED_COVERAGE_STATUSES = frozenset({"official", "pending"})
SUPPORTED_CLOSURE_TYPES = frozenset({"exchange_holiday", "special_closure"})


@dataclass(frozen=True, slots=True)
class MarketClosure:
    trading_date: date
    name: str
    closure_type: str


@dataclass(frozen=True, slots=True)
class CalendarYearCoverage:
    year: int
    status: str
    closures: tuple[MarketClosure, ...]


@dataclass(frozen=True, slots=True)
class MarketCalendar:
    calendar_version: str
    exchange: str
    timezone: ZoneInfo
    source_reference: str | None
    source_published_date: date | None
    coverage: dict[int, CalendarYearCoverage]
    checksum: str

    @property
    def official_years(self) -> tuple[int, ...]:
        return tuple(
            year for year, value in sorted(self.coverage.items())
            if value.status == "official"
        )

    @property
    def pending_years(self) -> tuple[int, ...]:
        return tuple(
            year for year, value in sorted(self.coverage.items())
            if value.status == "pending"
        )

    def coverage_status(self, year: int) -> str:
        value = self.coverage.get(year)
        return value.status if value is not None else "unconfigured"

    def closures_for_year(self, year: int) -> tuple[MarketClosure, ...]:
        value = self.coverage.get(year)
        return value.closures if value is not None else ()

    def is_trading_day(self, value: date) -> bool:
        if value.weekday() >= 5:
            return False
        return all(
            closure.trading_date != value
            for closure in self.closures_for_year(value.year)
        )

    def previous_trading_day(self, value: date, *, inclusive: bool = False) -> date:
        candidate = value if inclusive else value - timedelta(days=1)
        while not self.is_trading_day(candidate):
            candidate -= timedelta(days=1)
        return candidate

    def next_trading_day(self, value: date, *, inclusive: bool = False) -> date:
        candidate = value if inclusive else value + timedelta(days=1)
        while not self.is_trading_day(candidate):
            candidate += timedelta(days=1)
        return candidate

    def nearby_closures(self, value: date, *, days: int = 60) -> tuple[MarketClosure, ...]:
        start = value - timedelta(days=days)
        end = value + timedelta(days=days)
        return tuple(
            closure
            for year in range(start.year, end.year + 1)
            for closure in self.closures_for_year(year)
            if start <= closure.trading_date <= end
        )


def load_market_calendar(path: Path) -> MarketCalendar:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise MarketCalendarConfigurationError(
            f"unable to load market calendar: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise MarketCalendarConfigurationError("market calendar must be an object")

    calendar_version = required_string(payload, "calendar_version")
    exchange = required_string(payload, "exchange")
    timezone_name = required_string(payload, "timezone")
    source = payload.get("source")
    if source is not None and not isinstance(source, dict):
        raise MarketCalendarConfigurationError("source must be an object")
    source_reference = optional_string(source or {}, "reference")
    source_published_date = optional_date(source or {}, "published_date")
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise MarketCalendarConfigurationError(
            f"unknown market calendar timezone: {timezone_name}"
        ) from error

    raw_coverage = payload.get("coverage")
    if not isinstance(raw_coverage, dict) or not raw_coverage:
        raise MarketCalendarConfigurationError("coverage must be a non-empty object")

    coverage: dict[int, CalendarYearCoverage] = {}
    seen_dates: set[date] = set()
    for raw_year, raw_value in raw_coverage.items():
        try:
            year = int(raw_year)
        except (TypeError, ValueError) as error:
            raise MarketCalendarConfigurationError(
                f"invalid coverage year: {raw_year}"
            ) from error
        if str(year) != str(raw_year) or year < 1900 or year > 2200:
            raise MarketCalendarConfigurationError(f"invalid coverage year: {raw_year}")
        if not isinstance(raw_value, dict):
            raise MarketCalendarConfigurationError(f"coverage {year} must be an object")
        status = required_string(raw_value, "status")
        if status not in SUPPORTED_COVERAGE_STATUSES:
            raise MarketCalendarConfigurationError(
                f"coverage {year} has unsupported status: {status}"
            )
        raw_closures = raw_value.get("closures", [])
        if not isinstance(raw_closures, list):
            raise MarketCalendarConfigurationError(
                f"coverage {year} closures must be a list"
            )
        closures = tuple(
            parse_closure(item, year=year, seen_dates=seen_dates)
            for item in raw_closures
        )
        if status == "pending" and closures:
            raise MarketCalendarConfigurationError(
                f"pending coverage {year} must not contain closures"
            )
        coverage[year] = CalendarYearCoverage(
            year=year,
            status=status,
            closures=tuple(sorted(closures, key=lambda item: item.trading_date)),
        )

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return MarketCalendar(
        calendar_version=calendar_version,
        exchange=exchange,
        timezone=timezone,
        source_reference=source_reference,
        source_published_date=source_published_date,
        coverage=coverage,
        checksum=hashlib.sha256(canonical.encode()).hexdigest(),
    )


def parse_closure(
    payload: object, *, year: int, seen_dates: set[date]
) -> MarketClosure:
    if not isinstance(payload, dict):
        raise MarketCalendarConfigurationError(
            f"coverage {year} closure must be an object"
        )
    raw_date = payload.get("date")
    if not isinstance(raw_date, str):
        raise MarketCalendarConfigurationError(
            f"coverage {year} closure date must be an ISO date"
        )
    try:
        trading_date = date.fromisoformat(raw_date)
    except ValueError as error:
        raise MarketCalendarConfigurationError(
            f"invalid closure date: {raw_date}"
        ) from error
    if trading_date.year != year:
        raise MarketCalendarConfigurationError(
            f"closure {trading_date} is outside coverage year {year}"
        )
    if trading_date in seen_dates:
        raise MarketCalendarConfigurationError(
            f"duplicate market closure date: {trading_date}"
        )
    closure_type = required_string(payload, "type")
    if closure_type not in SUPPORTED_CLOSURE_TYPES:
        raise MarketCalendarConfigurationError(
            f"unsupported closure type: {closure_type}"
        )
    seen_dates.add(trading_date)
    return MarketClosure(
        trading_date=trading_date,
        name=required_string(payload, "name"),
        closure_type=closure_type,
    )


def required_string(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MarketCalendarConfigurationError(f"{key} must be a non-empty string")
    return value.strip()


def optional_string(payload: dict, key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise MarketCalendarConfigurationError(f"{key} must be a non-empty string")
    return value.strip()


def optional_date(payload: dict, key: str) -> date | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise MarketCalendarConfigurationError(f"{key} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise MarketCalendarConfigurationError(f"invalid {key}: {value}") from error
