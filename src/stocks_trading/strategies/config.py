import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from stocks_trading.persistence.repositories import RULE_BOOLEAN_FIELDS


class StrategyConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StrategyConfiguration:
    name: str
    version: str
    description: str
    source_rule_formula_version: str
    source_rule_config_checksum: str
    required_rules: tuple[str, ...]
    checksum: str
    enabled: bool = True
    default: bool = False
    holding_period: str = ""
    exit_rules: tuple[str, ...] = ()
    strict_trend_filter: bool = True


def load_strategy_configuration(path: Path) -> StrategyConfiguration:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise StrategyConfigurationError(f"unable to load strategy configuration: {error}") from error
    if not isinstance(payload, dict):
        raise StrategyConfigurationError("strategy configuration must be an object")
    source = payload.get("source_rules")
    rules = payload.get("required_rules")
    if not isinstance(source, dict):
        raise StrategyConfigurationError("source_rules must be an object")
    if not isinstance(rules, list) or not rules:
        raise StrategyConfigurationError("required_rules must be a non-empty list")
    required_rules = tuple(str(item) for item in rules)
    unknown = set(required_rules) - set(RULE_BOOLEAN_FIELDS)
    if unknown:
        raise StrategyConfigurationError(f"unknown required rules: {', '.join(sorted(unknown))}")
    if len(set(required_rules)) != len(required_rules):
        raise StrategyConfigurationError("required_rules must not contain duplicates")
    enabled = bool(payload.get("enabled", True))
    default = bool(payload.get("default", False))
    if default and not enabled:
        raise StrategyConfigurationError("disabled strategy configuration cannot be default")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return StrategyConfiguration(
        name=required_string(payload, "name"),
        version=required_string(payload, "version"),
        description=required_string(payload, "description"),
        source_rule_formula_version=required_string(source, "formula_version"),
        source_rule_config_checksum=required_string(source, "config_checksum"),
        required_rules=required_rules,
        checksum=hashlib.sha256(canonical.encode()).hexdigest(),
        enabled=enabled,
        default=default,
        holding_period=str(payload.get("holding_period", "")),
        exit_rules=tuple(str(item) for item in payload.get("exit_rules", [])),
        strict_trend_filter=bool(payload.get("strict_trend_filter", True)),
    )


def required_string(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise StrategyConfigurationError(f"{key} must be a non-empty string")
    return value.strip()
