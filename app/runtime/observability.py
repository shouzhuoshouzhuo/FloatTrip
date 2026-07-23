"""Small dependency-free metrics/logging layer for the single-node runtime."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

logger = logging.getLogger("app.runtime")


class RuntimeMetrics:
    def __init__(self):
        self._lock = threading.Lock()
        self._counters: Counter[str] = Counter()
        self._active: Counter[str] = Counter()
        self._durations: dict[str, list[float]] = defaultdict(list)
        self._started: dict[str, float] = {}

    def run_started(self, run: dict[str, Any]) -> None:
        now = time.monotonic()
        queued_at = datetime.fromisoformat(run["queued_at"]).timestamp()
        queue_seconds = max(0.0, time.time() - queued_at)
        with self._lock:
            self._counters["runs_started"] += 1
            self._active[run["kind"]] += 1
            self._started[run["id"]] = now
            self._record("queue_seconds", queue_seconds)
        self.log(
            "run_started",
            run_id=run["id"],
            kind=run["kind"],
            queue_seconds=round(queue_seconds, 3),
        )

    def run_finished(
        self,
        run: dict[str, Any],
        status: str,
        *,
        failure_reason: str | None = None,
    ) -> None:
        with self._lock:
            started = self._started.pop(run["id"], None)
            self._active[run["kind"]] = max(0, self._active[run["kind"]] - 1)
            self._counters[f"runs_{status}"] += 1
            if failure_reason:
                self._counters[f"failure:{failure_reason}"] += 1
            duration = time.monotonic() - started if started is not None else None
            if duration is not None:
                self._record("run_seconds", duration)
        self.log(
            "run_finished",
            run_id=run["id"],
            kind=run["kind"],
            status=status,
            duration_seconds=round(duration, 3) if duration is not None else None,
            failure_reason=failure_reason,
        )

    def provider_acquired(self, provider: str) -> None:
        with self._lock:
            self._active[f"provider:{provider}"] += 1
            self._counters[f"provider_calls:{provider}"] += 1

    def provider_released(self, provider: str, duration: float) -> None:
        with self._lock:
            self._active[f"provider:{provider}"] = max(
                0, self._active[f"provider:{provider}"] - 1
            )
            self._record(f"provider_seconds:{provider}", duration)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "active": dict(self._active),
                "durations": {
                    key: {
                        "count": len(values),
                        "avg": sum(values) / len(values) if values else 0,
                        "max": max(values) if values else 0,
                    }
                    for key, values in self._durations.items()
                },
            }

    def _record(self, key: str, value: float) -> None:
        values = self._durations[key]
        values.append(value)
        if len(values) > 1000:
            del values[: len(values) - 1000]

    @staticmethod
    def log(event: str, **fields: Any) -> None:
        logger.info(
            json.dumps({"event": event, **fields}, ensure_ascii=False, default=str)
        )


metrics = RuntimeMetrics()
