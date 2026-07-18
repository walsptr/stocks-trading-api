from datetime import date, timedelta
from decimal import Decimal

import pytest

from stocks_trading.domain.models import DailyCandle
from stocks_trading.indicators.calculator import (
    IndicatorCalculationError,
    calculate_indicators,
    calculate_wilder_atr,
)


def candles(count: int, *, volume: int = 100) -> list[DailyCandle]:
    start = date(2025, 1, 1)
    return [
        DailyCandle(
            symbol="BBCA.JK",
            trading_date=start + timedelta(days=index),
            open=Decimal(index + 1),
            high=Decimal(index + 3),
            low=Decimal(index),
            close=Decimal(index + 2),
            adjusted_close=Decimal(index + 2),
            volume=volume,
        )
        for index in range(count)
    ]


def test_calculates_required_windows_and_shifted_breakout() -> None:
    result = calculate_indicators(candles(205))

    assert result[3].sma_5 is None
    assert result[4].sma_5 == Decimal("4")
    assert result[19].volume_ma_20 == Decimal("100")
    assert result[19].volume_ratio == Decimal("1")
    assert result[19].average_traded_value_20 == Decimal("1150")
    assert result[1].daily_change_percent == Decimal("50.0")
    assert result[199].sma_200 == Decimal("101.5")
    assert result[19].highest_high_20 is None
    assert result[20].highest_high_20 == Decimal("22")
    assert result[20].lowest_low_20 == Decimal("0")


def test_wilder_atr_seeds_and_recurses() -> None:
    values = calculate_wilder_atr(
        [None] + [Decimal(value) for value in range(1, 16)], 14
    )

    assert values[13] is None
    assert values[14] == Decimal("7.5")
    assert values[15] == (Decimal("7.5") * 13 + Decimal(15)) / 14


def test_zero_volume_average_produces_null_ratio() -> None:
    result = calculate_indicators(candles(20, volume=0))

    assert result[-1].volume_ma_20 == Decimal(0)
    assert result[-1].volume_ratio is None


def test_rejects_unsorted_or_duplicate_dates() -> None:
    source = candles(2)
    source[1] = DailyCandle(
        symbol=source[1].symbol,
        trading_date=source[0].trading_date,
        open=source[1].open,
        high=source[1].high,
        low=source[1].low,
        close=source[1].close,
        adjusted_close=source[1].adjusted_close,
        volume=source[1].volume,
    )

    with pytest.raises(IndicatorCalculationError, match="strictly increasing"):
        calculate_indicators(source)
