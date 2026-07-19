from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import AsyncIterator, Callable
from zoneinfo import ZoneInfo

from yfinance import AsyncWebSocket


LOGGER = logging.getLogger("stocks_trading.debug.live_stream")


@dataclass(frozen=True)
class LiveTick:
    symbol: str
    price: float
    volume: int | None
    source_timestamp: str | None
    received_at: str
    source_latency_seconds: float | None
    inter_tick_gap_seconds: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class _SymbolStream:
    symbol: str
    ticks: deque[LiveTick]
    subscribers: set[asyncio.Queue[dict[str, object]]]
    task: asyncio.Task[None] | None = None
    status: str = "idle"
    error: str | None = None


def yahoo_timestamp(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    try:
        return datetime.fromtimestamp(timestamp, UTC)
    except (OverflowError, OSError, ValueError):
        return None


class LiveStreamManager:
    def __init__(
        self,
        timezone: ZoneInfo,
        *,
        retention: int = 10_000,
        websocket_factory: Callable[[], AsyncWebSocket] | None = None,
    ) -> None:
        self.timezone = timezone
        self.retention = retention
        self.websocket_factory = websocket_factory or (lambda: AsyncWebSocket(verbose=False))
        self._streams: dict[str, _SymbolStream] = {}
        self._lock = asyncio.Lock()

    async def stream(self, symbol: str) -> AsyncIterator[dict[str, object]]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=500)
        state = await self._subscribe(symbol, queue)
        try:
            yield {"event": "status", "data": self._status_payload(state)}
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield {
                        "event": "heartbeat",
                        "data": {
                            "symbol": symbol,
                            "received_at": datetime.now(UTC).astimezone(self.timezone).isoformat(),
                        },
                    }
        finally:
            await self._unsubscribe(symbol, queue)

    def snapshot(self, symbol: str) -> dict[str, object]:
        state = self._streams.get(symbol)
        if state is None:
            return {
                "symbol": symbol,
                "status": "idle",
                "error": None,
                "subscriber_count": 0,
                "tick_count": 0,
                "retention": self.retention,
                "ticks": [],
            }
        return {
            "symbol": symbol,
            "status": state.status,
            "error": state.error,
            "subscriber_count": len(state.subscribers),
            "tick_count": len(state.ticks),
            "retention": self.retention,
            "ticks": [tick.to_dict() for tick in state.ticks],
        }

    async def close(self) -> None:
        async with self._lock:
            tasks = [state.task for state in self._streams.values() if state.task]
            for task in tasks:
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _subscribe(
        self, symbol: str, queue: asyncio.Queue[dict[str, object]]
    ) -> _SymbolStream:
        async with self._lock:
            state = self._streams.setdefault(
                symbol,
                _SymbolStream(symbol, deque(maxlen=self.retention), set()),
            )
            state.subscribers.add(queue)
            if state.task is None or state.task.done():
                state.status = "connecting"
                state.error = None
                state.task = asyncio.create_task(self._run(state))
            return state

    async def _unsubscribe(
        self, symbol: str, queue: asyncio.Queue[dict[str, object]]
    ) -> None:
        task: asyncio.Task[None] | None = None
        async with self._lock:
            state = self._streams.get(symbol)
            if state is None:
                return
            state.subscribers.discard(queue)
            if not state.subscribers and state.task and not state.task.done():
                task = state.task
                task.cancel()
        if task:
            with contextlib.suppress(asyncio.CancelledError):
                await task
            state.status = "disconnected"
            state.task = None

    async def _run(self, state: _SymbolStream) -> None:
        websocket = self.websocket_factory()
        try:
            await websocket.subscribe(state.symbol)
            state.status = "connected"
            self._publish(state, "status", self._status_payload(state))

            async def handle(message: dict[str, object]) -> None:
                message_symbol = str(message.get("id") or "").upper()
                if message_symbol and message_symbol != state.symbol:
                    return
                tick = self._tick(state, message)
                if tick is None:
                    return
                state.ticks.append(tick)
                LOGGER.info(
                    "yfinance tick symbol=%s price=%s day_volume=%s source_at=%s received_at=%s gap_seconds=%s latency_seconds=%s",
                    tick.symbol,
                    tick.price,
                    tick.volume,
                    tick.source_timestamp,
                    tick.received_at,
                    tick.inter_tick_gap_seconds,
                    tick.source_latency_seconds,
                )
                self._publish(state, "tick", tick.to_dict())

            await websocket.listen(handle)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            state.status = "error"
            state.error = str(error)
            LOGGER.exception("yfinance live stream failed for %s", state.symbol)
            self._publish(state, "stream_error", self._status_payload(state))
        finally:
            with contextlib.suppress(Exception):
                await websocket.close()
            if state.status != "error" and state.subscribers:
                state.status = "disconnected"
                self._publish(state, "status", self._status_payload(state))

    def _tick(self, state: _SymbolStream, message: dict[str, object]) -> LiveTick | None:
        try:
            price = float(message["price"])
        except (KeyError, TypeError, ValueError):
            return None
        received = datetime.now(UTC)
        source = yahoo_timestamp(message.get("time"))
        previous = state.ticks[-1] if state.ticks else None
        previous_received = (
            datetime.fromisoformat(previous.received_at).astimezone(UTC) if previous else None
        )
        volume_value = message.get("day_volume")
        try:
            volume = int(volume_value) if volume_value is not None else None
        except (TypeError, ValueError):
            volume = None
        return LiveTick(
            symbol=state.symbol,
            price=price,
            volume=volume,
            source_timestamp=source.astimezone(self.timezone).isoformat() if source else None,
            received_at=received.astimezone(self.timezone).isoformat(),
            source_latency_seconds=round((received - source).total_seconds(), 3) if source else None,
            inter_tick_gap_seconds=(
                round((received - previous_received).total_seconds(), 3)
                if previous_received
                else None
            ),
        )

    @staticmethod
    def _publish(state: _SymbolStream, event: str, data: dict[str, object]) -> None:
        payload = {"event": event, "data": data}
        for queue in tuple(state.subscribers):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(payload)

    @staticmethod
    def _status_payload(state: _SymbolStream) -> dict[str, object]:
        return {
            "symbol": state.symbol,
            "status": state.status,
            "error": state.error,
            "subscriber_count": len(state.subscribers),
            "tick_count": len(state.ticks),
        }
