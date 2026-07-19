from datetime import date
from decimal import Decimal
from pathlib import Path

from stocks_trading.fundamentals.config import load_fundamental_configuration
from stocks_trading.fundamentals.evaluator import evaluate, valuation_thresholds


CONFIG = load_fundamental_configuration(Path("config/fundamentals/fundamental-v1.yaml"))


def record(**overrides):
    value = {
        "sector": "Industrials", "is_bank": False,
        "net_income": {date(2026, 3, 31): Decimal("120"), date(2025, 12, 31): Decimal("100"), date(2025, 3, 31): Decimal("90")},
        "roe_percent": Decimal("15"), "der_percent": Decimal("44.115"),
        "per": Decimal("10"), "pbv": Decimal("2"),
    }
    value.update(overrides)
    return value


def test_der_uses_yahoo_percent_units_and_score_is_complete() -> None:
    result = evaluate(record(), {"per": Decimal("20"), "pbv": Decimal("4")}, CONFIG)
    assert result["rule_values"]["manageable_der"] is True
    assert result["data_status"] == "complete"
    assert result["fundamental_score"] == Decimal("100")


def test_bank_der_is_not_applicable_and_excluded_from_denominator() -> None:
    result = evaluate(record(is_bank=True, der_percent=None), {"per": Decimal("20"), "pbv": Decimal("4")}, CONFIG)
    assert result["rule_values"]["manageable_der"] is None
    assert result["rule_metadata"]["manageable_der"]["status"] == "not_applicable"
    assert result["applicable_core_rules"] == 4
    assert result["data_status"] == "complete"


def test_insufficient_data_requires_three_available_core_rules() -> None:
    result = evaluate(record(net_income={}, roe_percent=Decimal("15"), der_percent=Decimal("50")), {"per": None, "pbv": None}, CONFIG)
    assert result["available_core_rules"] == 2
    assert result["data_status"] == "insufficient_data"
    assert result["fundamental_score"] is None


def test_two_consecutive_losses_create_red_flag() -> None:
    losses = {date(2026, 3, 31): Decimal("-10"), date(2025, 12, 31): Decimal("-5"), date(2025, 3, 31): Decimal("10")}
    result = evaluate(record(net_income=losses), {"per": Decimal("20"), "pbv": Decimal("4")}, CONFIG)
    assert result["rule_values"]["no_consecutive_losses"] is False
    assert result["is_red_flagged"] is True


def test_gap_does_not_count_as_consecutive_quarter_loss() -> None:
    losses = {date(2026, 3, 31): Decimal("-10"), date(2025, 9, 30): Decimal("-5"), date(2025, 3, 31): Decimal("10")}
    result = evaluate(record(net_income=losses), {"per": Decimal("20"), "pbv": Decimal("4")}, CONFIG)
    assert result["rule_values"]["no_consecutive_losses"] is None
    assert result["is_red_flagged"] is False


def test_outliers_are_excluded_before_valuation_thresholds() -> None:
    records = [{"sector": "Utilities", "per": Decimal(str(index)), "pbv": Decimal(str(index / 10))} for index in range(1, 11)]
    records.append({"sector": "Utilities", "per": None, "pbv": None})
    thresholds = valuation_thresholds(records, CONFIG)
    assert thresholds["Utilities"]["per"] < Decimal("10")
    assert thresholds["Utilities"]["pbv"] < Decimal("1")
