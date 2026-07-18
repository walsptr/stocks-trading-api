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
        required = [rules.price_above_ma5, rules.price_above_ma10, rules.ma5_above_ma10,
                    rules.ma10_above_ma20, rules.positive_momentum, rules.high_liquidity]
        if parameters["require_breakout"]:
            required.append(rules.breakout_20)
        if parameters["require_volume_spike"]:
            required.append(rules.volume_spike)
        passed = False if False in required else None if None in required else True
        signals.append(StrategyResult(
            candle.symbol, candle.trading_date, backtest_configuration.strategy_name,
            backtest_configuration.strategy_version, candidate_id, passed, {},
            "optimizer-rules-v1", candidate_id,
        ))
    return signals


def candidate_rules(candle, indicator, parameters, candidate_id):
    compare = lambda left, right, operation: None if left is None or right is None else operation(left, right)
    return DailyRules(
        symbol=candle.symbol, trading_date=candle.trading_date,
        price_above_ma5=compare(candle.close, indicator.sma_5, lambda a,b:a>b),
        price_above_ma10=compare(candle.close, indicator.sma_10, lambda a,b:a>b),
        price_above_ma20=compare(candle.close, indicator.sma_20, lambda a,b:a>b),
        ma5_above_ma10=compare(indicator.sma_5, indicator.sma_10, lambda a,b:a>b),
        ma10_above_ma20=compare(indicator.sma_10, indicator.sma_20, lambda a,b:a>b),
        volume_spike=compare(indicator.volume_ratio, Decimal(parameters["volume_spike_ratio"]), lambda a,b:a>=b),
        breakout_20=compare(candle.close, indicator.highest_high_20, lambda a,b:a>b),
        high_liquidity=compare(indicator.average_traded_value_20, Decimal(parameters["liquidity_threshold"]), lambda a,b:a>=b),
        positive_momentum=compare(indicator.daily_change_percent, Decimal(0), lambda a,b:a>b),
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
