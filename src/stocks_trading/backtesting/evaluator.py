from collections import defaultdict
from decimal import Decimal
from math import sqrt
from statistics import stdev

from stocks_trading.backtesting.config import BacktestConfiguration
from stocks_trading.domain.models import BacktestMetrics, BacktestResult, BacktestTrade, DailyCandle, StrategyResult

ZERO = Decimal("0")
HUNDRED = Decimal("100")
ONE = Decimal("1")


def run_backtest(
    signals: list[StrategyResult], candles: dict[str, list[DailyCandle]],
    configuration: BacktestConfiguration,
) -> BacktestResult:
    if configuration.execution_model == "swing_lifecycle":
        if configuration.lifecycle_config_path is None:
            raise ValueError("lifecycle configuration is required")
        from stocks_trading.positions.config import load_position_configuration
        return run_swing_backtest(signals, candles, configuration,
                                  load_position_configuration(configuration.lifecycle_config_path))
    signals_by_symbol = defaultdict(list)
    for signal in signals:
        if signal.strategy_name != configuration.strategy_name or signal.strategy_version != configuration.strategy_version or signal.strategy_config_checksum != configuration.strategy_config_checksum:
            raise ValueError("strategy source identity does not match backtest configuration")
        if signal.passed is True:
            signals_by_symbol[signal.symbol].append(signal)

    trades = []
    unclosed = defaultdict(int)
    signal_counts = {symbol: len(items) for symbol, items in signals_by_symbol.items()}
    for symbol, symbol_signals in signals_by_symbol.items():
        prices = sorted(candles.get(symbol, []), key=lambda item: item.trading_date)
        price_index = {item.trading_date: index for index, item in enumerate(prices)}
        last_exit = None
        for signal in sorted(symbol_signals, key=lambda item: item.trading_date):
            if last_exit is not None and signal.trading_date < last_exit:
                continue
            index = price_index.get(signal.trading_date)
            if index is None or index + 1 >= len(prices):
                unclosed[symbol] += 1
                continue
            entry = prices[index]
            exit_candle = prices[index + 1]
            trade = calculate_trade(symbol, entry, exit_candle, configuration)
            trades.append(trade)
            last_exit = exit_candle.trading_date

    trades.sort(key=lambda item: (item.exit_date, item.symbol, item.signal_date))
    symbols = {}
    all_symbols = set(signal_counts)
    for symbol in sorted(all_symbols):
        symbol_trades = [item for item in trades if item.symbol == symbol]
        symbols[symbol] = calculate_metrics(symbol_trades, signal_counts[symbol], unclosed[symbol], configuration)
    aggregate = calculate_metrics(trades, sum(signal_counts.values()), sum(unclosed.values()), configuration)
    return BacktestResult(tuple(trades), aggregate, symbols)


