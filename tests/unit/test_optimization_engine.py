from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import stocks_trading.optimization.evaluator as evaluator
from stocks_trading.backtesting.config import load_backtest_configuration
from stocks_trading.domain.models import (
    BacktestMetrics,
    BacktestResult,
    DailyCandle,
    DailyIndicators,
    OptimizationCandidate,
)
from stocks_trading.optimization.config import load_optimization_configuration
from stocks_trading.optimization.evaluator import candidate_rules, candidate_sort_key


def candle(day: date, close: str = "110") -> DailyCandle:
    return DailyCandle(
        "BBCA.JK", day, Decimal("100"), Decimal("115"), Decimal("95"),
        Decimal(close), Decimal(close), 1_000_000,
    )


def indicator(day: date, *, volume_ratio: str = "1.5", liquidity: str = "10000000000") -> DailyIndicators:
    return DailyIndicators(
        "BBCA.JK", day, Decimal("105"), Decimal("100"), Decimal("95"),
        Decimal("90"), Decimal("80"), Decimal("900000"), Decimal(volume_ratio),
        Decimal("1"), Decimal("2"), Decimal("109"), Decimal("90"),
        Decimal(liquidity), calculation_version="technical-v2",
    )


def metrics(*, trades: int, sharpe: str | None, compounded: str = "0.1", drawdown: str = "-0.1") -> BacktestMetrics:
    return BacktestMetrics(
        trades, trades, 0, trades, 0, Decimal("1") if trades else None,
        Decimal("0.01") if trades else None, Decimal("0.01") if trades else None,
        Decimal(compounded) if trades else None, Decimal("1"), Decimal("0"), None,
        Decimal(drawdown) if trades else None, Decimal(sharpe) if sharpe else None,
    )


def test_candidate_rules_use_persisted_indicators_and_candidate_thresholds() -> None:
    rules = candidate_rules(candle(date(2026, 1, 1)), indicator(date(2026, 1, 1)), {
        "volume_spike_ratio": "2.0", "liquidity_threshold": "5000000000",
        "require_breakout": False, "require_volume_spike": False,
    }, "candidate")

    assert rules.volume_spike is False
    assert rules.high_liquidity is True
    assert rules.breakout_20 is True
    assert rules.indicator_version == "technical-v2"


def test_candidate_sort_key_applies_documented_tie_breaks() -> None:
    base = metrics(trades=30, sharpe="1.5")
    candidates = [
        OptimizationCandidate("more-return", {}, True, None, base, replace(base, total_compounded_return=Decimal("0.2"))),
        OptimizationCandidate("less-drawdown", {}, True, None, base, replace(base, total_compounded_return=Decimal("0.2"), maximum_drawdown=Decimal("-0.05"))),
        OptimizationCandidate("ineligible", {}, False, "reason", base, base),
    ]

    assert [item.candidate_id for item in sorted(candidates, key=candidate_sort_key)] == [
        "less-drawdown", "more-return", "ineligible"
    ]


def test_optimize_uses_chronological_70_30_split_and_eligibility(monkeypatch) -> None:
    configuration = load_optimization_configuration(Path("config/optimization/bsjp-v1.yaml"))
    backtest = load_backtest_configuration(configuration.backtest_config_path)
    days = [date(2026, 1, 1) + timedelta(days=index) for index in range(10)]
    sources = [(candle(day), indicator(day)) for day in days]
    calls = []

    def fake_backtest(signals, candles, candidate_configuration):
        calls.append(tuple(item.trading_date for item in signals))
        validation = bool(signals and min(item.trading_date for item in signals) >= days[7])
        candidate_metrics = metrics(trades=30 if validation else 10, sharpe="1.0")
        return BacktestResult((), candidate_metrics, {})

    monkeypatch.setattr(evaluator, "run_backtest", fake_backtest)
    result = evaluator.optimize(sources, {"BBCA.JK": [item[0] for item in sources]}, configuration, backtest)

    assert result.training_start == days[0]
    assert result.training_end == days[6]
    assert result.validation_start == days[7]
    assert result.validation_end == days[9]
    assert result.winner_id is not None
    assert len(result.candidates) == 24
    assert all(item.eligible for item in result.candidates)
    assert calls[0] == tuple(days[:7])
    assert calls[1] == tuple(days[7:])


def test_null_sharpe_and_trade_floor_are_ineligible(monkeypatch) -> None:
    configuration = load_optimization_configuration(Path("config/optimization/bsjp-v1.yaml"))
    backtest = load_backtest_configuration(configuration.backtest_config_path)
    days = [date(2026, 1, 1), date(2026, 1, 2)]
    sources = [(candle(day), indicator(day)) for day in days]
    call_count = 0

    def fake_backtest(signals, candles, candidate_configuration):
        nonlocal call_count
        call_count += 1
        candidate_index = (call_count - 1) // 2
        validation = call_count % 2 == 0
        if validation and candidate_index == 0:
            candidate_metrics = metrics(trades=29, sharpe="1")
        elif validation:
            candidate_metrics = metrics(trades=30, sharpe=None)
        else:
            candidate_metrics = metrics(trades=1, sharpe=None)
        return BacktestResult((), candidate_metrics, {})

    monkeypatch.setattr(evaluator, "run_backtest", fake_backtest)
    result = evaluator.optimize(sources, {"BBCA.JK": [item[0] for item in sources]}, configuration, backtest)

    assert result.winner_id is None
    assert {item.ineligible_reason for item in result.candidates} == {
        "insufficient_validation_trades", "null_validation_sharpe"
    }
