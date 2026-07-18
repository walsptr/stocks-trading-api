from stocks_trading.domain.models import DailyRules, TechnicalScore
from stocks_trading.scoring.config import ScoringConfiguration


class ScoringEvaluationError(ValueError):
    pass


def calculate_score(
    rules: DailyRules, configuration: ScoringConfiguration
) -> TechnicalScore:
    if rules.formula_version != configuration.source_rule_formula_version:
        raise ScoringEvaluationError("source rule formula version does not match")
    if rules.config_checksum != configuration.source_rule_config_checksum:
        raise ScoringEvaluationError("source rule configuration checksum does not match")
    unavailable = False
    total = 0
    contributions: dict[str, dict[str, object]] = {}
    for name, weight in configuration.weights.items():
        value = getattr(rules, name)
        awarded = weight if value is True else 0
        unavailable = unavailable or value is None
        total += awarded
        contributions[name] = {"value": value, "weight": weight, "awarded": awarded}
    score = None if unavailable else total
    rating = None if score is None else rating_for(score, configuration)
    return TechnicalScore(
        symbol=rules.symbol,
        trading_date=rules.trading_date,
        scoring_version=configuration.version,
        scoring_config_checksum=configuration.checksum,
        score=score,
        rating=rating,
        contributions=contributions,
        source_rule_formula_version=rules.formula_version,
        source_rule_config_checksum=rules.config_checksum,
        provider=rules.provider,
        interval=rules.interval,
    )


def rating_for(score: int, configuration: ScoringConfiguration) -> str:
    for band in configuration.ratings:
        if band.minimum <= score <= band.maximum:
            return band.name
    raise ScoringEvaluationError(f"score {score} has no rating")
