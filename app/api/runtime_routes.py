"""Resource-oriented conversation, brief, run, and event APIs."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.auth import decode_token
from app.core.database import get_conn
from app.core.travel_memory import (
    ArchivedConversationError,
    ConversationMemoryRepository,
    MemoryJobRepository,
    MemoryNotFound,
    MemoryRepository,
)
from app.runtime.container import chat_service, manager, scheduler
from app.runtime.models import RunKind, RunStatus, TERMINAL_STATUSES
from app.runtime.observability import metrics
from app.runtime.repositories import (
    ConversationRepository,
    OwnedResourceNotFound,
    PlanningBriefRepository,
)

router = APIRouter(prefix="/api")
conversations = ConversationRepository()
briefs = PlanningBriefRepository()
conversation_memories = ConversationMemoryRepository()
memory_jobs = MemoryJobRepository()
memory_facts = MemoryRepository()


@router.get("/runtime/metrics")
async def runtime_metrics(
    authorization: str | None = Header(default=None),
):
    _owner(authorization)
    return metrics.snapshot()


def _owner(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="需要登录")
    user_id = decode_token(authorization[7:])
    if not user_id:
        raise HTTPException(status_code=401, detail="token 无效或已过期")
    return user_id


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


class ConversationCreate(BaseModel):
    title: str = Field(default="", max_length=100)


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)
    related_run_id: str | None = None
    related_itinerary_id: str | None = None


class BriefPatch(BaseModel):
    destination: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    days: int | None = Field(default=None, ge=1, le=30)
    budget: str | None = None
    trip_budget: str | None = Field(default=None, max_length=500)
    attraction_preference: str | None = None
    food_preference: str | None = None
    habit_preference: str | None = None
    trip_constraints: list[dict[str, Any]] | None = Field(default=None, max_length=30)
    excluded_memory_fact_ids: list[str] | None = Field(default=None, max_length=100)


class RunCreate(BaseModel):
    kind: RunKind
    conversation_id: str | None = None
    related_itinerary_id: str | None = None
    request: dict[str, Any]


class RunResume(BaseModel):
    interaction_id: str = Field(min_length=1)
    value: Any


@router.post("/conversations")
async def create_conversation(
    body: ConversationCreate,
    authorization: str | None = Header(default=None),
):
    return await asyncio.to_thread(
        conversations.create, _owner(authorization), body.title
    )


@router.get("/conversations")
async def list_conversations(
    limit: int = Query(default=50, ge=1, le=100),
    authorization: str | None = Header(default=None),
):
    return await asyncio.to_thread(
        conversations.list, _owner(authorization), limit
    )


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    authorization: str | None = Header(default=None),
):
    user_id = _owner(authorization)
    try:
        return await asyncio.to_thread(
            conversations.get, user_id, conversation_id
        )
    except OwnedResourceNotFound as exc:
        raise _not_found(exc) from exc


@router.post("/conversations/{conversation_id}/view")
async def mark_conversation_viewed(
    conversation_id: str,
    authorization: str | None = Header(default=None),
):
    try:
        return await asyncio.to_thread(
            conversations.mark_viewed, _owner(authorization), conversation_id
        )
    except OwnedResourceNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: str,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    authorization: str | None = Header(default=None),
):
    try:
        return await asyncio.to_thread(
            conversations.messages,
            _owner(authorization),
            conversation_id,
            after_sequence=after_sequence,
            limit=limit,
        )
    except OwnedResourceNotFound as exc:
        raise _not_found(exc) from exc


@router.post("/conversations/{conversation_id}/messages", status_code=202)
async def submit_message(
    conversation_id: str,
    body: MessageCreate,
    authorization: str | None = Header(default=None),
):
    try:
        message, run = await chat_service.submit_message(
            _owner(authorization),
            conversation_id,
            body.content.strip(),
            related_run_id=body.related_run_id,
            related_itinerary_id=body.related_itinerary_id,
        )
    except OwnedResourceNotFound as exc:
        raise _not_found(exc) from exc
    except ArchivedConversationError as exc:
        raise HTTPException(status_code=409, detail="conversation_archived") from exc
    except ValueError as exc:
        if str(exc) == "message_too_long":
            raise HTTPException(
                status_code=422,
                detail="消息过长，请拆成几条发送，以便我准确记住每个要求。",
            ) from exc
        if str(exc) == "message_empty":
            raise HTTPException(status_code=422, detail="消息不能为空。") from exc
        raise
    scheduler.notify()
    return {"message": message, "run": run}


@router.post("/conversations/{conversation_id}/archive")
async def archive_conversation(
    conversation_id: str,
    authorization: str | None = Header(default=None),
):
    try:
        return await asyncio.to_thread(
            conversations.archive, _owner(authorization), conversation_id
        )
    except OwnedResourceNotFound as exc:
        raise _not_found(exc) from exc


@router.post("/conversations/{conversation_id}/compress")
async def compress_conversation(
    conversation_id: str,
    authorization: str | None = Header(default=None),
):
    try:
        return await chat_service.memory_context.compress_now(
            _owner(authorization), conversation_id
        )
    except OwnedResourceNotFound as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        code = str(exc)
        if code == "conversation_archived":
            raise HTTPException(status_code=409, detail=code) from exc
        if code == "nothing_to_compress":
            raise HTTPException(status_code=409, detail="当前对话还没有可以压缩的内容。") from exc
        raise
    except RuntimeError as exc:
        if str(exc) == "conversation_compression_failed":
            raise HTTPException(
                status_code=503,
                detail="这次压缩没有完成，原始消息和旧摘要均已保留，请稍后重试。",
            ) from exc
        raise


@router.post("/conversations/{conversation_id}/memory/retry")
async def retry_conversation_memory(
    conversation_id: str,
    authorization: str | None = Header(default=None),
):
    user_id = _owner(authorization)
    try:
        await asyncio.to_thread(conversations.get, user_id, conversation_id)
        job = await asyncio.to_thread(
            memory_jobs.retry_archive, user_id, conversation_id
        )
    except (OwnedResourceNotFound, MemoryNotFound) as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"conversation_id": conversation_id, "finalization_status": "pending", "job_id": job["id"]}


@router.get("/conversations/{conversation_id}/planning-brief")
async def get_active_brief(
    conversation_id: str,
    authorization: str | None = Header(default=None),
):
    user_id = _owner(authorization)
    try:
        await asyncio.to_thread(
            conversations.get, user_id, conversation_id
        )
    except OwnedResourceNotFound as exc:
        raise _not_found(exc) from exc
    return await asyncio.to_thread(
        briefs.active_for_conversation, user_id, conversation_id
    )


@router.patch("/planning-briefs/{brief_id}")
async def update_brief(
    brief_id: str,
    body: BriefPatch,
    authorization: str | None = Header(default=None),
):
    user_id = _owner(authorization)
    try:
        return await chat_service.update_brief(
            user_id,
            brief_id,
            body.model_dump(exclude_none=True, exclude_unset=True),
        )
    except OwnedResourceNotFound as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/planning-briefs/{brief_id}/memory/refresh")
async def refresh_brief_memory(
    brief_id: str,
    authorization: str | None = Header(default=None),
):
    try:
        return await chat_service.refresh_brief_memory(_owner(authorization), brief_id)
    except OwnedResourceNotFound as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/planning-briefs/{brief_id}/submit", status_code=202)
async def submit_brief(
    brief_id: str,
    authorization: str | None = Header(default=None),
):
    try:
        brief, run = await chat_service.submit_brief(_owner(authorization), brief_id)
    except OwnedResourceNotFound as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    scheduler.notify()
    return {"brief": brief, "run": run}


@router.post("/planning-briefs/{brief_id}/discard")
async def discard_brief(
    brief_id: str,
    authorization: str | None = Header(default=None),
):
    try:
        return await asyncio.to_thread(
            briefs.transition, _owner(authorization), brief_id, "discarded"
        )
    except OwnedResourceNotFound as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/runs", status_code=202)
async def create_run(
    body: RunCreate,
    authorization: str | None = Header(default=None),
):
    user_id = _owner(authorization)
    if body.kind is RunKind.CHAT:
        raise HTTPException(status_code=400, detail="Chat Run 请通过消息接口创建")
    request_snapshot = dict(body.request)
    for server_field in (
        "memory_profile_revision", "memory_profile_snapshot", "memory_context",
        "effective_constraints", "constraint_coverage",
    ):
        request_snapshot.pop(server_field, None)
    if body.conversation_id:
        try:
            def freeze_conversation_memory():
                with get_conn() as conn:
                    return conversation_memories.ensure_snapshot(
                        user_id, body.conversation_id, conn
                    )

            memory = await asyncio.to_thread(freeze_conversation_memory)
            request_snapshot["memory_profile_revision"] = memory["profile_revision"]
            request_snapshot["memory_profile_snapshot"] = memory["profile_snapshot"]
        except MemoryNotFound as exc:
            raise _not_found(exc) from exc
    else:
        revision, facts = await asyncio.to_thread(memory_facts.snapshot, user_id)
        request_snapshot["memory_profile_revision"] = revision
        request_snapshot["memory_profile_snapshot"] = facts
    projected = await chat_service.planning_memory.project_snapshot(
        request_snapshot,
        revision=int(request_snapshot.get("memory_profile_revision", 0)),
        facts=request_snapshot.get("memory_profile_snapshot") or [],
    )
    request_snapshot.update(projected)
    if body.kind is RunKind.REVISION:
        if not body.related_itinerary_id:
            raise HTTPException(
                status_code=422, detail="revision requires related_itinerary_id"
            )
        with get_conn() as conn:
            base = conn.execute(
                "SELECT id FROM itineraries WHERE id=? AND user_id=?",
                (body.related_itinerary_id, user_id),
            ).fetchone()
        if not base:
            raise HTTPException(status_code=404, detail="基础行程不存在")
        request_snapshot["parent_plan_id"] = body.related_itinerary_id
        request_snapshot["related_itinerary_id"] = body.related_itinerary_id
        with get_conn() as conn:
            parent_run = conn.execute(
                "SELECT request_snapshot_json FROM runs WHERE user_id=? "
                "AND result_itinerary_id=? ORDER BY finished_at DESC,id DESC LIMIT 1",
                (user_id, body.related_itinerary_id),
            ).fetchone()
        if parent_run:
            inherited = json.loads(parent_run["request_snapshot_json"] or "{}")
            for key in (
                "memory_profile_revision", "memory_profile_snapshot", "memory_context",
                "effective_constraints", "constraint_coverage", "trip_budget",
            ):
                if key in inherited:
                    request_snapshot[key] = inherited[key]
            request_snapshot["constraint_snapshot_source"] = "parent_run"
    missing = PlanningBriefRepository.required_missing(request_snapshot)
    if body.kind is RunKind.TRAVEL_PLAN and missing:
        raise HTTPException(status_code=422, detail={"missing_fields": missing})
    try:
        run = await asyncio.to_thread(
            manager.create,
            user_id=user_id,
            kind=body.kind,
            request_snapshot=request_snapshot,
            conversation_id=body.conversation_id,
            itinerary_id=body.related_itinerary_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    scheduler.notify()
    return run


@router.get("/runs")
async def list_runs(
    conversation_id: str | None = None,
    active_only: bool = False,
    authorization: str | None = Header(default=None),
):
    return await asyncio.to_thread(
        manager.runs.list,
        _owner(authorization),
        conversation_id=conversation_id,
        active_only=active_only,
    )


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    authorization: str | None = Header(default=None),
):
    try:
        return await asyncio.to_thread(
            manager.runs.get, _owner(authorization), run_id
        )
    except OwnedResourceNotFound as exc:
        raise _not_found(exc) from exc


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    authorization: str | None = Header(default=None),
):
    try:
        return await manager.cancel(_owner(authorization), run_id)
    except OwnedResourceNotFound as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/runs/{run_id}/retry", status_code=202)
async def retry_run(
    run_id: str,
    authorization: str | None = Header(default=None),
):
    try:
        run = await asyncio.to_thread(
            manager.retry, _owner(authorization), run_id
        )
    except OwnedResourceNotFound as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    scheduler.notify()
    return run


@router.post("/runs/{run_id}/resume", status_code=202)
async def resume_run(
    run_id: str,
    body: RunResume,
    authorization: str | None = Header(default=None),
):
    try:
        run = await asyncio.to_thread(
            manager.runs.get, _owner(authorization), run_id
        )
        return await scheduler.resume(run, body.interaction_id, body.value)
    except OwnedResourceNotFound as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: str,
    after_seq: int = Query(default=0, ge=0),
    authorization: str | None = Header(default=None),
):
    try:
        await asyncio.to_thread(
            manager.runs.get, _owner(authorization), run_id
        )
    except OwnedResourceNotFound as exc:
        raise _not_found(exc) from exc
    return await asyncio.to_thread(
        manager.events.after, run_id, after_seq
    )


@router.get("/runs/{run_id}/result")
async def get_run_result(
    run_id: str,
    authorization: str | None = Header(default=None),
):
    try:
        run = await asyncio.to_thread(
            manager.runs.get, _owner(authorization), run_id
        )
    except OwnedResourceNotFound as exc:
        raise _not_found(exc) from exc
    if not run["result_itinerary_id"]:
        raise HTTPException(status_code=404, detail="任务尚无行程结果")
    return {
        "run_id": run_id,
        "itinerary_id": run["result_itinerary_id"],
        "status": run["status"],
    }


def _sse(kind: str, payload: dict[str, Any], sequence: int | None = None) -> str:
    lines = []
    if sequence is not None:
        lines.append(f"id: {sequence}")
    lines.append(f"event: {kind}")
    lines.append(f"data: {json.dumps(payload, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


@router.get("/runs/{run_id}/stream")
async def stream_run(
    run_id: str,
    after_seq: int = Query(default=0, ge=0),
    authorization: str | None = Header(default=None),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    user_id = _owner(authorization)
    try:
        await __import__("asyncio").to_thread(manager.runs.get, user_id, run_id)
    except OwnedResourceNotFound as exc:
        raise _not_found(exc) from exc
    cursor = after_seq
    if last_event_id and last_event_id.isdigit():
        cursor = max(cursor, int(last_event_id))

    async def generate() -> AsyncIterator[str]:
        current = cursor
        async with manager.bridge.subscribe(run_id, after_sequence=current) as live:
            replay = await asyncio.to_thread(
                manager.events.after, run_id, current
            )
            for event in replay:
                current = max(current, event["sequence"])
                yield _sse(event["kind"], event["payload"], event["sequence"])
            run = await asyncio.to_thread(
                manager.runs.get_internal, run_id
            )
            if RunStatus(run["status"]) in TERMINAL_STATUSES:
                return
            async for item in live:
                if item.sequence is not None and item.sequence <= current:
                    continue
                if item.sequence is not None:
                    current = item.sequence
                yield _sse(item.kind, item.payload, item.sequence)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
