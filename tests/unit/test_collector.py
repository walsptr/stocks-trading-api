from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from stocks_trading.config.settings import Settings
from stocks_trading.domain.models import DailyCandle, SymbolStatus
from stocks_trading.market_data.service import MarketDataCollector


class FakeProvider:
    def __init__(self, failing_symbol: str | None = None) -> None:
        self.failing_symbol = failing_symbol
        self.calls = []

    def download(self, symbols, start_date, end_date):
        self.calls.append((tuple(symbols), start_date, end_date))
        if self.failing_symbol in symbols:
            raise RuntimeError("temporary provider error token=secret")
        return {
            symbol: [
                DailyCandle(
                    symbol=symbol,
                    trading_date=end_date,
                    open=Decimal("1"),
                    high=Decimal("2"),
                    low=Decimal("1"),
                    close=Decimal("2"),
                    adjusted_close=Decimal("2"),
                    volume=10,
                )
            ]
            for symbol in symbols
        }


class FakeMarketRepository:
    def __init__(self, latest=date(2026, 7, 10)) -> None:
        self.candles = []
        self.latest = latest

    def active_symbols(self):
        return ["BBCA.JK", "TLKM.JK"]

    def latest_trading_date(self, symbol):
        return self.latest

    def upsert_candles(self, candles):
        self.candles.extend(candles)
        return len(candles)


class FakeRunRepository:
    def __init__(self) -> None:
        self.run_id = uuid4()
        self.results = []

    def create_run(self, request):
        self.request = request
        return self.run_id

    def record_symbol_result(self, run_id, result):
        self.results.append(result)

    def finish_run(self, run_id):
        self.finished = run_id

    def failed_symbols(self, run_id: UUID):
        return ["TLKM.JK"]

    def abandon_run(self, run_id: UUID):
        self.abandoned = run_id


def settings(**overrides) -> Settings:
    values = {
        "database_url": "postgresql+psycopg://unused",
        "batch_size": 1,
        "max_workers": 2,
        "max_attempts": 2,
        "retry_base_seconds": 0,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_collect_persists_partial_success_and_failure() -> None:
    provider = FakeProvider(failing_symbol="TLKM.JK")
    market_repository = FakeMarketRepository()
    run_repository = FakeRunRepository()
    collector = MarketDataCollector(
        provider=provider,
        market_repository=market_repository,
        run_repository=run_repository,
        settings=settings(),
    )

    result = await collector.bootstrap(
        years=1,
        symbols=["BBCA.JK", "TLKM.JK"],
        as_of=date(2026, 7, 16),
    )

    assert result.failed_count == 1
    assert len(market_repository.candles) == 1
    assert {item.status for item in result.symbols} == {
        SymbolStatus.SUCCESS,
        SymbolStatus.FAILED,
    }
    failed = next(item for item in result.symbols if item.status == SymbolStatus.FAILED)
    assert failed.attempts == 2


@pytest.mark.asyncio
async def test_update_starts_after_local_cache() -> None:
    provider = FakeProvider()
    collector = MarketDataCollector(
        provider=provider,
        market_repository=FakeMarketRepository(),
        run_repository=FakeRunRepository(),
        settings=settings(incremental_overlap_days=7),
    )

    await collector.update(symbols=["BBCA.JK"], as_of=date(2026, 7, 16))

    assert provider.calls[0][1] == date(2026, 7, 11)


@pytest.mark.asyncio
async def test_update_skips_provider_when_local_cache_is_current() -> None:
    provider = FakeProvider()
    repository = FakeMarketRepository(latest=date(2026, 7, 16))
    collector = MarketDataCollector(
        provider=provider, market_repository=repository,
        run_repository=FakeRunRepository(), settings=settings(),
    )

    result = await collector.update(symbols=["BBCA.JK"], as_of=date(2026, 7, 16))

    assert provider.calls == []
    assert result.symbols[0].status == SymbolStatus.NO_NEW_DATA
    assert result.symbols[0].attempts == 0
