from datetime import date
from pathlib import Path

import pytest

from stocks_trading.analysis.config import (
    AnalysisConfigurationError,
    load_analysis_configuration,
)
from stocks_trading.analysis.evaluator import generate_analysis
from stocks_trading.domain.models import AnalysisInput, DailyRanking, DailyRules, StrategyResult


def configuration():
    return load_analysis_configuration(Path("config/analysis/technical-v1.yaml"))


def ranking(score=90, rating="Strong Buy"):
    config = configuration()
    return DailyRanking(
        symbol="BBCA.JK", trading_date=date(2026, 7, 16), rank=1,
        score=score, rating=rating,
        ranking_version=config.source_versions["ranking_version"],
        ranking_config_checksum=config.source_versions["ranking_config_checksum"],
        source_scoring_version=config.source_versions["scoring_version"],
        source_scoring_config_checksum=config.source_versions["scoring_config_checksum"],
    )


def rules(**overrides):
    config = configuration()
    values = dict(
        price_above_ma5=True, price_above_ma10=True, price_above_ma20=True,
        ma5_above_ma10=True, ma10_above_ma20=True, volume_spike=True,
        breakout_20=True, high_liquidity=True, positive_momentum=True,
    )
    values.update(overrides)
    return DailyRules(
        symbol="BBCA.JK", trading_date=date(2026, 7, 16),
        formula_version=config.source_versions["rule_formula_version"],
        config_checksum=config.source_versions["rule_config_checksum"],
        indicator_version=config.source_versions["indicator_version"], **values,
    )


def strategy(passed):
    config = configuration()
    return StrategyResult(
        symbol="BBCA.JK", trading_date=date(2026, 7, 16),
        strategy_name=config.source_versions["strategy_name"], strategy_version=config.source_versions["strategy_version"],
        strategy_config_checksum=config.source_versions["strategy_config_checksum"],
        passed=passed, evaluation_details={}, source_rule_formula_version=config.source_versions["rule_formula_version"],
        source_rule_config_checksum=config.source_versions["rule_config_checksum"],
    )


def test_deterministic_reason_order_and_strategy_status() -> None:
    result = generate_analysis(
        AnalysisInput(ranking=ranking(), indicators=None, rules=rules(), strategy=strategy(True)),
        configuration(),
    )
    assert result.bullish_reasons[:4] == (
        "Price is above SMA5.", "Price is above SMA10.",
        "SMA5 is above SMA10.", "SMA10 is above SMA20.",
    )
    assert result.strategy_status == "passed"
    assert "ranked #1" in result.narrative


def test_missing_sources_are_explicit_and_never_block_output() -> None:
    result = generate_analysis(
        AnalysisInput(ranking=ranking(60, "Watchlist"), indicators=None, rules=None, strategy=None),
        configuration(),
    )
    assert result.source_availability["rules"] is False
    assert result.strategy_status == "unavailable"
    assert "Rule evaluation is unavailable" in result.narrative


def test_below_threshold_rejected() -> None:
    with pytest.raises(ValueError, match="threshold"):
        generate_analysis(
            AnalysisInput(ranking=ranking(59, "Ignore"), indicators=None, rules=None, strategy=None),
            configuration(),
        )


def test_non_english_config_rejected(tmp_path: Path) -> None:
    text = Path("config/analysis/technical-v1.yaml").read_text().replace("language: en", "language: id")
    path = tmp_path / "analysis.yaml"
    path.write_text(text)
    with pytest.raises(AnalysisConfigurationError, match="English"):
        load_analysis_configuration(path)
