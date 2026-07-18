from datetime import date
from pathlib import Path

import pytest

from stocks_trading.domain.models import DailyRules
from stocks_trading.scoring.config import (
    ScoringConfigurationError,
    load_scoring_configuration,
)
from stocks_trading.scoring.evaluator import ScoringEvaluationError, calculate_score


def configuration():
    return load_scoring_configuration(Path("config/scoring/technical-v1.yaml"))


def rules(**overrides) -> DailyRules:
    values = {
        "symbol": "BBCA.JK",
        "trading_date": date(2026, 7, 16),
        "price_above_ma5": True,
        "price_above_ma10": True,
        "price_above_ma20": False,
        "ma5_above_ma10": True,
        "ma10_above_ma20": True,
        "volume_spike": True,
        "breakout_20": True,
        "high_liquidity": True,
        "positive_momentum": True,
        "formula_version": "rules-v1",
        "config_checksum": "f6f6f946ea40fd38a7fd70b1a8e2fb4144e0fa09462f19eb812154c548ee7bae",
        "indicator_version": "technical-v2",
    }
    values.update(overrides)
    return DailyRules(**values)


def test_all_weighted_rules_true_scores_100() -> None:
    result = calculate_score(rules(), configuration())

    assert result.score == 100
    assert result.rating == "Strong Buy"
    assert sum(item["awarded"] for item in result.contributions.values()) == 100


def test_all_weighted_rules_false_scores_zero() -> None:
    source = rules(**{name: False for name in configuration().weights})
    result = calculate_score(source, configuration())

    assert result.score == 0
    assert result.rating == "Ignore"


@pytest.mark.parametrize(
    "score,rating",
    [(90, "Strong Buy"), (89, "Buy"), (75, "Buy"), (74, "Watchlist"), (60, "Watchlist"), (59, "Ignore")],
)
def test_rating_boundaries(score: int, rating: str) -> None:
    config = configuration()
    assert next(
        band.name for band in config.ratings if band.minimum <= score <= band.maximum
    ) == rating


def test_null_weighted_rule_makes_score_unavailable() -> None:
    result = calculate_score(rules(volume_spike=None), configuration())

    assert result.score is None
    assert result.rating is None
    assert result.contributions["volume_spike"]["value"] is None


def test_source_identity_must_match() -> None:
    with pytest.raises(ScoringEvaluationError, match="checksum"):
        calculate_score(rules(config_checksum="wrong"), configuration())


def test_config_checksum_stable() -> None:
    assert configuration().checksum == configuration().checksum


def test_invalid_weight_total_rejected(tmp_path: Path) -> None:
    path = tmp_path / "score.yaml"
    path.write_text(
        "version: v1\nsource_rules:\n  formula_version: rules-v1\n  config_checksum: abc\n"
        "weights:\n  price_above_ma5: 10\nratings:\n"
        "  - name: Ignore\n    minimum: 0\n    maximum: 100\n",
        encoding="utf-8",
    )
    with pytest.raises(ScoringConfigurationError, match="total 100"):
        load_scoring_configuration(path)
