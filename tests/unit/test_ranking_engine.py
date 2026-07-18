from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from stocks_trading.domain.models import TechnicalScore
from stocks_trading.ranking.config import (
    RankingConfigurationError,
    load_ranking_configuration,
)
from stocks_trading.ranking.evaluator import RankingEvaluationError, rank_scores


def configuration():
    return load_ranking_configuration(Path("config/ranking/technical-v1.yaml"))


def score(symbol: str, value: int | None, rating: str | None = "Buy") -> TechnicalScore:
    config = configuration()
    return TechnicalScore(
        symbol=symbol,
        trading_date=date(2026, 7, 16),
        scoring_version=config.source_scoring_version,
        scoring_config_checksum=config.source_scoring_config_checksum,
        score=value,
        rating=rating if value is not None else None,
        contributions={},
        source_rule_formula_version="rules-v1",
        source_rule_config_checksum="rules-checksum",
    )


def test_competition_ranking_excludes_null_scores() -> None:
    rankings = rank_scores(
        [
            (score("TLKM.JK", 90), None),
            (score("BBCA.JK", 90), None),
            (score("ASII.JK", 80), None),
            (score("NULL.JK", None), None),
        ],
        configuration(),
    )

    assert [(item.symbol, item.rank, item.score) for item in rankings] == [
        ("BBCA.JK", 1, 90),
        ("TLKM.JK", 1, 90),
        ("ASII.JK", 3, 80),
    ]


def test_source_identity_must_match() -> None:
    invalid = score("BBCA.JK", 90)
    invalid = replace(invalid, scoring_config_checksum="wrong")
    with pytest.raises(RankingEvaluationError, match="checksum"):
        rank_scores([(invalid, None)], configuration())


def test_invalid_ordering_rejected(tmp_path: Path) -> None:
    path = tmp_path / "ranking.yaml"
    path.write_text(
        "version: v1\nsource_scores:\n  scoring_version: score-v1\n  config_checksum: abc\n"
        "eligibility:\n  require_non_null_score: true\n"
        "ordering:\n  score: ascending\n  tie_method: competition\n"
        "  tie_display: symbol_ascending\n",
        encoding="utf-8",
    )
    with pytest.raises(RankingConfigurationError, match="ordering"):
        load_ranking_configuration(path)
