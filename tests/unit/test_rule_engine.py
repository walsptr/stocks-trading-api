from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from stocks_trading.domain.models import DailyCandle, DailyIndicators, RuleEvaluationInput
from stocks_trading.rules.config import RuleConfigurationError, load_rule_configuration
from stocks_trading.rules.evaluator import RuleEvaluationError, evaluate_rules


def source(**indicator_overrides) -> RuleEvaluationInput:
    values = {
        "symbol": "BBCA.JK",
        "trading_date": date(2026, 7, 16),
        "sma_5": Decimal("9000"),
        "sma_10": Decimal("8900"),
        "sma_20": Decimal("8800"),
        "sma_50": Decimal("8500"),
        "sma_200": Decimal("8000"),
        "volume_ma_20": Decimal("1000000"),
        "volume_ratio": Decimal("1.5"),
        "daily_change_percent": Decimal("1"),
        "atr_14": Decimal("200"),
        "highest_high_20": Decimal("9100"),
        "lowest_low_20": Decimal("8000"),
        "average_traded_value_20": Decimal("10000000000"),
        "calculation_version": "technical-v2",
    }
    values.update(indicator_overrides)
    return RuleEvaluationInput(
        candle=DailyCandle(
            symbol="BBCA.JK",
            trading_date=date(2026, 7, 16),
            open=Decimal("9000"),
            high=Decimal("9300"),
            low=Decimal("8950"),
            close=Decimal("9200"),
            adjusted_close=Decimal("9200"),
            volume=2_000_000,
        ),
        indicators=DailyIndicators(**values),
    )


def configuration():
    return load_rule_configuration(Path("config/rules-v1.yaml"))


def test_evaluates_all_rules_and_inclusive_thresholds() -> None:
    result = evaluate_rules(source(), configuration())

    assert result.price_above_ma5 is True
    assert result.price_above_ma10 is True
    assert result.price_above_ma20 is True
    assert result.ma5_above_ma10 is True
    assert result.ma10_above_ma20 is True
    assert result.volume_spike is True
    assert result.breakout_20 is True
    assert result.high_liquidity is True
    assert result.positive_momentum is True


def test_propagates_null_inputs() -> None:
    result = evaluate_rules(
        source(sma_5=None, volume_ratio=None, average_traded_value_20=None),
        configuration(),
    )

    assert result.price_above_ma5 is None
    assert result.ma5_above_ma10 is None
    assert result.volume_spike is None
    assert result.high_liquidity is None


def test_rejects_wrong_indicator_version() -> None:
    with pytest.raises(RuleEvaluationError, match="expected technical-v2"):
        evaluate_rules(source(calculation_version="technical-v1"), configuration())


def test_config_checksum_is_stable() -> None:
    first = configuration()
    second = configuration()

    assert first.checksum == second.checksum
    assert len(first.checksum) == 64


def test_invalid_config_rejected(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text("formula_version: rules-v1\n", encoding="utf-8")

    with pytest.raises(RuleConfigurationError, match="thresholds"):
        load_rule_configuration(path)
