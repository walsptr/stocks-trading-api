from __future__ import annotations

from datetime import date
from decimal import Decimal

from .config import CORE_RULES, FundamentalConfiguration


def decimal_or_none(value) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except Exception:
        return None


def same_quarter_previous_year(latest: date, candidates: dict[date, Decimal]) -> Decimal | None:
    return next((value for period, value in candidates.items()
                 if period.year == latest.year - 1 and period.month == latest.month), None)


def previous_calendar_quarter(period: date) -> tuple[int, int]:
    quarter = (period.month - 1) // 3 + 1
    return (period.year - 1, 4) if quarter == 1 else (period.year, quarter - 1)


def percentile(values: list[Decimal], percentage: Decimal) -> Decimal | None:
    ordered = sorted(values)
    if not ordered:
        return None
    position = (Decimal(len(ordered) - 1) * percentage / Decimal(100))
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def valuation_thresholds(records: list[dict], configuration: FundamentalConfiguration) -> dict[str, dict[str, Decimal | None]]:
    valid_per = [item["per"] for item in records if item["per"] is not None]
    valid_pbv = [item["pbv"] for item in records if item["pbv"] is not None]
    global_values = {
        "per": percentile(valid_per, configuration.valuation_percentile),
        "pbv": percentile(valid_pbv, configuration.valuation_percentile),
    }
    result = {}
    for sector in {item["sector"] for item in records}:
        sector_records = [item for item in records if item["sector"] == sector]
        sector_per = [item["per"] for item in sector_records if item["per"] is not None]
        sector_pbv = [item["pbv"] for item in sector_records if item["pbv"] is not None]
        result[sector] = {
            "per": percentile(sector_per, configuration.valuation_percentile)
            if len(sector_per) >= configuration.sector_min_observations else global_values["per"],
            "pbv": percentile(sector_pbv, configuration.valuation_percentile)
            if len(sector_pbv) >= configuration.sector_min_observations else global_values["pbv"],
        }
    return result


def evaluate(record: dict, thresholds: dict[str, Decimal | None], configuration: FundamentalConfiguration) -> dict:
    net_income = record["net_income"]
    latest_period = max(net_income) if net_income else None
    latest_profit = net_income.get(latest_period) if latest_period else None
    prior_year_profit = same_quarter_previous_year(latest_period, net_income) if latest_period else None
    previous_key = previous_calendar_quarter(latest_period) if latest_period else None
    previous_profit = next((value for period, value in net_income.items()
                            if ((period.month - 1) // 3 + 1, period.year) == (previous_key[1], previous_key[0])), None) if previous_key else None
    is_bank = record["is_bank"]
    roe = record["roe_percent"]
    der = record["der_percent"]
    rules = {
        "positive_net_profit": latest_profit > 0 if latest_profit is not None else None,
        "profit_growth_yoy": latest_profit > prior_year_profit if latest_profit is not None and prior_year_profit is not None else None,
        "healthy_roe": roe > configuration.healthy_roe_percent if roe is not None else None,
        "manageable_der": None if is_bank else (der < configuration.manageable_der_percent if der is not None else None),
        "no_consecutive_losses": not (latest_profit < 0 and previous_profit < 0)
        if latest_profit is not None and previous_profit is not None else None,
        "reasonable_valuation": (
            record["per"] <= thresholds["per"] and record["pbv"] <= thresholds["pbv"]
            if record["per"] is not None and record["pbv"] is not None
            and thresholds["per"] is not None and thresholds["pbv"] is not None else None
        ),
        "not_delisting_watch": None,
    }
    applicable = [name for name in CORE_RULES if not (is_bank and name == "manageable_der")]
    available = [name for name in applicable if rules[name] is not None]
    if len(available) < configuration.minimum_available_core_rules:
        status, score = "insufficient_data", None
    else:
        status = "complete" if len(available) == len(applicable) else "partial"
        denominator = sum(configuration.weights[name] for name in available)
        core = sum(configuration.weights[name] for name in available if rules[name]) / denominator * 100
        score = min(Decimal(100), core + (configuration.valuation_bonus if rules["reasonable_valuation"] is True else 0))
    red_flagged = rules["no_consecutive_losses"] is False
    rule_metadata = {
        name: {"value": value, "status": "not_applicable" if is_bank and name == "manageable_der" else
               "data_unavailable" if value is None else "available"}
        for name, value in rules.items()
    }
    return {
        "fundamental_score": score, "data_status": status,
        "available_core_rules": len(available), "applicable_core_rules": len(applicable),
        "rule_values": rules, "rule_metadata": rule_metadata,
        "is_red_flagged": red_flagged,
        "red_flag_reasons": ["Net loss recorded in two consecutive reported quarters"] if red_flagged else [],
    }
