from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from stocks_trading.indicators import CALCULATION_VERSION
from stocks_trading.liquidity.config import TIERS, LiquidityConfiguration
from stocks_trading.market_data.calendar import load_market_calendar
from stocks_trading.market_data.yahoo import YahooFinanceProvider, latest_completed_market_date


PERIOD_DAYS = {
    "1mo": 31,
    "3mo": 93,
    "6mo": 186,
    "1y": 366,
    "2y": 732,
    "5y": 1830,
}
SUPPORTED_PERIODS = frozenset((*PERIOD_DAYS, "max"))
SUPPORTED_INTERVALS = frozenset(
    {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"}
)


class StockNotFoundError(ValueError):
    pass


class StockDataError(RuntimeError):
    pass


class StockValidationError(ValueError):
    pass


class StockService:
    def __init__(self, repository, collector, provider: YahooFinanceProvider, settings,
                 liquidity: LiquidityConfiguration) -> None:
        self.repository = repository
        self.collector = collector
        self.provider = provider
        self.settings = settings
        self.liquidity = liquidity

    def list(self, *, search: str | None, limit: int, offset: int,
             min_turnover: Decimal | None = None,
             liquidity_tiers: tuple[str, ...] = ()) -> dict[str, object]:
        invalid = set(liquidity_tiers) - set(TIERS)
        if invalid:
            raise StockValidationError(f"unsupported liquidity tier: {', '.join(sorted(invalid))}")
        if min_turnover is not None and min_turnover < 0:
            raise StockValidationError("min_turnover must be non-negative")
        as_of_date = self.repository.liquidity_snapshot_date(self.liquidity.indicator_version)
        rows, total_stocks, filtered_count = self.repository.list_stock_summaries(
            search=search, limit=limit, offset=offset,
            indicator_version=self.liquidity.indicator_version, as_of_date=as_of_date,
            min_turnover=min_turnover, liquidity_tiers=liquidity_tiers,
            liquidity_thresholds=self.liquidity.thresholds,
        )
        items = [self._summary(row) for row in rows]
        filters_applied = {}
        if search:
            filters_applied["search"] = search
        if min_turnover is not None:
            filters_applied["min_turnover"] = min_turnover
        if liquidity_tiers:
            filters_applied["liquidity_tier"] = list(liquidity_tiers)
        return {
            "total_stocks": total_stocks, "filtered_count": filtered_count,
            "filters_applied": filters_applied, "as_of_date": as_of_date,
            "stocks": items, "items": items, "total": filtered_count,
            "limit": limit, "offset": offset,
        }

    def liquidity_breakdown(self, *, scoring_version: str, scoring_config_checksum: str):
        as_of_date = self.repository.liquidity_snapshot_date(self.liquidity.indicator_version)
        if as_of_date is None:
            return {"as_of_date": None, "breakdown": [], "unclassified_count": 0}
        rows = self.repository.liquidity_breakdown(
            as_of_date=as_of_date, indicator_version=self.liquidity.indicator_version,
            scoring_version=scoring_version, scoring_config_checksum=scoring_config_checksum,
        )
        buckets = {tier: {"turnover": [], "scores": []} for tier in TIERS}
        unclassified = 0
        for row in rows:
            turnover = row.get("average_traded_value_20")
            tier = self.liquidity.tier(turnover if isinstance(turnover, Decimal) else None)
            if tier is None:
                unclassified += 1
                continue
            buckets[tier]["turnover"].append(turnover)
            if row.get("score") is not None:
                buckets[tier]["scores"].append(Decimal(row["score"]))
        breakdown = []
        for tier in TIERS:
            turnovers = buckets[tier]["turnover"]
            scores = buckets[tier]["scores"]
            breakdown.append({
                "tier": tier, "stock_count": len(turnovers),
                "avg_technical_score": sum(scores) / len(scores) if scores else None,
                "avg_daily_turnover_value": sum(turnovers) / len(turnovers) if turnovers else None,
            })
        return {"as_of_date": as_of_date, "breakdown": breakdown, "unclassified_count": unclassified}

    async def detail(self, symbol: str, *, period: str, interval: str) -> dict[str, object]:
        if period not in SUPPORTED_PERIODS:
            raise StockValidationError(
                f"unsupported period '{period}'; use {', '.join(sorted(SUPPORTED_PERIODS))}"
            )
        if interval not in SUPPORTED_INTERVALS:
            raise StockValidationError(
                f"unsupported interval '{interval}'; use {', '.join(sorted(SUPPORTED_INTERVALS))}"
            )
        metadata = self.repository.stock_metadata(symbol)
        if metadata is None:
            raise StockNotFoundError(f"symbol {symbol} is not active in the IDX universe")

        if interval != "1d":
            try:
                candles = self.provider.download_period(symbol, period, interval)
            except Exception as error:
                raise StockDataError(f"Yahoo Finance request failed for {symbol}: {error}") from error
            if not candles:
                raise StockDataError(f"Yahoo Finance returned no {interval} data for {symbol}")
            return self._detail_response(metadata, period, interval, candles)

        end_date = self._end_date()
        start_date = self._start_date(period, end_date)
        candles = self.repository.load_stock_candles(
            symbol, start_date=start_date, end_date=end_date
        )
        if not candles:
            try:
                fallback_start = start_date or end_date - timedelta(days=5 * 366)
                result = await self.collector.refresh(
                    start_date=fallback_start, end_date=end_date, symbols=[symbol]
                )
                if result.failed_count:
                    failure = next(item for item in result.symbols if item.error)
                    raise StockDataError(failure.error or "Yahoo Finance collection failed")
            except StockDataError:
                raise
            except Exception as error:
                raise StockDataError(f"Yahoo Finance request failed for {symbol}: {error}") from error
            candles = self.repository.load_stock_candles(
                symbol, start_date=start_date, end_date=end_date
            )
        if not candles:
            raise StockDataError(f"no historical market data is available for {symbol}")

        indicators = self.repository.load_stock_indicators(
            symbol,
            start_date=start_date,
            end_date=end_date,
            calculation_version=CALCULATION_VERSION,
        )
        rows = []
        for candle in candles:
            row = {
                "date": candle.trading_date.isoformat(),
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "adjusted_close": candle.adjusted_close,
                "volume": candle.volume,
            }
            row.update(indicators.get(candle.trading_date, {}))
            rows.append(row)
        return self._detail_response(metadata, period, interval, rows)

    def _end_date(self) -> date:
        calendar = load_market_calendar(self.settings.market_calendar_config_path)
        return latest_completed_market_date(
            datetime.now(UTC), self.settings.market_timezone, calendar
        )

    @staticmethod
    def _start_date(period: str, end_date: date) -> date | None:
        days = PERIOD_DAYS.get(period)
        return end_date - timedelta(days=days) if days is not None else None

    def _summary(self, row: dict[str, object]) -> dict[str, object]:
        last_price = row.get("last_price")
        previous_close = row.pop("previous_close", None)
        change = None
        change_percent = None
        if isinstance(last_price, Decimal) and isinstance(previous_close, Decimal):
            change = last_price - previous_close
            if previous_close:
                change_percent = change / previous_close * Decimal("100")
        turnover = row.get("avg_daily_turnover_value")
        return {
            **row, "daily_change": change, "daily_change_percent": change_percent,
            "liquidity_tier": self.liquidity.tier(turnover if isinstance(turnover, Decimal) else None),
        }

    @staticmethod
    def _detail_response(
        metadata: dict[str, object], period: str, interval: str, candles: list[dict[str, object]]
    ) -> dict[str, object]:
        latest = candles[-1]
        previous = candles[-2] if len(candles) > 1 else None
        close = Decimal(str(latest["close"]))
        previous_close = Decimal(str(previous["close"])) if previous else None
        daily_change = close - previous_close if previous_close is not None else None
        daily_change_percent = (
            daily_change / previous_close * Decimal("100")
            if daily_change is not None and previous_close
            else None
        )
        return {
            **metadata,
            "period": period,
            "interval": interval,
            "last_price": close,
            "daily_change": daily_change,
            "daily_change_percent": daily_change_percent,
            "volume": latest["volume"],
            "trading_date": latest["date"],
            "candles": candles,
        }
