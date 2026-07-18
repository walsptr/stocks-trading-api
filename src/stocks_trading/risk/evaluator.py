from decimal import Decimal, ROUND_CEILING

from stocks_trading.domain.models import DailyRiskRecommendation, RiskInput
from stocks_trading.risk.config import RiskConfiguration


def idx_tick_size(price: Decimal) -> Decimal:
    if price < 200:
        return Decimal("1")
    if price < 500:
        return Decimal("2")
    if price < 2000:
        return Decimal("5")
    if price < 5000:
        return Decimal("10")
    return Decimal("25")


def round_up_to_tick(price: Decimal) -> Decimal:
    tick = idx_tick_size(price)
    rounded = (price / tick).to_integral_value(rounding=ROUND_CEILING) * tick
    next_tick = idx_tick_size(rounded)
    if next_tick != tick:
        rounded = (price / next_tick).to_integral_value(rounding=ROUND_CEILING) * next_tick
    return rounded


def generate_recommendation(source: RiskInput, configuration: RiskConfiguration) -> DailyRiskRecommendation:
    if source.ranking.score < configuration.minimum_score:
        raise ValueError("ranking score is below the risk threshold")
    if source.atr_14 is None or source.atr_14 <= 0:
        raise ValueError("ATR is unavailable or non-positive")
    entry = source.close
    stop = round_up_to_tick(entry - source.atr_14 * configuration.stop_atr_multiple)
    target = round_up_to_tick(entry + source.atr_14 * configuration.target_atr_multiple)
    if stop >= entry or target <= entry:
        raise ValueError("rounded risk levels are invalid")
    risk = entry - stop
    take_profit_1 = round_up_to_tick(entry + risk * configuration.take_profit_1_r_multiple)
    take_profit_2 = round_up_to_tick(entry + risk * configuration.take_profit_2_r_multiple)
    reward = take_profit_2 - entry
    position_size = min(
        configuration.position_cap_pct,
        configuration.account_risk_pct * entry / risk,
    )
    return DailyRiskRecommendation(
        symbol=source.ranking.symbol,
        trading_date=source.ranking.trading_date,
        risk_version=configuration.version,
        risk_config_checksum=configuration.checksum,
        entry_price=entry,
        atr_14=source.atr_14,
        stop_loss=stop,
        take_profit=target,
        take_profit_1=take_profit_1,
        take_profit_2=take_profit_2,
        risk_amount=risk,
        reward_amount=reward,
        reward_risk_ratio=reward / risk,
        suggested_position_size_pct=position_size,
        score=source.ranking.score,
        rating=source.ranking.rating,
        rank=source.ranking.rank,
        source_indicator_version=configuration.indicator_version,
        source_ranking_version=configuration.ranking_version,
        source_ranking_config_checksum=configuration.ranking_config_checksum,
        disclaimer=configuration.disclaimer,
    )
