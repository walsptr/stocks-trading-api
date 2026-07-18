import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from stocks_trading.persistence.repositories import RULE_BOOLEAN_FIELDS


class ScoringConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RatingBand:
    name: str
    minimum: int
    maximum: int


@dataclass(frozen=True, slots=True)
class ScoringConfiguration:
    version: str
    source_rule_formula_version: str
    source_rule_config_checksum: str
    weights: dict[str, int]
    ratings: tuple[RatingBand, ...]
    maximum_score: int
    checksum: str


def load_scoring_configuration(path: Path) -> ScoringConfiguration:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ScoringConfigurationError(f"unable to load scoring configuration: {error}") from error
    if not isinstance(payload, dict):
        raise ScoringConfigurationError("scoring configuration must be an object")
    source = payload.get("source_rules")
    weights = payload.get("weights")
    ratings = payload.get("ratings")
    if not isinstance(source, dict) or not isinstance(weights, dict) or not isinstance(ratings, list):
        raise ScoringConfigurationError("source_rules, weights, and ratings are required")
    unknown = set(weights) - set(RULE_BOOLEAN_FIELDS)
    if unknown:
        raise ScoringConfigurationError(f"unknown weighted rules: {', '.join(sorted(unknown))}")
    normalized_weights = {}
    for name, value in weights.items():
        if not isinstance(value, int) or value <= 0:
            raise ScoringConfigurationError("weights must be positive integers")
        normalized_weights[name] = value
    maximum = sum(normalized_weights.values())
    if maximum != 100:
        raise ScoringConfigurationError("weights must total 100")
    bands = tuple(parse_band(item) for item in ratings)
    covered = [0] * 101
    for band in bands:
        if band.minimum < 0 or band.maximum > 100 or band.minimum > band.maximum:
            raise ScoringConfigurationError("invalid rating range")
        for score in range(band.minimum, band.maximum + 1):
            covered[score] += 1
    if any(value != 1 for value in covered):
        raise ScoringConfigurationError("rating bands must cover 0-100 exactly once")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return ScoringConfiguration(
        version=required_string(payload, "version"),
        source_rule_formula_version=required_string(source, "formula_version"),
        source_rule_config_checksum=required_string(source, "config_checksum"),
        weights=normalized_weights,
        ratings=bands,
        maximum_score=maximum,
        checksum=hashlib.sha256(canonical.encode()).hexdigest(),
    )


def parse_band(payload) -> RatingBand:
    if not isinstance(payload, dict):
        raise ScoringConfigurationError("rating band must be an object")
    name = required_string(payload, "name")
    minimum = payload.get("minimum")
    maximum = payload.get("maximum")
    if not isinstance(minimum, int) or not isinstance(maximum, int):
        raise ScoringConfigurationError("rating limits must be integers")
    return RatingBand(name, minimum, maximum)


def required_string(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ScoringConfigurationError(f"{key} must be a non-empty string")
    return value.strip()
