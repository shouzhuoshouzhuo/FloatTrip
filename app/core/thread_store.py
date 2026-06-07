"""进程内多轮续接存储：保存 missing_fields 时的原始 query，TTL 30 分钟。"""

from __future__ import annotations

import threading
import time
import uuid

_TTL = 30 * 60  # 秒


class ThreadStore:
    def __init__(self):
        self._store: dict[str, tuple[str, float]] = {}  # thread_id → (query, created_at)
        self._lock = threading.Lock()

    def create(self, original_query: str) -> str:
        self._evict()
        tid = str(uuid.uuid4())
        with self._lock:
            self._store[tid] = (original_query, time.monotonic())
        return tid

    def get(self, thread_id: str) -> str | None:
        with self._lock:
            item = self._store.get(thread_id)
        if not item:
            return None
        query, created_at = item
        if time.monotonic() - created_at > _TTL:
            self.delete(thread_id)
            return None
        return query

    def delete(self, thread_id: str) -> None:
        with self._lock:
            self._store.pop(thread_id, None)

    def _evict(self) -> None:
        now = time.monotonic()
        with self._lock:
            expired = [tid for tid, (_, t) in self._store.items() if now - t > _TTL]
            for tid in expired:
                del self._store[tid]


# 全局单例
thread_store = ThreadStore()
