import hashlib
import json
from dataclasses import replace
from datetime import date
from decimal import Decimal

from stocks_trading.backtesting.config import BacktestConfiguration
from stocks_trading.backtesting.evaluator import run_backtest
from stocks_trading.domain.models import (
    DailyCandle, DailyIndicators, DailyRules, OptimizationCandidate,
    OptimizationResult, StrategyResult,
)
from stocks_trading.optimization.config import OptimizationConfiguration


def optimize(
    sources: list[tuple[DailyCandle, DailyIndicators]],
    candles: dict[str, list[DailyCandle]],
    configuration: OptimizationConfiguration,
    backtest_configuration: BacktestConfiguration,
) -> OptimizationResult:
    dates = sorted({item[0].trading_date for item in sources})
    if len(dates) < 2:
        raise ValueError("optimization requires at least two trading dates")
    split_index = max(
        1,
        min(len(dates) - 1, int(len(dates) * float(configuration.training_fraction))),
    )
    training_dates = set(dates[:split_index])
    validation_dates = set(dates[split_index:])
    candidates = []
    validation_results = {}
    for parameters in configuration.candidates():
        candidate_id = candidate_identity(parameters)
        signals = candidate_signals(sources, parameters, candidate_id, backtest_configuration)
        train_result = run_backtest(
            [item for item in signals if item.trading_date in training_dates], candles,
            replace(backtest_configuration, strategy_config_checksum=candidate_id),
        )
        validation_result = run_backtest(
            [item for item in signals if item.trading_date in validation_dates], candles,
            replace(backtest_configuration, strategy_config_checksum=candidate_id),
        )
        metrics = validation_result.aggregate
        eligible = metrics.completed_trades >= configuration.minimum_validation_trades and metrics.sharpe_ratio is not None
        reason = None if eligible else (
            "insufficient_validation_trades" if metrics.completed_trades < configuration.minimum_validation_trades
            else "null_validation_sharpe"
        )
        candidates.append(OptimizationCandidate(
            candidate_id, parameters, eligible, reason,
            train_result.aggregate, validation_result.aggregate,
        ))
        validation_results[candidate_id] = validation_result
    ordered = sorted(candidates, key=candidate_sort_key)
    ranked = []
    eligible_rank = 0
    for item in ordered:
        rank = None
        if item.eligible:
            eligible_rank += 1
            rank = eligible_rank
        ranked.append(replace(item, rank=rank))
    winner_id = next((item.candidate_id for item in ranked if item.eligible), None)
    return OptimizationResult(
        candidates=tuple(ranked), winner_id=winner_id,
        training_start=min(training_dates), training_end=max(training_dates),
        validation_start=min(validation_dates), validation_end=max(validation_dates),
        winner_backtest=validation_results.get(winner_id),
    )


def candidate_identity(parameters: dict[str, object]) -> str:
    canonical = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def candidate_signals(sources, parameters, candidate_id, backtest_configuration):
    signals = []
    for candle, indicator in sources:
        rules = candidate_rules(candle, indicator, parameters, candidate_id)
        if "pullback_tolerance" in parameters:
            required_rules = [
                "ma20_above_ma50", "pullback_to_ma20", "rsi_not_overbought",
                "macd_bullish_crossover", "positive_momentum", "high_liquidity",
            ]
            if parameters["require_ma50_above_ma200"]:
                required_rules.append("ma50_above_ma200")
        else:
            required_rules = ["price_above_ma5", "price_above_ma10", "ma5_above_ma10",
                              "ma10_above_ma20", "positive_momentum", "high_liquidity"]
            if parameters["require_breakout"]:
                required_rules.append("breakout_20")
            if parameters["require_volume_spike"]:
                required_rules.append("volume_spike")
        values = [getattr(rules, name) for name in required_rules]
        passed = False if False in values else None if None in values else True
        details = {name: "passed" if getattr(rules, name) is True else "failed" if getattr(rules, name) is False else "unavailable" for name in required_rules}
        if indicator.atr_14 is not None:
            details["atr_14"] = str(indicator.atr_14)
        signals.append(StrategyResult(candle.symbol, candle.trading_date,
            backtest_configuration.strategy_name, backtest_configuration.strategy_version,
            candidate_id, passed, details,
            "optimizer-rules-v1", candidate_id))
    return signals


def candidate_rules(candle, indicator, parameters, candidate_id):
    compare = lambda left, right, operation: None if left is None or right is None else operation(left, right)
    swing = "pullback_tolerance" in parameters
    return DailyRules(
        symbol=candle.symbol, trading_date=candle.trading_date,
        price_above_ma5=compare(candle.close, indicator.sma_5, lambda a,b:a>b),
        price_above_ma10=compare(candle.close, indicator.sma_10, lambda a,b:a>b),
        price_above_ma20=compare(candle.close, indicator.sma_20, lambda a,b:a>b),
        ma5_above_ma10=compare(indicator.sma_5, indicator.sma_10, lambda a,b:a>b),
        ma10_above_ma20=compare(indicator.sma_10, indicator.sma_20, lambda a,b:a>b),
        volume_spike=compare(indicator.volume_ratio, Decimal(parameters.get("volume_spike_ratio", "1.5")), lambda a,b:a>=b),
        breakout_20=compare(candle.close, indicator.highest_high_20, lambda a,b:a>b),
        high_liquidity=compare(indicator.average_traded_value_20, Decimal(parameters.get("liquidity_threshold", "10000000000")), lambda a,b:a>=b),
        positive_momentum=compare(indicator.daily_change_percent, Decimal(0), lambda a,b:a>b),
        price_above_ma50=compare(candle.close, indicator.sma_50, lambda a,b:a>b),
        ma20_above_ma50=compare(indicator.sma_20, indicator.sma_50, lambda a,b:a>b),
        ma50_above_ma200=compare(indicator.sma_50, indicator.sma_200, lambda a,b:a>b),
        pullback_to_ma20=compare(candle.close, indicator.sma_20, lambda a,b: abs(a-b)/b <= Decimal(parameters.get("pullback_tolerance", "0.03")) if b else False),
        rsi_not_overbought=compare(indicator.rsi_14, Decimal(parameters.get("rsi_overbought_threshold", "70")), lambda a,b:a<b),
        rsi_not_oversold=compare(indicator.rsi_14, Decimal("30"), lambda a,b:a>b),
        macd_bullish_crossover=indicator.macd_bullish_crossover,
        higher_low_formed=indicator.higher_low_formed,
        volume_confirmation=None if indicator.volume_ratio is None or indicator.daily_change_percent is None else indicator.volume_ratio >= Decimal(parameters.get("volume_confirmation_ratio", "1.0")) and indicator.daily_change_percent > 0,
        ma20_below_ma50=compare(indicator.sma_20, indicator.sma_50, lambda a,b:a<b),
        rsi_extreme_overbought=compare(indicator.rsi_14, Decimal("80"), lambda a,b:a>b),
        formula_version="optimizer-rules-v1", config_checksum=candidate_id,
        indicator_version=indicator.calculation_version,
    )


def candidate_sort_key(item):
    if not item.eligible:
        return (1, item.candidate_id)
    metrics = item.validation_metrics
    drawdown = abs(metrics.maximum_drawdown or Decimal(0))
    return (0, -metrics.sharpe_ratio, -(metrics.total_compounded_return or Decimal(0)), drawdown,
            -metrics.completed_trades, item.candidate_id)
