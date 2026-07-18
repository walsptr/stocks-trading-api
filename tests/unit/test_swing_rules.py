from datetime import date
from decimal import Decimal
from pathlib import Path

from stocks_trading.domain.models import DailyCandle, DailyIndicators, RuleEvaluationInput
from stocks_trading.rules.config import load_rule_configuration
from stocks_trading.rules.evaluator import evaluate_rules


def test_swing_rules_evaluate_required_signals():
    configuration = load_rule_configuration(Path("config/rules-swing-v1.yaml"))
    candle = DailyCandle("BBCA.JK", date(2026, 7, 18), Decimal("100"), Decimal("106"), Decimal("99"), Decimal("103"), Decimal("103"), 2_000_000)
    indicators = DailyIndicators(
        "BBCA.JK", date(2026, 7, 18), Decimal("102"), Decimal("101"), Decimal("100"), Decimal("90"), Decimal("80"),
        Decimal("1000000"), Decimal("2"), Decimal("1"), Decimal("3"), Decimal("104"), Decimal("85"),
        average_traded_value_20=Decimal("12000000000"), rsi_14=Decimal("55"), macd=Decimal("2"),
        macd_signal=Decimal("1"), macd_histogram=Decimal("1"), macd_bullish_crossover=True,
        higher_low_formed=True, calculation_version="technical-v3",
    )
    result = evaluate_rules(RuleEvaluationInput(candle, indicators), configuration)
    assert result.ma20_above_ma50 is True
    assert result.ma50_above_ma200 is True
    assert result.pullback_to_ma20 is True
    assert result.rsi_not_overbought is True
    assert result.rsi_not_oversold is True
    assert result.macd_bullish_crossover is True
    assert result.higher_low_formed is True
    assert result.volume_confirmation is True
