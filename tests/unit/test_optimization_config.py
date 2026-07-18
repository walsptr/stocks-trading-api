from pathlib import Path

import pytest

from stocks_trading.optimization.config import (
    OptimizationConfigurationError,
    load_optimization_configuration,
)
from stocks_trading.optimization.evaluator import candidate_identity


def test_configuration_builds_exactly_24_stable_unique_candidates() -> None:
    configuration = load_optimization_configuration(
        Path("config/optimization/bsjp-v1.yaml")
    )
    candidates = configuration.candidates()
    identities = [candidate_identity(item) for item in candidates]

    assert len(candidates) == 24
    assert len(set(identities)) == 24
    assert identities == [candidate_identity(item) for item in candidates]


def test_configuration_rejects_non_grid_method(tmp_path: Path) -> None:
    path = tmp_path / "optimizer.yaml"
    path.write_text("method: random_search\n", encoding="utf-8")

    with pytest.raises(OptimizationConfigurationError, match="grid_search"):
        load_optimization_configuration(path)
