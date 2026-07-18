from datetime import date
from pathlib import Path

from stocks_trading.domain.models import DailyRules
from stocks_trading.scoring.config import load_scoring_configuration
from stocks_trading.scoring.evaluator import calculate_score
from stocks_trading.strategies.config import load_strategy_configuration
from stocks_trading.strategies.evaluator import evaluate_strategy


def swing_rules(**overrides):
    configuration = load_strategy_configuration(Path("config/strategies/swing-trend-following-v1.yaml"))
    values = dict(
        symbol="BBCA.JK", trading_date=date(2026, 7, 18),
        price_above_ma5=True, price_above_ma10=True, price_above_ma20=True,
        ma5_above_ma10=True, ma10_above_ma20=True, volume_spike=False,
        breakout_20=False, high_liquidity=True, positive_momentum=True,
        formula_version=configuration.source_rule_formula_version,
        config_checksum=configuration.source_rule_config_checksum,
        indicator_version="technical-v3", price_above_ma50=True,
        ma20_above_ma50=True, ma50_above_ma200=True, pullback_to_ma20=True,
        rsi_not_overbought=True, rsi_not_oversold=True,
        macd_bullish_crossover=True, higher_low_formed=True,
        volume_confirmation=True, ma20_below_ma50=False,
        rsi_extreme_overbought=False,
    )
    values.update(overrides)
    return DailyRules(**values)


def test_swing_entry_conditions_match():
    configuration = load_strategy_configuration(Path("config/strategies/swing-trend-following-v1.yaml"))
    result = evaluate_strategy(swing_rules(), configuration)
    assert result.passed is True
    assert all(result.evaluation_details[name] == "passed" for name in configuration.required_rules)


def test_swing_entry_fails_when_trend_filter_fails():
    configuration = load_strategy_configuration(Path("config/strategies/swing-trend-following-v1.yaml"))
    result = evaluate_strategy(swing_rules(ma50_above_ma200=False), configuration)
    assert result.passed is False


def test_swing_exit_rules_are_exposed_by_configuration():
    configuration = load_strategy_configuration(Path("config/strategies/swing-trend-following-v1.yaml"))
    assert configuration.exit_rules == ("ma20_below_ma50", "rsi_extreme_overbought")
    assert configuration.holding_period == "3-20 trading days"


def test_swing_score_weights_total_one_hundred():
    configuration = load_scoring_configuration(Path("config/scoring/swing-trend-following-v1.yaml"))
    result = calculate_score(swing_rules(), configuration)
    assert result.score == 100
    assert result.rating == "Strong Buy"
    assert result.contributions["volume_confirmation"]["awarded"] == 5
