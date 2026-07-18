from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from stocks_trading.domain.models import DailyRanking, RiskInput
from stocks_trading.risk.config import load_risk_configuration
from stocks_trading.risk.evaluator import generate_recommendation, idx_tick_size


@pytest.fixture
def configuration():
    return load_risk_configuration(Path("config/risk/technical-v1.yaml"))


def ranking(score=80):
    return DailyRanking(
        symbol="BBCA.JK", trading_date=date(2026, 7, 17), rank=1, score=score,
        rating="Buy", ranking_version="technical-ranking-v1",
        ranking_config_checksum="checksum", source_scoring_version="technical-score-v1",
        source_scoring_config_checksum="score-checksum",
    )


def test_generates_conservative_atr_levels(configuration):
    result = generate_recommendation(
        RiskInput(ranking(), Decimal("1000"), Decimal("20")), configuration
    )

    assert result.entry_price == Decimal("1000")
    assert result.stop_loss == Decimal("970")
    assert result.take_profit == Decimal("1060")
    assert result.take_profit_1 == Decimal("1045")
    assert result.take_profit_2 == Decimal("1060")
    assert result.reward_risk_ratio == Decimal("2")
    assert result.suggested_position_size_pct == Decimal("5")
    assert result.stop_loss < result.entry_price < result.take_profit


def test_skips_below_threshold(configuration):
    with pytest.raises(ValueError, match="below the risk threshold"):
        generate_recommendation(
            RiskInput(ranking(59), Decimal("1000"), Decimal("20")), configuration
        )


def test_rejects_missing_atr(configuration):
    with pytest.raises(ValueError, match="ATR is unavailable"):
        generate_recommendation(RiskInput(ranking(), Decimal("1000"), None), configuration)


def test_idx_tick_bands():
    assert idx_tick_size(Decimal("199")) == Decimal("1")
    assert idx_tick_size(Decimal("200")) == Decimal("2")
    assert idx_tick_size(Decimal("500")) == Decimal("5")
    assert idx_tick_size(Decimal("2000")) == Decimal("10")
    assert idx_tick_size(Decimal("5000")) == Decimal("25")
