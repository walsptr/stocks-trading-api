import asyncio
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from stocks_trading.debug.live_stream import LiveStreamManager, yahoo_timestamp


class FakeWebSocket:
    def __init__(self, messages):
        self.messages = messages
        self.closed = False

    async def subscribe(self, symbol):
        self.symbol = symbol

    async def listen(self, handler):
        for message in self.messages:
            await handler(message)
        await asyncio.Event().wait()

    async def close(self):
        self.closed = True


def test_yahoo_timestamp_accepts_seconds_and_milliseconds():
    expected = datetime(2026, 7, 19, tzinfo=UTC)
    assert yahoo_timestamp(expected.timestamp()) == expected
    assert yahoo_timestamp(expected.timestamp() * 1000) == expected
    assert yahoo_timestamp("invalid") is None


@pytest.mark.asyncio
async def test_stream_publishes_ticks_and_retains_bounded_history():
    messages = [
        {"id": "BBCA.JK", "price": index, "day_volume": index * 10, "time": 1_768_000_000 + index}
        for index in range(1, 5)
    ]
    websocket = FakeWebSocket(messages)
    manager = LiveStreamManager(
        ZoneInfo("Asia/Jakarta"), retention=3, websocket_factory=lambda: websocket
    )
    stream = manager.stream("BBCA.JK")
    try:
        first = await anext(stream)
        assert first["event"] == "status"
        events = [await asyncio.wait_for(anext(stream), 1) for _ in range(5)]
        ticks = [event for event in events if event["event"] == "tick"]
        assert len(ticks) == 4
        snapshot = manager.snapshot("BBCA.JK")
        assert snapshot["tick_count"] == 3
        assert [tick["price"] for tick in snapshot["ticks"]] == [2.0, 3.0, 4.0]
        assert snapshot["subscriber_count"] == 1
    finally:
        await stream.aclose()
        await manager.close()
    assert websocket.closed is True
    assert manager.snapshot("BBCA.JK")["subscriber_count"] == 0
    assert manager.snapshot("BBCA.JK")["status"] == "disconnected"


@pytest.mark.asyncio
async def test_multiple_subscribers_share_one_symbol_task():
    websocket_count = 0

    def factory():
        nonlocal websocket_count
        websocket_count += 1
        return FakeWebSocket([])

    manager = LiveStreamManager(ZoneInfo("Asia/Jakarta"), websocket_factory=factory)
    first = manager.stream("TLKM.JK")
    second = manager.stream("TLKM.JK")
    try:
        await anext(first)
        await anext(second)
        await asyncio.sleep(0)
        assert websocket_count == 1
        assert manager.snapshot("TLKM.JK")["subscriber_count"] == 2
    finally:
        await first.aclose()
        await second.aclose()
        await manager.close()
