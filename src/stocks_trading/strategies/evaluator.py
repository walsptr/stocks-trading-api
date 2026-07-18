from stocks_trading.domain.models import DailyRules, StrategyResult
from stocks_trading.strategies.config import StrategyConfiguration


class StrategyEvaluationError(ValueError):
    pass


def evaluate_strategy(
    rules: DailyRules, configuration: StrategyConfiguration
) -> StrategyResult:
    if rules.formula_version != configuration.source_rule_formula_version:
        raise StrategyEvaluationError("source rule formula version does not match")
    if rules.config_checksum != configuration.source_rule_config_checksum:
        raise StrategyEvaluationError("source rule configuration checksum does not match")
    details: dict[str, str] = {}
    values: list[bool | None] = []
    for name in configuration.required_rules:
        value = getattr(rules, name)
        values.append(value)
        details[name] = "passed" if value is True else "failed" if value is False else "unavailable"
    passed = False if False in values else None if None in values else True
    if not configuration.enabled:
        passed = None
        details["disabled"] = "disabled"
    return StrategyResult(
        symbol=rules.symbol,
        trading_date=rules.trading_date,
        strategy_name=configuration.name,
        strategy_version=configuration.version,
        strategy_config_checksum=configuration.checksum,
        passed=passed,
        evaluation_details=details,
        source_rule_formula_version=rules.formula_version,
        source_rule_config_checksum=rules.config_checksum,
        provider=rules.provider,
        interval=rules.interval,
    )
