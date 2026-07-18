from datetime import date
from pathlib import Path

from stocks_trading.alerts.config import load_alert_configuration
from stocks_trading.alerts.evaluator import build_alert
from stocks_trading.domain.models import AlertSourceState


def config():
    return load_alert_configuration(Path("config/alerts/technical-v1.yaml"))


def state(**changes):
    values = dict(
        symbol="BBCA.JK", trading_date=date(2026, 7, 16), score=95,
        rating="Strong Buy", rank=1, strategy_status="passed",
        breakout_20=True, volume_spike=True,
        bullish_reasons=("Price is above SMA5.",), caution_reasons=(),
        source_versions={},
    )
    values.update(changes)
    return AlertSourceState(**values)


def test_combines_all_transitions_into_one_event() -> None:
    previous = state(
        trading_date=date(2026, 7, 15), score=80, rating="Buy", rank=3,
        strategy_status="failed", breakout_20=False, volume_spike=False,
    )
    event = build_alert(state(), previous, config())
    assert event is not None
    assert event.triggers == (
        "new_strong_buy", "strategy_matched", "breakout_detected",
        "volume_spike_detected", "score_upgrade",
    )
    assert "previous 80" in event.message


def test_downgrade_from_watchlist_remains_eligible() -> None:
    current = state(score=50, rating="Ignore", strategy_status="failed", breakout_20=False, volume_spike=False)
    previous = state(trading_date=date(2026, 7, 15), score=60, rating="Watchlist", strategy_status="failed", breakout_20=False, volume_spike=False)
    event = build_alert(current, previous, config())
    assert event is not None
    assert event.triggers == ("score_downgrade",)


def test_low_score_without_prior_eligibility_is_ignored() -> None:
    current = state(score=50, rating="Ignore", strategy_status="failed", breakout_20=False, volume_spike=False)
    previous = state(trading_date=date(2026, 7, 15), score=40, rating="Ignore", strategy_status="failed", breakout_20=False, volume_spike=False)
    assert build_alert(current, previous, config()) is None
