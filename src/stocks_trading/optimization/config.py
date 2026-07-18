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
    parameter_grid: tuple[dict[str, object], ...]
    backtest_config_path: Path
    checksum: str
    enabled: bool = True
    default: bool = False

    def candidates(self) -> tuple[dict[str, object], ...]:
        return self.parameter_grid


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
    legacy_keys = ("volume_spike_ratios", "liquidity_thresholds", "require_breakout", "require_volume_spike")
    swing_keys = ("pullback_tolerances", "rsi_overbought_thresholds", "volume_confirmation_ratios", "require_ma50_above_ma200")
    selected_keys = legacy_keys if all(key in parameters for key in legacy_keys) else swing_keys
    for key in selected_keys:
        if not isinstance(parameters.get(key), list) or not parameters[key]:
            raise OptimizationConfigurationError(f"parameters.{key} must be a non-empty list")
    expected_candidates = 1
    for key in selected_keys:
        expected_candidates *= len(parameters[key])
    if expected_candidates != 24:
        raise OptimizationConfigurationError("optimizer grid must contain exactly 24 candidates")
    enabled = bool(payload.get("enabled", True))
    default = bool(payload.get("default", False))
    if default and not enabled:
        raise OptimizationConfigurationError("disabled optimization configuration cannot be default")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    def normalize(key, value):
        return bool(value) if key.startswith("require_") else str(value)
    parameter_grid = tuple(
        {key.removesuffix("s"): normalize(key, value) for key, value in zip(selected_keys, values)}
        for values in product(*(parameters[key] for key in selected_keys))
    )
    return OptimizationConfiguration(
        version=payload["version"], indicator_version=payload["indicator_version"],
        training_fraction=training_fraction,
        minimum_validation_trades=minimum_trades,
        parameter_grid=parameter_grid,
        backtest_config_path=Path(payload["backtest_config"]),
        checksum=hashlib.sha256(canonical.encode()).hexdigest(),
        enabled=enabled,
        default=default,
    )
