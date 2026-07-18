from datetime import date
from pathlib import Path

import pytest

from stocks_trading.domain.models import DailyRules
from stocks_trading.strategies.config import (
    StrategyConfigurationError,
    load_strategy_configuration,
)
from stocks_trading.strategies.evaluator import (
    StrategyEvaluationError,
    evaluate_strategy,
)


def configuration():
    return load_strategy_configuration(Path("config/strategies/bsjp-v1.yaml"))


def rules(**overrides) -> DailyRules:
    values = {
        "symbol": "BBCA.JK",
        "trading_date": date(2026, 7, 16),
        "price_above_ma5": True,
        "price_above_ma10": True,
        "price_above_ma20": True,
        "ma5_above_ma10": True,
        "ma10_above_ma20": True,
        "volume_spike": True,
        "breakout_20": True,
        "high_liquidity": True,
        "positive_momentum": True,
        "formula_version": "rules-v1",
        "config_checksum": "f6f6f946ea40fd38a7fd70b1a8e2fb4144e0fa09462f19eb812154c548ee7bae",
        "indicator_version": "technical-v2",
    }
    values.update(overrides)
    return DailyRules(**values)


def test_all_required_rules_pass() -> None:
    result = evaluate_strategy(rules(), configuration())

    assert result.passed is None
    assert result.evaluation_details["disabled"] == "disabled"
    assert {value for key, value in result.evaluation_details.items() if key != "disabled"} == {"passed"}


def test_false_rule_fails_even_with_unavailable_rule() -> None:
    result = evaluate_strategy(
        rules(volume_spike=False, breakout_20=None), configuration()
    )

    assert result.passed is None
    assert result.evaluation_details["volume_spike"] == "failed"
    assert result.evaluation_details["volume_spike"] == "failed"
    assert result.evaluation_details["breakout_20"] == "unavailable"


def test_unavailable_rule_returns_not_evaluable() -> None:
    result = evaluate_strategy(rules(breakout_20=None), configuration())

    assert result.passed is None


def test_rejects_wrong_rule_identity() -> None:
    with pytest.raises(StrategyEvaluationError, match="checksum"):
        evaluate_strategy(rules(config_checksum="wrong"), configuration())


def test_configuration_checksum_is_stable() -> None:
    assert configuration().checksum == configuration().checksum
    assert len(configuration().checksum) == 64


def test_configuration_rejects_unknown_rule(tmp_path: Path) -> None:
    path = tmp_path / "strategy.yaml"
    path.write_text(
        "name: TEST\nversion: v1\ndescription: Test\n"
        "source_rules:\n  formula_version: rules-v1\n  config_checksum: abc\n"
        "required_rules:\n  - missing_rule\n",
        encoding="utf-8",
    )

    with pytest.raises(StrategyConfigurationError, match="unknown required rules"):
        load_strategy_configuration(path)
