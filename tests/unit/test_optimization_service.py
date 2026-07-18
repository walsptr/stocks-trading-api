from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from stocks_trading.domain.models import BacktestTrade, OptimizationResult
from stocks_trading.optimization.config import load_optimization_configuration
from stocks_trading.optimization.service import OptimizationService
from stocks_trading.persistence.repositories import trade_to_json


class FakeRepository:
    def __init__(self):
        self.run_id = uuid4()

    def load_sources(self, indicator_version, start_date, end_date):
        self.loaded = (indicator_version, start_date, end_date)
        return [], {}

    def save_result(self, *args):
        self.saved = args
        return self.run_id


def test_service_loads_sources_once_and_persists_result(monkeypatch) -> None:
    repository = FakeRepository()
    configuration = load_optimization_configuration(Path("config/optimization/bsjp-v1.yaml"))
    expected = OptimizationResult((), None, date(2026, 1, 1), date(2026, 1, 7), date(2026, 1, 8), date(2026, 1, 10), None)
    monkeypatch.setattr("stocks_trading.optimization.service.optimize", lambda *args: expected)

    result = OptimizationService(repository, configuration).run(
        start_date=date(2026, 1, 1), end_date=date(2026, 1, 10)
    )

    assert repository.loaded == ("technical-v2", date(2026, 1, 1), date(2026, 1, 10))
    assert repository.saved[-1] is expected
    assert result.run_id == repository.run_id
    assert result.candidate_count == 0


def test_service_rejects_invalid_range() -> None:
    configuration = load_optimization_configuration(Path("config/optimization/bsjp-v1.yaml"))
    with pytest.raises(ValueError, match="start_date"):
        OptimizationService(FakeRepository(), configuration).run(
            start_date=date(2026, 1, 2), end_date=date(2026, 1, 1)
        )


def test_trade_to_json_serializes_decimal_values() -> None:
    trade = BacktestTrade(
        symbol="BBCA.JK",
        signal_date=date(2026, 7, 16),
        exit_date=date(2026, 7, 17),
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        gross_return=Decimal("0.01"),
        net_return=Decimal("0.009"),
        buy_fee=Decimal("1500"),
        sell_fee=Decimal("2752.5"),
        gross_profit=Decimal("100000"),
        net_profit=Decimal("95747.5"),
    )

    payload = trade_to_json(trade)

    assert payload["entry_price"] == "100"
    assert payload["net_profit"] == "95747.5"
    assert payload["signal_date"] == "2026-07-16"
    assert payload["symbol"] == "BBCA.JK"
