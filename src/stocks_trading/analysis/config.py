import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml


class AnalysisConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AnalysisConfiguration:
    version: str
    language: str
    minimum_score: int
    source_versions: dict[str, str]
    disclaimer: str
    checksum: str


def load_analysis_configuration(path: Path) -> AnalysisConfiguration:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise AnalysisConfigurationError(
            f"unable to load analysis configuration: {error}"
        ) from error
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), dict):
        raise AnalysisConfigurationError("analysis configuration and sources are required")
    if payload.get("language") != "en":
        raise AnalysisConfigurationError("only English analysis is supported")
    minimum_score = payload.get("minimum_score")
    if not isinstance(minimum_score, int) or not 0 <= minimum_score <= 100:
        raise AnalysisConfigurationError("minimum_score must be between 0 and 100")
    source_keys = (
        "indicator_version", "rule_formula_version", "rule_config_checksum",
        "strategy_name", "strategy_version", "strategy_config_checksum",
        "scoring_version", "scoring_config_checksum", "ranking_version",
        "ranking_config_checksum",
    )
    sources = {key: required_string(payload["sources"], key) for key in source_keys}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return AnalysisConfiguration(
        version=required_string(payload, "version"),
        language="en",
        minimum_score=minimum_score,
        source_versions=sources,
        disclaimer=required_string(payload, "disclaimer"),
        checksum=hashlib.sha256(canonical.encode()).hexdigest(),
    )


def required_string(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AnalysisConfigurationError(f"{key} must be a non-empty string")
    return value.strip()
