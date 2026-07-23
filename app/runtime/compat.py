"""Compatibility projection from persistent Run events to the legacy SSE contract."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from app.core.database import get_conn
from app.core.memory import load_itinerary
from app.runtime.manager import RunManager
from app.runtime.models import RunKind, RunStatus, TERMINAL_STATUSES
from app.runtime.scheduler import RuntimeScheduler


def create_legacy_run(
    manager: RunManager,
    *,
    user_id: str,
    query: str,
    overrides: dict[str, Any],
    plan_id: str | None = None,
    modification_notes: str | None = None,
) -> dict[str, Any]:
    snapshot = {"query": query, **overrides}
    if plan_id and modification_notes:
        snapshot.update(
            {
                "related_itinerary_id": plan_id,
                "parent_plan_id": plan_id,
                "modification_notes": modification_notes,
            }
        )
        return manager.create(
            user_id=user_id,
            kind=RunKind.REVISION,
            request_snapshot=snapshot,
            itinerary_id=plan_id,
        )
    return manager.create(
        user_id=user_id,
        kind=RunKind.TRAVEL_PLAN,
        request_snapshot=snapshot,
    )


async def resume_legacy_run(
    manager: RunManager,
    scheduler: RuntimeScheduler,
    *,
    user_id: str,
    run_id: str,
    value: Any,
) -> dict[str, Any]:
    run = await asyncio.to_thread(manager.runs.get, user_id, run_id)
    if run["status"] != RunStatus.WAITING_USER.value:
        raise ValueError("legacy thread is not waiting for input")
    return await scheduler.resume(
        run,
        run["outstanding_interaction_id"],
        value,
    )


async def legacy_events(
    manager: RunManager,
    run_id: str,
    *,
    after_sequence: int = 0,
) -> AsyncIterator[dict[str, Any]]:
    """Subscribe first, replay second, then project durable/live events once."""
    cursor = after_sequence
    emitted_result = False
    async with manager.bridge.subscribe(run_id, after_sequence=cursor) as live:
        replay = await asyncio.to_thread(manager.events.after, run_id, cursor)
        for event in replay:
            cursor = max(cursor, event["sequence"])
            projected = await _project(
                event["kind"], event["payload"], run_id, manager
            )
            if projected:
                yield projected
                emitted_result = emitted_result or projected.get("type") == "result"
        run = await asyncio.to_thread(manager.runs.get_internal, run_id)
        if RunStatus(run["status"]) in TERMINAL_STATUSES:
            if not emitted_result and run["status"] != RunStatus.SUCCEEDED.value:
                yield {
                    "type": "error",
                    "message": (run["error_public"] or {}).get(
                        "message", "规划任务未成功完成"
                    ),
                }
            return
        async for item in live:
            if item.sequence is not None and item.sequence <= cursor:
                continue
            if item.sequence is not None:
                cursor = item.sequence
            projected = await _project(item.kind, item.payload, run_id, manager)
            if projected:
                yield projected
                if projected.get("type") == "result":
                    return
            if item.kind == "end":
                return


async def _project(
    event_kind: str,
    payload: dict[str, Any],
    run_id: str,
    manager: RunManager,
) -> dict[str, Any] | None:
    if event_kind == "custom":
        kind = payload.get("kind")
        if kind == "planning_run.progress":
            return {
                "type": "stage",
                "node": payload.get("stage"),
                "label": payload.get("label", "正在规划"),
                **({"round": payload["round"]} if payload.get("round") else {}),
            }
        if kind == "run.waiting_user":
            return {
                "type": "result",
                "success": False,
                "missing_fields": [payload.get("question", "请补充信息")],
                "history": [],
                "plan": None,
                "thread_id": run_id,
                "interaction_id": payload.get("interaction_id"),
            }
        if kind == "planning.itinerary_created":
            itinerary_id = payload["itinerary_id"]

            def load():
                with get_conn(manager.db_path) as conn:
                    return load_itinerary(itinerary_id, conn)

            itinerary = await asyncio.to_thread(load)
            return {
                "type": "result",
                "success": True,
                "missing_fields": [],
                "history": [],
                "plan": itinerary["plan"] if itinerary else None,
                "plan_id": itinerary_id,
            }
    if event_kind == "error":
        return {"type": "error", "message": payload.get("message", "规划出错")}
    return None
