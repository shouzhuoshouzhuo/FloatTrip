"""Run lifecycle service and durable-first event publication."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from app.core.database import get_conn
from app.runtime.models import (
    DisconnectPolicy,
    PublicError,
    RunKind,
    RunStatus,
    TERMINAL_STATUSES,
    concurrency_key,
)
from app.runtime.repositories import RunEventRepository, RunRepository
from app.runtime.stream import StreamBridge, StreamItem


class RunManager:
    def __init__(
        self,
        db_path: str | Path | None = None,
        bridge: StreamBridge | None = None,
    ):
        self.db_path = db_path
        self.runs = RunRepository(db_path)
        self.events = RunEventRepository(db_path)
        self.bridge = bridge or StreamBridge()
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}

    def create(
        self,
        *,
        user_id: str,
        kind: RunKind | str,
        request_snapshot: dict[str, Any],
        conversation_id: str | None = None,
        itinerary_id: str | None = None,
        retry_of_run_id: str | None = None,
        disconnect_policy: DisconnectPolicy | str = DisconnectPolicy.CONTINUE,
    ) -> dict[str, Any]:
        run_id = str(uuid.uuid4())
        key = concurrency_key(
            kind,
            conversation_id=conversation_id,
            run_id=run_id,
            itinerary_id=itinerary_id,
        )
        with get_conn(self.db_path) as conn:
            run = self.runs.insert(
                conn,
                run_id=run_id,
                user_id=user_id,
                kind=kind,
                concurrency_key=key,
                request_snapshot=request_snapshot,
                conversation_id=conversation_id,
                retry_of_run_id=retry_of_run_id,
                disconnect_policy=disconnect_policy,
            )
        return run

    def retry(self, user_id: str, run_id: str) -> dict[str, Any]:
        original = self.runs.get(user_id, run_id)
        if RunStatus(original["status"]) not in {
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }:
            raise ValueError("only failed or cancelled runs can be retried")
        itinerary_id = (
            original["request_snapshot"].get("related_itinerary_id")
            if original["kind"] == RunKind.REVISION.value
            else None
        )
        return self.create(
            user_id=user_id,
            kind=original["kind"],
            request_snapshot=original["request_snapshot"],
            conversation_id=original["conversation_id"],
            itinerary_id=itinerary_id,
            retry_of_run_id=run_id,
            disconnect_policy=original["disconnect_policy"],
        )

    async def publish(
        self,
        run_id: str,
        kind: str,
        payload: dict[str, Any],
        *,
        durable: bool = True,
        validate_custom: bool = True,
    ) -> StreamItem:
        sequence = None
        if durable:
            event = await asyncio.to_thread(
                self.events.append, run_id, kind, payload, durable=True
            )
            sequence = event["sequence"]
        item = StreamItem(run_id, kind, payload, sequence, durable)
        await self.bridge.publish(item)
        return item

    async def transition(
        self,
        run_id: str,
        target: RunStatus | str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        run = await asyncio.to_thread(self.runs.transition, run_id, target, **kwargs)
        await self.publish(
            run_id,
            "custom",
            {"kind": "run.status", "status": run["status"]},
            durable=True,
        )
        if RunStatus(run["status"]) is RunStatus.FAILED and run["error_public"]:
            await self.publish(
                run_id,
                "error",
                run["error_public"],
                durable=True,
            )
        if RunStatus(run["status"]) in TERMINAL_STATUSES:
            await self.publish(
                run_id,
                "end",
                {"status": run["status"]},
                durable=True,
            )
        return run

    async def cancel(self, user_id: str, run_id: str) -> dict[str, Any]:
        run = await asyncio.to_thread(self.runs.get, user_id, run_id)
        current = RunStatus(run["status"])
        if current is RunStatus.CANCELLED:
            return run
        if current in TERMINAL_STATUSES:
            raise ValueError("completed run cannot be cancelled")
        cancel_event = self._cancel_events.get(run_id)
        if cancel_event:
            cancel_event.set()
        task = self._tasks.get(run_id)
        if task:
            task.cancel()
        return await self.transition(run_id, RunStatus.CANCELLED)

    def register_task(
        self, run_id: str, task: asyncio.Task[Any], cancel_event: asyncio.Event
    ) -> None:
        self._tasks[run_id] = task
        self._cancel_events[run_id] = cancel_event

        def cleanup(_task: asyncio.Task[Any]) -> None:
            self._tasks.pop(run_id, None)
            self._cancel_events.pop(run_id, None)

        task.add_done_callback(cleanup)

    async def reconcile_startup(self) -> list[str]:
        reconciled = []
        for run in await asyncio.to_thread(self.runs.orphaned_active):
            await self.transition(
                run["id"],
                RunStatus.FAILED,
                error_public=PublicError(
                    code="server_restarted",
                    message="服务重启导致任务中断，请重试",
                    retryable=True,
                ).model_dump(),
                error_internal="orphaned run found during single-node startup reconciliation",
            )
            reconciled.append(run["id"])
        return reconciled
