from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

import pandas as pd
import yfinance as yf

from .config import FundamentalConfiguration
from .evaluator import decimal_or_none, evaluate, same_quarter_previous_year, previous_calendar_quarter, valuation_thresholds


class FundamentalService:
    def __init__(self, repository, configuration: FundamentalConfiguration, max_workers: int = 4) -> None:
        self.repository = repository
        self.configuration = configuration
        self.max_workers = max_workers

    async def update(self, symbols: list[str] | None = None) -> dict[str, object]:
        securities = self.repository.active_securities(symbols)
        run_id = self.repository.create_run(self.configuration.version, self.configuration.checksum, len(securities))
        semaphore = asyncio.Semaphore(self.max_workers)

        async def collect(security):
            async with semaphore:
                try:
                    return await asyncio.to_thread(self._collect, security), None
                except Exception as error:
                    return None, f"{security['symbol']}: {' '.join(str(error).split())[:500]}"

        collected = await asyncio.gather(*(collect(item) for item in securities))
        records = [record for record, error in collected if record]
        errors = [error for record, error in collected if error]
        thresholds = valuation_thresholds(records, self.configuration)
        rows = []
        insufficient = 0
        for record in records:
            result = evaluate(record, thresholds.get(record["sector"], {"per": None, "pbv": None}), self.configuration)
            insufficient += result["data_status"] == "insufficient_data"
            rows.append({
                "security_id": record["security_id"], "provider": self.configuration.provider,
                "fundamental_data_as_of": record["fundamental_data_as_of"],
                "calculation_version": self.configuration.version, "config_checksum": self.configuration.checksum,
                "sector": record["sector"], "industry": record["industry"], "is_bank": record["is_bank"],
                "latest_report_period": record["latest_report_period"], "currency": record["currency"],
                "net_income_latest": record["net_income_latest"], "net_income_prior_year": record["net_income_prior_year"],
                "net_income_previous_quarter": record["net_income_previous_quarter"], "total_debt": record["total_debt"],
                "stockholders_equity": record["stockholders_equity"], "roe_percent": record["roe_percent"],
                "der_percent": record["der_percent"], "trailing_pe": record["per"], "price_to_book": record["pbv"],
                "valuation_per_threshold": thresholds.get(record["sector"], {}).get("per"),
                "valuation_pbv_threshold": thresholds.get(record["sector"], {}).get("pbv"),
                **result, "raw_metrics": record["raw_metrics"],
            })
        self.repository.save_snapshots(rows)
        self.repository.finish_run(run_id, success=len(rows) - insufficient, insufficient=insufficient, failed=len(errors), error="; ".join(errors[:5]) or None)
        return {"run_id": run_id, "status": "partial_failure" if errors else "succeeded", "processed": len(rows), "insufficient_data": insufficient, "failed": len(errors), "errors": errors[:20]}

    def _collect(self, security: dict[str, object]) -> dict[str, object]:
        ticker = yf.Ticker(str(security["symbol"]))
        info = ticker.get_info()
        income = ticker.quarterly_income_stmt
        balance = ticker.quarterly_balance_sheet
        net_income = self._dated_series(income, ("Net Income", "Net Income Common Stockholders", "Net Income Including Noncontrolling Interests"))
        debt = self._dated_series(balance, ("Total Debt",))
        equity = self._dated_series(balance, ("Stockholders Equity", "Total Equity Gross Minority Interest"))
        latest_period = max(net_income) if net_income else self._date_from_epoch(info.get("mostRecentQuarter"))
        latest_profit = net_income.get(latest_period) if latest_period else None
        prior_profit = same_quarter_previous_year(latest_period, net_income) if latest_period else None
        previous_profit = None
        if latest_period:
            previous_year, previous_quarter = previous_calendar_quarter(latest_period)
            previous_profit = next((value for period, value in net_income.items() if period.year == previous_year and ((period.month - 1)//3 + 1) == previous_quarter), None)
        sector = str(info.get("sector") or security.get("sector") or "Unknown")
        industry = str(info.get("industry") or "") or None
        per = decimal_or_none(info.get("trailingPE")); pbv = decimal_or_none(info.get("priceToBook"))
        if per is not None and not (self.configuration.per_min < per <= self.configuration.per_max): per = None
        if pbv is not None and not (self.configuration.pbv_min < pbv <= self.configuration.pbv_max): pbv = None
        roe = decimal_or_none(info.get("returnOnEquity")); roe_percent = roe * 100 if roe is not None else None
        return {
            "security_id": security["id"], "symbol": security["symbol"], "sector": sector, "industry": industry,
            "is_bank": bool(industry and "bank" in industry.lower()), "fundamental_data_as_of": latest_period or date.today(),
            "latest_report_period": latest_period, "currency": info.get("financialCurrency"), "net_income": net_income,
            "net_income_latest": latest_profit, "net_income_prior_year": prior_profit, "net_income_previous_quarter": previous_profit,
            "total_debt": debt.get(max(debt)) if debt else decimal_or_none(info.get("totalDebt")),
            "stockholders_equity": equity.get(max(equity)) if equity else None,
            "roe_percent": roe_percent, "der_percent": decimal_or_none(info.get("debtToEquity")), "per": per, "pbv": pbv,
            "raw_metrics": {"net_income_quarters": {period.isoformat(): str(value) for period, value in net_income.items()},
                            "total_debt_quarters": {period.isoformat(): str(value) for period, value in debt.items()},
                            "equity_quarters": {period.isoformat(): str(value) for period, value in equity.items()}},
        }

    @staticmethod
    def _dated_series(frame: pd.DataFrame, candidates: tuple[str, ...]) -> dict[date, Decimal]:
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return {}
        for candidate in candidates:
            if candidate in frame.index:
                return {pd.Timestamp(period).date(): value for period, raw in frame.loc[candidate].items() if (value := decimal_or_none(raw)) is not None}
        return {}

    @staticmethod
    def _date_from_epoch(value) -> date | None:
        return datetime.fromtimestamp(value, UTC).date() if value else None


class FundamentalJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


@dataclass(slots=True)
class FundamentalJob:
    id: UUID
    status: FundamentalJobStatus = FundamentalJobStatus.QUEUED
    stage: str = "queued"
    stage_index: int = 0
    stage_count: int = 2
    message: str = "Preparing fundamental sync"
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class FundamentalSyncManager:
    def __init__(self, service_factory, coordinator) -> None:
        self.service_factory = service_factory
        self.coordinator = coordinator
        self.jobs: dict[UUID, FundamentalJob] = {}
        self.latest_job_id: UUID | None = None
        self.active_job_id: UUID | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> tuple[FundamentalJob, bool]:
        async with self._lock:
            if self.active_job_id:
                active = self.jobs[self.active_job_id]
                if active.status in {FundamentalJobStatus.QUEUED, FundamentalJobStatus.RUNNING}:
                    return active, False
            job = FundamentalJob(uuid4())
            self.jobs[job.id] = job
            self.latest_job_id = self.active_job_id = job.id
            asyncio.create_task(self._run(job))
            return job, True

    def get(self, job_id: UUID) -> FundamentalJob | None:
        return self.jobs.get(job_id)

    def current(self) -> FundamentalJob | None:
        return self.jobs.get(self.active_job_id or self.latest_job_id) if (self.active_job_id or self.latest_job_id) else None

    async def _run(self, job: FundamentalJob) -> None:
        job.status = FundamentalJobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        job.stage = "fundamentals"
        job.stage_index = 1
        job.message = "Collecting and scoring Yahoo Finance fundamentals"
        try:
            async with self.coordinator.lock():
                job.result = await self.service_factory().update()
            job.stage = "rankings"
            job.stage_index = 2
            job.message = "Fundamental and combined rankings are ready"
            job.status = FundamentalJobStatus.PARTIAL_FAILURE if job.result.get("failed") else FundamentalJobStatus.SUCCEEDED
        except Exception as error:
            job.status = FundamentalJobStatus.FAILED
            job.error = " ".join(str(error).split())[:1000]
            job.message = "Fundamental sync failed"
        finally:
            job.finished_at = datetime.now(UTC)
            async with self._lock:
                if self.active_job_id == job.id:
                    self.active_job_id = None
