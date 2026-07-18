from datetime import date
from decimal import Decimal

import pytest

from stocks_trading.domain.models import DailyCandle
from stocks_trading.market_data.validation import CandleValidationError, validate_candles


def candle(**overrides) -> DailyCandle:
    values = {
        "symbol": "BBCA.JK",
        "trading_date": date(2026, 7, 16),
        "open": Decimal("9000"),
        "high": Decimal("9200"),
        "low": Decimal("8950"),
        "close": Decimal("9150"),
        "adjusted_close": Decimal("9150"),
        "volume": 10_000_000,
    }
    values.update(overrides)
    return DailyCandle(**values)


def test_accepts_valid_candle() -> None:
    assert validate_candles([candle()]) == [candle()]


def test_rejects_invalid_high() -> None:
    with pytest.raises(CandleValidationError, match="high is below"):
        validate_candles([candle(high=Decimal("9050"))])


def test_rejects_duplicate_identity() -> None:
    with pytest.raises(CandleValidationError, match="duplicate candle"):
        validate_candles([candle(), candle()])

