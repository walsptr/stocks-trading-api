import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml


class RiskConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RiskConfiguration:
    version: str
    indicator_version: str
    ranking_version: str
    ranking_config_checksum: str
    minimum_score: int
    stop_atr_multiple: Decimal
    target_atr_multiple: Decimal
    take_profit_1_r_multiple: Decimal
    take_profit_2_r_multiple: Decimal
    account_risk_pct: Decimal
    position_cap_pct: Decimal
    disclaimer: str
    checksum: str


def load_risk_configuration(path: Path) -> RiskConfiguration:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise RiskConfigurationError(f"unable to load risk configuration: {error}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), dict):
        raise RiskConfigurationError("risk configuration and sources are required")
    try:
        stop = Decimal(str(payload["stop_atr_multiple"]))
        target = Decimal(str(payload["target_atr_multiple"]))
        target_1 = Decimal(str(payload["take_profit_1_r_multiple"]))
        target_2 = Decimal(str(payload["take_profit_2_r_multiple"]))
        account_risk = Decimal(str(payload["account_risk_pct"]))
        position_cap = Decimal(str(payload["position_cap_pct"]))
    except (KeyError, InvalidOperation) as error:
        raise RiskConfigurationError("ATR multiples must be valid decimals") from error
    minimum_score = payload.get("minimum_score")
    if not isinstance(minimum_score, int) or not 0 <= minimum_score <= 100:
        raise RiskConfigurationError("minimum_score must be between 0 and 100")
    if stop <= 0 or target <= 0 or target_1 <= 0 or target_2 <= 0 or account_risk <= 0 or position_cap <= 0:
        raise RiskConfigurationError("ATR multiples must be positive")
    sources = payload["sources"]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return RiskConfiguration(
        version=_required(payload, "version"),
        indicator_version=_required(sources, "indicator_version"),
        ranking_version=_required(sources, "ranking_version"),
        ranking_config_checksum=_required(sources, "ranking_config_checksum"),
        minimum_score=minimum_score,
        stop_atr_multiple=stop,
        target_atr_multiple=target,
        take_profit_1_r_multiple=target_1,
        take_profit_2_r_multiple=target_2,
        account_risk_pct=account_risk,
        position_cap_pct=position_cap,
        disclaimer=_required(payload, "disclaimer"),
        checksum=hashlib.sha256(canonical.encode()).hexdigest(),
    )


def _required(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RiskConfigurationError(f"{key} must be a non-empty string")
    return value.strip()
