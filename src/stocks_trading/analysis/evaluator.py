from stocks_trading.analysis.config import AnalysisConfiguration
from stocks_trading.domain.models import AnalysisInput, DailyAnalysis


def generate_analysis(
    source: AnalysisInput, configuration: AnalysisConfiguration
) -> DailyAnalysis:
    ranking = source.ranking
    if ranking.score < configuration.minimum_score:
        raise ValueError("ranking score is below the analysis threshold")

    bullish: list[str] = []
    cautions: list[str] = []
    rules = source.rules
    if rules is None:
        cautions.append("Rule evaluation is unavailable for this trading date.")
    else:
        add_rule_reason(rules.price_above_ma5, "Price is above SMA5.", "Price is not above SMA5.", bullish, cautions)
        add_rule_reason(rules.price_above_ma10, "Price is above SMA10.", "Price is not above SMA10.", bullish, cautions)
        add_rule_reason(rules.ma5_above_ma10, "SMA5 is above SMA10.", "SMA5 is not above SMA10.", bullish, cautions)
        add_rule_reason(rules.ma10_above_ma20, "SMA10 is above SMA20.", "SMA10 is not above SMA20.", bullish, cautions)
        add_rule_reason(rules.positive_momentum, "Daily momentum is positive.", "Daily momentum is not positive.", bullish, cautions)
        add_rule_reason(rules.volume_spike, "A volume spike is present.", "No volume spike is present.", bullish, cautions)
        add_rule_reason(rules.breakout_20, "Price broke above the prior 20-session high.", "No 20-session breakout is present.", bullish, cautions)
        add_rule_reason(rules.high_liquidity, "Liquidity meets the configured threshold.", "Liquidity is below the configured threshold.", bullish, cautions)

    if source.indicators is None:
        cautions.append("Indicator details are unavailable for this trading date.")

    strategy_status = (
        "unavailable" if source.strategy is None or source.strategy.passed is None
        else "passed" if source.strategy.passed else "failed"
    )
    if strategy_status == "passed":
        bullish.append("The Swing Trend Following strategy passed.")
    elif strategy_status == "failed":
        cautions.append("The Swing Trend Following strategy did not pass.")
    else:
        cautions.append("The Swing Trend Following strategy result is unavailable.")

    narrative_parts = []
    if bullish:
        narrative_parts.append(" ".join(bullish))
    if cautions:
        narrative_parts.append("Cautions: " + " ".join(cautions))
    narrative_parts.append(
        f"{ranking.symbol} has a Technical Score of {ranking.score} ({ranking.rating}) "
        f"and is ranked #{ranking.rank} for {ranking.trading_date.isoformat()}."
    )
    return DailyAnalysis(
        symbol=ranking.symbol,
        trading_date=ranking.trading_date,
        analysis_version=configuration.version,
        analysis_config_checksum=configuration.checksum,
        narrative=" ".join(narrative_parts),
        bullish_reasons=tuple(bullish),
        caution_reasons=tuple(cautions),
        source_availability={
            "indicators": source.indicators is not None,
            "rules": rules is not None,
            "strategy": source.strategy is not None,
            "score": True,
            "ranking": True,
        },
        strategy_status=strategy_status,
        score=ranking.score,
        rating=ranking.rating,
        rank=ranking.rank,
        disclaimer=configuration.disclaimer,
        source_versions=configuration.source_versions,
        provider=ranking.provider,
        interval=ranking.interval,
    )


def add_rule_reason(value, positive, negative, bullish, cautions) -> None:
    if value is True:
        bullish.append(positive)
    elif value is False:
        cautions.append(negative)
