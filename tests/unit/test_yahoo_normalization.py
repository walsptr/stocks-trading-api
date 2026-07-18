from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd

from stocks_trading.market_data.yahoo import normalize_yahoo_frame


def test_normalizes_single_symbol_frame_and_preserves_adjusted_close() -> None:
    frame = pd.DataFrame(
        {
            "Open": [9000.0],
            "High": [9200.0],
            "Low": [8950.0],
            "Close": [9150.0],
            "Adj Close": [9100.5],
            "Volume": [1_000_000],
        },
        index=pd.DatetimeIndex(["2026-07-16"]),
    )

    result = normalize_yahoo_frame(
        frame=frame,
        symbols=["BBCA.JK"],
        market_timezone=ZoneInfo("Asia/Jakarta"),
    )

    assert result["BBCA.JK"][0].trading_date == date(2026, 7, 16)
    assert result["BBCA.JK"][0].adjusted_close == Decimal("9100.5")


def test_normalizes_multi_symbol_frame() -> None:
    columns = pd.MultiIndex.from_product(
        [["Open", "High", "Low", "Close", "Adj Close", "Volume"], ["BBCA.JK", "TLKM.JK"]]
    )
    frame = pd.DataFrame(
        [[9000, 3000, 9200, 3050, 8950, 2980, 9150, 3030, 9100, 3020, 100, 200]],
        index=pd.DatetimeIndex(["2026-07-16"]),
        columns=columns,
    )

    result = normalize_yahoo_frame(
        frame=frame,
        symbols=["BBCA.JK", "TLKM.JK"],
        market_timezone=ZoneInfo("Asia/Jakarta"),
    )

    assert result["BBCA.JK"][0].close == Decimal("9150.0")
    assert result["TLKM.JK"][0].close == Decimal("3030.0")

