from datetime import date
from decimal import Decimal
from pathlib import Path

from stocks_trading.backtesting.config import load_backtest_configuration
from stocks_trading.backtesting.evaluator import run_backtest
from stocks_trading.domain.models import DailyCandle, StrategyResult


def config():
    return load_backtest_configuration(Path("config/backtesting/bsjp-v1.yaml"))


def signal(trading_date):
    c = config()
    return StrategyResult("BBCA.JK", trading_date, "BSJP", c.strategy_version, c.strategy_config_checksum, True, {}, "rules-v1", "rules")


def candle(trading_date, open_price, close_price):
    return DailyCandle("BBCA.JK", trading_date, Decimal(open_price), Decimal(open_price), Decimal(open_price), Decimal(close_price), Decimal(close_price), 1000)


def test_close_to_next_open_with_fees() -> None:
    result = run_backtest(
        [signal(date(2026, 7, 15))],
        {"BBCA.JK": [candle(date(2026, 7, 15), "100", "100"), candle(date(2026, 7, 16), "110", "111")]},
        config(),
    )
    trade = result.trades[0]
    assert trade.entry_price == Decimal("100")
    assert trade.exit_price == Decimal("110")
    assert trade.gross_return == Decimal("0.1")
    assert trade.buy_fee == Decimal("1500.0000")
    assert trade.sell_fee == Decimal("2750.00000")
    assert trade.net_return == Decimal("0.09575")


def test_unclosed_signal_counted_without_trade() -> None:
    result = run_backtest(
        [signal(date(2026, 7, 16))],
        {"BBCA.JK": [candle(date(2026, 7, 16), "100", "100")]}, config(),
    )
    assert result.aggregate.completed_trades == 0
    assert result.aggregate.unclosed_signals == 1
    assert result.aggregate.sharpe_ratio is None


def test_metrics_profit_factor_drawdown_and_sharpe() -> None:
    signals = [signal(date(2026, 7, 13)), signal(date(2026, 7, 15))]
    candles = {"BBCA.JK": [
        candle(date(2026, 7, 13), "100", "100"), candle(date(2026, 7, 14), "110", "110"),
        candle(date(2026, 7, 15), "100", "100"), candle(date(2026, 7, 16), "90", "90"),
    ]}
    result = run_backtest(signals, candles, config())
    assert result.aggregate.completed_trades == 2
    assert result.aggregate.wins == 1
    assert result.aggregate.losses == 1
    assert result.aggregate.profit_factor is not None
    assert result.aggregate.maximum_drawdown < 0
    assert result.aggregate.sharpe_ratio is not None
