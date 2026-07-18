from datetime import date, datetime, timedelta, UTC
from decimal import Decimal
from uuid import uuid4

import pytest

from stocks_trading.config.settings import Settings
from stocks_trading.domain.models import (
    DailyCandle,
    IndicatorSymbolStatus,
)
from stocks_trading.indicators.service import IndicatorService


class FakeIndicatorRepository:
    def __init__(self, *, no_data: bool = False, fail: bool = False) -> None:
        self.no_data = no_data
        self.fail = fail
        self.written = []
        self.load_calls = []

    def active_symbols(self):
        return ["BBCA.JK", "TLKM.JK"]

    def latest_indicator_date(self, symbol, calculation_version):
        return date(2026, 7, 10)

    def load_candles(
        self, symbol, *, start_date=None, end_date=None, warmup_sessions=0
    ):
        self.load_calls.append((symbol, start_date, end_date, warmup_sessions))
        if self.fail and symbol == "TLKM.JK":
            raise RuntimeError("broken source")
        if self.no_data:
            return []
        start = date(2025, 10, 1)
        return [
            DailyCandle(
                symbol=symbol,
                trading_date=start + timedelta(days=index),
                open=Decimal(index + 1),
                high=Decimal(index + 3),
                low=Decimal(index),
                close=Decimal(index + 2),
                adjusted_close=Decimal(index + 2),
                volume=100,
            )
            for index in range(290)
            if end_date is None or start + timedelta(days=index) <= end_date
        ]

    def source_update_times(self, symbol, trading_dates):
        return {item: datetime(2026, 7, 16, tzinfo=UTC) for item in trading_dates}

    def upsert_indicators(self, indicators):
        self.written.extend(indicators)
        return len(indicators)


class FakeIndicatorRunRepository:
    def __init__(self) -> None:
        self.run_id = uuid4()
        self.results = []

    def create_indicator_run(self, request):
        self.request = request
        return self.run_id

    def record_indicator_symbol_result(self, run_id, result):
        self.results.append(result)

    def finish_indicator_run(self, run_id):
        self.finished = run_id

    def abandon_indicator_run(self, run_id):
        self.abandoned = run_id


def settings() -> Settings:
    return Settings(database_url="postgresql+psycopg://unused", max_workers=2)


@pytest.mark.asyncio
async def test_update_loads_warmup_and_writes_overlap_forward() -> None:
    repository = FakeIndicatorRepository()
    service = IndicatorService(
        indicator_repository=repository,
        run_repository=FakeIndicatorRunRepository(),
        settings=settings(),
    )

    result = await service.update(
        symbols=["BBCA.JK"], as_of=date(2026, 7, 16)
    )

    assert result.failed_count == 0
    assert repository.load_calls[0][1:] == (
        date(2026, 7, 3),
        date(2026, 7, 16),
        260,
    )
    assert all(item.trading_date >= date(2026, 7, 3) for item in repository.written)


@pytest.mark.asyncio
async def test_symbol_failure_isolated_from_success() -> None:
    repository = FakeIndicatorRepository(fail=True)
    service = IndicatorService(
        indicator_repository=repository,
        run_repository=FakeIndicatorRunRepository(),
        settings=settings(),
    )

    result = await service.rebuild(symbols=["BBCA.JK", "TLKM.JK"])

    assert result.failed_count == 1
    assert {item.status for item in result.symbols} == {
        IndicatorSymbolStatus.SUCCESS,
        IndicatorSymbolStatus.FAILED,
    }


@pytest.mark.asyncio
async def test_date_filtered_rebuild_keeps_full_history_for_warmup() -> None:
    repository = FakeIndicatorRepository()
    service = IndicatorService(
        indicator_repository=repository,
        run_repository=FakeIndicatorRunRepository(),
        settings=settings(),
    )

    await service.rebuild(
        symbols=["BBCA.JK"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 16),
    )

    assert repository.load_calls[0][1:] == (
        date(2026, 7, 1),
        date(2026, 7, 16),
        260,
    )
    assert all(item.trading_date >= date(2026, 7, 1) for item in repository.written)


@pytest.mark.asyncio
async def test_no_candles_records_no_data() -> None:
    repository = FakeIndicatorRepository(no_data=True)
    service = IndicatorService(
        indicator_repository=repository,
        run_repository=FakeIndicatorRunRepository(),
        settings=settings(),
    )

    result = await service.rebuild(symbols=["BBCA.JK"])

    assert result.symbols[0].status == IndicatorSymbolStatus.NO_DATA
