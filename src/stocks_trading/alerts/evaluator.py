from uuid import uuid4

from stocks_trading.alerts.config import AlertConfiguration
from stocks_trading.domain.models import AlertEvent, AlertSourceState


def build_alert(
    current: AlertSourceState,
    previous: AlertSourceState | None,
    configuration: AlertConfiguration,
) -> AlertEvent | None:
    previous_score = previous.score if previous else None
    eligible = current.score >= configuration.minimum_score or (
        previous_score is not None and previous_score >= configuration.minimum_score
        and current.score < previous_score
    ) or current.ma20_below_ma50 is True or current.stop_loss is not None or current.take_profit_1 is not None
    if not eligible:
        return None
    triggers = []
    if current.rating == "Strong Buy" and (previous is None or previous.rating != "Strong Buy"):
        triggers.append("new_strong_buy")
    if current.strategy_status == "passed" and (previous is None or previous.strategy_status != "passed"):
        triggers.append("strategy_matched")
    if current.breakout_20 is True and (previous is None or previous.breakout_20 is not True):
        triggers.append("breakout_detected")
    if current.volume_spike is True and (previous is None or previous.volume_spike is not True):
        triggers.append("volume_spike_detected")
    if "trend_exit" in current.position_event_types or (
        current.ma20_below_ma50 is True and (previous is None or previous.ma20_below_ma50 is not True)
    ):
        triggers.append("trend_reversal_warning")
    if current.close is not None and current.stop_loss is not None:
        threshold = current.stop_loss * 1.03
        if current.close <= threshold and (previous is None or previous.close is None or previous.close > threshold):
            triggers.append("approaching_stop_loss")
    if "tp1_filled" in current.position_event_types or "tp2_filled" in current.position_event_types:
        triggers.append("take_profit_reached")
    elif current.close is not None and current.take_profit_1 is not None:
        if current.close >= current.take_profit_1 and (previous is None or previous.close is None or previous.close < current.take_profit_1):
            triggers.append("take_profit_reached")
    if previous_score is not None and current.score > previous_score:
        triggers.append("score_upgrade")
    if previous_score is not None and current.score < previous_score:
        triggers.append("score_downgrade")
    triggers = [item for item in triggers if item in configuration.triggers]
    if not triggers:
        return None
    message = render_message(current, previous, triggers)
    return AlertEvent(
        id=uuid4(), symbol=current.symbol, trading_date=current.trading_date,
        alert_version=configuration.version,
        alert_config_checksum=configuration.checksum,
        triggers=tuple(triggers), message=message,
        current_score=current.score, previous_score=previous_score,
        current_rating=current.rating,
        previous_rating=previous.rating if previous else None,
        rank=current.rank, strategy_status=current.strategy_status,
        bullish_reasons=current.bullish_reasons[:4],
        caution_reasons=current.caution_reasons[:2],
        source_versions=current.source_versions,
    )


def render_message(current, previous, triggers) -> str:
    labels = ", ".join(item.replace("_", " ").title() for item in triggers)
    score_change = ""
    if previous is not None and previous.score != current.score:
        score_change = f" (previous {previous.score})"
    lines = [
        "📈 Swing Buy Candidate", f"Ticker: {current.symbol}",
        f"Date: {current.trading_date.isoformat()}",
        f"Score: {current.score}{score_change} — {current.rating}",
        f"Rank: #{current.rank}", "Strategy: Swing Trend Following",
        "Suggested Holding: 3-20 trading days",
        f"Status: {current.strategy_status}",
        f"Triggers: {labels}",
    ]
    if current.bullish_reasons:
        lines.append("Reasons: " + "; ".join(current.bullish_reasons[:4]))
    if current.caution_reasons:
        lines.append("Cautions: " + "; ".join(current.caution_reasons[:2]))
    if current.stop_loss is not None:
        lines.append(f"Stop Loss: {current.stop_loss}")
    if current.take_profit_1 is not None and current.take_profit_2 is not None:
        lines.append(f"Take Profit: {current.take_profit_1} / {current.take_profit_2}")
    return "\n".join(lines)
