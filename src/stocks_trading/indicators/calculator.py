from collections.abc import Sequence
from decimal import Decimal, localcontext

from stocks_trading.domain.models import DailyCandle, DailyIndicators
from stocks_trading.market_data.validation import validate_candles


class IndicatorCalculationError(ValueError):
    pass


def calculate_indicators(
    candles: Sequence[DailyCandle],
    *,
    calculation_version: str = "technical-v3",
) -> list[DailyIndicators]:
    if not candles:
        return []
    for previous, current in zip(candles, candles[1:]):
        if current.trading_date <= previous.trading_date:
            raise IndicatorCalculationError(
                "candles must have unique, strictly increasing trading dates"
            )
        if current.symbol != previous.symbol:
            raise IndicatorCalculationError("all candles must use one symbol")
    try:
        validated = validate_candles(candles)
    except ValueError as error:
        raise IndicatorCalculationError(str(error)) from error

    closes = [item.close for item in validated]
    highs = [item.high for item in validated]
    lows = [item.low for item in validated]
    volumes = [Decimal(item.volume) for item in validated]
    traded_values = [item.close * Decimal(item.volume) for item in validated]
    true_ranges = calculate_true_ranges(validated)
    atr_values = calculate_wilder_atr(true_ranges, period=14)
    rsi_values = calculate_wilder_rsi(closes, period=14)
    macd_values, macd_signal_values, macd_histogram_values = calculate_macd(closes)
    higher_low_values = calculate_higher_lows(lows)
    results: list[DailyIndicators] = []

    for index, candle in enumerate(validated):
        volume_ma_20 = rolling_average(volumes, index, 20)
        results.append(
            DailyIndicators(
                symbol=candle.symbol,
                trading_date=candle.trading_date,
                sma_5=rolling_average(closes, index, 5),
                sma_10=rolling_average(closes, index, 10),
                sma_20=rolling_average(closes, index, 20),
                sma_50=rolling_average(closes, index, 50),
                sma_200=rolling_average(closes, index, 200),
                volume_ma_20=volume_ma_20,
                volume_ratio=(
                    divide(volumes[index], volume_ma_20)
                    if volume_ma_20 not in (None, Decimal(0))
                    else None
                ),
                daily_change_percent=(
                    percentage_change(closes[index], closes[index - 1])
                    if index > 0 and closes[index - 1] != 0
                    else None
                ),
                atr_14=atr_values[index],
                highest_high_20=prior_window_value(highs, index, 20, max),
                lowest_low_20=prior_window_value(lows, index, 20, min),
                average_traded_value_20=rolling_average(traded_values, index, 20),
                rsi_14=rsi_values[index],
                macd=macd_values[index],
                macd_signal=macd_signal_values[index],
                macd_histogram=macd_histogram_values[index],
                macd_bullish_crossover=(
                    macd_values[index] > macd_signal_values[index]
                    and macd_values[index - 1] <= macd_signal_values[index - 1]
                    if index > 0 and None not in (
                        macd_values[index], macd_signal_values[index],
                        macd_values[index - 1], macd_signal_values[index - 1],
                    ) else None
                ),
                higher_low_formed=higher_low_values[index],
                calculation_version=calculation_version,
                provider=candle.provider,
                interval=candle.interval,
            )
        )
    return results


def calculate_wilder_rsi(closes: Sequence[Decimal], period: int = 14) -> list[Decimal | None]:
    values: list[Decimal | None] = [None] * len(closes)
    if len(closes) <= period:
        return values
    gains = [max(closes[index] - closes[index - 1], Decimal(0)) for index in range(1, len(closes))]
    losses = [max(closes[index - 1] - closes[index], Decimal(0)) for index in range(1, len(closes))]
    average_gain = average(gains[:period])
    average_loss = average(losses[:period])
    values[period] = rsi_value(average_gain, average_loss)
    for index in range(period + 1, len(closes)):
        average_gain = (average_gain * Decimal(period - 1) + gains[index - 1]) / Decimal(period)
        average_loss = (average_loss * Decimal(period - 1) + losses[index - 1]) / Decimal(period)
        values[index] = rsi_value(average_gain, average_loss)
    return values


