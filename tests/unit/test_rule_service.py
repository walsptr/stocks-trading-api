from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from stocks_trading.config.settings import Settings
from stocks_trading.domain.models import (
    DailyCandle,
    DailyIndicators,
    RuleEvaluationInput,
    RuleSymbolStatus,
)
from stocks_trading.rules.config import load_rule_configuration
from stocks_trading.rules.service import RuleService


class FakeRuleRepository:
    def __init__(self, *, fail_symbol=None, no_data=False):
        self.fail_symbol = fail_symbol
        self.no_data = no_data
        self.load_calls = []
        self.written = []

    def active_symbols(self):
        return ["BBCA.JK", "TLKM.JK"]

    def latest_rule_date(self, symbol, formula_version, config_checksum):
        return date(2026, 7, 10)

    def load_rule_inputs(
        self, symbol, *, indicator_version, start_date=None, end_date=None
    ):
        self.load_calls.append((symbol, indicator_version, start_date, end_date))
        if symbol == self.fail_symbol:
            raise RuntimeError("broken join")
        if self.no_data:
            return []
        trading_date = date(2026, 7, 16)
        return [
            RuleEvaluationInput(
                candle=DailyCandle(
                    symbol=symbol,
                    trading_date=trading_date,
                    open=Decimal("90"),
                    high=Decimal("100"),
                    low=Decimal("80"),
                    close=Decimal("95"),
                    adjusted_close=Decimal("95"),
                    volume=1000,
                ),
                indicators=DailyIndicators(
                    symbol=symbol,
                    trading_date=trading_date,
                    sma_5=Decimal("90"),
                    sma_10=Decimal("89"),
                    sma_20=Decimal("88"),
                    sma_50=None,
                    sma_200=None,
                    volume_ma_20=Decimal("500"),
                    volume_ratio=Decimal("2"),
                    daily_change_percent=Decimal("1"),
                    atr_14=Decimal("4"),
                    highest_high_20=Decimal("94"),
                    lowest_low_20=Decimal("70"),
                    average_traded_value_20=Decimal("11000000000"),
                ),
            )
        ]

    def upsert_rules(self, rules):
        self.written.extend(rules)
        return len(rules)


class FakeRuleRunRepository:
    def __init__(self):
        self.run_id = uuid4()
        self.results = []

    def create_rule_run(self, request):
        self.request = request
        return self.run_id

    def record_rule_symbol_result(self, run_id, result):
        self.results.append(result)

    def finish_rule_run(self, run_id):
        self.finished = run_id

    def abandon_rule_run(self, run_id):
        self.abandoned = run_id


def service(repository):
    return RuleService(
        rule_repository=repository,
        run_repository=FakeRuleRunRepository(),
        settings=Settings(database_url="postgresql+psycopg://unused"),
        configuration=load_rule_configuration(Path("config/rules-v1.yaml")),
    )


@pytest.mark.asyncio
async def test_update_uses_seven_day_overlap() -> None:
    repository = FakeRuleRepository()

    result = await service(repository).update(
        symbols=["BBCA.JK"], as_of=date(2026, 7, 16)
    )

    assert result.failed_count == 0
    assert repository.load_calls[0][2] == date(2026, 7, 3)
    assert repository.written[0].breakout_20 is True


@pytest.mark.asyncio
async def test_failure_isolated() -> None:
    result = await service(FakeRuleRepository(fail_symbol="TLKM.JK")).rebuild(
        symbols=["BBCA.JK", "TLKM.JK"]
    )

    assert result.failed_count == 1
    assert {item.status for item in result.symbols} == {
        RuleSymbolStatus.SUCCESS,
        RuleSymbolStatus.FAILED,
    }


@pytest.mark.asyncio
async def test_no_inputs_records_no_data() -> None:
    result = await service(FakeRuleRepository(no_data=True)).rebuild(
        symbols=["BBCA.JK"]
    )

    assert result.symbols[0].status == RuleSymbolStatus.NO_DATA
