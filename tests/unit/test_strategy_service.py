from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

pytestmark = pytest.mark.legacy_bsjp

from stocks_trading.config.settings import Settings
from stocks_trading.domain.models import DailyRules, StrategySymbolStatus
from stocks_trading.strategies.config import load_strategy_configuration
from stocks_trading.strategies.service import StrategyService


class FakeStrategyRepository:
    def __init__(self, *, fail_symbol=None, no_data=False):
        self.fail_symbol = fail_symbol
        self.no_data = no_data
        self.load_calls = []
        self.written = []

    def active_symbols(self):
        return ["BBCA.JK", "TLKM.JK"]

    def latest_strategy_date(self, symbol, name, version, checksum):
        return date(2026, 7, 10)

    def load_rule_results(
        self, symbol, *, formula_version, config_checksum, start_date=None, end_date=None
    ):
        self.load_calls.append((symbol, formula_version, config_checksum, start_date, end_date))
        if symbol == self.fail_symbol:
            raise RuntimeError("broken source")
        if self.no_data:
            return []
        return [(daily_rules(symbol), None)]

    def upsert_strategy_results(self, results):
        self.written.extend(results)
        return len(results)


class FakeRunRepository:
    def __init__(self):
        self.run_id = uuid4()
        self.results = []

    def create_strategy_run(self, request):
        self.request = request
        return self.run_id

    def record_strategy_symbol_result(self, run_id, result):
        self.results.append(result)

    def finish_strategy_run(self, run_id):
        self.finished = run_id

    def abandon_strategy_run(self, run_id):
        self.abandoned = run_id


def daily_rules(symbol):
    return DailyRules(
        symbol=symbol,
        trading_date=date(2026, 7, 16),
        price_above_ma5=True,
        price_above_ma10=True,
        price_above_ma20=True,
        ma5_above_ma10=True,
        ma10_above_ma20=True,
        volume_spike=True,
        breakout_20=True,
        high_liquidity=True,
        positive_momentum=True,
        formula_version="rules-v1",
        config_checksum="f6f6f946ea40fd38a7fd70b1a8e2fb4144e0fa09462f19eb812154c548ee7bae",
        indicator_version="technical-v2",
    )


def service(repository):
    return StrategyService(
        strategy_repository=repository,
        run_repository=FakeRunRepository(),
        settings=Settings(database_url="postgresql+psycopg://unused"),
        configuration=load_strategy_configuration(Path("config/strategies/bsjp-v1.yaml")),
    )


@pytest.mark.asyncio
async def test_update_uses_seven_day_overlap() -> None:
    repository = FakeStrategyRepository()

    result = await service(repository).update(
        symbols=["BBCA.JK"], as_of=date(2026, 7, 16)
    )

    assert result.failed_count == 0
    assert repository.load_calls[0][3] == date(2026, 7, 3)
    assert repository.written[0].passed is None
    assert repository.written[0].evaluation_details["disabled"] == "disabled"


@pytest.mark.asyncio
async def test_failure_isolated() -> None:
    result = await service(FakeStrategyRepository(fail_symbol="TLKM.JK")).rebuild(
        symbols=["BBCA.JK", "TLKM.JK"]
    )

    assert result.failed_count == 1
    assert {item.status for item in result.symbols} == {
        StrategySymbolStatus.SUCCESS,
        StrategySymbolStatus.FAILED,
    }


@pytest.mark.asyncio
async def test_no_rules_records_no_data() -> None:
    result = await service(FakeStrategyRepository(no_data=True)).rebuild(
        symbols=["BBCA.JK"]
    )

    assert result.symbols[0].status == StrategySymbolStatus.NO_DATA
