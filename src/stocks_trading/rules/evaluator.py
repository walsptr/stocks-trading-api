from decimal import Decimal

from stocks_trading.domain.models import DailyRules, RuleEvaluationInput
from stocks_trading.rules.config import RuleConfiguration


class RuleEvaluationError(ValueError):
    pass


def evaluate_rules(
    source: RuleEvaluationInput, configuration: RuleConfiguration
) -> DailyRules:
    candle = source.candle
    indicators = source.indicators
    if candle.symbol != indicators.symbol or candle.trading_date != indicators.trading_date:
        raise RuleEvaluationError("candle and indicators must share symbol and date")
    if candle.provider != indicators.provider or candle.interval != indicators.interval:
        raise RuleEvaluationError("candle and indicators must share provider and interval")
    if indicators.calculation_version != configuration.indicator_version:
        raise RuleEvaluationError(
            f"expected {configuration.indicator_version}, got {indicators.calculation_version}"
        )
    return DailyRules(
        symbol=candle.symbol,
        trading_date=candle.trading_date,
        price_above_ma5=compare(candle.close, indicators.sma_5, lambda a, b: a > b),
        price_above_ma10=compare(candle.close, indicators.sma_10, lambda a, b: a > b),
        price_above_ma20=compare(candle.close, indicators.sma_20, lambda a, b: a > b),
        ma5_above_ma10=compare(
            indicators.sma_5, indicators.sma_10, lambda a, b: a > b
        ),
        ma10_above_ma20=compare(
            indicators.sma_10, indicators.sma_20, lambda a, b: a > b
        ),
        volume_spike=compare(
            indicators.volume_ratio,
            configuration.volume_spike_ratio,
            lambda a, b: a >= b,
        ),
        breakout_20=compare(
            candle.close, indicators.highest_high_20, lambda a, b: a > b
        ),
        high_liquidity=compare(
            indicators.average_traded_value_20,
            configuration.high_liquidity_average_traded_value,
            lambda a, b: a >= b,
        ),
        positive_momentum=compare(
            indicators.daily_change_percent, Decimal(0), lambda a, b: a > b
        ),
        price_above_ma50=compare(candle.close, indicators.sma_50, lambda a, b: a > b),
        ma20_above_ma50=compare(indicators.sma_20, indicators.sma_50, lambda a, b: a > b),
        ma50_above_ma200=compare(indicators.sma_50, indicators.sma_200, lambda a, b: a > b),
        pullback_to_ma20=compare(
            candle.close, indicators.sma_20,
            lambda a, b: abs(a - b) / b <= configuration.pullback_tolerance if b else False,
        ),
        rsi_not_overbought=compare(indicators.rsi_14, Decimal(70), lambda a, b: a < b),
        rsi_not_oversold=compare(indicators.rsi_14, Decimal(30), lambda a, b: a > b),
        macd_bullish_crossover=indicators.macd_bullish_crossover,
        higher_low_formed=indicators.higher_low_formed,
        volume_confirmation=(
            None if indicators.volume_ratio is None or indicators.daily_change_percent is None
            else indicators.volume_ratio >= configuration.volume_confirmation_ratio
            and indicators.daily_change_percent > 0
        ),
        ma20_below_ma50=compare(indicators.sma_20, indicators.sma_50, lambda a, b: a < b),
        rsi_extreme_overbought=compare(indicators.rsi_14, Decimal(80), lambda a, b: a > b),
        formula_version=configuration.formula_version,
        config_checksum=configuration.checksum,
        indicator_version=configuration.indicator_version,
        candle_updated_at=source.candle_updated_at,
        indicator_calculated_at=source.indicator_calculated_at,
        provider=candle.provider,
        interval=candle.interval,
    )


def compare(left, right, operation):
    if left is None or right is None:
        return None
    return operation(left, right)
