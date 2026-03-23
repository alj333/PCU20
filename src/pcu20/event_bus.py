"""In-process async event bus bridging TCP server events to WebSocket clients."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import structlog

log = structlog.get_logger()


class EventBus:
    """Async pub/sub event bus for internal communication."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []

    def emit(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        event = {
            "type": event_type,
            "data": data or {},
            "ts": time.time(),
        }
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("event_bus.queue_full", event_type=event_type)

    async def subscribe(self, max_size: int = 256) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max_size)
        self._subscribers.append(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subscribers.remove(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
