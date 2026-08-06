"""Application-scoped runtime wiring."""

from __future__ import annotations

import os
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from app.chat.graph import build_chat_graph
from app.chat.memory_service import MemoryExtractionWorker
from app.chat.service import ChatService
from app.core.http import close_async_http_client
from app.planning.graph import build_graph, build_runtime_revision_graph
from app.planning.runtime_worker import (
    PlanningFinalizer,
    planning_run_to_state,
    revision_snapshot_to_state,
    snapshot_to_state,
)
from app.runtime.manager import RunManager
from app.runtime.models import RunKind
from app.runtime.scheduler import RuntimeScheduler
from app.runtime.worker import GraphRuntimeWorker

_checkpoint_path = Path(
    os.getenv("RUNTIME_CHECKPOINT_DB", "data/langgraph-checkpoints.db")
)
_checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
manager = RunManager()
chat_service = ChatService(manager)
scheduler = RuntimeScheduler(
    manager,
    chat_limit=int(os.getenv("RUNTIME_CHAT_CONCURRENCY", "8")),
    planning_limit=int(os.getenv("RUNTIME_PLANNING_CONCURRENCY", "2")),
    planning_per_user=int(os.getenv("RUNTIME_PLANNING_PER_USER", "2")),
    llm_limit=int(os.getenv("RUNTIME_LLM_CONCURRENCY", "8")),
    amap_limit=int(os.getenv("RUNTIME_AMAP_CONCURRENCY", "8")),
)

checkpointer: AsyncSqliteSaver | None = None
chat_worker: GraphRuntimeWorker | None = None
planning_worker: GraphRuntimeWorker | None = None
revision_worker: GraphRuntimeWorker | None = None
memory_worker = MemoryExtractionWorker(manager.db_path)
_checkpoint_context = None


async def start_runtime() -> None:
    global checkpointer, chat_worker, planning_worker, revision_worker, _checkpoint_context
    _checkpoint_context = AsyncSqliteSaver.from_conn_string(str(_checkpoint_path))
    checkpointer = await _checkpoint_context.__aenter__()
    await checkpointer.setup()
    chat_worker = GraphRuntimeWorker(
        manager,
        build_chat_graph(checkpointer=checkpointer),
        chat_service.chat_input,
        stream_messages=False,
        finalizer=chat_service.finalize_chat,
    )
    planning_worker = GraphRuntimeWorker(
        manager,
        build_graph(
            memory_writer=None,
            checkpointer=checkpointer,
            interrupt_on_missing=True,
        ),
        planning_run_to_state,
        stream_messages=False,
        finalizer=PlanningFinalizer(manager),
    )
    revision_worker = GraphRuntimeWorker(
        manager,
        build_runtime_revision_graph(checkpointer=checkpointer),
        revision_snapshot_to_state,
        stream_messages=False,
        finalizer=PlanningFinalizer(manager),
    )
    scheduler.register(RunKind.CHAT, chat_worker)
    scheduler.register(RunKind.TRAVEL_PLAN, planning_worker)
    scheduler.register(RunKind.REVISION, revision_worker)
    await scheduler.start()
    await memory_worker.start()


async def stop_runtime() -> None:
    await memory_worker.stop()
    await scheduler.stop()
    await close_async_http_client()
    if _checkpoint_context is not None:
        await _checkpoint_context.__aexit__(None, None, None)
