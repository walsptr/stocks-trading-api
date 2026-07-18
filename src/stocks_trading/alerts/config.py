import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml


class AlertConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AlertConfiguration:
    version: str
    minimum_score: int
    maximum_attempts: int
    retry_base_seconds: float
    triggers: tuple[str, ...]
    source_versions: dict[str, str]
    checksum: str


def load_alert_configuration(path: Path) -> AlertConfiguration:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise AlertConfigurationError(f"unable to load alert configuration: {error}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), dict):
        raise AlertConfigurationError("alert configuration and sources are required")
    triggers = payload.get("triggers")
    if not isinstance(triggers, list) or not triggers:
        raise AlertConfigurationError("triggers are required")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return AlertConfiguration(
        version=required_string(payload, "version"),
        minimum_score=required_int(payload, "minimum_score", 0),
        maximum_attempts=required_int(payload, "maximum_attempts", 1),
        retry_base_seconds=float(payload.get("retry_base_seconds", 1.0)),
        triggers=tuple(str(item) for item in triggers),
        source_versions={key: required_string(payload["sources"], key) for key in (
            "analysis_version", "analysis_config_checksum",
            "rule_formula_version", "rule_config_checksum",
        )},
        checksum=hashlib.sha256(canonical.encode()).hexdigest(),
    )


def required_string(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AlertConfigurationError(f"{key} must be a non-empty string")
    return value.strip()


def required_int(payload: dict, key: str, minimum: int) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or value < minimum:
        raise AlertConfigurationError(f"{key} must be at least {minimum}")
    return value
