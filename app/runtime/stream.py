"""In-process live notification bridge with replay-safe cursors."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class StreamItem:
    run_id: str
    kind: str
    payload: dict[str, Any]
    sequence: int | None = None
    durable: bool = False


class StreamBridge:
    def __init__(self, retention: int = 256, heartbeat_seconds: float = 15.0):
        self.retention = max(1, retention)
        self.heartbeat_seconds = heartbeat_seconds
        self._history: dict[str, deque[StreamItem]] = defaultdict(
            lambda: deque(maxlen=self.retention)
        )
        self._subscribers: dict[str, set[asyncio.Queue[StreamItem]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def publish(self, item: StreamItem) -> None:
        async with self._lock:
            self._history[item.run_id].append(item)
            subscribers = list(self._subscribers[item.run_id])
        for queue in subscribers:
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                _ = queue.get_nowait()
                queue.put_nowait(item)

    @asynccontextmanager
    async def subscribe(self, run_id: str, *, after_sequence: int = 0):
        queue: asyncio.Queue[StreamItem] = asyncio.Queue(maxsize=self.retention)
        async with self._lock:
            for item in self._history.get(run_id, ()):
                if item.sequence is None or item.sequence > after_sequence:
                    queue.put_nowait(item)
            self._subscribers[run_id].add(queue)
        try:
            yield self._iterate(run_id, queue, after_sequence)
        finally:
            async with self._lock:
                self._subscribers[run_id].discard(queue)

    async def _iterate(
        self,
        run_id: str,
        queue: asyncio.Queue[StreamItem],
        after_sequence: int,
    ) -> AsyncIterator[StreamItem]:
        cursor = after_sequence
        while True:
            try:
                item = await asyncio.wait_for(
                    queue.get(), timeout=self.heartbeat_seconds
                )
            except TimeoutError:
                yield StreamItem(run_id, "heartbeat", {}, durable=False)
                continue
            if item.sequence is not None:
                if item.sequence <= cursor:
                    continue
                cursor = item.sequence
            yield item
            if item.kind == "end":
                return
