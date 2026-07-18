from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

from stocks_trading.backtesting.config import load_backtest_configuration
from stocks_trading.backtesting.service import BacktestService


class FakeRepository:
    def load_sources(self, *args):
        return [], {}
    def save_run(self, configuration, start_date, end_date, result):
        self.result = result
        return uuid4()


def test_service_persists_empty_result() -> None:
    repository = FakeRepository()
    result = BacktestService(repository, load_backtest_configuration(Path("config/backtesting/swing-trend-following-v1.yaml"))).run(
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 16)
    )
    assert result.metrics.completed_trades == 0


def test_invalid_range_rejected() -> None:
    with pytest.raises(ValueError, match="start_date"):
        BacktestService(FakeRepository(), load_backtest_configuration(Path("config/backtesting/swing-trend-following-v1.yaml"))).run(
            start_date=date(2026, 7, 16), end_date=date(2026, 7, 1)
        )


def test_legacy_bsjp_backtest_is_disabled() -> None:
    configuration = load_backtest_configuration(Path("config/backtesting/bsjp-v1.yaml"))
    assert configuration.enabled is False
    assert configuration.default is False
    with pytest.raises(ValueError, match="disabled"):
        BacktestService(FakeRepository(), configuration).run(
            start_date=date(2026, 7, 1), end_date=date(2026, 7, 16)
        )
