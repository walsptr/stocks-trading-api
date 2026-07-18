import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml


class BacktestConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BacktestConfiguration:
    version: str
    strategy_name: str
    strategy_version: str
    strategy_config_checksum: str
    buy_fee_rate: Decimal
    sell_fee_rate: Decimal
    notional: Decimal
    sharpe_periods: int
    checksum: str
    execution_model: str = "legacy_next_open"
    lifecycle_config_path: Path | None = None


def load_backtest_configuration(path: Path) -> BacktestConfiguration:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise BacktestConfigurationError(f"unable to load backtest configuration: {error}") from error
    strategy = payload.get("strategy", {}) if isinstance(payload, dict) else {}
    execution = payload.get("execution", {}) if isinstance(payload, dict) else {}
    fees = payload.get("fees", {}) if isinstance(payload, dict) else {}
    metrics = payload.get("metrics", {}) if isinstance(payload, dict) else {}
    legacy_execution = {"entry": "signal_close", "exit": "next_session_open", "price_basis": "raw", "allow_overlapping_positions": False}
    swing_execution = {"entry": "next_session_open", "exit": "swing_lifecycle", "price_basis": "raw", "allow_overlapping_positions": False}
    if execution not in (legacy_execution, swing_execution):
        raise BacktestConfigurationError("unsupported execution model")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return BacktestConfiguration(
        version=required_string(payload, "version"),
        strategy_name=required_string(strategy, "name"),
        strategy_version=required_string(strategy, "version"),
        strategy_config_checksum=required_string(strategy, "config_checksum"),
        buy_fee_rate=Decimal(str(fees["buy_percent"])) / 100,
        sell_fee_rate=Decimal(str(fees["sell_percent"])) / 100,
        notional=Decimal(str(metrics["notional"])),
        sharpe_periods=int(metrics["sharpe_periods"]),
        checksum=hashlib.sha256(canonical.encode()).hexdigest(),
        execution_model="swing_lifecycle" if execution == swing_execution else "legacy_next_open",
        lifecycle_config_path=Path(payload["lifecycle_config"]) if payload.get("lifecycle_config") else None,
    )


def required_string(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BacktestConfigurationError(f"{key} must be a non-empty string")
    return value.strip()
