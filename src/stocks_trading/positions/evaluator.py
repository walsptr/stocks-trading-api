from dataclasses import replace
from decimal import Decimal, ROUND_FLOOR
from uuid import uuid4

from stocks_trading.domain.models import PositionEvent, PositionSourceDay, PositionStatus, VirtualPosition
from stocks_trading.positions.config import PositionConfiguration
from stocks_trading.risk.evaluator import idx_tick_size, round_up_to_tick

ONE = Decimal("1")
ZERO = Decimal("0")


def round_down_to_tick(price: Decimal) -> Decimal:
    tick = idx_tick_size(price)
    rounded = (price / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
    next_tick = idx_tick_size(rounded)
    return (price / next_tick).to_integral_value(rounding=ROUND_FLOOR) * next_tick


def new_pending_position(source: PositionSourceDay, configuration: PositionConfiguration) -> tuple[VirtualPosition, PositionEvent]:
    position_id = uuid4()
    position = VirtualPosition(
        id=position_id, symbol=source.candle.symbol,
        strategy_name=configuration.strategy_name, strategy_version=configuration.strategy_version,
        lifecycle_version=configuration.version, lifecycle_config_checksum=configuration.checksum,
        status=PositionStatus.PENDING_ENTRY, signal_date=source.candle.trading_date,
        entry_date=None, exit_date=None, signal_atr=source.atr_14,
        entry_price=None, initial_stop=None, active_stop=None,
        take_profit_1=None, take_profit_2=None, highest_close=None,
        remaining_fraction=ONE,
        suggested_position_size_pct=source.suggested_position_size_pct or ZERO,
        holding_sessions=0, queued_action=None, queued_action_date=None,
        tp1_filled=False, realized_gross_return=ZERO, realized_net_return=ZERO,
        unrealized_return=None, exit_reason=None, average_exit_price=None,
        last_processed_date=source.candle.trading_date,
    )
    return position, event(position, source.candle.trading_date, "signal_created")


def process_position(position: VirtualPosition, source: PositionSourceDay,
                     configuration: PositionConfiguration) -> tuple[VirtualPosition, tuple[PositionEvent, ...]]:
    if source.candle.trading_date <= position.last_processed_date:
        return position, ()
    if position.status == PositionStatus.PENDING_ENTRY:
        return fill_entry(position, source, configuration)
    if position.status == PositionStatus.CLOSED:
        return position, ()

    events: list[PositionEvent] = []
    current = position
    if current.queued_action == "trend_exit":
        return close_position(current, source.candle.trading_date, source.candle.open, ONE, "trend_exit", configuration)
    if current.queued_action == "rsi_partial" and not current.tp1_filled:
        current, partial_events = realize(current, source.candle.trading_date, source.candle.open,
                                          configuration.partial_fraction, "partial_exit", configuration)
        events.extend(partial_events)
        current = replace(current, tp1_filled=True, status=PositionStatus.PARTIAL,
                          active_stop=max(current.active_stop or source.candle.open, current.entry_price or source.candle.open))
    current = replace(current, queued_action=None, queued_action_date=None,
                      holding_sessions=current.holding_sessions + 1)

    if current.active_stop is not None and source.candle.low <= current.active_stop:
        closed, stop_events = close_position(current, source.candle.trading_date, current.active_stop,
                                             current.remaining_fraction, "stop_exit", configuration)
        return closed, tuple(events) + stop_events

    if not current.tp1_filled and current.take_profit_1 is not None and source.candle.high >= current.take_profit_1:
        current, tp1_events = realize(current, source.candle.trading_date, current.take_profit_1,
                                      configuration.partial_fraction, "tp1_filled", configuration)
        events.extend(tp1_events)
        current = replace(current, tp1_filled=True, status=PositionStatus.PARTIAL,
                          active_stop=max(current.active_stop or current.entry_price, current.entry_price))
    if current.take_profit_2 is not None and source.candle.high >= current.take_profit_2:
        closed, tp2_events = close_position(current, source.candle.trading_date, current.take_profit_2,
                                            current.remaining_fraction, "tp2_filled", configuration)
        return closed, tuple(events) + tp2_events

    highest_close = max(current.highest_close or source.candle.close, source.candle.close)
    active_stop = current.active_stop
    if source.atr_14 is not None:
        candidate = round_down_to_tick(highest_close - source.atr_14 * configuration.trailing_atr_multiple)
        if current.tp1_filled and current.entry_price is not None:
            candidate = max(candidate, current.entry_price)
        if active_stop is None or candidate > active_stop:
            active_stop = candidate
            events.append(event(current, source.candle.trading_date, "stop_updated", candidate))

    queued_action = "trend_exit" if source.ma20_below_ma50 is True else (
        "rsi_partial" if source.rsi_extreme_overbought is True and not current.tp1_filled else None
    )
    if current.holding_sessions >= configuration.maximum_holding_sessions:
        closed, time_events = close_position(current, source.candle.trading_date, source.candle.close,
                                             current.remaining_fraction, "time_exit", configuration)
        return closed, tuple(events) + time_events
    unrealized = None if current.entry_price is None else (source.candle.close / current.entry_price - ONE) * current.remaining_fraction
    return replace(current, highest_close=highest_close, active_stop=active_stop,
                   queued_action=queued_action,
                   queued_action_date=source.candle.trading_date if queued_action else None,
                   unrealized_return=unrealized, last_processed_date=source.candle.trading_date), tuple(events)


def fill_entry(position: VirtualPosition, source: PositionSourceDay,
               configuration: PositionConfiguration) -> tuple[VirtualPosition, tuple[PositionEvent, ...]]:
    if position.signal_atr is None or position.signal_atr <= ZERO:
        closed = replace(position, status=PositionStatus.CLOSED, exit_date=source.candle.trading_date,
                         exit_reason="invalid_atr", last_processed_date=source.candle.trading_date)
        return closed, (event(closed, source.candle.trading_date, "entry_cancelled"),)
    entry = source.candle.open
    stop = round_down_to_tick(entry - position.signal_atr * configuration.stop_atr_multiple)
    risk = entry - stop
    tp1 = round_up_to_tick(entry + risk * configuration.take_profit_1_r_multiple)
    tp2 = round_up_to_tick(entry + risk * configuration.take_profit_2_r_multiple)
    current = replace(position, status=PositionStatus.OPEN, entry_date=source.candle.trading_date,
                      entry_price=entry, initial_stop=stop, active_stop=stop,
                      take_profit_1=tp1, take_profit_2=tp2, highest_close=source.candle.close,
                      holding_sessions=1, unrealized_return=source.candle.close / entry - ONE,
                      last_processed_date=source.candle.trading_date)
    events = [event(current, source.candle.trading_date, "entry_filled", entry)]
    if source.candle.low <= stop:
        closed, close_events = close_position(current, source.candle.trading_date, stop, ONE, "stop_exit", configuration)
        return closed, tuple(events) + close_events
    if source.candle.high >= tp1:
        current, partial_events = realize(current, source.candle.trading_date, tp1,
                                          configuration.partial_fraction, "tp1_filled", configuration)
        events.extend(partial_events)
        current = replace(current, tp1_filled=True, status=PositionStatus.PARTIAL,
                          active_stop=max(current.active_stop or entry, entry))
    if source.candle.high >= tp2:
        closed, close_events = close_position(current, source.candle.trading_date, tp2,
                                              current.remaining_fraction, "tp2_filled", configuration)
        return closed, tuple(events) + close_events
    return current, tuple(events)


def realize(position: VirtualPosition, trading_date, price: Decimal, fraction: Decimal,
            event_type: str, configuration: PositionConfiguration):
    fraction = min(fraction, position.remaining_fraction)
    gross = (price / position.entry_price - ONE) * fraction
    net = gross - configuration.buy_fee_rate * fraction - configuration.sell_fee_rate * (price / position.entry_price) * fraction
    updated = replace(position, remaining_fraction=position.remaining_fraction - fraction,
                      realized_gross_return=position.realized_gross_return + gross,
                      realized_net_return=position.realized_net_return + net,
                      average_exit_price=weighted_exit(position, price, fraction),
                      last_processed_date=trading_date)
    return updated, (event(updated, trading_date, event_type, price, fraction),)


def close_position(position, trading_date, price, fraction, reason, configuration):
    updated, events = realize(position, trading_date, price, fraction, reason, configuration)
    updated = replace(updated, status=PositionStatus.CLOSED, exit_date=trading_date,
                      remaining_fraction=ZERO, unrealized_return=ZERO, exit_reason=reason,
                      queued_action=None, queued_action_date=None)
    return updated, events


def weighted_exit(position: VirtualPosition, price: Decimal, fraction: Decimal) -> Decimal:
    exited_before = ONE - position.remaining_fraction
    if exited_before <= ZERO or position.average_exit_price is None:
        return price
    return (position.average_exit_price * exited_before + price * fraction) / (exited_before + fraction)


def event(position, trading_date, event_type, price=None, fraction=None):
    return PositionEvent(uuid4(), position.id, position.symbol, trading_date, event_type, price, fraction, {})