def run_swing_backtest(signals, candles, configuration, lifecycle_configuration):
    from stocks_trading.domain.models import PositionSourceDay, PositionStatus
    from stocks_trading.positions.evaluator import new_pending_position, process_position

    signals_by_symbol = defaultdict(dict)
    for signal in signals:
        if signal.strategy_name != configuration.strategy_name or signal.strategy_version != configuration.strategy_version or signal.strategy_config_checksum != configuration.strategy_config_checksum:
            raise ValueError("strategy source identity does not match backtest configuration")
        if signal.passed is True:
            signals_by_symbol[signal.symbol][signal.trading_date] = signal
    trades = []
    unclosed = defaultdict(int)
    signal_counts = {symbol: len(items) for symbol, items in signals_by_symbol.items()}
    for symbol, symbol_signals in signals_by_symbol.items():
        active = None
        for candle in sorted(candles.get(symbol, []), key=lambda item: item.trading_date):
            signal = symbol_signals.get(candle.trading_date)
            if signal and active is None:
                atr_value = signal.evaluation_details.get("atr_14", "1")
                source = PositionSourceDay(candle, True, Decimal(str(atr_value)), False, False, Decimal("5"))
                active, _ = new_pending_position(source, lifecycle_configuration)
                continue
            if active is not None:
                source = PositionSourceDay(candle, False, active.signal_atr or Decimal("1"), False, False, Decimal("5"))
                active, _ = process_position(active, source, lifecycle_configuration)
                if active.status == PositionStatus.CLOSED and active.entry_price is not None and active.average_exit_price is not None:
                    gross_return = active.realized_gross_return
                    net_return = active.realized_net_return
                    trades.append(BacktestTrade(
                        symbol=symbol, signal_date=active.signal_date, exit_date=active.exit_date,
                        entry_price=active.entry_price, exit_price=active.average_exit_price,
                        gross_return=gross_return, net_return=net_return,
                        buy_fee=configuration.notional * configuration.buy_fee_rate,
                        sell_fee=configuration.notional * max(Decimal("0"), ONE + gross_return) * configuration.sell_fee_rate,
                        gross_profit=configuration.notional * gross_return,
                        net_profit=configuration.notional * net_return,
                        holding_sessions=active.holding_sessions,
                    ))
                    active = None
        if active is not None:
            unclosed[symbol] += 1
    trades.sort(key=lambda item: (item.exit_date, item.symbol, item.signal_date))
    symbols = {symbol: calculate_metrics([item for item in trades if item.symbol == symbol], signal_counts[symbol], unclosed[symbol], configuration) for symbol in signal_counts}
    aggregate = calculate_metrics(trades, sum(signal_counts.values()), sum(unclosed.values()), configuration)
    return BacktestResult(tuple(trades), aggregate, symbols)


def calculate_trade(symbol: str, entry: DailyCandle, exit_candle: DailyCandle,
                    configuration: BacktestConfiguration) -> BacktestTrade:
    entry_price = entry.close
    exit_price = exit_candle.open
    gross_return = exit_price / entry_price - 1
    buy_fee = configuration.notional * configuration.buy_fee_rate
    sale_value = configuration.notional * (1 + gross_return)
    sell_fee = sale_value * configuration.sell_fee_rate
    gross_profit = configuration.notional * gross_return
    net_profit = gross_profit - buy_fee - sell_fee
    net_return = net_profit / configuration.notional
    return BacktestTrade(
        symbol=symbol, signal_date=entry.trading_date, exit_date=exit_candle.trading_date,
        entry_price=entry_price, exit_price=exit_price, gross_return=gross_return,
        net_return=net_return, buy_fee=buy_fee, sell_fee=sell_fee,
        gross_profit=gross_profit, net_profit=net_profit,
    )


def calculate_metrics(trades, signal_count, unclosed_signals, configuration):
    returns = [item.net_return for item in trades]
    gross_returns = [item.gross_return for item in trades]
    wins = sum(item > 0 for item in returns)
    losses = sum(item < 0 for item in returns)
    positive = sum((item for item in returns if item > 0), ZERO)
    negative = sum((item for item in returns if item < 0), ZERO)
    equity = Decimal("1")
    peak = Decimal("1")
    maximum_drawdown = ZERO
    for item in returns:
        equity *= 1 + item
        peak = max(peak, equity)
        maximum_drawdown = min(maximum_drawdown, equity / peak - 1)
    sharpe = None
    if len(returns) >= 2:
        deviation = stdev([float(item) for item in returns])
        if deviation:
            sharpe = Decimal(str((sum(float(item) for item in returns) / len(returns)) / deviation * sqrt(configuration.sharpe_periods)))
    count = len(trades)
    return BacktestMetrics(
        signal_count=signal_count, completed_trades=count, unclosed_signals=unclosed_signals,
        wins=wins, losses=losses,
        win_rate=Decimal(wins) / count if count else None,
        average_gross_return=sum(gross_returns, ZERO) / count if count else None,
        average_net_return=sum(returns, ZERO) / count if count else None,
        total_compounded_return=equity - 1 if count else None,
        gross_profit=positive * configuration.notional,
        gross_loss=negative * configuration.notional,
        profit_factor=positive / abs(negative) if negative else None,
        maximum_drawdown=maximum_drawdown if count else None,
        sharpe_ratio=sharpe,
    )
