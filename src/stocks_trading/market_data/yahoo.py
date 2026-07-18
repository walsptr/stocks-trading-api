from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from stocks_trading.domain.models import DailyCandle
from stocks_trading.market_data.validation import validate_candles


class YahooFinanceProvider:
    def __init__(self, market_timezone: ZoneInfo) -> None:
        self.market_timezone = market_timezone

    def download(
        self, symbols: Sequence[str], start_date: date, end_date: date
    ) -> dict[str, list[DailyCandle]]:
        if not symbols:
            return {}
        frame = yf.download(
            tickers=list(symbols),
            start=start_date.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=False,
            actions=False,
            group_by="column",
            threads=False,
            progress=False,
            timeout=30,
        )
        return normalize_yahoo_frame(
            frame=frame,
            symbols=symbols,
            market_timezone=self.market_timezone,
        )


def normalize_yahoo_frame(
    *,
    frame: pd.DataFrame,
    symbols: Sequence[str],
    market_timezone: ZoneInfo,
) -> dict[str, list[DailyCandle]]:
    result = {symbol: [] for symbol in symbols}
    if frame.empty:
        return result

    for symbol in symbols:
        symbol_frame = extract_symbol_frame(frame, symbol, len(symbols))
        if symbol_frame.empty:
            continue
        candles: list[DailyCandle] = []
        for index, row in symbol_frame.iterrows():
            required = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
            if any(column not in row.index or pd.isna(row[column]) for column in required):
                continue
            trading_date = normalize_trading_date(index, market_timezone)
            candles.append(
                DailyCandle(
                    symbol=symbol,
                    trading_date=trading_date,
                    open=to_decimal(row["Open"]),
                    high=to_decimal(row["High"]),
                    low=to_decimal(row["Low"]),
                    close=to_decimal(row["Close"]),
                    adjusted_close=to_decimal(row["Adj Close"]),
                    volume=int(row["Volume"]),
                )
            )
        result[symbol] = validate_candles(candles)
    return result


def extract_symbol_frame(
    frame: pd.DataFrame, symbol: str, symbol_count: int
) -> pd.DataFrame:
    if not isinstance(frame.columns, pd.MultiIndex):
        return frame if symbol_count == 1 else pd.DataFrame()
    if symbol in frame.columns.get_level_values(1):
        return frame.xs(symbol, axis=1, level=1, drop_level=True)
    if symbol in frame.columns.get_level_values(0):
        return frame.xs(symbol, axis=1, level=0, drop_level=True)
    return pd.DataFrame(index=frame.index)


def normalize_trading_date(value: object, market_timezone: ZoneInfo) -> date:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.date()
    return timestamp.tz_convert(market_timezone).date()


def latest_completed_market_date(now: datetime, market_timezone: ZoneInfo) -> date:
    local_now = now.astimezone(market_timezone)
    candidate = local_now.date()
    if local_now.time() < time(17, 0):
        candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def to_decimal(value: object) -> Decimal:
    return Decimal(str(float(value)))

