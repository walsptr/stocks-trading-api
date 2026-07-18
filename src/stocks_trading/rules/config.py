import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml


class RuleConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RuleConfiguration:
    formula_version: str
    indicator_version: str
    volume_spike_ratio: Decimal
    high_liquidity_average_traded_value: Decimal
    checksum: str
    pullback_tolerance: Decimal = Decimal("0.03")
    volume_confirmation_ratio: Decimal = Decimal("1.0")


def load_rule_configuration(path: Path) -> RuleConfiguration:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise RuleConfigurationError(f"unable to load rule configuration: {error}") from error
    if not isinstance(payload, dict):
        raise RuleConfigurationError("rule configuration must be an object")
    thresholds = payload.get("thresholds")
    if not isinstance(thresholds, dict):
        raise RuleConfigurationError("thresholds must be an object")
    formula_version = required_string(payload, "formula_version")
    indicator_version = required_string(payload, "indicator_version")
    volume_spike_ratio = required_decimal(thresholds, "volume_spike_ratio")
    liquidity = required_decimal(
        thresholds, "high_liquidity_average_traded_value"
    )
    pullback_tolerance = required_decimal(thresholds, "pullback_to_ma20_tolerance", Decimal("0.03"))
    volume_confirmation_ratio = required_decimal(thresholds, "volume_confirmation_ratio", Decimal("1.0"))
    if volume_spike_ratio <= 0 or liquidity < 0 or pullback_tolerance < 0 or volume_confirmation_ratio <= 0:
        raise RuleConfigurationError("rule thresholds must be positive")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return RuleConfiguration(
        formula_version=formula_version,
        indicator_version=indicator_version,
        volume_spike_ratio=volume_spike_ratio,
        high_liquidity_average_traded_value=liquidity,
        pullback_tolerance=pullback_tolerance,
        volume_confirmation_ratio=volume_confirmation_ratio,
        checksum=hashlib.sha256(canonical.encode()).hexdigest(),
    )


def required_string(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuleConfigurationError(f"{key} must be a non-empty string")
    return value.strip()


def required_decimal(payload: dict, key: str, default: Decimal | None = None) -> Decimal:
    value = payload.get(key, default)
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError) as error:
        raise RuleConfigurationError(f"{key} must be numeric") from error
