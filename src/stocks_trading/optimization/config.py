import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from itertools import product
from pathlib import Path

import yaml


class OptimizationConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OptimizationConfiguration:
    version: str
    indicator_version: str
    training_fraction: Decimal
    minimum_validation_trades: int
    volume_ratios: tuple[Decimal, ...]
    liquidity_thresholds: tuple[Decimal, ...]
    breakout_values: tuple[bool, ...]
    volume_required_values: tuple[bool, ...]
    backtest_config_path: Path
    checksum: str

    def candidates(self) -> tuple[dict[str, object], ...]:
        return tuple({
            "volume_spike_ratio": str(volume),
            "liquidity_threshold": str(liquidity),
            "require_breakout": breakout,
            "require_volume_spike": volume_required,
        } for volume, liquidity, breakout, volume_required in product(
            self.volume_ratios, self.liquidity_thresholds,
            self.breakout_values, self.volume_required_values,
        ))


def load_optimization_configuration(path: Path) -> OptimizationConfiguration:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise OptimizationConfigurationError(
            f"unable to load optimization configuration: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise OptimizationConfigurationError("optimization configuration must be an object")
    if payload.get("method") != "grid_search":
        raise OptimizationConfigurationError("only grid_search optimization is supported")
    split = payload.get("split")
    selection = payload.get("selection")
    parameters = payload.get("parameters")
    if not isinstance(split, dict) or not isinstance(selection, dict) or not isinstance(parameters, dict):
        raise OptimizationConfigurationError("split, selection, and parameters are required")
    training_fraction = Decimal(str(split.get("training_fraction")))
    if not Decimal("0") < training_fraction < Decimal("1"):
        raise OptimizationConfigurationError("training_fraction must be between 0 and 1")
    if selection.get("objective") != "validation_sharpe":
        raise OptimizationConfigurationError("objective must be validation_sharpe")
    minimum_trades = int(selection.get("minimum_validation_trades", 0))
    if minimum_trades < 1:
        raise OptimizationConfigurationError("minimum_validation_trades must be positive")
    for key in ("volume_spike_ratios", "liquidity_thresholds", "require_breakout", "require_volume_spike"):
        if not isinstance(parameters.get(key), list) or not parameters[key]:
            raise OptimizationConfigurationError(f"parameters.{key} must be a non-empty list")
    expected_candidates = (
        len(parameters["volume_spike_ratios"])
        * len(parameters["liquidity_thresholds"])
        * len(parameters["require_breakout"])
        * len(parameters["require_volume_spike"])
    )
    if expected_candidates != 24:
        raise OptimizationConfigurationError("optimizer grid must contain exactly 24 candidates")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return OptimizationConfiguration(
        version=payload["version"], indicator_version=payload["indicator_version"],
        training_fraction=training_fraction,
        minimum_validation_trades=minimum_trades,
        volume_ratios=tuple(Decimal(item) for item in parameters["volume_spike_ratios"]),
        liquidity_thresholds=tuple(Decimal(item) for item in parameters["liquidity_thresholds"]),
        breakout_values=tuple(parameters["require_breakout"]),
        volume_required_values=tuple(parameters["require_volume_spike"]),
        backtest_config_path=Path(payload["backtest_config"]),
        checksum=hashlib.sha256(canonical.encode()).hexdigest(),
    )
