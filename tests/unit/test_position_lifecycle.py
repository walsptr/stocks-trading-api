from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from stocks_trading.domain.models import DailyCandle, PositionSourceDay, PositionStatus
from stocks_trading.positions.config import load_position_configuration
from stocks_trading.positions.evaluator import new_pending_position, process_position

CONFIG = load_position_configuration(Path("config/positions/swing-lifecycle-v1.yaml"))


def source(day, *, open="100", high="103", low="99", close="102", signal=False,
           atr="10", reversal=False, overbought=False):
    return PositionSourceDay(
        DailyCandle("BBCA.JK", day, Decimal(open), Decimal(high), Decimal(low),
                    Decimal(close), Decimal(close), 1_000_000),
        signal, Decimal(atr), reversal, overbought, Decimal("5"),
    )


def test_signal_enters_at_next_open_and_recalculates_levels():
    day = date(2026, 7, 1)
    position, created = new_pending_position(source(day, signal=True), CONFIG)
    updated, events = process_position(position, source(day + timedelta(days=1), open="110", high="112", low="108", close="111"), CONFIG)
    assert created.event_type == "signal_created"
    assert updated.status == PositionStatus.OPEN
    assert updated.entry_price == Decimal("110")
    assert updated.active_stop == Decimal("95")
    assert updated.take_profit_1 == Decimal("133")
    assert events[0].event_type == "entry_filled"


def test_stop_has_priority_when_stop_and_target_touch_same_candle():
    day = date(2026, 7, 1)
    position, _ = new_pending_position(source(day, signal=True), CONFIG)
    updated, events = process_position(position, source(day + timedelta(days=1), open="100", high="140", low="80", close="110"), CONFIG)
    assert updated.status == PositionStatus.CLOSED
    assert updated.exit_reason == "stop_exit"
    assert [item.event_type for item in events] == ["entry_filled", "stop_exit"]


def test_tp1_sells_half_and_moves_stop_to_breakeven():
    day = date(2026, 7, 1)
    position, _ = new_pending_position(source(day, signal=True), CONFIG)
    opened, _ = process_position(position, source(day + timedelta(days=1), open="100", high="102", low="99", close="101"), CONFIG)
    partial, events = process_position(opened, source(day + timedelta(days=2), high="125", low="99", close="120"), CONFIG)
    assert partial.status == PositionStatus.PARTIAL
    assert partial.remaining_fraction == Decimal("0.5")
    assert partial.active_stop >= partial.entry_price
    assert "tp1_filled" in [item.event_type for item in events]


def test_reversal_queues_next_open_exit():
    day = date(2026, 7, 1)
    position, _ = new_pending_position(source(day, signal=True), CONFIG)
    opened, _ = process_position(position, source(day + timedelta(days=1)), CONFIG)
    queued, _ = process_position(opened, source(day + timedelta(days=2), reversal=True), CONFIG)
    closed, events = process_position(queued, source(day + timedelta(days=3), open="105"), CONFIG)
    assert queued.queued_action == "trend_exit"
    assert closed.exit_reason == "trend_exit"
    assert events[0].price == Decimal("105")


def test_time_exit_closes_on_twentieth_session_close():
    day = date(2026, 7, 1)
    position, _ = new_pending_position(source(day, signal=True), CONFIG)
    current, _ = process_position(position, source(day + timedelta(days=1)), CONFIG)
    for index in range(2, 21):
        current, _ = process_position(current, source(day + timedelta(days=index), high="103", low="99", close="102"), CONFIG)
    assert current.status == PositionStatus.CLOSED
    assert current.exit_reason == "time_exit"
    assert current.holding_sessions == 20
