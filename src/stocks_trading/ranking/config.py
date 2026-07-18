import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml


class RankingConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RankingConfiguration:
    version: str
    source_scoring_version: str
    source_scoring_config_checksum: str
    checksum: str


def load_ranking_configuration(path: Path) -> RankingConfiguration:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise RankingConfigurationError(
            f"unable to load ranking configuration: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise RankingConfigurationError("ranking configuration must be an object")
    source = payload.get("source_scores")
    eligibility = payload.get("eligibility")
    ordering = payload.get("ordering")
    if not isinstance(source, dict):
        raise RankingConfigurationError("source_scores is required")
    if eligibility != {"require_non_null_score": True}:
        raise RankingConfigurationError("ranking must require non-null scores")
    if ordering != {
        "score": "descending",
        "tie_method": "competition",
        "tie_display": "symbol_ascending",
    }:
        raise RankingConfigurationError("unsupported ranking ordering")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return RankingConfiguration(
        version=required_string(payload, "version"),
        source_scoring_version=required_string(source, "scoring_version"),
        source_scoring_config_checksum=required_string(source, "config_checksum"),
        checksum=hashlib.sha256(canonical.encode()).hexdigest(),
    )


def required_string(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RankingConfigurationError(f"{key} must be a non-empty string")
    return value.strip()
