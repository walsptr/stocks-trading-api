from datetime import date
from decimal import Decimal

import pytest

from stocks_trading.config.settings import Settings
from stocks_trading.domain.models import DailyCandle
from stocks_trading.stocks.service import StockService, StockValidationError
from stocks_trading.liquidity.config import load_liquidity_configuration
from pathlib import Path


class Repository:
    def liquidity_snapshot_date(self, indicator_version):
        return date(2026, 7, 17)

    def list_stock_summaries(self, **kwargs):
        return ([{
            "symbol": "BBCA.JK", "idx_code": "BBCA", "issuer_name": "Bank Central Asia Tbk",
            "board": "Main", "sector": "Financials", "last_price": Decimal("9200"),
            "previous_close": Decimal("9100"), "volume": 12_000_000,
            "trading_date": date(2026, 7, 17), "avg_daily_turnover_value": Decimal("6000000000"),
            "avg_daily_volume": Decimal("650000"),
        }], 863, 1)

    def liquidity_breakdown(self, **kwargs):
        return [
            {"symbol": "BBCA.JK", "average_traded_value_20": Decimal("6000000000"), "volume_ma_20": Decimal("650000"), "score": 80},
            {"symbol": "ZERO.JK", "average_traded_value_20": Decimal("0"), "volume_ma_20": Decimal("0"), "score": None},
            {"symbol": "NONE.JK", "average_traded_value_20": None, "volume_ma_20": None, "score": None},
        ]
    def stock_metadata(self, symbol):
        if symbol != "BBCA.JK":
            return None
        return {
            "symbol": symbol,
            "idx_code": "BBCA",
            "issuer_name": "Bank Central Asia Tbk",
            "board": "Main",
            "sector": "Financials",
        }

    def load_stock_candles(self, symbol, *, start_date, end_date):
        return [
            DailyCandle(symbol, date(2026, 7, 16), Decimal("8900"), Decimal("9150"), Decimal("8850"), Decimal("9100"), Decimal("9100"), 10),
            DailyCandle(symbol, date(2026, 7, 17), Decimal("9100"), Decimal("9250"), Decimal("9050"), Decimal("9200"), Decimal("9200"), 12),
        ]

    def load_stock_indicators(self, symbol, **kwargs):
        return {date(2026, 7, 17): {"ma20": Decimal("9000"), "ma50": Decimal("8800"), "rsi14": Decimal("58.2")}}


class Collector:
    async def refresh(self, **kwargs):
        raise AssertionError("database data should be preferred")


class Provider:
    def download_period(self, symbol, period, interval):
        raise AssertionError("daily data should be read from storage")


@pytest.mark.asyncio
async def test_daily_stock_detail_uses_persisted_prices_and_indicators() -> None:
    service = StockService(Repository(), Collector(), Provider(), Settings(), load_liquidity_configuration(Path("config/liquidity/tiers-v1.yaml")))
    service._end_date = lambda: date(2026, 7, 17)

    result = await service.detail("BBCA.JK", period="6mo", interval="1d")

    assert result["last_price"] == Decimal("9200")
    assert result["daily_change_percent"].quantize(Decimal("0.01")) == Decimal("1.10")
    assert result["candles"][-1]["ma20"] == Decimal("9000")


@pytest.mark.asyncio
async def test_stock_detail_rejects_unknown_period() -> None:
    service = StockService(Repository(), Collector(), Provider(), Settings(), load_liquidity_configuration(Path("config/liquidity/tiers-v1.yaml")))

    with pytest.raises(StockValidationError, match="unsupported period"):
        await service.detail("BBCA.JK", period="7mo", interval="1d")


def test_stock_list_exposes_liquidity_metadata_and_tier() -> None:
    service = StockService(Repository(), Collector(), Provider(), Settings(), load_liquidity_configuration(Path("config/liquidity/tiers-v1.yaml")))
    result = service.list(search=None, limit=20, offset=0, liquidity_tiers=("high",))
    assert result["total_stocks"] == 863
    assert result["filtered_count"] == 1
    assert result["stocks"][0]["liquidity_tier"] == "high"
    assert result["items"] == result["stocks"]


def test_liquidity_breakdown_treats_zero_as_low_and_null_as_unclassified() -> None:
    service = StockService(Repository(), Collector(), Provider(), Settings(), load_liquidity_configuration(Path("config/liquidity/tiers-v1.yaml")))
    result = service.liquidity_breakdown(scoring_version="score-v1", scoring_config_checksum="checksum")
    assert result["breakdown"][0]["stock_count"] == 1
    assert result["breakdown"][2]["stock_count"] == 1
    assert result["unclassified_count"] == 1


@pytest.mark.parametrize(("turnover", "expected"), [
    (Decimal("5000000000"), "high"),
    (Decimal("4999999999.99"), "medium"),
    (Decimal("1000000000"), "medium"),
    (Decimal("999999999.99"), "low"),
    (Decimal("0"), "low"),
    (None, None),
])
def test_liquidity_tier_boundaries(turnover, expected) -> None:
    configuration = load_liquidity_configuration(Path("config/liquidity/tiers-v1.yaml"))

    assert configuration.tier(turnover) == expected


def test_stock_list_rejects_unknown_liquidity_tier() -> None:
    service = StockService(Repository(), Collector(), Provider(), Settings(), load_liquidity_configuration(Path("config/liquidity/tiers-v1.yaml")))

    with pytest.raises(StockValidationError, match="unsupported liquidity tier"):
        service.list(search=None, limit=20, offset=0, liquidity_tiers=("very-high",))
