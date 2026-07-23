"""Shared bounded provider capacity for async graph nodes."""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager

from app.runtime.observability import metrics

llm_capacity = asyncio.Semaphore(max(1, int(os.getenv("RUNTIME_LLM_CONCURRENCY", "8"))))
amap_capacity = asyncio.Semaphore(max(1, int(os.getenv("RUNTIME_AMAP_CONCURRENCY", "8"))))


@asynccontextmanager
async def provider_slot(provider: str):
    semaphore = llm_capacity if provider == "llm" else amap_capacity
    async with semaphore:
        started = time.monotonic()
        metrics.provider_acquired(provider)
        try:
            yield
        finally:
            metrics.provider_released(provider, time.monotonic() - started)
