import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml


@dataclass(frozen=True, slots=True)
class PositionConfiguration:
    version: str
    strategy_name: str
    strategy_version: str
    strategy_config_checksum: str
    stop_atr_multiple: Decimal
    trailing_atr_multiple: Decimal
    take_profit_1_r_multiple: Decimal
    take_profit_2_r_multiple: Decimal
    partial_fraction: Decimal
    maximum_holding_sessions: int
    buy_fee_rate: Decimal
    sell_fee_rate: Decimal
    checksum: str


def load_position_configuration(path: Path) -> PositionConfiguration:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    strategy = payload["strategy"]
    return PositionConfiguration(
        version=str(payload["version"]),
        strategy_name=str(strategy["name"]),
        strategy_version=str(strategy["version"]),
        strategy_config_checksum=str(strategy["config_checksum"]),
        stop_atr_multiple=Decimal(str(payload["stop_atr_multiple"])),
        trailing_atr_multiple=Decimal(str(payload["trailing_atr_multiple"])),
        take_profit_1_r_multiple=Decimal(str(payload["take_profit_1_r_multiple"])),
        take_profit_2_r_multiple=Decimal(str(payload["take_profit_2_r_multiple"])),
        partial_fraction=Decimal(str(payload["partial_fraction"])),
        maximum_holding_sessions=int(payload["maximum_holding_sessions"]),
        buy_fee_rate=Decimal(str(payload["fees"]["buy_percent"])) / 100,
        sell_fee_rate=Decimal(str(payload["fees"]["sell_percent"])) / 100,
        checksum=hashlib.sha256(canonical.encode()).hexdigest(),
    )