def rsi_value(average_gain: Decimal, average_loss: Decimal) -> Decimal:
    if average_loss == 0:
        return Decimal(100)
    strength = average_gain / average_loss
    return Decimal(100) - Decimal(100) / (Decimal(1) + strength)


def calculate_macd(closes: Sequence[Decimal]) -> tuple[list[Decimal | None], list[Decimal | None], list[Decimal | None]]:
    fast = calculate_ema(closes, 12)
    slow = calculate_ema(closes, 26)
    macd = [None if fast_value is None or slow_value is None else fast_value - slow_value for fast_value, slow_value in zip(fast, slow)]
    signal = calculate_optional_ema(macd, 9)
    histogram = [None if value is None or signal_value is None else value - signal_value for value, signal_value in zip(macd, signal)]
    return macd, signal, histogram


def calculate_ema(values: Sequence[Decimal], period: int) -> list[Decimal | None]:
    result: list[Decimal | None] = [None] * len(values)
    if len(values) < period:
        return result
    current = average(values[:period])
    result[period - 1] = current
    multiplier = Decimal(2) / Decimal(period + 1)
    for index in range(period, len(values)):
        current = (values[index] - current) * multiplier + current
        result[index] = current
    return result


def calculate_optional_ema(values: Sequence[Decimal | None], period: int) -> list[Decimal | None]:
    result: list[Decimal | None] = [None] * len(values)
    available = [(index, value) for index, value in enumerate(values) if value is not None]
    if len(available) < period:
        return result
    current = average([value for _, value in available[:period]])
    result[available[period - 1][0]] = current
    multiplier = Decimal(2) / Decimal(period + 1)
    for index, value in available[period:]:
        current = (value - current) * multiplier + current
        result[index] = current
    return result


def calculate_higher_lows(lows: Sequence[Decimal], lookback: int = 5) -> list[bool | None]:
    result: list[bool | None] = [None] * len(lows)
    window = lookback * 2
    for index in range(window - 1, len(lows)):
        previous_low = min(lows[index - window + 1:index - lookback + 1])
        current_low = min(lows[index - lookback + 1:index + 1])
        result[index] = current_low > previous_low
    return result


def calculate_true_ranges(candles: Sequence[DailyCandle]) -> list[Decimal | None]:
    true_ranges: list[Decimal | None] = []
    for index, candle in enumerate(candles):
        if index == 0:
            true_ranges.append(None)
            continue
        previous_close = candles[index - 1].close
        true_ranges.append(
            max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        )
    return true_ranges


def calculate_wilder_atr(
    true_ranges: Sequence[Decimal | None], period: int
) -> list[Decimal | None]:
    values: list[Decimal | None] = [None] * len(true_ranges)
    if len(true_ranges) <= period:
        return values
    seed = [value for value in true_ranges[1 : period + 1] if value is not None]
    if len(seed) != period:
        return values
    previous_atr = average(seed)
    values[period] = previous_atr
    for index in range(period + 1, len(true_ranges)):
        current_true_range = true_ranges[index]
        if current_true_range is None:
            continue
        previous_atr = divide(
            previous_atr * Decimal(period - 1) + current_true_range,
            Decimal(period),
        )
        values[index] = previous_atr
    return values


def rolling_average(
    values: Sequence[Decimal], index: int, period: int
) -> Decimal | None:
    if index + 1 < period:
        return None
    return average(values[index + 1 - period : index + 1])


def prior_window_value(values, index: int, period: int, operation):
    if index < period:
        return None
    return operation(values[index - period : index])


def average(values: Sequence[Decimal]) -> Decimal:
    return divide(sum(values, Decimal(0)), Decimal(len(values)))


def percentage_change(current: Decimal, previous: Decimal) -> Decimal:
    return (divide(current, previous) - Decimal(1)) * Decimal(100)


def divide(numerator: Decimal, denominator: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 28
        return numerator / denominator
