from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import yaml

CORE_RULES = (
    "positive_net_profit",
    "profit_growth_yoy",
    "healthy_roe",
    "manageable_der",
    "no_consecutive_losses",
)


@dataclass(frozen=True, slots=True)
class FundamentalConfiguration:
    version: str
    provider: str
    checksum: str
    healthy_roe_percent: Decimal
    manageable_der_percent: Decimal
    per_min: Decimal
    per_max: Decimal
    pbv_min: Decimal
    pbv_max: Decimal
    valuation_percentile: Decimal
    sector_min_observations: int
    minimum_available_core_rules: int
    weights: dict[str, Decimal]
    valuation_bonus: Decimal
    technical_weight: Decimal
    fundamental_weight: Decimal


def load_fundamental_configuration(path: Path) -> FundamentalConfiguration:
    content = path.read_bytes()
    payload = yaml.safe_load(content)
    thresholds = payload["thresholds"]
    weights = {name: Decimal(str(payload["weights"][name])) for name in CORE_RULES}
    combined = payload["combined_weights"]
    technical_weight = Decimal(str(combined["technical"]))
    fundamental_weight = Decimal(str(combined["fundamental"]))
    if sum(weights.values()) != 100:
        raise ValueError("fundamental core weights must total 100")
    if technical_weight + fundamental_weight != 100:
        raise ValueError("combined weights must total 100")
    return FundamentalConfiguration(
        version=str(payload["version"]), provider=str(payload["provider"]),
        checksum=sha256(content).hexdigest(),
        healthy_roe_percent=Decimal(str(thresholds["healthy_roe_percent"])),
        manageable_der_percent=Decimal(str(thresholds["manageable_der_percent"])),
        per_min=Decimal(str(thresholds["per_min"])), per_max=Decimal(str(thresholds["per_max"])),
        pbv_min=Decimal(str(thresholds["pbv_min"])), pbv_max=Decimal(str(thresholds["pbv_max"])),
        valuation_percentile=Decimal(str(thresholds["valuation_percentile"])),
        sector_min_observations=int(thresholds["sector_min_observations"]),
        minimum_available_core_rules=int(payload["completeness"]["minimum_available_core_rules"]),
        weights=weights, valuation_bonus=Decimal(str(payload["valuation_bonus"])),
        technical_weight=technical_weight, fundamental_weight=fundamental_weight,
    )
