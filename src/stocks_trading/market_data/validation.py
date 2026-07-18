from collections.abc import Iterable
from decimal import Decimal

from stocks_trading.domain.models import DailyCandle


class CandleValidationError(ValueError):
    pass


def validate_candles(candles: Iterable[DailyCandle]) -> list[DailyCandle]:
    validated: list[DailyCandle] = []
    identities: set[tuple[str, object]] = set()
    for candle in candles:
        identity = (candle.symbol, candle.trading_date)
        if identity in identities:
            raise CandleValidationError(
                f"duplicate candle for {candle.symbol} on {candle.trading_date}"
            )
        identities.add(identity)

        prices: tuple[Decimal, ...] = (
            candle.open,
            candle.high,
            candle.low,
            candle.close,
            candle.adjusted_close,
        )
        if any(price < 0 for price in prices):
            raise CandleValidationError(
                f"negative price for {candle.symbol} on {candle.trading_date}"
            )
        if candle.volume < 0:
            raise CandleValidationError(
                f"negative volume for {candle.symbol} on {candle.trading_date}"
            )
        if candle.low > min(candle.open, candle.close, candle.high):
            raise CandleValidationError(
                f"low exceeds OHLC values for {candle.symbol} on {candle.trading_date}"
            )
        if candle.high < max(candle.open, candle.close, candle.low):
            raise CandleValidationError(
                f"high is below OHLC values for {candle.symbol} on {candle.trading_date}"
            )
        validated.append(candle)
    return validated

