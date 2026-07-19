from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml


TIERS = ("high", "medium", "low")


class LiquidityConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LiquidityConfiguration:
    version: str
    indicator_version: str
    thresholds: dict[str, Decimal]

    def tier(self, turnover: Decimal | None) -> str | None:
        if turnover is None:
            return None
        for tier in TIERS:
            if turnover >= self.thresholds[tier]:
                return tier
        return "low"


def load_liquidity_configuration(path: Path) -> LiquidityConfiguration:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise LiquidityConfigurationError(f"unable to load liquidity configuration: {error}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("tiers"), dict):
        raise LiquidityConfigurationError("liquidity configuration and tiers are required")
    try:
        thresholds = {
            tier: Decimal(str(payload["tiers"][tier]["min_turnover"])) for tier in TIERS
        }
    except (KeyError, TypeError, InvalidOperation) as error:
        raise LiquidityConfigurationError("all liquidity tier thresholds must be valid decimals") from error
    if thresholds["high"] <= thresholds["medium"] or thresholds["medium"] <= thresholds["low"] or thresholds["low"] < 0:
        raise LiquidityConfigurationError("liquidity thresholds must descend from high to low")
    version = payload.get("version")
    indicator_version = payload.get("indicator_version")
    if not isinstance(version, str) or not version or not isinstance(indicator_version, str) or not indicator_version:
        raise LiquidityConfigurationError("version and indicator_version are required")
    return LiquidityConfiguration(version, indicator_version, thresholds)
